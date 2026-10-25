"""Tek komutla ortam kontrolu — uygulama calismadan da calistirilabilir."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from akifactory.system_live import run_healthcheck_async  # noqa: E402


def main() -> int:
    engine = "http://127.0.0.1:8080"
    if len(sys.argv) > 1 and sys.argv[1].strip():
        engine = sys.argv[1].strip().rstrip("/")
    code, lines = asyncio.run(run_healthcheck_async(engine_base=engine))
    for line in lines:
        print(line, flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
