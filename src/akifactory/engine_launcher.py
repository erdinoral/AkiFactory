"""
AkiFactory video motoru — API sunucusunu ayri surecte baslatir.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8080


def project_root() -> Path:
    from akifactory.paths import app_root

    return app_root()


def ensure_engine_present(root: Path | None = None) -> Path:
    from akifactory.paths import src_dir

    engine = src_dir() / "akifactory" / "engine"
    if not (engine / "server.py").is_file():
        raise FileNotFoundError(f"Video motoru bulunamadi: {engine}")
    return engine


def pick_free_port(host: str, preferred: int, end: int = 8099) -> int:
    candidates = [preferred] + [p for p in range(preferred + 1, end + 1) if p != preferred]
    for port in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    raise OSError(f"{host} uzerinde bos port yok ({preferred}-{end})")


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def _pids_on_port(port: int) -> list[int]:
    """Dinleyen surec PID'leri (Windows netstat)."""
    if sys.platform != "win32":
        return []
    try:
        out = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except Exception:
        return []
    needle = f":{int(port)}"
    pids: list[int] = []
    seen: set[int] = set()
    for line in out.splitlines():
        if "LISTENING" not in line.upper():
            continue
        if needle not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        try:
            pid = int(parts[-1])
        except ValueError:
            continue
        if pid > 0 and pid not in seen:
            seen.add(pid)
            pids.append(pid)
    return pids


def _cmdline_looks_like_engine(pid: int) -> bool:
    """Yalnizca AkiFactory motor sureclerini oldur — yanlis PID korumasi."""
    if sys.platform != "win32":
        return True
    # PowerShell kullanma — baslangicta konsol flash eder. WMIC sessiz.
    try:
        out = subprocess.run(
            [
                "wmic",
                "process",
                "where",
                f"ProcessId={int(pid)}",
                "get",
                "CommandLine",
                "/FORMAT:LIST",
            ],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout or ""
    except Exception:
        out = ""
    if not out.strip():
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {int(pid)}", "/V", "/FO", "LIST"],
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8",
                errors="replace",
                timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout or ""
        except Exception:
            return False
    low = out.lower()
    return (
        "akifactory" in low
        or "uvicorn" in low
        or "run_backend" in low
    )


def _kill_pids(pids: list[int]) -> None:
    for pid in pids:
        if pid <= 0 or pid == os.getpid():
            continue
        if not _cmdline_looks_like_engine(pid):
            print(
                f"[AkiFactory] Port uzerindeki PID {pid} motor degil — dokunulmuyor.",
                flush=True,
            )
            continue
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            try:
                os.kill(pid, 9)
            except OSError:
                pass


def _free_port(host: str, port: int) -> None:
    """Eski/orphan motor surecini kapat — patch'siz motor kalmasin."""
    if not _port_open(host, port):
        return
    pids = _pids_on_port(port)
    if not pids:
        return
    print(
        f"[AkiFactory] Port {port} uzerindeki eski motor kapatiliyor (PID: {', '.join(map(str, pids))})...",
        flush=True,
    )
    _kill_pids(pids)
    deadline = time.time() + 8.0
    while time.time() < deadline:
        if not _port_open(host, port):
            return
        time.sleep(0.4)


def _engine_api_ready(host: str, port: int, timeout: float = 3.0) -> bool:
    """motor FastAPI ayakta mi? /docs veya openapi — baska yazilimlar (or. NVIDIA Broadcast :8080) elenir."""
    if not _port_open(host, port):
        return False
    try:
        import urllib.error
        import urllib.request

        for path in ("/openapi.json", "/docs"):
            try:
                with urllib.request.urlopen(
                    f"http://{host}:{port}{path}", timeout=timeout
                ) as resp:
                    code = getattr(resp, "status", None) or resp.getcode()
                    if code != 200:
                        continue
                    if path == "/openapi.json":
                        raw = resp.read(4000).decode("utf-8", errors="replace")
                        if "AkiFactory Engine" in raw or '"openapi"' in raw:
                            return True
                        continue
                    return True
            except urllib.error.HTTPError:
                continue
            except Exception:
                continue
        return False
    except Exception:
        return False


def wait_for_api(host: str, port: int, timeout: float = 120.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _engine_api_ready(host, port, timeout=3.0):
            return True
        time.sleep(0.8)
    return False


def read_engine_log_tail(path: Path, max_lines: int = 12) -> str:
    return _read_log_tail(path, max_lines)


def _read_log_tail(path: Path, max_lines: int = 12) -> str:
    if not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    tail = [ln for ln in lines[-max_lines:] if ln.strip()]
    return "\n".join(tail)


def _emit_status(
    on_status: Callable[[str, int | None], None] | None,
    msg: str,
    pct: int | None = None,
) -> None:
    if on_status:
        on_status(msg, pct)
    elif not getattr(sys, "frozen", False):
        print(f"[AkiFactory] {msg}", flush=True)


def start_engine_api(
    *,
    root: Path | None = None,
    host: str | None = None,
    port: int | None = None,
    python_exe: str | None = None,
    on_status: Callable[[str, int | None], None] | None = None,
) -> tuple[subprocess.Popen, str, int]:
    """Motor FastAPI; Popen dondurur."""
    ensure_engine_present(root)
    host = (host or os.environ.get("ENGINE_API_HOST") or DEFAULT_API_HOST).strip()
    selected = int(port or os.environ.get("ENGINE_API_PORT") or DEFAULT_API_PORT)
    if _port_open(host, selected):
        if _engine_api_ready(host, selected):
            _emit_status(
                on_status,
                f"Eski motor yeniden baslatiliyor ({selected})…",
                56,
            )
            _free_port(host, selected)
        else:
            alt = pick_free_port(host, selected + 1)
            _emit_status(
                on_status,
                f"Port {selected} dolu (motor degil) — motor icin {alt} kullaniliyor.",
                56,
            )
            selected = alt

    from akifactory.runtime import python_for_subprocess
    from akifactory.paths import src_dir

    py = python_exe or python_for_subprocess(root)
    src = src_dir()
    if not (src / "akifactory").is_dir():
        raise FileNotFoundError(
            f"akifactory kaynaklari bulunamadi: {src / 'akifactory'}\n"
            "EXE paketi eksik — AkiFactory.bat veya AkiFactory.bat ile yeniden kurun."
        )
    from akifactory.gpu import ffmpeg_env

    env = {
        **os.environ,
        **ffmpeg_env(),
        "PYTHONPATH": str(src),
        "AKI_ENGINE_LISTEN_HOST": host,
        "AKI_ENGINE_LISTEN_PORT": str(selected),
        "ENGINE_API_PORT": str(selected),
    }
    # engine.toml listen_port sabit kalabilir; secilen portu sunucu baslamadan once enjekte et
    # (8080 NVIDIA Broadcast vb. doluysa launcher 8081+ secer — motor de ayni porta baglanmali)
    bootstrap = (
        "import akifactory.win_subprocess as _aki_ws; _aki_ws.install_no_console_patch(); "
        "import akifactory.engine_voice_bootstrap; akifactory.engine_voice_bootstrap.prepare(); "
        "import akifactory.rvc_util; akifactory.rvc_util.apply_rvc_runtime_patch(); "
        "import akifactory.engine_llm_patch; akifactory.engine_llm_patch.apply_llm_runtime_patch(); "
        "import akifactory.engine_script_patch; akifactory.engine_script_patch.apply_script_runtime_patch(); "
        "import akifactory.engine_outro_patch; akifactory.engine_outro_patch.apply_outro_runtime_patch(); "
        "import akifactory.engine_video_patch; akifactory.engine_video_patch.apply_video_runtime_patch(); "
        "import akifactory.engine_material_patch; akifactory.engine_material_patch.apply_material_runtime_patch(); "
        "import os as _aki_os; "
        "import akifactory.engine.config.config as _aki_cfg; "
        f"_aki_cfg.listen_host = _aki_os.environ.get('AKI_ENGINE_LISTEN_HOST', {host!r}); "
        f"_aki_cfg.listen_port = int(_aki_os.environ.get('AKI_ENGINE_LISTEN_PORT', '{selected}')); "
        "import runpy; runpy.run_module('akifactory.engine.server', run_name='__main__')"
    )
    log_path = (root or project_root()) / ".aki_engine.log"
    log_file = open(log_path, "a", encoding="utf-8", buffering=1)
    log_file.write(f"\n--- motor start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    log_file.flush()
    popen_kw: dict = {
        "cwd": str(root or project_root()),
        "env": env,
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
    }
    if sys.platform == "win32":
        popen_kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.Popen([py, "-c", bootstrap], **popen_kw)
    pid_file = (root or project_root()) / ".aki_engine_pid"
    pid_file.write_text(str(proc.pid), encoding="ascii")
    _emit_status(
        on_status,
        f"Motor kutuphaneleri yukleniyor… (ilk acilis 1-2 dk)",
        58,
    )
    api_timeout = 300.0
    deadline = time.time() + api_timeout
    last_msg = 0.0
    while time.time() < deadline:
        if proc.poll() is not None:
            tail = _read_log_tail(log_path)
            raise RuntimeError(
                "Video motoru beklenmedik sekilde kapandi "
                f"(cikis {proc.returncode}).\n"
                f"Detay: {log_path}\n{tail or '(log bos)'}"
            )
        if wait_for_api(host, selected, timeout=2.0):
            _emit_status(on_status, f"Motor baglandi (:{selected}).", 80)
            return proc, host, selected
        if time.time() - last_msg > 4:
            _emit_status(
                on_status,
                f"Motor baglantisi bekleniyor… (:{selected})",
                None,
            )
            last_msg = time.time()
        time.sleep(1.0)
    proc.terminate()
    tail = _read_log_tail(log_path)
    raise RuntimeError(
        "Video motoru API zaman asimina ugradi.\n"
        f"Detay: {log_path}\n{tail or '(log bos)'}"
    )


def stop_process_tree(proc: subprocess.Popen | None, *, wait_sec: float = 8.0) -> None:
    """motor alt surec agacini kapat (Whisper/CUDA bellek serbest)."""
    if proc is None or proc.poll() is not None:
        return
    pid = proc.pid
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=wait_sec)
    except Exception:
        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=3)
            except Exception:
                pass


def launch_webui(*args, **kwargs) -> int:
    """Eski Streamlit — kullanilmiyor."""
    raise RuntimeError(
        "Streamlit kaldirildi. AkiFactory.bat kullanin."
    )
