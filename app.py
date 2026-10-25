"""
AkiFactory — gelistirici girisi (Electron olmadan motor testi).

Normal kullanim: AkiFactory.bat
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_SCRIPTS = ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def main() -> int:
    print("[AkiFactory] Gelistirici modu — Electron yok.", flush=True)
    print("  Normal kullanim icin: AkiFactory.bat", flush=True)
    from run_backend import main as backend_main

    return backend_main()


if __name__ == "__main__":
    raise SystemExit(main())
