"""Ilk kurulum / ortam kontrolu — ffmpeg, Ollama, LLM modeli, stok API."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from akifactory import ollama_util, stock_api_keys
from akifactory.paths import data_dir

SETUP_STATE_FILE = data_dir() / "setup_state.json"
DEFAULT_MODEL = "qwen3.5:9b"

_pull_running = False
_pull_message = ""
_pull_lock = threading.Lock()
_ollama_start_lock = threading.Lock()
_ollama_start_attempted_at = 0.0


def _load_state() -> dict[str, Any]:
    if not SETUP_STATE_FILE.is_file():
        return {}
    try:
        raw = json.loads(SETUP_STATE_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _save_state(**kwargs: Any) -> None:
    state = _load_state()
    state.update(kwargs)
    SETUP_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETUP_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


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


def _ollama_exe() -> str | None:
    return shutil.which("ollama")


def _ollama_app_exe() -> str | None:
    """Windows Ollama tray uygulamasi — `ollama serve` yerine (konsolsuz)."""
    if sys.platform != "win32":
        return None
    names = ("ollama app.exe", "Ollama.exe")
    candidates: list[Path] = []
    exe = _ollama_exe()
    if exe:
        parent = Path(exe).resolve().parent
        for name in names:
            candidates.append(parent / name)
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama"
    for name in names:
        candidates.append(local / name)
    # Eski kurulum yolu
    candidates.append(Path(os.environ.get("LOCALAPPDATA", "")) / "Ollama" / "ollama app.exe")
    seen: set[str] = set()
    for path in candidates:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            return str(path)
    # PATH'te "ollama app.exe"
    found = shutil.which("ollama app.exe")
    return found


def check_ffmpeg() -> tuple[bool, str]:
    from akifactory.gpu import apply_runtime_env, resolve_ffmpeg_exe

    apply_runtime_env()
    exe = resolve_ffmpeg_exe()
    if not exe:
        return False, "ffmpeg yok — otomatik kurulum denenecek"
    if shutil.which("ffmpeg"):
        return True, f"ffmpeg (sistem): {Path(exe).name}"
    return True, f"ffmpeg (paket ici): {Path(exe).name}"


def ensure_ffmpeg(*, install: bool = True) -> tuple[bool, str]:
    ok, msg = check_ffmpeg()
    if ok:
        return True, msg

    if install and sys.platform == "win32" and shutil.which("winget"):
        from akifactory.win_subprocess import run as _run_hidden

        r = _run_hidden(
            [
                "winget",
                "install",
                "--id",
                "Gyan.FFmpeg",
                "-e",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            _refresh_windows_path()
            from akifactory.gpu import apply_runtime_env

            apply_runtime_env()
            ok, msg = check_ffmpeg()
            if ok:
                return True, f"ffmpeg kuruldu — {msg}"

    ok, msg = check_ffmpeg()
    if ok:
        return True, msg
    return (
        False,
        "ffmpeg bulunamadi. winget install Gyan.FFmpeg veya uygulamayi yeniden baslatin.",
    )


def try_start_ollama(*, wait_sec: float = 20.0) -> bool:
    """
    Ollama'yi sessiz baslat.

    Windows: `ollama app.exe --hide --fast-startup` (resmi yol).
    `ollama serve` + DETACHED_PROCESS konsol flash eder — KULLANMA.
    """
    global _ollama_start_attempted_at

    if ollama_util.ping_sync():
        return True

    with _ollama_start_lock:
        # Ayni oturumda 30 sn icinde tekrar Popen etme (surekli flash)
        now = time.time()
        if _ollama_start_attempted_at and (now - _ollama_start_attempted_at) < 30:
            deadline = now + min(wait_sec, 8.0)
            while time.time() < deadline:
                if ollama_util.ping_sync():
                    return True
                time.sleep(0.4)
            return ollama_util.ping_sync()
        _ollama_start_attempted_at = now

    from akifactory.win_subprocess import popen as _popen_hidden

    try:
        if sys.platform == "win32":
            app = _ollama_app_exe()
            if app:
                # Ollama'nin kendi Windows baslaticisi ile ayni bayraklar
                _popen_hidden(
                    [app, "--hide", "--fast-startup"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    close_fds=True,
                )
            else:
                exe = _ollama_exe()
                if not exe:
                    return False
                _popen_hidden(
                    [exe, "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    close_fds=True,
                )
        else:
            exe = _ollama_exe()
            if not exe:
                return False
            subprocess.Popen(
                [exe, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
    except Exception:
        return False

    deadline = time.time() + wait_sec
    while time.time() < deadline:
        if ollama_util.ping_sync():
            return True
        time.sleep(0.5)
    return False


def _model_installed(model: str) -> bool:
    if not ollama_util.ping_sync():
        return False
    try:
        import urllib.request

        with urllib.request.urlopen(ollama_util.OLLAMA_TAGS_URL, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        names = [m.get("name", "") for m in data.get("models") or [] if m.get("name")]
        base = model.split(":")[0]
        return any(n == model or n.startswith(f"{base}:") for n in names)
    except Exception:
        return False


def _mark_ready_if_complete() -> None:
    if not ollama_util.ping_sync():
        return
    model = ollama_util.get_config_model() or DEFAULT_MODEL
    if not _model_installed(model):
        return
    _save_state(setup_completed=True, completed_at=time.strftime("%Y-%m-%d %H:%M:%S"))


def pull_model(model: str | None = None) -> tuple[bool, str]:
    global _pull_running, _pull_message
    m = (model or ollama_util.get_config_model() or DEFAULT_MODEL).strip()
    exe = _ollama_exe()
    if not exe:
        return False, "Ollama kurulu degil — https://ollama.com"
    if not ollama_util.ping_sync() and not try_start_ollama():
        return False, "Ollama baslatilamadi (ollama serve)"
    if _model_installed(m):
        _mark_ready_if_complete()
        return True, f"Model zaten yuklu: {m}"

    with _pull_lock:
        if _pull_running:
            return True, _pull_message or f"Model indiriliyor: {m}"
        _pull_running = True
        _pull_message = f"Model indiriliyor: {m} (~5-9 GB, internet gerekli)"

    try:
        from akifactory.win_subprocess import run as _run_hidden

        r = _run_hidden(
            [exe, "pull", m],
            capture_output=True,
            text=True,
            timeout=7200,
        )
        if r.returncode == 0:
            _save_state(model_pulled=m, model_pulled_at=time.strftime("%Y-%m-%d %H:%M:%S"))
            _mark_ready_if_complete()
            return True, f"Model indirildi: {m}"
        err = (r.stderr or r.stdout or "ollama pull basarisiz").strip()
        return False, err[:400]
    except subprocess.TimeoutExpired:
        return False, "Model indirme zaman asimi"
    except Exception as exc:
        return False, str(exc)
    finally:
        with _pull_lock:
            _pull_running = False
            _pull_message = ""


def start_background_pull(model: str | None = None) -> bool:
    m = (model or ollama_util.get_config_model() or DEFAULT_MODEL).strip()
    if _model_installed(m):
        return False
    with _pull_lock:
        if _pull_running:
            return True

    def _worker() -> None:
        pull_model(m)

    threading.Thread(target=_worker, name="aki-ollama-pull", daemon=True).start()
    return True


async def check_internet() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.head("https://www.microsoft.com")
            return r.status_code < 500
    except Exception:
        return False


def check_gpu() -> dict[str, Any]:
    try:
        from akifactory.gpu import gpu_profile_for_ui

        info = gpu_profile_for_ui()
        return {
            "ok": bool(info.get("gpu_available")),
            "name": info.get("gpu_name") or "",
            "encoder": info.get("video_encoder") or "",
        }
    except Exception:
        return {"ok": False, "name": "", "encoder": ""}


async def fetch_setup_status() -> dict[str, Any]:
    ollama_running = ollama_util.ping_sync()
    model = ollama_util.get_config_model() or DEFAULT_MODEL
    model_installed = _model_installed(model) if ollama_running else False
    gpu = check_gpu()
    internet = await check_internet()
    pexels = await stock_api_keys.test_pexels()
    pixabay = await stock_api_keys.test_pixabay()
    ollama_installed = bool(_ollama_exe())
    ffmpeg_ok, ffmpeg_hint = check_ffmpeg()

    if model_installed and ollama_running and ffmpeg_ok:
        _mark_ready_if_complete()

    checks = {
        "ffmpeg": {
            "ok": ffmpeg_ok,
            "label": "ffmpeg (video / ses)",
            "hint": ffmpeg_hint if ffmpeg_ok else "Ilk acilista otomatik kurulur",
        },
        "ollama_installed": {
            "ok": ollama_installed,
            "label": "Ollama kurulu",
            "hint": "" if ollama_installed else "https://ollama.com adresinden kurun",
        },
        "ollama_running": {
            "ok": ollama_running,
            "label": "Ollama calisiyor",
            "hint": "" if ollama_running else "Otomatik baslatilir",
        },
        "llm_model": {
            "ok": model_installed,
            "label": f"LLM modeli ({model})",
            "hint": "" if model_installed else "Ilk acilista otomatik indirilir",
        },
        "gpu": {
            "ok": gpu["ok"],
            "label": "NVIDIA GPU (CUDA)",
            "hint": gpu["name"] if gpu["ok"] else "GPU yok — CPU modu (daha yavas)",
        },
        "internet": {
            "ok": internet,
            "label": "Internet (Edge TTS / stok / model)",
            "hint": "" if internet else "Model indirme ve TTS icin gerekli",
        },
        "pexels_api": {
            "ok": bool(pexels.get("ok")),
            "label": "Pexels API",
            "hint": "" if pexels.get("ok") else (pexels.get("error") or "Ayarlar → Stok API"),
        },
        "pixabay_api": {
            "ok": bool(pixabay.get("ok")),
            "label": "Pixabay API",
            "hint": "" if pixabay.get("ok") else (pixabay.get("error") or "Ayarlar → Stok API"),
        },
    }
    required_ok = (
        checks["ffmpeg"]["ok"]
        and checks["ollama_running"]["ok"]
        and checks["llm_model"]["ok"]
        and checks["pexels_api"]["ok"]
    )
    return {
        "checks": checks,
        "ready": required_ok,
        "model_name": model,
        "pull_running": _pull_running,
        "pull_message": _pull_message,
        "setup_completed": bool(_load_state().get("setup_completed")),
    }


async def run_setup(
    *,
    start_ollama: bool = True,
    pull_model_flag: bool = True,
    install_ffmpeg: bool = True,
) -> dict[str, Any]:
    messages: list[str] = []

    if install_ffmpeg:
        ok_ff, msg_ff = await asyncio.to_thread(ensure_ffmpeg)
        messages.append(msg_ff)
        if not ok_ff:
            status = await fetch_setup_status()
            status["messages"] = messages
            status["ok"] = False
            return status

    if start_ollama:
        if try_start_ollama():
            messages.append("Ollama baslatildi")
        elif ollama_util.ping_sync():
            messages.append("Ollama zaten calisiyor")
        else:
            messages.append("Ollama baslatilamadi — https://ollama.com kurulu mu?")

    stock_api_keys.sync_engine_config()
    messages.append("Stok API anahtarlari senkronlandi")

    model = ollama_util.get_config_model() or DEFAULT_MODEL
    if pull_model_flag and ollama_util.ping_sync():
        if _model_installed(model):
            messages.append(f"Model zaten yuklu: {model}")
            _mark_ready_if_complete()
        elif start_background_pull(model):
            messages.append(f"Model arka planda indiriliyor: {model}")
        else:
            messages.append("Model indirme baslatilamadi")

        try:
            from akifactory.llm_profiles import EDITOR_DEFAULT

            editor_model = EDITOR_DEFAULT
            if editor_model != model and not _model_installed(editor_model):
                if start_background_pull(editor_model):
                    messages.append(f"Editor modeli arka planda indiriliyor: {editor_model}")
        except Exception:
            pass

    status = await fetch_setup_status()
    status["messages"] = messages
    status["ok"] = bool(status.get("ready") or status.get("pull_running"))
    return status
