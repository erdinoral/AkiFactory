"""RVC runtime — motor voice.tts patch."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from akifactory.paths import data_dir
from akifactory.rvc_registry import default_voice, get_voice, parse_rvc_voice_id
from akifactory.text_utils import prepare_video_script
from akifactory.rvc_tts import (
    DEFAULT_INDEX_RATE,
    DEFAULT_PITCH,
    edge_voice_from_engine_name,
    generate_rvc_audio,
    is_rvc_available,
)

SETTINGS_FILE = data_dir() / "rvc_runtime.json"

DEFAULT_SETTINGS: dict[str, Any] = {
    "voice_id": "",
    "pitch": DEFAULT_PITCH,
    "index_rate": DEFAULT_INDEX_RATE,
    "edge_voice": "tr-TR-AhmetNeural-Male",
    "post_chain": "",
}


def is_rvc_voice(voice_name: str) -> bool:
    return (voice_name or "").startswith("rvc:")


def write_runtime_settings(
    *,
    voice_id: str | None = None,
    pitch: int = DEFAULT_PITCH,
    index_rate: float = DEFAULT_INDEX_RATE,
    edge_voice: str | None = None,
    post_chain: str | None = None,
) -> None:
    vid = (voice_id or "").strip()
    chain = (post_chain or "").strip().lower()
    if not vid and chain != "chatterbox":
        dv = default_voice()
        vid = dv.id if dv else ""
    payload = {
        "voice_id": vid,
        "pitch": int(pitch),
        "index_rate": float(index_rate),
        "edge_voice": edge_voice or DEFAULT_SETTINGS["edge_voice"],
        "post_chain": chain,
    }
    SETTINGS_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def configure_tts_rvc_chain(
    tts_engine: str,
    *,
    rvc_voice: str | None = None,
    rvc_pitch: int = DEFAULT_PITCH,
    rvc_index_rate: float = DEFAULT_INDEX_RATE,
    production_language: str = "tr",
    edge_voice: str | None = None,
) -> None:
    """Uretim oncesi RVC runtime — Edge tabanli RVC veya Chatterbox sonrasi RVC."""
    tts = (tts_engine or "").strip().lower()
    rvc_id = (rvc_voice or "").strip()
    if tts == "rvc":
        from akifactory.rvc_registry import get_voice, resolve_edge_voice_for_rvc

        voice_meta = get_voice(rvc_id)
        pitch = int(rvc_pitch)
        index_rate = float(rvc_index_rate)
        if voice_meta:
            if abs(pitch) > 3 and voice_meta.pitch is not None:
                pitch = int(voice_meta.pitch)
            if index_rate > 0.85 and voice_meta.index_rate < 0.85:
                index_rate = float(voice_meta.index_rate)
        write_runtime_settings(
            voice_id=rvc_id or (voice_meta.id if voice_meta else None),
            pitch=pitch,
            index_rate=index_rate,
            edge_voice=resolve_edge_voice_for_rvc(
                voice_meta, production_language, edge_voice
            ),
            post_chain="",
        )
        return
    if tts == "chatterbox":
        from akifactory.rvc_registry import default_voice, get_voice, resolve_edge_voice_for_rvc

        if not rvc_id:
            dv = default_voice()
            rvc_id = dv.id if dv else ""
        if not rvc_id:
            write_runtime_settings(post_chain="")
            return
        voice_meta = get_voice(rvc_id)
        pitch = int(rvc_pitch)
        index_rate = float(rvc_index_rate)
        if voice_meta:
            if abs(pitch) > 3 and voice_meta.pitch is not None:
                pitch = int(voice_meta.pitch)
            if index_rate > 0.85 and voice_meta.index_rate < 0.85:
                index_rate = float(voice_meta.index_rate)
        write_runtime_settings(
            voice_id=rvc_id,
            pitch=pitch,
            index_rate=index_rate,
            edge_voice=resolve_edge_voice_for_rvc(
                voice_meta, production_language, edge_voice
            ),
            post_chain=tts,
        )
        return
    write_runtime_settings(post_chain="")


def should_apply_post_rvc(expected_chain: str) -> bool:
    chain = (expected_chain or "").strip().lower()
    if chain != "chatterbox":
        return False
    cfg = read_runtime_settings()
    if cfg.get("post_chain") != chain:
        return False
    if not (cfg.get("voice_id") or "").strip():
        return False
    return is_rvc_available()


def apply_post_rvc_to_file(
    base_path: str,
    output_path: str,
    *,
    expected_chain: str,
) -> bool:
    """Yerel taban (Chatterbox) WAV ciktisini secilen RVC modeline donustur."""
    if not should_apply_post_rvc(expected_chain):
        return False
    from akifactory.rvc_tts import (
        FILE_CONVERT_INDEX_RATE,
        POST_LOCAL_RVC_INDEX_CAP,
        convert_audio_file_sync,
        prepare_wav_for_rvc_convert,
    )

    cfg = read_runtime_settings()
    vid = str(cfg.get("voice_id") or "")
    voice = get_voice(vid)
    pitch = int(cfg.get("pitch", DEFAULT_PITCH))
    index_rate = float(cfg.get("index_rate", DEFAULT_INDEX_RATE))
    if voice:
        if pitch == DEFAULT_PITCH and voice.pitch is not None:
            pitch = int(voice.pitch)
        if index_rate >= 0.99 and voice.index_rate < 0.99:
            index_rate = float(voice.index_rate)
    if index_rate >= 0.99:
        index_rate = FILE_CONVERT_INDEX_RATE
    if expected_chain == "chatterbox":
        index_rate = min(index_rate, POST_LOCAL_RVC_INDEX_CAP)

    src = Path(base_path)
    work = prepare_wav_for_rvc_convert(src, source=expected_chain)
    try:
        convert_audio_file_sync(
            str(work),
            output_path,
            voice_id=vid,
            pitch=pitch,
            index_rate=index_rate,
        )
    finally:
        if work.resolve() != src.resolve():
            try:
                work.unlink(missing_ok=True)
            except OSError:
                pass
    return True


def apply_post_rvc_on_output(
    voice_file: str,
    *,
    expected_chain: str,
    voice_volume: float = 1.0,
) -> bool:
    """Uretilmis ses dosyasina (wav/mp3) RVC son katmani uygula."""
    if not should_apply_post_rvc(expected_chain):
        return False
    from pathlib import Path

    import shutil

    from akifactory.rvc_tts import _ensure_wav_input

    out = Path(voice_file)
    if not out.is_file() or out.stat().st_size == 0:
        raise RuntimeError("RVC icin kaynak ses dosyasi yok")

    work_wav = out
    temp_wav: Path | None = None
    if out.suffix.lower() == ".mp3":
        temp_wav = _ensure_wav_input(out)
        work_wav = temp_wav

    rvc_wav = out.with_name(out.stem + "._rvc.wav")
    apply_post_rvc_to_file(str(work_wav), str(rvc_wav), expected_chain=expected_chain)

    if out.suffix.lower() == ".mp3":
        try:
            from pydub import AudioSegment

            seg = AudioSegment.from_wav(str(rvc_wav))
            if voice_volume != 1.0:
                seg = seg + (20 * (voice_volume - 1.0))
            seg.export(str(out), format="mp3")
        except Exception:
            from akifactory.gpu import resolve_ffmpeg_exe

            ffmpeg = resolve_ffmpeg_exe()
            if not ffmpeg:
                raise RuntimeError("RVC sonrasi MP3 olusturulamadi (FFmpeg yok)")
            import subprocess

            r = subprocess.run(
                [ffmpeg, "-y", "-i", str(rvc_wav), "-q:a", "4", str(out)],
                capture_output=True,
                text=True,
            )
            if r.returncode != 0:
                raise RuntimeError((r.stderr or r.stdout or "MP3 encode hatasi")[:400])
    else:
        shutil.copy2(rvc_wav, out)

    if temp_wav and temp_wav.is_file():
        temp_wav.unlink(missing_ok=True)
    if rvc_wav.is_file():
        rvc_wav.unlink(missing_ok=True)
    return True


def read_runtime_settings() -> dict[str, Any]:
    if not SETTINGS_FILE.is_file():
        return dict(DEFAULT_SETTINGS)
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return {**DEFAULT_SETTINGS, **data}
    except Exception:
        return dict(DEFAULT_SETTINGS)


def rvc_tts_engine(
    text: str,
    voice_name: str,
    voice_rate: float,
    voice_file: str,
    voice_volume: float = 1.0,
    video_language: str = "",
    display_text: str | None = None,
) -> Any:
    from edge_tts import SubMaker
    from loguru import logger
    from moviepy.audio.io.AudioFileClip import AudioFileClip

    from akifactory.engine.services.voice import ensure_file_path_exists, populate_legacy_submaker_with_full_text

    if not is_rvc_available():
        logger.error("RVC kullanilamiyor — AkiFactory.bat rvc")
        return None

    # Ekran/altyazi: orijinal; ses: TR rakam genisletmesi (40.000 → kırk bin)
    subtitle_text = prepare_video_script(display_text if display_text is not None else text)
    spoken = _normalize_spoken_for_tts(
        prepare_video_script(text) or text,
        video_language,
        voice_name,
    )
    cfg = read_runtime_settings()
    voice_id = (cfg.get("voice_id") or "").strip() or parse_rvc_voice_id(voice_name)
    voice_meta = get_voice(voice_id)
    edge_src = cfg.get("edge_voice") or (voice_meta.edge_voice if voice_meta else "")
    edge = edge_voice_from_engine_name(edge_src)
    ensure_file_path_exists(voice_file)
    try:
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                generate_rvc_audio(
                    spoken,
                    voice_file,
                    voice_id=voice_id,
                    tts_voice=edge,
                    pitch=int(cfg.get("pitch", DEFAULT_PITCH)),
                    index_rate=float(cfg.get("index_rate", DEFAULT_INDEX_RATE)),
                    voice_rate=voice_rate,
                    voice_volume=voice_volume,
                )
            )
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"RVC TTS hatasi: {e}")
        return None

    if not Path(voice_file).is_file() or Path(voice_file).stat().st_size == 0:
        logger.error("RVC: bos ses dosyasi")
        return None

    try:
        with AudioFileClip(voice_file) as clip:
            duration = float(clip.duration or 0)
    except Exception as e:
        logger.error(f"RVC ses suresi okunamadi: {e}")
        return None

    return populate_legacy_submaker_with_full_text(
        SubMaker(), subtitle_text or spoken, duration
    )


def _normalize_spoken_for_tts(text: str, video_language: str = "", voice_name: str = "") -> str:
    """TR seslendirme — 40.000 → kırk bin (altyazi metnine dokunmaz)."""
    raw = (text or "").strip()
    if not raw:
        return raw
    lang = (video_language or "").strip().lower()
    voice = (voice_name or "").strip().lower()
    is_tr = lang.startswith("tr") or voice.startswith("tr-") or "tr-tr" in voice
    if not is_tr:
        return raw
    try:
        from akifactory.chatterbox_util import normalize_turkish_tts_text

        return normalize_turkish_tts_text(raw) or raw
    except Exception:
        try:
            from akifactory.tts_numbers import expand_numbers_for_turkish_tts

            return expand_numbers_for_turkish_tts(raw) or raw
        except Exception:
            return raw


def apply_rvc_runtime_patch() -> None:
    try:
        from akifactory.engine.services import voice as v
    except ImportError:
        return

    if getattr(v, "_aki_rvc_patched", False):
        return

    from akifactory.tts_common import apply_voice_name_parse_patch

    apply_voice_name_parse_patch()

    _orig = v.tts

    def _tts_patched(
        text: str,
        voice_name: str,
        voice_rate: float,
        voice_file: str,
        voice_volume: float = 1.0,
        video_language: str = "",
    ):
        spoken = _normalize_spoken_for_tts(text, video_language, voice_name)
        if is_rvc_voice(voice_name):
            return rvc_tts_engine(
                spoken,
                voice_name,
                voice_rate,
                voice_file,
                voice_volume=voice_volume,
                video_language=video_language,
                display_text=text,
            )
        return _orig(
            spoken,
            voice_name,
            voice_rate,
            voice_file,
            voice_volume=voice_volume,
            video_language=video_language,
        )

    v.tts = _tts_patched
    v._aki_rvc_patched = True
