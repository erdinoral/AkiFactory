"""RVC Mazlum Kiper model kurulumu — yerel kopya veya Hugging Face."""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RVC_DIR = ROOT / "models" / "rvc"
MODEL_DIR = RVC_DIR / "MazlumKiper"
LOCAL_SRC = ROOT / "MazlumKiper"
HF_REPO = "ailabturkiye/Hagrid_Mazlum_Kiper"
ZIP_FILENAME = "MazlumKiper.zip"


def _pip(pkg: str) -> bool:
    print(f"[RVC] pip install {pkg}...")
    return (
        subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg],
            cwd=str(ROOT),
        ).returncode
        == 0
    )


def _flatten_nested(base: Path) -> None:
    nested = [d for d in base.iterdir() if d.is_dir()]
    if len(nested) != 1:
        return
    inner = nested[0]
    for f in inner.iterdir():
        dest = base / f.name
        if dest.exists():
            continue
        shutil.move(str(f), str(dest))
    try:
        inner.rmdir()
    except OSError:
        pass


def _copy_local_models() -> bool:
    if not LOCAL_SRC.is_dir():
        return False
    pth_files = list(LOCAL_SRC.glob("*.pth"))
    if not pth_files:
        return False
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for f in LOCAL_SRC.iterdir():
        if f.is_file() and f.suffix.lower() in (".pth", ".index"):
            dest = MODEL_DIR / f.name
            if not dest.exists() or dest.stat().st_size != f.stat().st_size:
                shutil.copy2(f, dest)
                print(f"[RVC] Kopyalandi: {f.name}")
    return bool(list(MODEL_DIR.glob("*.pth")))


def _download_hf() -> bool:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        if not _pip("huggingface_hub"):
            return False
        from huggingface_hub import hf_hub_download

    print("[RVC] Hugging Face'den model indiriliyor (~84 MB)...")
    zip_path = hf_hub_download(
        repo_id=HF_REPO,
        filename=ZIP_FILENAME,
        local_dir=str(RVC_DIR),
    )
    print("[RVC] ZIP aciliyor...")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(MODEL_DIR)
    _flatten_nested(MODEL_DIR)
    Path(zip_path).unlink(missing_ok=True)
    return bool(list(MODEL_DIR.glob("*.pth")))


def setup_rvc() -> int:
    print("[RVC] Klasor yapisi olusturuluyor...")
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    if list(MODEL_DIR.glob("*.pth")):
        print("[RVC] Model zaten models/rvc/MazlumKiper/ icinde.")
    elif _copy_local_models():
        print("[RVC] Kok klasordeki MazlumKiper/ modeli kopyalandi.")
    elif not _download_hf():
        print("[RVC] Model bulunamadi.")
        print("      Kok klasore MazlumKiper/*.pth koyun veya internet ile tekrar deneyin.")
        return 1

    try:
        import tts_with_rvc  # noqa: F401
    except ImportError:
        if not _pip("tts-with-rvc"):
            print("[RVC] tts-with-rvc kurulamadi.")
            return 1

    pth_files = list(MODEL_DIR.glob("*.pth"))
    idx_files = list(MODEL_DIR.glob("*.index"))
    print("[RVC] Kurulum tamamlandi:")
    print(f"  Model : {pth_files[0].name if pth_files else 'BULUNAMADI'}")
    print(f"  Index : {idx_files[0].name if idx_files else 'yok (opsiyonel)'}")

    try:
        import sys

        sys.path.insert(0, str(ROOT / "src"))
        from akifactory.rvc_registry import discover_voices

        voices = discover_voices()
        if voices:
            print("[RVC] Kayitli sesler:")
            for v in voices:
                mark = " (varsayilan)" if v.default else ""
                print(f"  - {v.label} [{v.id}]{mark}")
        print(f"[RVC] Yeni ses: {RVC_DIR}/<SesAdi>/ klasorune .pth koy, uygulamayi yenile.")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(setup_rvc())
