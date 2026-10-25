"""data/ klasoru yedekleme — tarih damgali zip."""

from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from akifactory.paths import data_dir

BACKUP_DIR_NAME = "backups"
BACKUP_PREFIX = "akifactory-backup-"
_SKIP_DIRS = frozenset({BACKUP_DIR_NAME, "logs"})


def backups_dir() -> Path:
    d = data_dir() / BACKUP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _human_size(num: int) -> str:
    if num < 1024:
        return f"{num} B"
    if num < 1024 * 1024:
        return f"{num / 1024:.1f} KB"
    if num < 1024 * 1024 * 1024:
        return f"{num / (1024 * 1024):.1f} MB"
    return f"{num / (1024 * 1024 * 1024):.2f} GB"


def create_backup() -> dict[str, Any]:
    """data/ altini zip'ler; backups/ klasoru haric tutulur."""
    root = data_dir()
    out_dir = backups_dir()
    name = f"{BACKUP_PREFIX}{_timestamp()}.zip"
    out_path = out_dir / name

    file_count = 0
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            parts = rel.parts
            if parts and parts[0] in _SKIP_DIRS:
                continue
            zf.write(path, arcname=str(Path("data") / rel))
            file_count += 1

    size = out_path.stat().st_size if out_path.is_file() else 0
    return {
        "ok": True,
        "filename": name,
        "path": str(out_path),
        "size_bytes": size,
        "size_human": _human_size(size),
        "file_count": file_count,
    }


def list_backups(max_items: int = 20) -> list[dict[str, Any]]:
    d = backups_dir()
    files = sorted(
        (p for p in d.glob(f"{BACKUP_PREFIX}*.zip") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    out: list[dict[str, Any]] = []
    for p in files[:max_items]:
        st = p.stat()
        out.append(
            {
                "filename": p.name,
                "path": str(p),
                "size_bytes": st.st_size,
                "size_human": _human_size(st.st_size),
                "created_at": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            }
        )
    return out
