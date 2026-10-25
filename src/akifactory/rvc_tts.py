"""Edge TTS + RVC pipeline — coklu ses modeli destegi."""

from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path

from akifactory.rvc_registry import (
    DEFAULT_EDGE_VOICE,
    discover_voices,
    get_voice,
    model_paths,
)

DEFAULT_PITCH = 0
DEFAULT_INDEX_RATE = 1.0
# Ham ses yuklemesinde 1.0 genelde robotik/bozuk — kutuphane varsayilani 0.75
FILE_CONVERT_INDEX_RATE = 0.75
# Chatterbox taban ses RVC'ye giderken ust sinir — cizirti azalir, akicilik icin cok dusuk tutma
POST_LOCAL_RVC_INDEX_CAP = 0.68
# Belgeselci / yumusak RVC — index ~0.65 civarinda daha az metalik
DOC_FILTER_RADIUS = 4
DOC_RMS_MIX_RATE = 0.55
DOC_PROTECT = 0.40
DEFAULT_F0_METHOD = "rmvpe"

_tts_instance = None
_tts_instance_key: tuple[str, str, str] | None = None


def rvc_package_installed() -> bool:
    """Paket var mi — GPU/model yuklemeden (config endpoint icin hizli)."""
    import importlib.util

    return importlib.util.find_spec("tts_with_rvc") is not None


def is_rvc_available() -> bool:
    return rvc_package_installed() and bool(discover_voices())


def edge_voice_from_engine_name(voice_name: str) -> str:
    """tr-TR-EmelNeural-Female -> tr-TR-EmelNeural"""
    v = (voice_name or "").strip()
    if v.startswith("rvc:"):
        v = ""
    return (
        v.replace("-Female", "")
        .replace("-Male", "")
        .strip()
        or DEFAULT_EDGE_VOICE
    )


def _get_tts_engine(pth: str, idx: str, f0method: str):
    global _tts_instance, _tts_instance_key
    key = (pth, idx, f0method)
    if _tts_instance is None or _tts_instance_key != key:
        from tts_with_rvc import TTS_RVC

        kwargs: dict = {
            "model_path": pth,
            "f0_method": f0method,
        }
        if idx:
            kwargs["index_path"] = idx
        _tts_instance = TTS_RVC(**kwargs)
        _tts_instance_key = key
    return _tts_instance


def _voice_rate_to_tts_rate(voice_rate: float) -> int:
    return int(round((float(voice_rate or 1.0) - 1.0) * 100))


def _generate_sync(
    text: str,
    output_path: str,
    *,
    voice_id: str | None = None,
    tts_voice: str = DEFAULT_EDGE_VOICE,
    pitch: int = DEFAULT_PITCH,
    index_rate: float = DEFAULT_INDEX_RATE,
    f0method: str = DEFAULT_F0_METHOD,
    voice_rate: float = 1.0,
    voice_volume: float = 1.0,
) -> str:
    voice = get_voice(voice_id)
    if voice:
        pitch = int(pitch if pitch is not None else voice.pitch)
        index_rate = float(index_rate if index_rate is not None else voice.index_rate)
        if not tts_voice or tts_voice == DEFAULT_EDGE_VOICE:
            tts_voice = voice.edge_voice

    pth_path, idx_path = model_paths(voice_id)
    tts = _get_tts_engine(pth_path, idx_path, f0method)
    tts.set_voice(edge_voice_from_engine_name(tts_voice))

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Edge sunucusu ayni ses icin aralikli NoAudioReceived / 403 donebiliyor
    attempts = 5
    for attempt in range(1, attempts + 1):
        try:
            generated = tts(
                text=text.strip(),
                pitch=int(pitch),
                index_rate=float(index_rate),
                tts_rate=_voice_rate_to_tts_rate(voice_rate),
            )
            break
        except Exception as e:
            transient = type(e).__name__ in ("NoAudioReceived", "WSServerHandshakeError", "ClientConnectorError")
            if not transient or attempt == attempts:
                raise
            time.sleep(2 * attempt)
    src = str(generated or out)
    if not Path(src).is_file():
        raise RuntimeError("RVC ses dosyasi uretilemedi")

    if str(out).lower().endswith(".mp3"):
        try:
            from akifactory.tts_common import wav_to_mp3

            if not wav_to_mp3(src, str(out), voice_volume):
                shutil.copy2(src, str(out))
        except Exception:
            shutil.copy2(src, str(out))
    elif Path(src).resolve() != out.resolve():
        shutil.copy2(src, str(out))

    return str(out)


async def generate_rvc_audio(
    text: str,
    output_path: str,
    *,
    voice_id: str | None = None,
    tts_voice: str = DEFAULT_EDGE_VOICE,
    pitch: int = DEFAULT_PITCH,
    index_rate: float = DEFAULT_INDEX_RATE,
    f0method: str = DEFAULT_F0_METHOD,
    voice_rate: float = 1.0,
    voice_volume: float = 1.0,
) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: _generate_sync(
            text,
            output_path,
            voice_id=voice_id,
            tts_voice=tts_voice,
            pitch=pitch,
            index_rate=index_rate,
            f0method=f0method,
            voice_rate=voice_rate,
            voice_volume=voice_volume,
        ),
    )


def _ensure_wav_input(input_path: Path, *, for_voice_convert: bool = False) -> Path:
    """RVC icin WAV — gerekirse ffmpeg ile donustur ve (istege bagli) ses on isle."""
    if input_path.suffix.lower() in (".wav", ".flac") and not for_voice_convert:
        return input_path
    from akifactory.gpu import resolve_ffmpeg_exe

    ffmpeg = resolve_ffmpeg_exe()
    if not ffmpeg:
        if input_path.suffix.lower() in (".wav", ".flac"):
            return input_path
        raise RuntimeError("FFmpeg gerekli — MP3/M4A dosyalari WAV'a cevrilemedi")
    out = input_path.with_suffix(".prep.wav")
    import subprocess

    af = (
        "highpass=f=80,lowpass=f=12000,dynaudnorm=f=150:g=15"
        if for_voice_convert
        else ""
    )
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(input_path),
        "-ac",
        "1",
        "-ar",
        "44100",
    ]
    if af:
        cmd.extend(["-af", af])
    cmd.append(str(out))
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0 or not out.is_file():
        raise RuntimeError(
            (r.stderr or r.stdout or "Ses dosyasi WAV'a cevrilemedi")[:400]
        )
    return out


def prepare_wav_for_rvc_convert(input_path: Path, *, source: str = "generic") -> Path:
    """RVC oncesi yerel TTS ciktisini normalize et — cizirti ve DC offset azaltir."""
    if not input_path.is_file():
        return input_path
    from akifactory.gpu import resolve_ffmpeg_exe

    ffmpeg = resolve_ffmpeg_exe()
    if not ffmpeg:
        return input_path
    if source == "chatterbox":
        af = "highpass=f=90,lowpass=f=11500,dynaudnorm=f=200:g=11"
    else:
        af = "highpass=f=80,lowpass=f=12000,dynaudnorm=f=150:g=15"
    out = input_path.with_suffix(".rvcprep.wav")
    import subprocess

    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(input_path),
        "-ac",
        "1",
        "-ar",
        "44100",
        "-af",
        af,
        str(out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out.is_file():
        return input_path
    return out


def convert_audio_file_sync(
    input_path: str,
    output_path: str,
    *,
    voice_id: str | None = None,
    pitch: int = DEFAULT_PITCH,
    index_rate: float = DEFAULT_INDEX_RATE,
    f0method: str = DEFAULT_F0_METHOD,
) -> str:
    """Mevcut ses dosyasini RVC modeline donustur."""
    voice = get_voice(voice_id)
    if voice:
        pitch = int(pitch if pitch is not None else voice.pitch)
        index_rate = float(index_rate if index_rate is not None else voice.index_rate)

    pth_path, idx_path = model_paths(voice_id)
    tts = _get_tts_engine(pth_path, idx_path, f0method)

    inp = Path(input_path)
    if not inp.is_file():
        raise FileNotFoundError(f"Ses dosyasi bulunamadi: {input_path}")

    work_in = _ensure_wav_input(inp, for_voice_convert=True)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    idx = float(index_rate)
    if idx >= 0.99:
        idx = FILE_CONVERT_INDEX_RATE
    # Yumusak index (belgeselci preset ~0.65) → biraz daha korumali / dogal
    soft = idx <= 0.72
    generated = tts.voiceover_file(
        str(work_in),
        pitch=int(pitch),
        index_rate=idx,
        output_directory=str(out.parent),
        filename=out.name,
        f0method=f0method,
        filter_radius=DOC_FILTER_RADIUS if soft else 3,
        rms_mix_rate=DOC_RMS_MIX_RATE if soft else 0.5,
        protect=DOC_PROTECT if soft else 0.33,
    )
    src = Path(str(generated or out))
    if not src.is_file():
        raise RuntimeError("RVC donusumu basarisiz — cikti dosyasi yok")

    if src.resolve() != out.resolve():
        shutil.copy2(src, out)

    if work_in != inp and work_in.is_file():
        work_in.unlink(missing_ok=True)

    return str(out)


async def convert_audio_file(
    input_path: str,
    output_path: str,
    *,
    voice_id: str | None = None,
    pitch: int = DEFAULT_PITCH,
    index_rate: float = DEFAULT_INDEX_RATE,
    f0method: str = DEFAULT_F0_METHOD,
) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: convert_audio_file_sync(
            input_path,
            output_path,
            voice_id=voice_id,
            pitch=pitch,
            index_rate=index_rate,
            f0method=f0method,
        ),
    )
