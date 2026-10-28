"""VoiceStudio (Pinokio) koprusu — OmniVoice klon sesle TR/EN/DE/FR seslendirme.

VoiceStudio ayri bir Pinokio uygulamasi olarak calisir (AGPL — kodu kopyalanmaz);
AkiFactory yalnizca OpenAI uyumlu ``/v1/audio/speech`` ucunu cagirir. Iki uygulama
ayni anda acik kalabilir; VoiceStudio istekleri kendi GPU kuyrugunda siralar.
"""

from __future__ import annotations

import json
import random
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from akifactory.paths import data_dir

APP_ID = "VoiceStudio-Pinokio.git"
MODEL_ID = "omnivoice"
VOICE_PREFIX = "voicestudio:"
SETTINGS_FILE = "voicestudio.json"
START_TIMEOUT_SEC = 300
REQUEST_TIMEOUT_SEC = 900
# Uzun tek istekte OmniVoice hizlanip kelime yutuyor ("taşıyan elleri" → "taşıyaneleri");
# cumle sinirinda ~250 harflik parcalar halinde uret
MAX_CHUNK_CHARS = 250
_CHUNK_GAP_SEC = 0.12
# OmniVoice dogal hizi ~15.5 harf/sn (Edge'den hizli); UI voice_rate 1.0 → 0.88
BASE_SPEED = 0.88
# Klon ses referansin temposunu da kopyalar (yavas reklam okumasi → yavas anlatim);
# profil temposu bunu dengeler: hiz = BASE_SPEED * tempo * voice_rate
TEMPO_MIN, TEMPO_MAX = 0.8, 1.4
# OmniVoice ara sira hece yutuyor/birlestiriyor ("köprüsünün" → "köprüsün"), her seed'de
# farkli yerde; parca Whisper ile dinlenip hataliysa baska seed ile yeniden uretilir
QA_MAX_ATTEMPTS = 3
_QA_SEED_STEP = 7919
PINOKIO_URL = "http://127.0.0.1:42000"
_LOG_URL_RE = re.compile(r"Uvicorn running on (http://[0-9.:]+)")

_cached_url: str | None = None


# --- ayarlar -----------------------------------------------------------------


def _settings_path() -> Path:
    return data_dir() / SETTINGS_FILE


def read_settings() -> dict[str, Any]:
    p = _settings_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_settings(**updates: Any) -> dict[str, Any]:
    data = read_settings()
    data.update({k: v for k, v in updates.items() if v is not None})
    p = _settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def selected_profile() -> str:
    return str(read_settings().get("profile_id") or "").strip()


def clamp_tempo(value: Any) -> float:
    try:
        t = float(value)
    except (TypeError, ValueError):
        return 1.0
    return round(max(TEMPO_MIN, min(TEMPO_MAX, t)), 2)


def profile_tempo(profile_id: str | None = None) -> float:
    pid = (profile_id or selected_profile()).strip()
    tempos = read_settings().get("tempos") or {}
    return clamp_tempo(tempos.get(pid, 1.0)) if isinstance(tempos, dict) else 1.0


def set_profile_tempo(profile_id: str, tempo: Any) -> float:
    t = clamp_tempo(tempo)
    tempos = read_settings().get("tempos") or {}
    if not isinstance(tempos, dict):
        tempos = {}
    tempos[profile_id] = t
    write_settings(tempos=tempos)
    return t


def engine_voice_name(profile_id: str | None = None) -> str:
    pid = (profile_id or selected_profile() or "default").strip()
    return f"{VOICE_PREFIX}{pid}"


def parse_profile_id(voice_name: str) -> str:
    raw = (voice_name or "").strip()
    if raw.startswith(VOICE_PREFIX):
        raw = raw[len(VOICE_PREFIX) :]
    return raw.strip() or "default"


# --- kesif ---------------------------------------------------------------------


def install_dir() -> Path | None:
    from akifactory.minimax_studio_launch import pinokio_home

    home = pinokio_home()
    if not home:
        return None
    api = home / "api"
    p = api / APP_ID
    if (p / "start.js").is_file():
        return p
    if not api.is_dir():
        return None
    for child in api.iterdir():
        if "voicestudio" in child.name.lower() and (child / "start.js").is_file():
            return child
    return None


def is_installed() -> bool:
    return install_dir() is not None


def _no_window_kwargs() -> dict[str, Any]:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}  # type: ignore[attr-defined]
    return {}


def _pterm_ready_url() -> str | None:
    from akifactory.minimax_studio_launch import pterm_exe

    exe = pterm_exe()
    if not exe:
        return None
    root = install_dir()
    target = root.name if root else APP_ID
    try:
        r = subprocess.run(
            [str(exe), "status", target],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
            **_no_window_kwargs(),
        )
        raw = r.stdout or ""
        data = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
    except Exception:
        return None
    url = data.get("ready_url")
    if isinstance(url, str) and url.startswith("http"):
        return url
    for entry in data.get("local_entries") or []:
        local = (entry or {}).get("local") or {}
        lu = local.get("url") if isinstance(local, dict) else None
        if isinstance(lu, str) and lu.startswith("http"):
            return lu
    return None


def _log_url() -> str | None:
    root = install_dir()
    if not root:
        return None
    log = root / "logs" / "api" / "start.js" / "latest"
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    found = _LOG_URL_RE.findall(text)
    return found[-1] if found else None


def probe(url: str | None) -> bool:
    if not url:
        return False
    import httpx

    try:
        r = httpx.get(f"{url.rstrip('/')}/health", timeout=5.0)
        return r.status_code == 200
    except Exception:
        return False


def discover_url() -> str | None:
    """Acik ve hazir VoiceStudio adresi (port her acilista degisir)."""
    global _cached_url
    cands = [str(read_settings().get("url") or "").strip(), _cached_url, _log_url()]
    for u in cands:
        if u and probe(u):
            _cached_url = u.rstrip("/")
            return _cached_url
    u = _pterm_ready_url()
    if u and probe(u):
        _cached_url = u.rstrip("/")
        return _cached_url
    return None


def _detached_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
        )
        kwargs["close_fds"] = True
    return kwargs


def _pinokio_up() -> bool:
    import httpx

    try:
        return httpx.get(f"{PINOKIO_URL}/pinokio/home", timeout=3.0).status_code == 200
    except Exception:
        return False


def _pinokio_app() -> Path | None:
    import os

    if sys.platform == "win32":
        p = Path(os.environ.get("LOCALAPPDATA") or "") / "Programs" / "Pinokio" / "Pinokio.exe"
    elif sys.platform == "darwin":
        p = Path("/Applications/Pinokio.app")
    else:
        return None
    return p if p.exists() else None


def ensure_pinokio(timeout_sec: float = 90.0) -> bool:
    """Pinokio kapaliyken pterm hicbir uygulamayi baslatamaz; once Pinokio'yu ac."""
    if _pinokio_up():
        return True
    app = _pinokio_app()
    if not app:
        return False
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-a", str(app)], **_detached_kwargs())
        else:
            subprocess.Popen([str(app)], **_detached_kwargs())
    except Exception:
        return False
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        time.sleep(2.0)
        if _pinokio_up():
            return True
    return False


def start_app() -> bool:
    from akifactory.minimax_studio_launch import pterm_exe

    exe = pterm_exe()
    root = install_dir()
    if not exe or not root:
        return False
    ensure_pinokio()
    try:
        subprocess.Popen([str(exe), "run", str(root), "--default", "start.js"], **_detached_kwargs())
        return True
    except Exception:
        return False


def ensure_url(*, timeout_sec: float = START_TIMEOUT_SEC) -> str | None:
    """Kapaliysa Pinokio uzerinden baslat ve hazir olmasini bekle."""
    url = discover_url()
    if url:
        return url
    if not start_app():
        return None
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        time.sleep(4.0)
        url = discover_url()
        if url:
            return url
    return None


# --- API -----------------------------------------------------------------------


def list_profiles(url: str) -> list[dict[str, str]]:
    import httpx

    r = httpx.get(f"{url}/v1/audio/voices", timeout=15.0)
    r.raise_for_status()
    out: list[dict[str, str]] = []
    for v in r.json().get("voices") or []:
        if v.get("type") != "profile":
            continue
        out.append(
            {
                "id": str(v.get("id") or v.get("voice_id") or ""),
                "label": str(v.get("name") or v.get("id") or ""),
            }
        )
    return [v for v in out if v["id"]]


def status_dict(*, refresh: bool = True) -> dict[str, Any]:
    settings = read_settings()
    installed = is_installed()
    url = discover_url() if (installed and refresh) else None
    voices = settings.get("voices") or []
    detail = ""
    if url:
        try:
            voices = list_profiles(url)
            write_settings(voices=voices)
        except Exception as exc:
            detail = f"Ses listesi alinamadi: {exc}"
    elif installed:
        detail = "VoiceStudio kapali — uretimde otomatik baslatilir"
    else:
        detail = "VoiceStudio kurulu degil (Pinokio → VoiceStudio-Pinokio)"
    return {
        "installed": installed,
        "online": bool(url),
        "url": url or "",
        "model": MODEL_ID,
        "voices": voices,
        "profile_id": str(settings.get("profile_id") or ""),
        "tempos": settings.get("tempos") or {},
        "detail": detail,
    }


def _speech_request(
    url: str, text: str, *, profile_id: str, lang: str, speed: float, seed: int | None = None
) -> bytes:
    import httpx

    body: dict[str, Any] = {
        "model": MODEL_ID,
        "voice": profile_id,
        "input": text,
        "language": lang,
        "response_format": "wav",
        "speed": speed,
    }
    if seed is not None:
        body["seed"] = seed
    r = httpx.post(f"{url}/v1/audio/speech", json=body, timeout=REQUEST_TIMEOUT_SEC)
    if r.status_code != 200:
        raise RuntimeError(f"VoiceStudio HTTP {r.status_code}: {r.text[:300]}")
    return r.content


# --- parca kontrolu (Whisper) --------------------------------------------------

# ğ, ç/ş, ö/ü, i noktasi — Turkce harfler kalir, diger aksanlar (â, á) duser
_QA_KEEP_MARKS = "\u0306\u0327\u0308\u0307"


def _qa_words(text: str, lang: str) -> list[str]:
    import unicodedata

    s = text or ""
    if lang == "tr":
        from akifactory.tts_numbers import expand_numbers_for_turkish_tts

        s = expand_numbers_for_turkish_tts(s)
    s = re.sub(r"\s*['’]\s*", "", s).replace("İ", "i").replace("I", "ı")
    s = "".join(
        c
        for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn" or c in _QA_KEEP_MARKS
    )
    return re.findall(r"[a-zçğıöşü]+", unicodedata.normalize("NFC", s).lower())


def _chunk_errors(model: Any, audio: Any, sr: int, expected: str, lang: str) -> list[str]:
    """Whisper'in duydugu ile metin arasindaki kelime farklari (bos = temiz)."""
    import difflib
    import io

    import numpy as np
    import soundfile as sf

    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV")
    buf.seek(0)
    segs, _ = model.transcribe(
        buf,
        language=lang,
        beam_size=5,
        word_timestamps=True,
        condition_on_previous_text=False,
    )
    dur = len(audio) / sr
    heard: list[str] = []
    for seg in segs:
        for w in seg.words or []:
            # Sessizlikte Whisper uydurur ("Altyazı M.K.", "izlediğiniz için teşekkürler")
            piece = audio[int(w.start * sr) : int(w.end * sr)]
            level = 20 * np.log10(float(np.sqrt(np.mean(piece**2))) + 1e-9) if len(piece) else -120.0
            if level < -45 or (w.probability < 0.3 and w.start > dur - 1.5):
                continue
            heard.append(w.word)
    ref = _qa_words(expected, lang)
    hyp = _qa_words(" ".join(heard), lang)
    sm = difflib.SequenceMatcher(a=ref, b=hyp, autojunk=False)
    return [
        f"{' '.join(ref[i1:i2]) or '-'}→{' '.join(hyp[j1:j2]) or '-'}"
        for op, i1, i2, j1, j2 in sm.get_opcodes()
        if op != "equal"
    ]


def _qa_model() -> Any:
    try:
        from akifactory.subtitle_align import shared_whisper_model

        return shared_whisper_model()
    except Exception:
        return None


def synthesize_wav(
    text: str,
    output_path: str | Path,
    *,
    profile_id: str,
    lang: str = "tr",
    voice_rate: float = 1.0,
    url: str | None = None,
    qa: bool = True,
    seed: int | None = None,
) -> Path:
    import io

    import numpy as np
    import soundfile as sf
    from loguru import logger

    from akifactory.chatterbox_util import split_chatterbox_chunks

    sample = (text or "").strip()
    if len(sample) < 2:
        raise ValueError("Metin cok kisa")
    base = url or ensure_url()
    if not base:
        raise RuntimeError("VoiceStudio acilamadi — Pinokio'dan VoiceStudio → Start")
    tempo = profile_tempo(profile_id)
    speed = max(0.6, min(1.5, BASE_SPEED * tempo * float(voice_rate or 1.0)))
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Tek seed → anlatici tonu video boyunca ayni kalir
    video_seed = seed if seed is not None else random.randint(1, 2**30)
    qa_model = _qa_model() if qa else None
    chunks = split_chatterbox_chunks(sample, max_chars=MAX_CHUNK_CHARS)
    parts: list[Any] = []
    sr = 24000
    for idx, chunk in enumerate(chunks, 1):
        best: tuple[int, Any] | None = None
        prev_diffs: list[str] | None = None
        attempts = QA_MAX_ATTEMPTS if qa_model is not None else 1
        for attempt in range(attempts):
            raw = _speech_request(
                base,
                chunk,
                profile_id=profile_id,
                lang=lang,
                speed=speed,
                seed=video_seed + attempt * _QA_SEED_STEP,
            )
            audio, sr = sf.read(io.BytesIO(raw), dtype="float32")
            if getattr(audio, "ndim", 1) > 1:
                audio = audio.mean(axis=1)
            if qa_model is None:
                best = (0, audio)
                break
            try:
                diffs = _chunk_errors(qa_model, audio, sr, chunk, lang)
            except Exception as exc:
                logger.warning(f"VoiceStudio parca kontrolu kapatildi: {exc}")
                qa_model = None
                best = (0, audio)
                break
            if best is None or len(diffs) < best[0]:
                best = (len(diffs), audio)
            if not diffs:
                break
            logger.info(
                f"VoiceStudio parca {idx}/{len(chunks)} deneme {attempt + 1}/{attempts}: "
                f"{', '.join(diffs)}"
            )
            # Her seed'de ayni fark → yabanci isim / Whisper yazimi, ses hatasi degil
            if diffs == prev_diffs:
                break
            prev_diffs = diffs
        if best is not None:
            parts.append(best[1])
    if not parts:
        raise RuntimeError("VoiceStudio bos ses dondurdu")
    if len(parts) == 1:
        audio_out = parts[0]
    else:
        gap = np.zeros(int(sr * _CHUNK_GAP_SEC), dtype=np.float32)
        joined: list[Any] = []
        for i, a in enumerate(parts):
            joined.append(a)
            if i < len(parts) - 1:
                joined.append(gap)
        audio_out = np.concatenate(joined)
    sf.write(str(out), audio_out, sr)
    if not out.is_file() or out.stat().st_size < 500:
        raise RuntimeError("VoiceStudio ses dosyasi olusturulamadi")
    return out


# --- motor yamasi ----------------------------------------------------------------


def _lang_id(video_language: str) -> str:
    vl = (video_language or "").strip().lower()
    for code in ("tr", "en", "de", "fr"):
        if vl.startswith(code):
            return code
    return "tr"


def voicestudio_tts_engine(
    text: str,
    voice_name: str,
    voice_rate: float,
    voice_file: str,
    voice_volume: float = 1.0,
    video_language: str = "",
    edge_fallback: Any = None,
):
    """motor voice.tts yolu — VoiceStudio OmniVoice → mp3 (kapaliysa Edge)."""
    import os
    import shutil

    from edge_tts import SubMaker
    from loguru import logger
    from moviepy.audio.io.AudioFileClip import AudioFileClip

    from akifactory.engine.services.voice import (
        ensure_file_path_exists,
        populate_legacy_submaker_with_full_text,
    )

    ensure_file_path_exists(voice_file)
    spoken = (text or "").strip()
    if not spoken:
        logger.error("VoiceStudio: bos metin")
        return None

    lang = _lang_id(video_language)
    profile_id = parse_profile_id(voice_name)
    spoken_norm = spoken
    if lang == "tr":
        from akifactory.chatterbox_util import normalize_turkish_tts_text

        spoken_norm = normalize_turkish_tts_text(spoken)

    url = ensure_url()
    if not url:
        if edge_fallback is None:
            logger.error("VoiceStudio acilamadi")
            return None
        from akifactory import languages as lang_mod

        edge_voice = lang_mod.resolve(lang).voice_name
        logger.warning(f"VoiceStudio acilamadi — Edge TTS ile devam: {edge_voice}")
        return edge_fallback(
            text,
            edge_voice,
            voice_rate,
            voice_file,
            voice_volume=voice_volume,
            video_language=video_language,
        )

    tmp_wav = voice_file.rsplit(".", 1)[0] + "._vs.wav"
    try:
        t0 = time.monotonic()
        synthesize_wav(
            spoken_norm,
            tmp_wav,
            profile_id=profile_id,
            lang=lang,
            voice_rate=voice_rate,
            url=url,
        )
        logger.info(
            f"VoiceStudio OmniVoice ({profile_id}, {lang}) hazir — "
            f"{len(spoken_norm)} harf, {time.monotonic() - t0:.1f} sn"
        )
    except Exception as exc:
        logger.error(f"VoiceStudio uretim hatasi ({profile_id}): {exc}")
        return None

    if voice_file.lower().endswith(".mp3"):
        from akifactory.tts_common import wav_to_mp3

        if wav_to_mp3(tmp_wav, voice_file, voice_volume):
            try:
                os.remove(tmp_wav)
            except OSError:
                pass
        else:
            shutil.copy2(tmp_wav, voice_file)
    else:
        shutil.copy2(tmp_wav, voice_file)

    if not Path(voice_file).is_file() or Path(voice_file).stat().st_size == 0:
        logger.error("VoiceStudio: bos ses dosyasi")
        return None

    with AudioFileClip(voice_file) as clip:
        duration = float(clip.duration or 0)
    return populate_legacy_submaker_with_full_text(SubMaker(), spoken, duration)


def apply_voicestudio_runtime_patch() -> None:
    """voice.tts: voicestudio: prefix → VoiceStudio OmniVoice."""
    try:
        from akifactory.engine.services import voice as v
    except ImportError:
        return
    if getattr(v, "_aki_voicestudio_patched", False):
        return

    from akifactory.tts_common import apply_voice_name_parse_patch

    apply_voice_name_parse_patch()

    _orig_tts = v.tts

    def _tts_patched(
        text: str,
        voice_name: str,
        voice_rate: float,
        voice_file: str,
        voice_volume: float = 1.0,
        video_language: str = "",
    ):
        if (voice_name or "").startswith(VOICE_PREFIX):
            return voicestudio_tts_engine(
                text,
                voice_name,
                voice_rate,
                voice_file,
                voice_volume=voice_volume,
                video_language=video_language,
                edge_fallback=_orig_tts,
            )
        return _orig_tts(
            text,
            voice_name,
            voice_rate,
            voice_file,
            voice_volume=voice_volume,
            video_language=video_language,
        )

    v.tts = _tts_patched
    v._aki_voicestudio_patched = True
