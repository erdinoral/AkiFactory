"""AkiFactory.bat — cift tiklamadan once yetim arka plan motorunu temizle."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    from akifactory.win_subprocess import install_no_console_patch

    install_no_console_patch()
except Exception:
    pass


def main() -> int:
    from akifactory.boot import (
        _cleanup_stale_instance_files,
        _electron_instance_active,
        _force_stop_orphan_backend,
        _running_instance_alive,
    )

    if _running_instance_alive(ROOT) and not _electron_instance_active(ROOT):
        _force_stop_orphan_backend(ROOT)
    elif not _running_instance_alive(ROOT):
        _cleanup_stale_instance_files(ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
