"""Chatterbox Multilingual — yerel TR TTS + RVC post."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any

from akifactory.paths import app_root

_SPEAKER_FILES = {
    "tr-male": "tr_speaker_male.wav",
    "tr-female": "tr_speaker_female.wav",
}
_VALID_KEYS = frozenset({"tr-male", "tr-female", "en-male", "en-female"})

# Chatterbox biraz hizli; 0.90 ≈ %10 yavas (ton korunur, atempo)
CHATTERBOX_BASE_SPEECH_RATE = 0.90
# Uzun metinde max_new_tokens=1000 tavanina carpinca tekrar/atlama olur.
# Normalize sonrasi ~300 harflik fazlar halinde uret, sonra birlestir.
CHATTERBOX_MAX_CHUNK_CHARS = 300
_CHUNK_GAP_SEC = 0.08
# Normal okuma ~12-15 harf/sn; bunun ustu cumle atlandigini gosterir
CHATTERBOX_MAX_CHARS_PER_SEC = 18.0

# Multilingual V3 (2026-06): ayni T3 mimarisi, daha iyi ses benzerligi, daha az tekrar/halusinasyon.
# AKI_CHATTERBOX_T3=v2 ile eski modele donulur.
CHATTERBOX_T3_VERSION = (os.environ.get("AKI_CHATTERBOX_T3") or "v3").strip().lower()
_T3_FILES = {"v2": "t3_mtl23ls_v2.safetensors", "v3": "t3_mtl23ls_v3.safetensors"}

_model_singleton: Any | None = None
_model_device: str | None = None
_model_t3_version: str | None = None


def split_chatterbox_chunks(
    text: str, *, max_chars: int = CHATTERBOX_MAX_CHUNK_CHARS
) -> list[str]:
    """Cumle/virgul sinirinda ~max_chars parcaya bol (kelime ortasindan kesme)."""
    sample = re.sub(r"\s+", " ", (text or "").strip())
    if not sample:
        return []
    if len(sample) <= max_chars:
        return [sample]

    # Once cumle
    parts = re.split(r"(?<=[.!?…])\s+", sample)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) <= 1:
        # Virgul / noktali virgul
        parts = re.split(r"(?<=[,;:])\s+", sample)
        parts = [p.strip() for p in parts if p.strip()]

    chunks: list[str] = []
    buf = ""

    def _flush() -> None:
        nonlocal buf
        if buf.strip():
            chunks.append(buf.strip())
        buf = ""

    def _append_piece(piece: str) -> None:
        nonlocal buf
        piece = piece.strip()
        if not piece:
            return
        if len(piece) <= max_chars:
            cand = f"{buf} {piece}".strip() if buf else piece
            if len(cand) <= max_chars:
                buf = cand
            else:
                _flush()
                buf = piece
            return
        # Parca kendi basina uzun — kelime kelime
        words = piece.split()
        for w in words:
            cand = f"{buf} {w}".strip() if buf else w
            if len(cand) <= max_chars:
                buf = cand
            else:
                _flush()
                if len(w) > max_chars:
                    # Son care: sert kes
                    for i in range(0, len(w), max_chars):
                        chunks.append(w[i : i + max_chars])
                    buf = ""
                else:
                    buf = w

    for part in parts:
        _append_piece(part)
    _flush()
    return chunks or [sample[:max_chars]]


def _concat_wavs(
    arrays: list[Any], *, sample_rate: int, gap_sec: float = _CHUNK_GAP_SEC
) -> Any:
    import numpy as np

    if not arrays:
        raise ValueError("Bos ses listesi")
    gap_n = max(0, int(sample_rate * gap_sec))
    gap = np.zeros(gap_n, dtype=np.float32) if gap_n else None
    out: list[Any] = []
    for i, arr in enumerate(arrays):
        a = np.asarray(arr, dtype=np.float32).reshape(-1)
        out.append(a)
        if gap is not None and i < len(arrays) - 1:
            out.append(gap)
    return np.concatenate(out)


def chatterbox_models_dir() -> Path:
    d = app_root() / "models" / "chatterbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ref_dir() -> Path:
    d = chatterbox_models_dir() / "ref"
    d.mkdir(parents=True, exist_ok=True)
    return d


def chatterbox_package_ready() -> bool:
    import importlib.util

    return importlib.util.find_spec("chatterbox") is not None


def chatterbox_model_ready() -> bool:
    cache = chatterbox_models_dir()
    if (cache / ".chatterbox_ready").is_file():
        return True
    return False


def speaker_wav_path(voice_key: str = "tr-male") -> Path | None:
    name = _SPEAKER_FILES.get(voice_key) or _SPEAKER_FILES["tr-male"]
    p = ref_dir() / name
    if p.is_file() and p.stat().st_size > 1000:
        return p
    return None


def status_dict() -> dict[str, Any]:
    pkg = chatterbox_package_ready()
    model = chatterbox_model_ready() if pkg else False
    ref = speaker_wav_path("tr-male")
    gpu = False
    try:
        import torch

        gpu = bool(torch.cuda.is_available())
    except Exception:
        pass
    return {
        "package_ready": pkg,
        "model_ready": model,
        "reference_wav": str(ref) if ref else "",
        "models_dir": str(chatterbox_models_dir()),
        "gpu_available": gpu,
        "t3_version": _model_t3_version or CHATTERBOX_T3_VERSION,
        "ready": pkg and model,
        "hint": (
            "Hazir"
            if pkg and model
            else "Kurulum: python scripts/bootstrap.py --chatterbox"
        ),
    }


def _under_1000(n: int) -> str:
    from akifactory.tts_numbers import _under_1000 as _u

    return _u(n)


def integer_to_turkish(n: int) -> str:
    from akifactory.tts_numbers import integer_to_turkish as _i

    return _i(n)


def _expand_number_token(raw: str) -> str:
    from akifactory.tts_numbers import expand_number_token

    return expand_number_token(raw)


def _expand_plain_number(s: str) -> str:
    from akifactory.tts_numbers import _expand_plain_number as _e

    return _e(s)


def normalize_turkish_tts_text(text: str) -> str:
    """Rakam / yuzde / homograf → Turkce TTS icin guvenli metin.

    Altyazi metnini degistirmez — yalnizca seslendirme girdisi.
    2600de → iki bin alti yuz de; 1. yuzyil → birinci yuzyil.
    """
    sample = (text or "").strip()
    if not sample:
        return sample

    try:
        from akifactory.turkish_imla import apply_context_spelling_repairs

        sample = apply_context_spelling_repairs(sample)
    except Exception:
        pass

    from akifactory.tts_numbers import expand_numbers_for_turkish_tts

    out = expand_numbers_for_turkish_tts(sample)
    # Sik kisaltmalar
    repls = (
        (r"\bDr\.\s*", "Doktor "),
        (r"\bProf\.\s*", "Profesör "),
        (r"\bvs\.\b", "ve saire"),
        (r"\bvb\.\b", "ve benzeri"),
        (r"\börn\.\b", "örneğin"),
    )
    for pat, rep in repls:
        out = re.sub(pat, rep, out, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", out).strip()


# Geriye donuk: eski _NUM_RE referanslari kirilmasin diye tut
_NUM_RE = re.compile(
    r"(?<![\w])(?:%\s*)?\d+(?:[.,]\d+)?(?:\s*%)?(?![\w])"
)


def parse_chatterbox_speaker_key(voice_name: str) -> str:
    raw = (voice_name or "").strip()
    body = raw.split(":", 1)[1].strip() if raw.startswith("chatterbox:") else raw
    for key in sorted(_VALID_KEYS, key=len, reverse=True):
        if body == key or body.startswith(f"{key}-"):
            return key
    low = body.lower()
    if "female" in low or "kadin" in low or "kadın" in low:
        return "tr-female" if not low.startswith("en") else "en-female"
    if low.startswith("en"):
        return "en-male"
    return "tr-male"


def _lang_id(video_language: str, voice_key: str) -> str:
    vl = (video_language or "").strip().lower()
    for code in ("tr", "en", "de", "fr"):
        if vl.startswith(code):
            return code
    if voice_key.startswith("en"):
        return "en"
    return "tr"


def _swap_t3_weights(model: Any, version: str) -> None:
    """PyPI paketi yalnizca v2 yukler; v3 agirliklari ayni T3 yapisina yuklenir."""
    from chatterbox.mtl_tts import REPO_ID
    from huggingface_hub import hf_hub_download
    from safetensors.torch import load_file

    path = hf_hub_download(
        repo_id=REPO_ID,
        filename=_T3_FILES[version],
        token=os.getenv("HF_TOKEN"),
    )
    state = load_file(path)
    if "model" in state.keys():
        state = state["model"][0]
    model.t3.load_state_dict(state)
    model.t3.to(model.device).eval()


def _get_model(device: str | None = None) -> Any:
    global _model_singleton, _model_device, _model_t3_version
    import inspect

    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    import torch
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    from loguru import logger

    dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
    if _model_singleton is not None and _model_device == dev:
        return _model_singleton
    want = CHATTERBOX_T3_VERSION if CHATTERBOX_T3_VERSION in _T3_FILES else "v3"
    if "t3_model" in inspect.signature(ChatterboxMultilingualTTS.from_pretrained).parameters:
        model = ChatterboxMultilingualTTS.from_pretrained(device=dev, t3_model=want)
        loaded = want
    else:
        model = ChatterboxMultilingualTTS.from_pretrained(device=dev)
        loaded = "v2"
        if want != "v2":
            try:
                _swap_t3_weights(model, want)
                loaded = want
            except Exception as exc:
                logger.warning(f"Chatterbox {want} yuklenemedi, v2 ile devam: {exc}")
    logger.info(f"Chatterbox Multilingual {loaded} hazir ({dev})")
    _model_singleton = model
    _model_device = dev
    _model_t3_version = loaded
    return _model_singleton


def _effective_speech_rate(voice_rate: float | None = None) -> float:
    """UI voice_rate (1.0=normal) × Chatterbox baz yavaslatma."""
    ui = float(voice_rate if voice_rate is not None else 1.0)
    if ui <= 0:
        ui = 1.0
    rate = CHATTERBOX_BASE_SPEECH_RATE * ui
    return max(0.55, min(1.35, rate))


def _slow_wav_inplace(path: Path, *, rate: float, sample_rate: int) -> None:
    """Pitch koruyarak yavaslat (ffmpeg atempo). rate<1 daha yavas."""
    if abs(rate - 1.0) < 0.02:
        return
    from akifactory.gpu import resolve_ffmpeg_exe

    ffmpeg = resolve_ffmpeg_exe()
    if not ffmpeg:
        return
    import subprocess

    # atempo yalnizca 0.5–2.0; gerekirse zincirle
    factors: list[float] = []
    rem = float(rate)
    while rem < 0.5 - 1e-9:
        factors.append(0.5)
        rem /= 0.5
    while rem > 2.0 + 1e-9:
        factors.append(2.0)
        rem /= 2.0
    factors.append(rem)
    af = ",".join(f"atempo={f:.4f}" for f in factors)
    tmp = path.with_suffix(".slow.wav")
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(path),
        "-af",
        af,
        "-ar",
        str(int(sample_rate)),
        str(tmp),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode == 0 and tmp.is_file() and tmp.stat().st_size > 500:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        tmp.replace(path)
    else:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def synthesize_chatterbox_wav(
    text: str,
    output_path: str | Path,
    *,
    voice_key: str = "tr-male",
    lang: str = "tr",
    normalize: bool = True,
    voice_rate: float | None = None,
    max_chunk_chars: int = CHATTERBOX_MAX_CHUNK_CHARS,
) -> Path:
    sample = (text or "").strip()
    if len(sample) < 2:
        raise ValueError("Metin cok kisa")
    if normalize and (lang == "tr" or lang.startswith("tr")):
        sample = normalize_turkish_tts_text(sample)
    key = (
        voice_key
        if voice_key in _VALID_KEYS
        else parse_chatterbox_speaker_key(voice_key)
    )
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if not chatterbox_package_ready():
        raise RuntimeError(
            "Chatterbox paketi yok — python scripts/bootstrap.py --chatterbox"
        )

    model = _get_model()
    lang_id = lang if lang in ("tr", "en", "de", "fr", "es", "it", "pt") else "tr"
    kwargs: dict[str, Any] = {"language_id": lang_id}
    ref = speaker_wav_path(key if key.startswith("tr") else "tr-male")
    if ref:
        kwargs["audio_prompt_path"] = str(ref)

    chunks = split_chatterbox_chunks(sample, max_chars=max(120, int(max_chunk_chars)))
    import numpy as np
    import soundfile as sf

    sr = int(model.sr)

    def _gen(chunk: str) -> Any:
        audio = model.generate(chunk, **kwargs).detach().cpu().numpy()
        return np.squeeze(audio) if getattr(audio, "ndim", 1) > 1 else audio

    wav_parts: list[Any] = []
    for i, chunk in enumerate(chunks):
        audio = _gen(chunk)
        # Model bazen erken durup son cumleyi atlar (~13 harf/sn normal); kisaysa bir kez yeniden uret
        if len(chunk) >= 60 and len(audio) / sr < len(chunk) / CHATTERBOX_MAX_CHARS_PER_SEC:
            retry = _gen(chunk)
            if len(retry) > len(audio):
                audio = retry
            try:
                from loguru import logger

                logger.warning(
                    f"Chatterbox parca {i + 1} kisa cikti (atlama suphesi) — yeniden uretildi"
                )
            except Exception:
                pass
        wav_parts.append(audio)
        # Ilk generate audio_prompt ile conditionals kurdu; sonrakiler ayni ref
        if i == 0 and "audio_prompt_path" in kwargs:
            # prepare_conditionals zaten yapildi — tekrar ayni prompt gereksiz
            # ama generate her cagrida path varsa yeniden kurar; tutarli kalsin
            pass

    if len(wav_parts) == 1:
        audio_out = np.asarray(wav_parts[0], dtype=np.float32).reshape(-1)
    else:
        audio_out = _concat_wavs(wav_parts, sample_rate=sr)
        try:
            from loguru import logger

            logger.info(
                f"Chatterbox cok fazli TTS: {len(chunks)} parca, "
                f"toplam {len(sample)} harf (limit={max_chunk_chars})"
            )
        except Exception:
            pass

    sf.write(str(out), audio_out, sr)
    if not out.is_file() or out.stat().st_size < 500:
        raise RuntimeError("Chatterbox ses dosyasi olusturulamadi")

    speech_rate = _effective_speech_rate(voice_rate)
    if abs(speech_rate - 1.0) >= 0.02:
        _slow_wav_inplace(out, rate=speech_rate, sample_rate=sr)

    (chatterbox_models_dir() / ".chatterbox_ready").write_text("ok", encoding="utf-8")
    return out


def synthesize_sample(
    text: str,
    *,
    voice_key: str = "tr-male",
    lang: str = "tr",
) -> Path:
    sample = (text or "").strip()
    if len(sample) < 4:
        sample = (
            "Merhaba. Bu AkiFactory Chatterbox Multilingual Turkce testidir. "
            "Yil bin dokuz yuz kirk ornegi icin rakam normalizasyonu kullanilir."
        )
    out_dir = app_root() / "data" / "chatterbox_samples"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"cb-test-{uuid.uuid4().hex[:10]}.wav"
    synthesize_chatterbox_wav(sample, out_path, voice_key=voice_key, lang=lang)
    return out_path


def _voice_key_from_rvc_gender() -> str:
    try:
        from akifactory.rvc_registry import get_voice
        from akifactory.rvc_util import read_runtime_settings

        cfg = read_runtime_settings()
        voice = get_voice(str(cfg.get("voice_id") or ""))
        gender = (voice.gender if voice else "Male").strip().lower()
        if gender in ("female", "f", "kadin", "kadın"):
            return "tr-female"
    except Exception:
        pass
    return "tr-male"


def chatterbox_tts_engine(
    text: str,
    voice_name: str,
    voice_rate: float,
    voice_file: str,
    voice_volume: float = 1.0,
    video_language: str = "",
):
    """motor voice.tts yolu — Chatterbox → (RVC) → mp3."""
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
        logger.error("Chatterbox: bos metin")
        return None

    key = parse_chatterbox_speaker_key(voice_name)
    if key in ("tr-male", "tr-female"):
        # RVC cinsiyetine gore referans
        key = _voice_key_from_rvc_gender()
    lang = _lang_id(video_language, key)
    if lang == "tr":
        spoken_norm = normalize_turkish_tts_text(spoken)
    else:
        spoken_norm = spoken

    n_chunks = len(split_chatterbox_chunks(spoken_norm))
    if n_chunks > 1:
        logger.info(
            f"Chatterbox fazli okuma: {n_chunks} parca "
            f"({len(spoken_norm)} harf, limit={CHATTERBOX_MAX_CHUNK_CHARS})"
        )

    tmp_wav = voice_file
    if voice_file.lower().endswith(".mp3"):
        tmp_wav = voice_file.rsplit(".", 1)[0] + "._cb.wav"

    try:
        synthesize_chatterbox_wav(
            spoken_norm,
            tmp_wav,
            voice_key=key,
            lang=lang,
            normalize=False,  # zaten normalize edildi
            voice_rate=voice_rate,
        )
    except Exception as exc:
        logger.error(f"Chatterbox uretim hatasi ({key}): {exc}")
        return None

    logger.info(f"Chatterbox taban ses hazir: {key}")
    audio_wav = tmp_wav

    try:
        from akifactory.rvc_util import apply_post_rvc_to_file, read_runtime_settings

        cfg = read_runtime_settings()
        if (cfg.get("post_chain") or "").strip().lower() == "chatterbox" and (
            cfg.get("voice_id") or ""
        ).strip():
            rvc_wav = str(Path(tmp_wav).with_suffix(".rvc.wav"))
            if apply_post_rvc_to_file(tmp_wav, rvc_wav, expected_chain="chatterbox"):
                audio_wav = rvc_wav
                logger.info(
                    f"Chatterbox ({key}) → RVC ({cfg.get('voice_id')}) donusumu tamam"
                )
            else:
                logger.warning(
                    "RVC donusumu uygulanamadi — yalnizca Chatterbox taban ses kullanildi"
                )
    except Exception as exc:
        logger.error(f"Chatterbox RVC donusumu basarisiz: {exc}")
        return None

    if voice_file.lower().endswith(".mp3"):
        try:
            from akifactory.tts_common import wav_to_mp3

            if not wav_to_mp3(audio_wav, voice_file, voice_volume):
                import shutil

                shutil.copy2(audio_wav, voice_file)
            else:
                for p in (tmp_wav, audio_wav):
                    if p != voice_file:
                        try:
                            os.remove(p)
                        except OSError:
                            pass
        except Exception:
            import shutil

            shutil.copy2(audio_wav, voice_file)
    elif Path(audio_wav).resolve() != Path(voice_file).resolve():
        import shutil

        shutil.copy2(audio_wav, voice_file)

    if not Path(voice_file).is_file() or Path(voice_file).stat().st_size == 0:
        logger.error("Chatterbox: bos ses dosyasi")
        return None

    with AudioFileClip(voice_file) as clip:
        duration = float(clip.duration or 0)
    # Altyazi metni orijinal senaryo (rakamlar senaryoda kalir); sure final audio
    return populate_legacy_submaker_with_full_text(SubMaker(), spoken, duration)


def apply_chatterbox_runtime_patch() -> None:
    """voice.tts: chatterbox: prefix → Chatterbox (+ RVC)."""
    try:
        from akifactory.engine.services import voice as v
    except ImportError:
        return
    if getattr(v, "_aki_chatterbox_patched", False):
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
        if (voice_name or "").startswith("chatterbox:"):
            return chatterbox_tts_engine(
                text,
                voice_name,
                voice_rate,
                voice_file,
                voice_volume=voice_volume,
                video_language=video_language,
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
    v._aki_chatterbox_patched = True
