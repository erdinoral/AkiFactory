"""Konu gecmisi ve favori sablonlar."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from akifactory import json_io as jio
from akifactory.paths import data_dir

HISTORY_FILE = "history.json"
MAX_ENTRIES = 50
RETENTION_DAYS = 30


def _path() -> Path:
    return data_dir() / HISTORY_FILE


def _load() -> list[dict[str, Any]]:
    p = _path()
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return list(data.get("history", []))
    except Exception:
        return []


def _save(items: list[dict[str, Any]]) -> None:
    jio.safe_write_json(
        _path(),
        jio.stamp_schema({"history": items}),
    )


def _prune(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    favorites: list[dict[str, Any]] = []
    others: list[dict[str, Any]] = []
    for e in items:
        if e.get("is_favorite"):
            favorites.append(e)
            continue
        try:
            created = datetime.fromisoformat(e.get("created_at", "").replace("Z", "+00:00"))
            if created >= cutoff:
                others.append(e)
        except Exception:
            others.append(e)
    # Favoriler MAX_ENTRIES kesiminden muaf; sadece digerleri sinirlanir
    room = max(0, MAX_ENTRIES - len(favorites))
    return favorites + others[:room]


def add_entry(
    *,
    topic: str,
    platform: str,
    language: str,
    voice: str,
    tts_engine: str,
    niche: str = "genel",
) -> dict[str, Any]:
    items = _prune(_load())
    entry = {
        "id": uuid.uuid4().hex[:12],
        "topic": topic[:500],
        "platform": platform,
        "language": language,
        "voice": voice,
        "tts_engine": tts_engine,
        "niche": niche,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_favorite": False,
        "label": "",
    }
    items.insert(0, entry)
    _save(_prune(items))
    return entry


def list_entries() -> list[dict[str, Any]]:
    return _prune(_load())


def toggle_favorite(entry_id: str) -> dict[str, Any] | None:
    items = _load()
    for e in items:
        if e.get("id") == entry_id:
            e["is_favorite"] = not e.get("is_favorite", False)
            _save(items)
            return e
    return None


def set_label(entry_id: str, label: str) -> dict[str, Any] | None:
    items = _load()
    for e in items:
        if e.get("id") == entry_id:
            e["label"] = label[:80]
            _save(items)
            return e
    return None


def delete_entry(entry_id: str) -> bool:
    items = _load()
    kept = [e for e in items if e.get("id") != entry_id]
    if len(kept) == len(items):
        return False
    _save(kept)
    return True
