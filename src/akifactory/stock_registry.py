"""Indirilen stok URL kaydi — ayni gorsel/klip tekrar cekilmesin."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from akifactory.paths import data_dir

_lock = threading.Lock()
_INDEX_NAME = "used_urls.json"


def _cache_dir() -> Path:
    d = data_dir() / "stock_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path() -> Path:
    return _cache_dir() / _INDEX_NAME


def normalize_stock_url(url: str) -> str:
    return (url or "").strip().split("?")[0]


def _load_index() -> dict[str, str]:
    p = _index_path()
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return {normalize_stock_url(k): str(v) for k, v in raw.items() if k}
        if isinstance(raw, list):
            return {normalize_stock_url(u): "" for u in raw if u}
    except Exception:
        pass
    return {}


def _save_index(data: dict[str, str]) -> None:
    _index_path().write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def is_url_used(url: str) -> bool:
    key = normalize_stock_url(url)
    if not key:
        return False
    with _lock:
        return key in _load_index()


def mark_url_used(url: str, local_path: str = "") -> None:
    key = normalize_stock_url(url)
    if not key:
        return
    with _lock:
        data = _load_index()
        if key in data:
            return
        data[key] = (local_path or "").strip()
        _save_index(data)


def used_count() -> int:
    with _lock:
        return len(_load_index())
