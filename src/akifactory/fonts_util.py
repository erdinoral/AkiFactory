"""Altyazi icin Latin/Turkce uyumlu font (sistem fontundan kopya; repoya font girmez)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from akifactory.paths import resource_dir

_FONT_NAME = "AkiFactory-Subtitle.ttf"


def _system_font_candidates() -> list[Path]:
    win = Path(os.environ.get("WINDIR", r"C:\Windows"))
    return [
        win / "Fonts" / "segoeui.ttf",
        win / "Fonts" / "arial.ttf",
        win / "Fonts" / "calibri.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
        Path("/usr/share/fonts/noto/NotoSans-Regular.ttf"),
        Path("/Library/Fonts/Arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    ]


def ensure_subtitle_font(lang_id: str | None = None) -> str:
    """motor resource/fonts altina Turkce karakter destekli font koyar."""
    fonts_dir = resource_dir() / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    target = fonts_dir / _FONT_NAME
    if target.is_file():
        return _FONT_NAME

    for src in _system_font_candidates():
        if src.is_file():
            shutil.copy2(src, target)
            return _FONT_NAME

    return _FONT_NAME
