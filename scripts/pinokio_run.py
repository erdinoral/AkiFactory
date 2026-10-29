"""Pinokio entry point; reuse this folder's running UI without a second engine."""
from __future__ import annotations
import sys
import os
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))


def existing_url():
    try:
        port = int((ROOT / ".aki_ui_port").read_text().strip())
        if not 1 <= port <= 65535:
            return None
        url = f"http://127.0.0.1:{port}"
        with urlopen(url + "/api/version", timeout=3) as response:
            import json
            if not json.load(response).get("api_json_safe"):
                return None
        return url
    except Exception:
        return None


def main():
    # Activation scripts can retain an old absolute path after moving a venv.
    # Do not let Pinokio's Conda/base Python start the engine in that case.
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        print("AkiFactory Python environment not found. In Pinokio, run Install / Repair.", flush=True)
        return 1
    if not os.path.samefile(sys.executable, python):
        env = dict(os.environ)
        env.pop("PYTHONHOME", None)
        return subprocess.call([str(python), str(Path(__file__).resolve())], cwd=ROOT, env=env)
    url = existing_url()
    if url:
        print(f"AKIFACTORY_READY {url}", flush=True)
        print("Connected to the running app. Stopping it in Pinokio does not close that app.", flush=True)
        while existing_url() == url:
            time.sleep(3)
        return 0
    import run_backend
    emit = run_backend._emit
    def pinokio_emit(kind, payload):
        if kind == "AKI_READY":
            print(f"AKIFACTORY_READY http://{payload['ui_host']}:{payload['ui_port']}", flush=True)
        emit(kind, payload)
    run_backend._emit = pinokio_emit
    return run_backend.main()


if __name__ == "__main__":
    raise SystemExit(main())
