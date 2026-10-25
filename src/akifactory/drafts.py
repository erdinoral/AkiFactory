"""Uretim taslaklari — konu, ayarlar ve senaryo."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from akifactory import json_io as jio
from akifactory.paths import data_dir

DRAFTS_FILE = "drafts.json"
MAX_DRAFTS = 40


def _path() -> Path:
    return data_dir() / DRAFTS_FILE


def _load() -> list[dict[str, Any]]:
    p = _path()
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return list(data.get("drafts", []))
    except Exception:
        return []


def _save(items: list[dict[str, Any]]) -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    jio.safe_write_json(
        _path(),
        jio.stamp_schema({"drafts": items[:MAX_DRAFTS]}),
    )


def _default_label(settings: dict[str, Any]) -> str:
    if (settings.get("mode") or "").strip().lower() == "longform":
        base = str(
            settings.get("longform_subject") or settings.get("subject") or "Uzun video"
        ).strip()[:60]
        chapters = settings.get("longform_chapters") or []
        if chapters:
            return f"{base} ({len(chapters)} bolum)"[:80]
        return base[:80] or "Uzun video"
    if settings.get("batch_mode"):
        topics = settings.get("batch_topics") or []
        if topics:
            base = str(topics[0]).strip()
            if len(topics) > 1:
                return f"{base[:40]} (+{len(topics) - 1})"
            return base[:80]
    return str(settings.get("subject") or "Taslak")[:80]


def list_drafts() -> list[dict[str, Any]]:
    return _load()


def get_draft(draft_id: str) -> dict[str, Any] | None:
    for d in _load():
        if d.get("id") == draft_id:
            return d
    return None


def save_draft(
    *,
    settings: dict[str, Any],
    draft_id: str | None = None,
    label: str = "",
) -> dict[str, Any]:
    items = _load()
    now = datetime.now(timezone.utc).isoformat()
    clean_label = (label or "").strip()[:80]
    if not clean_label:
        clean_label = _default_label(settings)

    if draft_id:
        for d in items:
            if d.get("id") == draft_id:
                d["label"] = clean_label
                d["settings"] = settings
                d["updated_at"] = now
                _save(items)
                return d

    entry = {
        "id": uuid.uuid4().hex[:12],
        "label": clean_label,
        "settings": settings,
        "created_at": now,
        "updated_at": now,
    }
    items.insert(0, entry)
    _save(items)
    return entry


def delete_draft(draft_id: str) -> bool:
    items = _load()
    new_items = [d for d in items if d.get("id") != draft_id]
    if len(new_items) == len(items):
        return False
    _save(new_items)
    return True
