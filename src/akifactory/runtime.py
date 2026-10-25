"""Frozen EXE / gelistirme ortami — Python yolu cozumleme."""

from __future__ import annotations

import sys
from pathlib import Path

from akifactory.paths import app_root


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def venv_python(root: Path | None = None) -> Path:
    """Proje kokundeki .venv Python (motor alt sureci icin)."""
    base = root or app_root()
    py = base / ".venv" / "Scripts" / "python.exe"
    if not py.is_file():
        raise FileNotFoundError(
            f"Python ortami bulunamadi: {py}\n"
            "Once AkiFactory.bat ile kurulum yapin."
        )
    return py


def python_for_subprocess(root: Path | None = None) -> str:
    """Alt surec (video motoru) icin kullanilacak python.exe yolu."""
    if is_frozen():
        return str(venv_python(root))
    return sys.executable
