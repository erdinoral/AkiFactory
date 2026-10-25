"""Uygulama yollari — gelistirme ve ileride EXE icin tek kaynak."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def is_packaged_runtime() -> bool:
    """Electron paket / portable: resources altinda python-base + .venv."""
    if os.environ.get("AKI_PACKAGED", "").strip() in ("1", "true", "yes"):
        return True
    root = app_root()
    return (root / "python-base" / "python.exe").is_file() and (
        root / ".venv" / "Scripts" / "python.exe"
    ).is_file()


def data_dir() -> Path:
    """Kullanici verisi — pakette LOCALAPPDATA (Program Files yazma sorununu onler)."""
    env = (os.environ.get("AKI_DATA_DIR") or "").strip()
    if env:
        d = Path(env)
        d.mkdir(parents=True, exist_ok=True)
        return d
    if is_packaged_runtime():
        local = (os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or "").strip()
        if local:
            d = Path(local) / "AkiFactory" / "data"
            d.mkdir(parents=True, exist_ok=True)
            return d
    d = app_root() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def gallery_dir() -> Path:
    d = data_dir() / "gallery"
    d.mkdir(parents=True, exist_ok=True)
    return d


def voice_convert_dir() -> Path:
    d = data_dir() / "voice_convert"
    d.mkdir(parents=True, exist_ok=True)
    return d


def analysis_dir() -> Path:
    d = data_dir() / "analysis"
    d.mkdir(parents=True, exist_ok=True)
    return d


def engine_config_file() -> Path:
    """Video motoru ayarlari (API anahtarlari icerir — data/ git disi)."""
    return data_dir() / "engine.toml"


def engine_storage_dir() -> Path:
    """Motor gorev ciktilari, stok video onbellegi, yerel klipler."""
    d = data_dir() / "storage"
    d.mkdir(parents=True, exist_ok=True)
    return d


def engine_task_dir(task_id: str) -> Path:
    return engine_storage_dir() / "tasks" / task_id


def resource_dir() -> Path:
    """Altyazi fontlari, motor BGM kopyalari, statik sayfa."""
    return app_root() / "resource"


def models_dir() -> Path:
    """Whisper, Chatterbox, RVC modelleri."""
    return app_root() / "models"


def src_dir() -> Path:
    """motor alt sureci icin akifactory kaynak agaci (EXE paketinde src/ kopyalanir)."""
    root = app_root()
    bundled = root / "src"
    if bundled.is_dir():
        return bundled
    dev = Path(__file__).resolve().parents[1]
    if dev.is_dir() and (dev / "akifactory").is_dir():
        return dev
    return bundled


def app_icon_path() -> Path | None:
    """Windows .ico — masaustu penceresi ve EXE."""
    p = app_root() / "assets" / "akifactory.ico"
    return p if p.is_file() else None


def web_icon_path() -> Path | None:
    p = app_root() / "web" / "assets" / "icon.png"
    return p if p.is_file() else None
