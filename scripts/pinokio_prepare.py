"""Validate the installed base; reset is recoverable and preserves user files."""
import argparse
import importlib
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    marker = ROOT / ".aki_pinokio_installed"
    if args.reset:
        import pinokio_run
        if pinokio_run.existing_url():
            raise SystemExit("AkiFactory acik. Once uygulamayi ve uretimleri durdurun.")
        env = (ROOT / ".venv").resolve()
        if env.parent != ROOT.resolve() or env.name != ".venv":
            raise SystemExit("Beklenmeyen ortam yolu")
        backup = ROOT / (".venv-backup-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        # Windows allows renaming the environment directory without deleting its contents.
        env.rename(backup)
        marker.unlink(missing_ok=True)
        print(f"Ortam yedeklendi: {backup.name}. Kur / Onar ile tekrar kurun.")
        return
    if not (3, 11) <= sys.version_info[:2] < (3, 13):
        raise SystemExit("Python 3.11 veya 3.12 gerekli")
    for module in ("fastapi", "uvicorn", "edge_tts", "moviepy", "httpx", "faster_whisper", "turkish.deasciifier"):
        importlib.import_module(module)
    from akifactory.gpu import resolve_ffmpeg_exe
    if not resolve_ffmpeg_exe():
        raise SystemExit("FFmpeg bulunamadi; imageio-ffmpeg veya Pinokio FFmpeg kurulumu gerekli")
    for script in ("apply_config.py", "sync_version.py"):
        subprocess.run([sys.executable, str(ROOT / "scripts" / script)], cwd=ROOT, check=True)
    marker.write_text("ok", encoding="utf-8")
    print("AkiFactory temel kurulumu hazir. API anahtarlarini ve LLM secimini Ayarlar'dan yapin.")


if __name__ == "__main__":
    main()
