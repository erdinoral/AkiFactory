"""
AkiFactory kurulum yardimcisi — opsiyonel alt komutlar.

Normal kullanim: AkiFactory.bat (otomatik kurulum + Electron).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _p(msg: str) -> None:
    print(msg, flush=True)


def _run(script: str, *args: str) -> int:
    path = _root() / "scripts" / script
    if not path.is_file():
        _p(f"[HATA] {path} yok")
        return 1
    return subprocess.run(
        [sys.executable, "-u", str(path), *args],
        cwd=str(_root()),
    ).returncode


def _marker() -> Path:
    return _root() / ".aki_kuruldu"


def cmd_update() -> int:
    root = _root()
    if not (root / ".git").is_dir():
        _p("[HATA] AkiFactory klasoru git deposu degil — guncelleme icin yeniden indirin")
        return 1
    _p("[guncelle] AkiFactory...")
    code = subprocess.run(["git", "pull", "--ff-only"], cwd=str(root)).returncode
    if code != 0:
        return code
    return subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(root / "requirements.txt")],
        cwd=str(root),
    ).returncode


def cmd_kur() -> int:
    _p("[1/3] Bagimlilik kontrolu...")
    if _run("launch_preflight.py", "--auto-install") != 0:
        return 1
    _p("[2/3] engine.toml...")
    if _run("apply_config.py") != 0:
        return 1
    _p("[3/3] Yerel modeller (Whisper)...")
    code = _run("setup_local.py")
    _run("sync_gpu.py")
    if code == 0:
        _marker().write_text("ok", encoding="utf-8")
    return code


def cmd_chatterbox() -> int:
    return _run("setup_chatterbox.py")


def cmd_rvc() -> int:
    return _run("setup_rvc.py")


def cmd_crawl4ai() -> int:
    return _run("setup_crawl4ai.py")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="AkiFactory kurulum yardimcisi (normal: AkiFactory.bat)"
    )
    ap.add_argument("--kur", action="store_true", help="Tam kurulum")
    ap.add_argument("--guncelle", action="store_true", help="AkiFactory git pull + bagimliliklar")
    ap.add_argument(
        "--chatterbox",
        action="store_true",
        help="Chatterbox Multilingual (TR) + RVC tabani",
    )
    ap.add_argument("--rvc", action="store_true", help="RVC paketi")
    ap.add_argument(
        "--crawl4ai",
        action="store_true",
        help="Crawl4AI — senaryo web arastirmasini derinlestir (opsiyonel)",
    )
    args = ap.parse_args()

    if args.guncelle:
        return cmd_update()
    if args.rvc:
        return cmd_rvc()
    if args.chatterbox:
        return cmd_chatterbox()
    if args.crawl4ai:
        return cmd_crawl4ai()
    if args.kur:
        return cmd_kur()

    ap.print_help()
    _p("\nNormal kullanim: AkiFactory.bat")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
