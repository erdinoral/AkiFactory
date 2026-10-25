"""AkiFactory smoke test — health, config, ollama (CI / agent dogrulama)."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _get(url: str, timeout: float = 15.0) -> tuple[int, dict | str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, body
    except Exception as e:
        return 0, str(e)


def main() -> int:
    port_file = ROOT / ".aki_ui_port"
    port = 7860
    if port_file.is_file():
        try:
            port = int(port_file.read_text(encoding="ascii").strip())
        except ValueError:
            pass
    base = f"http://127.0.0.1:{port}"
    errors: list[str] = []

    t0 = time.time()
    code, health = _get(f"{base}/api/health", timeout=8)
    dt = time.time() - t0
    if code != 200 or not isinstance(health, dict):
        errors.append(f"health FAIL ({code}): {health}")
    elif not health.get("ok"):
        errors.append(f"motor not ready: {health}")
    elif not (health.get("ollama") or {}).get("running"):
        errors.append(f"Ollama not running: {health.get('ollama')}")
    else:
        print(f"[OK] health {dt:.2f}s ollama={health['ollama'].get('running')}")

    t0 = time.time()
    code, cfg = _get(f"{base}/api/config", timeout=25)
    dt = time.time() - t0
    if code != 200 or not isinstance(cfg, dict):
        errors.append(f"config FAIL ({code}): {str(cfg)[:200]}")
    elif dt > 5.0:
        errors.append(f"config too slow: {dt:.1f}s")
    elif not cfg.get("niches") or not cfg.get("tts_engines"):
        errors.append("config missing niches/tts_engines")
    else:
        cb = (cfg.get("chatterbox_status") or {}).get("ready")
        print(f"[OK] config {dt:.2f}s niches={len(cfg['niches'])} tts={len(cfg['tts_engines'])} chatterbox={cb}")

    if errors:
        for e in errors:
            print(f"[HATA] {e}", file=sys.stderr)
        return 1
    print("[OK] Tum kontroller gecti")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
