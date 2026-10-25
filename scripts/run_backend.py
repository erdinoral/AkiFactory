"""
Electron / headless baslatici — motor + FastAPI, masaustu penceresi acmaz.

Stdout protokolu (Electron main.js okur):
  AKI_PROGRESS {"message":"...", "pct": 42}
  AKI_READY    {"ui_host":"127.0.0.1", "ui_port":7860, "engine_api":"...", "warnings":[]}
  AKI_ERROR    {"error":"..."}
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
_SRC = ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("AKI_ELECTRON", "1")

# ffmpeg / MoviePy / nvidia-smi — Electron altinda siyah konsol flash etmesin
try:
    from akifactory.win_subprocess import install_no_console_patch

    install_no_console_patch()
except Exception:
    pass


def _emit(kind: str, payload: dict) -> None:
    print(f"{kind} {json.dumps(payload, ensure_ascii=False)}", flush=True)


def _progress(msg: str, pct: int) -> None:
    _emit("AKI_PROGRESS", {"message": msg, "pct": max(0, min(100, int(pct)))})


def main() -> int:
    from akifactory.boot import run_boot
    from akifactory.engine_launcher import stop_process_tree
    from akifactory.ollama_util import unload_all_models_sync

    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    boot = run_boot(ROOT, _progress)
    if not boot.ok:
        _emit("AKI_ERROR", {"error": boot.error or "Baslangic basarisiz"})
        stop_process_tree(boot.api_proc)
        return 1

    _emit(
        "AKI_READY",
        {
            "ui_host": boot.ui_host,
            "ui_port": boot.ui_port,
            "engine_api": boot.engine_api,
            "warnings": list(boot.warnings or []),
        },
    )

    stop = False

    def _stop(*_args: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _stop)

    from urllib.parse import urlparse

    api_proc = boot.api_proc
    engine_parts = urlparse(boot.engine_api or "http://127.0.0.1:8080")
    engine_host = engine_parts.hostname or "127.0.0.1"
    engine_port = engine_parts.port or 8080

    restart_count = 0
    restart_window = time.time()

    try:
        while not stop:
            if api_proc is not None and api_proc.poll() is not None:
                code = api_proc.returncode
                log_path = ROOT / ".aki_engine.log"
                tail = ""
                try:
                    from akifactory.engine_launcher import read_engine_log_tail

                    tail = read_engine_log_tail(log_path)
                except Exception:
                    pass
                now = time.time()
                if now - restart_window > 600:
                    restart_count = 0
                    restart_window = now
                restart_count += 1
                _progress(
                    f"Video motoru yeniden baslatiliyor ({restart_count})…",
                    72,
                )
                try:
                    from akifactory.engine_launcher import start_engine_api

                    api_proc, engine_host, engine_port = start_engine_api(
                        root=ROOT,
                        host=engine_host,
                        port=engine_port,
                        on_status=_progress,
                    )
                    os.environ["AKI_ENGINE_API"] = f"http://{engine_host}:{engine_port}"
                except Exception as exc:
                    err = f"Motor yeniden baslatilamadi (kod {code}): {exc}"
                    if tail:
                        err += f"\n{tail}"
                    try:
                        log = ROOT / ".aki_app.log"
                        with log.open("a", encoding="utf-8") as f:
                            f.write(f"\n[motor restart fail] {err}\n")
                    except OSError:
                        pass
                    time.sleep(min(8.0, 1.5 + restart_count * 0.5))
            time.sleep(0.4)
    finally:
        unload_all_models_sync()
        stop_process_tree(api_proc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
