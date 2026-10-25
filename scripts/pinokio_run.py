"""Pinokio entry point; reuse this folder's running UI without a second engine."""
from __future__ import annotations
import sys
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
    url = existing_url()
    if url:
        print(f"AKIFACTORY_READY {url}", flush=True)
        print("Mevcut uygulamaya baglanildi. Pinokio'yu durdurmak mevcut uygulamayi kapatmaz.", flush=True)
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
