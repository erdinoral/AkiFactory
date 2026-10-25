"""
AkiFactory on kontrolu — PC formati / eksik kurulum sonrasi dogrulama.

  python launch_preflight.py
  python launch_preflight.py --auto-install
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

REQ_FILE = "requirements.txt"
CONFIG_FILE = "engine.toml"

# Motor + arayuz icin zorunlu (streamlit artik kullanilmiyor)
CRITICAL_IMPORTS: tuple[tuple[str, str], ...] = (
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("edge_tts", "edge_tts"),
    ("moviepy", "moviepy"),
    ("loguru", "loguru"),
    ("httpx", "httpx"),
    ("faster_whisper", "faster-whisper"),
    ("pydub", "pydub"),
)


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _p(msg: str) -> None:
    print(msg, flush=True)


def _engine_dir() -> Path:
    return _root() / "src" / "akifactory" / "engine"


def _ensure_import_path() -> None:
    src = _root() / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


def _refresh_windows_path() -> None:
    if sys.platform != "win32":
        return
    try:
        import winreg
    except ImportError:
        return
    parts: list[str] = []
    for hive, subkey in (
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        (winreg.HKEY_CURRENT_USER, r"Environment"),
    ):
        try:
            with winreg.OpenKey(hive, subkey) as key:
                val, _ = winreg.QueryValueEx(key, "Path")
                if val:
                    parts.append(str(val))
        except OSError:
            pass
    if parts:
        os.environ["Path"] = ";".join(parts)


def _pip_install_requirements(req: Path) -> bool:
    _p(f"[auto] pip install -r {req}")
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    if subprocess.run(
        [sys.executable, "-m", "pip", "install", "-U", "pip"],
        cwd=str(_root()),
        env=env,
    ).returncode != 0:
        return False
    return (
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req)],
            cwd=str(_root()),
            env=env,
        ).returncode
        == 0
    )


def _check_python_version() -> tuple[bool, str]:
    v = sys.version_info
    if v.major == 3 and 11 <= v.minor < 13:
        return True, f"Python {v.major}.{v.minor}.{v.micro}"
    return (
        False,
        f"Python {v.major}.{v.minor} — 3.11 veya 3.12 gerekli (AkiFactory.bat .venv olusturur)",
    )


def _check_venv() -> tuple[bool, str]:
    root = _root()
    py = root / ".venv" / "Scripts" / "python.exe"
    if py.is_file():
        return True, f".venv OK ({py.parent.parent.name})"
    return False, ".venv yok — AkiFactory.bat otomatik olusturur; once calistirin"


def _check_engine_tree() -> tuple[bool, str]:
    server_py = _engine_dir() / "server.py"
    req = _root() / REQ_FILE
    if not server_py.is_file():
        return False, f"Video motoru eksik (beklenen: {server_py}) — uygulamayi yeniden indirin"
    if not req.is_file():
        return False, f"{REQ_FILE} bulunamadi: {req}"
    return True, "Video motoru OK"


def _missing_critical_imports() -> list[str]:
    missing: list[str] = []
    for mod, label in CRITICAL_IMPORTS:
        if importlib.util.find_spec(mod) is None:
            missing.append(label)
    return missing


def _ensure_critical_packages(auto: bool) -> tuple[bool, str]:
    missing = _missing_critical_imports()
    if not missing:
        return True, f"Python paketleri OK ({len(CRITICAL_IMPORTS)} kontrol)"
    if not auto:
        return (
            False,
            "Eksik paketler: " + ", ".join(missing) + f"\n  pip install -r {_root() / REQ_FILE}",
        )
    req = _root() / REQ_FILE
    if not _pip_install_requirements(req):
        return False, "pip kurulumu basarisiz"
    missing = _missing_critical_imports()
    if missing:
        return False, "Hala eksik: " + ", ".join(missing)
    return True, "Python paketleri kuruldu"


def _ensure_ffmpeg(auto: bool) -> tuple[bool, str]:
    _ensure_import_path()
    from akifactory.gpu import resolve_ffmpeg_exe

    exe = resolve_ffmpeg_exe()
    if exe:
        return True, f"ffmpeg OK ({exe})"

    if auto and sys.platform == "win32" and shutil.which("winget"):
        _p("[auto] ffmpeg kuruluyor (winget Gyan.FFmpeg)...")
        r = subprocess.run(
            [
                "winget",
                "install",
                "--id",
                "Gyan.FFmpeg",
                "-e",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ],
            cwd=str(_root()),
        )
        if r.returncode == 0:
            _refresh_windows_path()
            exe = resolve_ffmpeg_exe()
            if exe:
                return True, f"ffmpeg kuruldu ({exe})"

    return (
        False,
        "ffmpeg YOK — RVC ses ve video birlestirme icin gerekli.\n"
        "  winget install Gyan.FFmpeg\n"
        "  veya AkiFactory.bat penceresini kapatip yeniden acin (PATH guncellenir)",
    )


def _check_ollama() -> tuple[str, bool]:
    """Mesaj + kritik mi (False = sadece uyari)."""
    _ensure_import_path()
    try:
        from akifactory.ollama_util import get_config_model, ping_sync
    except Exception as exc:
        return f"Ollama modulu yuklenemedi: {exc}", False

    if not ping_sync():
        return (
            "Ollama calismiyor — video senaryosu icin ayri terminalde: ollama serve\n"
            "  Indir: https://ollama.com  sonra: ollama pull qwen3.5:9b",
            False,
        )

    model = (get_config_model() or "qwen3.5:9b").strip()
    try:
        import httpx

        r = httpx.get("http://127.0.0.1:11434/api/tags", timeout=5.0)
        names: set[str] = set()
        if r.status_code == 200:
            for item in r.json().get("models") or []:
                n = (item.get("name") or "").strip()
                if n:
                    names.add(n)
                    names.add(n.split(":")[0])
        if model not in names and not any(n.startswith(model.split(":")[0]) for n in names):
            return (
                f"Ollama acik ama model yok: {model}\n"
                f"  Terminal: ollama pull {model}",
                False,
            )
        return f"Ollama + model {model} OK", True
    except Exception as exc:
        return f"Ollama model listesi alinamadi: {exc}", False


def _check_gpu() -> str:
    _ensure_import_path()
    try:
        from akifactory.gpu import gpu_profile_for_ui

        info = gpu_profile_for_ui()
        if info.get("gpu_available"):
            name = info.get("gpu_name") or "NVIDIA"
            enc = info.get("video_encoder") or "?"
            wh = info.get("whisper_device") or "?"
            return f"GPU: {name} | encode {enc} | Whisper {wh}"
        return "GPU yok — CPU modu (yavas ama calisir)"
    except Exception:
        return "GPU kontrolu atlandi"


def _check_rvc() -> str:
    _ensure_import_path()
    try:
        import tts_with_rvc  # noqa: F401
    except ImportError:
        return (
            "RVC paketi yok — Tamer Karadagli sesi calismaz.\n"
            "  AkiFactory.bat rvc"
        )

    try:
        from akifactory.rvc_registry import discover_voices
        from akifactory.rvc_tts import is_rvc_available

        if not is_rvc_available():
            return (
                "RVC modeli yok — models/rvc/ altinda .pth gerekli.\n"
                "  AkiFactory.bat rvc"
            )
        voices = discover_voices()
        ids = ", ".join(v.id for v in voices[:4])
        extra = f" (+{len(voices) - 4})" if len(voices) > 4 else ""
        return f"RVC OK — {ids}{extra}"
    except Exception as exc:
        return f"RVC kontrolu: {exc}"


def _check_local_models() -> str:
    marker = _root() / ".aki_kuruldu"
    whisper = _root() / "models" / "whisper-large-v3" / "model.bin"
    if marker.is_file() and whisper.is_file():
        return "Yerel modeller (Whisper) OK"
    if whisper.is_file():
        return "Whisper modeli var — tam kurulum: AkiFactory.bat kur"
    return "Whisper henuz kurulmadi — opsiyonel: AkiFactory.bat kur"


def _check_config() -> str:
    cfg = _root() / "data" / CONFIG_FILE
    if not cfg.is_file():
        if (_engine_dir() / "config.example.toml").is_file():
            return f"{CONFIG_FILE} yok — apply_config olusturacak"
        return "engine.toml / config.example.toml eksik"
    text = cfg.read_text(encoding="utf-8", errors="replace")
    if "pexels_api_keys = []" in text or 'pexels_api_keys = [""]' in text:
        return f"{CONFIG_FILE} OK — Pexels anahtari bos olabilir (stok video)"
    return f"{CONFIG_FILE} OK"


def _ensure_turkish_deasciifier(auto: bool) -> None:
    if importlib.util.find_spec("turkish") is not None:
        _p("[OK] turkish-deasciifier")
        return
    if not auto:
        _p(
            "[UYARI] turkish-deasciifier yok — Turkce s/c/g duzeltmesi zayif.\n"
            "  pip install git+https://github.com/emres/turkish-deasciifier.git"
        )
        return
    _p("[auto] turkish-deasciifier kuruluyor...")
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    ok = (
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "git+https://github.com/emres/turkish-deasciifier.git",
            ],
            cwd=str(_root()),
            env=env,
        ).returncode
        == 0
    )
    _p(("[OK] " if ok else "[UYARI] ") + "turkish-deasciifier")


def _print_summary(*, fails: list[str], warns: list[str]) -> None:
    _p("")
    _p("=== Ozet ===")
    if fails:
        _p(f"[HATA] {len(fails)} kritik sorun — uygulama baslatilmayacak:")
        for item in fails:
            for line in item.splitlines():
                _p(f"  • {line}")
    if warns:
        _p(f"[UYARI] {len(warns)} konu (uygulama yine acilir):")
        for item in warns:
            for line in item.splitlines():
                _p(f"  • {line}")
    if not fails and not warns:
        _p("[OK] Tum kontroller gecti.")
    _p("")
    if not fails:
        _p("Devam: motor + arayuz aciliyor...")
        _p("Tarayici: http://127.0.0.1:7860 | Motor API: :8080")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--auto-install",
        action="store_true",
        help="Eksik pip paketleri ve ffmpeg (winget) kur",
    )
    args = ap.parse_args()
    auto = args.auto_install

    os.chdir(_root())
    _ensure_import_path()

    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except Exception:
        pass

    fails: list[str] = []
    warns: list[str] = []

    _p("=== AkiFactory sistem dogrulamasi ===")
    _p("(Format sonrasi eksikleri burada gorursunuz)")
    _p("")

    ok_py, msg_py = _check_python_version()
    _p(("[OK] " if ok_py else "[HATA] ") + msg_py)
    if not ok_py:
        fails.append(msg_py)

    ok_venv, msg_venv = _check_venv()
    _p(("[OK] " if ok_venv else "[i] ") + msg_venv)
    if not ok_venv:
        warns.append(msg_venv)

    ok_engine, msg_engine = _check_engine_tree()
    _p(("[OK] " if ok_engine else "[HATA] ") + msg_engine)
    if not ok_engine:
        fails.append(msg_engine)

    ok_pkg, msg_pkg = _ensure_critical_packages(auto=auto)
    _p(("[OK] " if ok_pkg else "[HATA] ") + msg_pkg)
    if not ok_pkg:
        fails.append(msg_pkg)

    ok_ff, msg_ff = _ensure_ffmpeg(auto=auto)
    _p(("[OK] " if ok_ff else "[HATA] ") + msg_ff)
    if not ok_ff:
        fails.append(msg_ff)

    _p("[i] " + _check_config())

    msg_ol, ol_ok = _check_ollama()
    _p(("[OK] " if ol_ok else "[UYARI] ") + msg_ol.replace("\n", " | "))
    if not ol_ok:
        warns.append(msg_ol)

    _p("[i] " + _check_gpu())

    rvc_msg = _check_rvc()
    rvc_ok = rvc_msg.startswith("RVC OK")
    _p(("[OK] " if rvc_ok else "[UYARI] ") + rvc_msg.replace("\n", " | "))
    if not rvc_ok:
        warns.append(rvc_msg)

    _p("[i] " + _check_local_models())

    _ensure_turkish_deasciifier(auto=auto)

    _print_summary(fails=fails, warns=warns)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
