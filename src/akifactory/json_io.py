"""Guvenli JSON okuma/yazma — atomic write ve sema surumu."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def stamp_schema(data: dict[str, Any], *, version: int = SCHEMA_VERSION) -> dict[str, Any]:
    """Yeni yazimlarda sema surumu ekler (mevcut anahtarlari silmez)."""
    out = dict(data)
    out["_schema_version"] = int(version)
    return out


def safe_write_json(
    path: Path | str,
    data: Any,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
) -> None:
    """Temp dosyaya yazip rename ile atomik kayit."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=ensure_ascii, indent=indent)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)


def read_json_file(path: Path | str, default: Any = None) -> Any:
    p = Path(path)
    if not p.is_file():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_wrapped_list(path: Path | str) -> list[Any]:
    """Liste veya {\"_schema_version\", \"items\"} formatini okur."""
    raw = read_json_file(path, default=[])
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        items = raw.get("items")
        if isinstance(items, list):
            return items
    return []


def save_wrapped_list(path: Path | str, items: list[Any]) -> None:
    safe_write_json(
        path,
        stamp_schema({"items": items}),
    )
