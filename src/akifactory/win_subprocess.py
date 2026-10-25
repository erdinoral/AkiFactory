"""Windows konsol flash onleme — nvidia-smi / ffmpeg / MoviePy / Ollama vb."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

_PATCHED = False


def creationflags() -> int:
    if sys.platform != "win32":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def startupinfo_hidden() -> Any:
    """STARTUPINFO — wShowWindow=SW_HIDE (ekstra guvence)."""
    if sys.platform != "win32":
        return None
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        return si
    except Exception:
        return None


def _inject_no_window(kwargs: dict[str, Any]) -> dict[str, Any]:
    if sys.platform != "win32":
        return kwargs
    flags = creationflags()
    if not flags:
        return kwargs

    existing = int(kwargs.get("creationflags") or 0)
    new_console = int(getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
    detached = int(getattr(subprocess, "DETACHED_PROCESS", 0))

    # CREATE_NEW_CONSOLE isteyen cagrilara dokunma
    if new_console and (existing & new_console):
        return kwargs

    # CREATE_NO_WINDOW, DETACHED_PROCESS ile BIRLIKTE YOK SAYILIR (MSDN).
    # Flash olmasin diye DETACHED'i kaldirip NO_WINDOW kullan.
    if detached:
        existing &= ~detached

    kwargs["creationflags"] = existing | flags

    # STARTUPINFO yoksa gizle
    if kwargs.get("startupinfo") is None:
        si = startupinfo_hidden()
        if si is not None:
            kwargs["startupinfo"] = si
    return kwargs


def run(cmd: list[str] | tuple[str, ...], **kwargs: Any) -> subprocess.CompletedProcess:
    """subprocess.run; Windows'ta konsol penceresi acmaz."""
    return subprocess.run(cmd, **_inject_no_window(kwargs))


def popen(cmd: list[str] | tuple[str, ...], **kwargs: Any) -> subprocess.Popen:
    """subprocess.Popen; Windows'ta konsol penceresi acmaz."""
    return subprocess.Popen(cmd, **_inject_no_window(kwargs))


def install_no_console_patch() -> None:
    """
    subprocess.run / Popen cagrilarina CREATE_NO_WINDOW ekle.

    MoviePy, imageio-ffmpeg, motor video.py, RVC ve Ollama cagrilari
    Electron altinda siyah terminal flash etmesin.
    """
    global _PATCHED
    if _PATCHED or sys.platform != "win32":
        return
    if not creationflags():
        return

    _orig_run = subprocess.run
    _orig_popen_init = subprocess.Popen.__init__

    def _run_patched(*args: Any, **kwargs: Any):
        return _orig_run(*args, **_inject_no_window(kwargs))

    def _popen_init_patched(self: Any, *args: Any, **kwargs: Any) -> None:
        _inject_no_window(kwargs)
        _orig_popen_init(self, *args, **kwargs)

    subprocess.run = _run_patched  # type: ignore[assignment]
    subprocess.Popen.__init__ = _popen_init_patched  # type: ignore[method-assign]
    _PATCHED = True
