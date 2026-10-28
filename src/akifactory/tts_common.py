"""Yerel TTS motorlarinin (RVC, Chatterbox) ortak yardimcilari."""

from __future__ import annotations

import os
import shutil
import subprocess

from loguru import logger


def wav_to_mp3(wav_path: str, mp3_path: str, voice_volume: float) -> bool:
    try:
        from pydub import AudioSegment

        seg = AudioSegment.from_wav(wav_path)
        if voice_volume != 1.0:
            seg = seg + (20 * (voice_volume - 1.0))
        # 24 kHz mono girdide pydub varsayilani 32 kb/s'e duser
        seg.export(mp3_path, format="mp3", bitrate="192k")
        return True
    except Exception as e:
        logger.warning(f"pydub mp3 donusumu basarisiz: {e}")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", wav_path, "-q:a", "4", mp3_path],
            check=True,
            capture_output=True,
        )
        return os.path.isfile(mp3_path) and os.path.getsize(mp3_path) > 0
    except Exception as e:
        logger.warning(f"ffmpeg mp3 donusumu basarisiz: {e}")
        return False


def apply_voice_name_parse_patch() -> None:
    """rvc:/chatterbox:/voicestudio: seslerinde -Male/-Female kirpma — yanlis konusmaci onleme."""
    try:
        from akifactory.engine.services import voice as v
    except ImportError:
        return
    if getattr(v, "_aki_parse_patched", False):
        return
    _orig = v.parse_voice_name

    def _parse_voice_name_safe(name: str) -> str:
        n = (name or "").strip()
        if n.startswith(("rvc:", "chatterbox:", "voicestudio:")):
            return n
        return _orig(n)

    v.parse_voice_name = _parse_voice_name_safe
    v._aki_parse_patched = True
