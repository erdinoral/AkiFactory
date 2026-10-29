"""EXE / splash icin tam baslangic — kontroller, motor, arayuz sunucusu."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ProgressFn = Callable[[str, int], None]

UI_HOST = os.environ.get("AKI_UI_HOST", "127.0.0.1")
UI_PORT_DEFAULT = int(os.environ.get("AKI_UI_PORT", "7860"))


@dataclass
class BootResult:
    ok: bool
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    api_proc: subprocess.Popen | None = None
    ui_host: str = UI_HOST
    ui_port: int = UI_PORT_DEFAULT
    engine_api: str = ""


def _venv_python(root: Path) -> Path | None:
    py = root / ".venv" / "Scripts" / "python.exe"
    return py if py.is_file() else None


def _run_apply_config(root: Path) -> bool:
    script = root / "scripts" / "apply_config.py"
    py = _venv_python(root) or Path(sys.executable)
    if not script.is_file():
        return (root / "data" / "engine.toml").is_file()
    try:
        from akifactory.win_subprocess import run as _run_hidden

        r = _run_hidden(
            [str(py), "-u", str(script)],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=120,
        )
        return r.returncode == 0
    except Exception:
        return (root / "data" / "engine.toml").is_file()


def _run_sync_gpu(root: Path) -> None:
    script = root / "scripts" / "sync_gpu.py"
    py = _venv_python(root) or Path(sys.executable)
    if not script.is_file():
        return
    try:
        from akifactory.win_subprocess import run as _run_hidden

        _run_hidden(
            [str(py), "-u", str(script)],
            cwd=str(root),
            capture_output=True,
            timeout=60,
        )
    except Exception:
        pass


def _health_url(root: Path) -> str | None:
    port_file = root / ".aki_ui_port"
    if not port_file.is_file():
        return None
    try:
        port = int(port_file.read_text(encoding="ascii").strip())
    except (ValueError, OSError):
        return None
    return f"http://{UI_HOST}:{port}/api/health"


def _running_instance_alive(root: Path) -> bool:
    url = _health_url(root)
    if not url:
        return False
    try:
        import urllib.request

        with urllib.request.urlopen(url, timeout=2.0) as resp:
            return int(getattr(resp, "status", 200) or 200) == 200
    except Exception:
        return False


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return str(pid) in (r.stdout or "")
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _electron_instance_active(root: Path) -> bool:
    pid_file = root / ".aki_electron.pid"
    if not pid_file.is_file():
        return False
    try:
        pid = int(pid_file.read_text(encoding="ascii").strip())
    except (ValueError, OSError):
        return False
    return _pid_alive(pid)


def _kill_pid_tree(pid: int) -> None:
    if pid <= 0 or pid == os.getpid():
        return
    if sys.platform == "win32":
        from akifactory.win_subprocess import run as _run_hidden

        _run_hidden(
            ["taskkill", "/PID", str(pid), "/F", "/T"],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def _force_stop_orphan_backend(root: Path) -> None:
    """Pencere yok ama /api/health cevap veriyor — eski arka plan motorunu kapat."""
    for name in (".aki_pid", ".aki_engine_pid"):
        pid_file = root / name
        if not pid_file.is_file():
            continue
        try:
            old = int(pid_file.read_text(encoding="ascii").strip())
        except (ValueError, OSError):
            continue
        _kill_pid_tree(old)

    for _ in range(24):
        if not _running_instance_alive(root):
            break
        time.sleep(0.5)

    _cleanup_stale_instance_files(root)


def _cleanup_stale_instance_files(root: Path) -> None:
    if _running_instance_alive(root):
        return
    for name in (".aki_pid", ".aki_engine_pid", ".aki_ui_port", ".aki_electron.pid"):
        path = root / name
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _stop_previous_instance(root: Path) -> None:
    """Yalnizca cevap vermeyen eski surecleri temizle — calisan kopyayi oldurme."""
    if _running_instance_alive(root):
        return
    for name in (".aki_pid", ".aki_engine_pid"):
        pid_file = root / name
        if not pid_file.is_file():
            continue
        try:
            old = int(pid_file.read_text(encoding="ascii").strip())
        except (ValueError, OSError):
            continue
        if old <= 0 or old == os.getpid():
            continue
        if sys.platform == "win32":
            from akifactory.win_subprocess import run as _run_hidden

            _run_hidden(
                ["taskkill", "/PID", str(old), "/F", "/T"],
                capture_output=True,
                check=False,
            )
        else:
            try:
                os.kill(old, 9)
            except OSError:
                pass


def _write_pid(root: Path) -> None:
    (root / ".aki_pid").write_text(str(os.getpid()), encoding="ascii")


def _log_boot_error(root: Path, msg: str) -> None:
    try:
        path = root / ".aki_app.log"
        with path.open("a", encoding="utf-8") as f:
            f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n{msg}\n")
    except OSError:
        pass


def run_boot(root: Path, on_progress: ProgressFn | None = None) -> BootResult:
    """Dosya kontrolleri → motor → arayuz sunucusu (webview henuz acilmaz)."""
    warnings: list[str] = []
    api_proc: subprocess.Popen | None = None

    try:
        from akifactory.win_subprocess import install_no_console_patch

        install_no_console_patch()
    except Exception:
        pass

    def progress(msg: str, pct: int) -> None:
        if on_progress:
            on_progress(msg, max(0, min(100, pct)))

    try:
        from akifactory.engine_launcher import ensure_engine_present, pick_free_port, start_engine_api
        from akifactory.desktop import run_uvicorn_thread, wait_for_url

        progress("Checking files…", 5)
        ensure_engine_present(root)
        if not (root / "web" / "index.html").is_file():
            raise FileNotFoundError("web/index.html is missing")

        if getattr(sys, "frozen", False):
            if not (root / "src" / "akifactory" / "__init__.py").is_file():
                raise FileNotFoundError(
                    "EXE package is incomplete: src/akifactory not found.\n"
                    "Reinstall with AkiFactory.bat --portable."
                )

        progress("Preparing Python environment…", 15)
        if not _venv_python(root):
            raise FileNotFoundError(
                ".venv not found — install with the portable package or AkiFactory.bat."
            )

        progress("Applying configuration…", 28)
        if not _run_apply_config(root):
            raise RuntimeError("Could not create config.toml.")

        progress("Starting Ollama…", 34)
        try:
            from akifactory.first_run import try_start_ollama

            if try_start_ollama(wait_sec=12.0):
                progress("Ollama service started.", 36)
        except Exception:
            pass

        progress("Connecting to Ollama…", 38)
        try:
            from akifactory.ollama_util import ping_sync

            if ping_sync():
                progress("Ollama ready.", 45)
            else:
                warnings.append(
                    "Ollama is not responding — run ollama serve in a separate window for script writing."
                )
                progress("Waiting for Ollama (optional)…", 45)
        except Exception:
            warnings.append("Ollama check skipped.")
            progress("Ollama skipped.", 45)

        progress("Setting up GPU profile…", 50)
        _run_sync_gpu(root)

        if _running_instance_alive(root):
            if _electron_instance_active(root):
                return BootResult(
                    ok=False,
                    error=(
                        "AkiFactory is already running. Click the AkiFactory window in the "
                        "taskbar instead of opening a second copy."
                    ),
                )
            _log_boot_error(
                root,
                "Yetim arka plan motoru bulundu (pencere yok) — temizleniyor.",
            )
            _force_stop_orphan_backend(root)

        _cleanup_stale_instance_files(root)
        _stop_previous_instance(root)
        _write_pid(root)

        from akifactory.gpu import apply_runtime_env, gpu_profile_for_ui

        apply_runtime_env()
        gpu_info = gpu_profile_for_ui()
        if gpu_info.get("gpu_available"):
            progress(
                f"GPU: {gpu_info.get('gpu_name') or 'NVIDIA'} — starting engine…",
                54,
            )
        else:
            progress("CPU mode — starting engine…", 54)

        wait_started = time.time()

        def engine_status(msg: str, pct: int | None) -> None:
            if pct is not None:
                progress(msg, pct)
                return
            elapsed = time.time() - wait_started
            sub = 54 + min(26, int(elapsed / 300.0 * 26))
            progress(msg, sub)

        api_proc, api_host, api_port = start_engine_api(
            root=root,
            on_status=engine_status,
        )
        os.environ["AKI_ENGINE_API"] = f"http://{api_host}:{api_port}"
        progress("Engine connected.", 82)

        progress("Preparing interface…", 88)
        from akifactory.ui_app import create_app

        ui_port = pick_free_port(UI_HOST, UI_PORT_DEFAULT)
        os.environ["AKI_UI_PORT"] = str(ui_port)
        (root / ".aki_ui_port").write_text(str(ui_port), encoding="ascii")

        app = create_app()
        run_uvicorn_thread(app, UI_HOST, ui_port)

        progress("Starting interface…", 93)
        url = f"http://{UI_HOST}:{ui_port}"
        if not wait_for_url(url, timeout=90.0):
            raise RuntimeError(f"Interface did not start: {url}")

        progress("Ready — opening the app…", 100)
        return BootResult(
            ok=True,
            warnings=warnings,
            api_proc=api_proc,
            ui_host=UI_HOST,
            ui_port=ui_port,
            engine_api=os.environ["AKI_ENGINE_API"],
        )
    except Exception as exc:
        msg = str(exc) or "Startup failed"
        _log_boot_error(root, msg)
        return BootResult(
            ok=False,
            error=msg,
            warnings=warnings,
            api_proc=api_proc,
        )
