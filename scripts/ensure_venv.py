"""
AkiFactory .venv onarici — bozuk veya eski kullanici yolundaki venv'yi duzeltir.

Windows'ta kullanici adinda Turkce karakter (ERDIN vs ERDİN) veya Python kaldirilip
yeniden kurulunca venv python.exe su hatayi verir:
  No Python at 'C:\\Users\\ERD?N\\...\\python.exe'
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _venv_py(root: Path) -> Path:
    return root / ".venv" / "Scripts" / "python.exe"


def _venv_works(py: Path) -> bool:
    if not py.is_file():
        return False
    try:
        r = subprocess.run(
            [str(py), "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _find_base_python() -> Path | None:
    candidates: list[Path] = []

    for name in ("py", "python", "python3"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    profile = Path(os.environ.get("USERPROFILE", ""))
    if profile.is_dir():
        for minor in (12, 11):
            candidates.append(
                profile / "AppData" / "Local" / "Programs" / "Python" / f"Python3{minor}" / "python.exe"
            )

    for py in candidates:
        if not py.is_file():
            continue
        try:
            r = subprocess.run(
                [str(py), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode != 0:
            continue
        ver = (r.stdout or "").strip()
        if ver in ("3.11", "3.12"):
            return py.resolve()
    return None


def _patch_pyvenv_cfg(root: Path, base_py: Path) -> bool:
    cfg = root / ".venv" / "pyvenv.cfg"
    if not cfg.is_file():
        return False
    home = base_py.parent
    lines: list[str] = []
    for line in cfg.read_text(encoding="utf-8").splitlines():
        if line.startswith("home = "):
            lines.append(f"home = {home}")
        elif line.startswith("executable = "):
            lines.append(f"executable = {base_py}")
        else:
            lines.append(line)
    cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def _recreate_venv(root: Path, base_py: Path) -> bool:
    venv_dir = root / ".venv"
    broken = venv_dir.with_name(".venv.broken")
    if venv_dir.is_dir():
        if broken.is_dir():
            shutil.rmtree(broken, ignore_errors=True)
        try:
            venv_dir.rename(broken)
        except OSError:
            shutil.rmtree(venv_dir, ignore_errors=True)
    r = subprocess.run([str(base_py), "-m", "venv", str(venv_dir)], cwd=str(root))
    if r.returncode != 0:
        return False
    req = root / "requirements.txt"
    if req.is_file():
        subprocess.run([str(_venv_py(root)), "-m", "pip", "install", "-U", "pip"], cwd=str(root))
        subprocess.run([str(_venv_py(root)), "-m", "pip", "install", "-r", str(req)], cwd=str(root))
    return _venv_works(_venv_py(root))


def main() -> int:
    root = _root()
    py = _venv_py(root)
    if _venv_works(py):
        return 0

    print("[venv] Mevcut .venv calismiyor, onariliyor...", flush=True)
    base = _find_base_python()
    if base is None:
        print(
            "[HATA] Python 3.11 veya 3.12 bulunamadi.\n"
            "  Kurulum: https://www.python.org/downloads/\n"
            "  veya: winget install Python.Python.3.12\n"
            "  Kurulumda 'Add python.exe to PATH' secenegini isaretleyin.",
            flush=True,
        )
        return 1

    print(f"[venv] Temel Python: {base}", flush=True)
    if py.is_file() and _patch_pyvenv_cfg(root, base) and _venv_works(py):
        print("[venv] pyvenv.cfg guncellendi, .venv hazir.", flush=True)
        return 0

    print("[venv] pyvenv yolu yetersiz, .venv yeniden olusturuluyor (pip kurulumu uzun surebilir)...", flush=True)
    if _recreate_venv(root, base):
        print("[venv] Yeni .venv hazir.", flush=True)
        return 0

    print("[HATA] .venv onarilamadi.", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
