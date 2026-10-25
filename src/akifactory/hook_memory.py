"""Hook hafizasi — iyi ve kotu acilis cumleleri (nis basina)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from akifactory.paths import data_dir
from akifactory.script_prompts import resolve_niche

STORE_FILE = "hook_memory.json"
MAX_PER_BUCKET = 25

Rating = Literal["good", "bad"]


def _path():
    return data_dir() / STORE_FILE


def _load() -> dict[str, Any]:
    p = _path()
    if not p.is_file():
        return {"niches": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("niches"), dict):
            return data
    except Exception:
        pass
    return {"niches": {}}


def _save(data: dict[str, Any]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _niche_key(niche_id: str | None) -> str:
    return resolve_niche(niche_id or "genel")


def _bucket(data: dict[str, Any], niche_id: str, rating: Rating) -> list[dict[str, Any]]:
    niches = data.setdefault("niches", {})
    row = niches.get(niche_id)
    if not isinstance(row, dict):
        return []
    raw = row.get(rating)
    if not isinstance(raw, list):
        return []
    return [it for it in raw if isinstance(it, dict) and (it.get("text") or "").strip()]


def list_for_niche(niche_id: str | None) -> dict[str, list[dict[str, Any]]]:
    key = _niche_key(niche_id)
    data = _load()
    return {
        "good": _bucket(data, key, "good"),
        "bad": _bucket(data, key, "bad"),
    }


def _text_exists(items: list[dict[str, Any]], text: str) -> bool:
    norm = (text or "").strip().lower()
    return any((it.get("text") or "").strip().lower() == norm for it in items)


def add_entry(
    niche_id: str,
    text: str,
    *,
    rating: Rating,
    topic: str = "",
    note: str = "",
    source: str = "manual",
) -> dict[str, Any]:
    hook = (text or "").strip()
    if len(hook) < 8:
        raise ValueError("Hook en az 8 karakter olmali")
    key = _niche_key(niche_id)
    data = _load()
    niches = data.setdefault("niches", {})
    row = niches.setdefault(key, {"good": [], "bad": []})
    bucket = row.setdefault(rating, [])
    if not isinstance(bucket, list):
        bucket = []
        row[rating] = bucket
    if _text_exists(bucket, hook):
        for it in bucket:
            if (it.get("text") or "").strip().lower() == hook.lower():
                return it
    entry = {
        "id": uuid.uuid4().hex[:10],
        "text": hook[:500],
        "topic": (topic or "").strip()[:300],
        "note": (note or "").strip()[:200],
        "source": source,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    bucket.insert(0, entry)
    row[rating] = bucket[:MAX_PER_BUCKET]
    niches[key] = row
    _save(data)
    return entry


def remove_entry(niche_id: str, entry_id: str, *, rating: Rating) -> bool:
    key = _niche_key(niche_id)
    eid = (entry_id or "").strip()
    data = _load()
    niches = data.setdefault("niches", {})
    row = niches.get(key)
    if not isinstance(row, dict):
        return False
    bucket = row.get(rating)
    if not isinstance(bucket, list):
        return False
    new_bucket = [it for it in bucket if it.get("id") != eid]
    if len(new_bucket) == len(bucket):
        return False
    row[rating] = new_bucket
    niches[key] = row
    _save(data)
    return True


def remember_auto(niche_id: str, hook: str, topic: str = "", *, good: bool) -> None:
    try:
        add_entry(
            niche_id,
            hook,
            rating="good" if good else "bad",
            topic=topic,
            source="auto",
        )
    except ValueError:
        pass
    except Exception:
        pass


def prompt_block(niche_id: str | None, *, good_limit: int = 6, bad_limit: int = 6) -> str:
    mem = list_for_niche(niche_id)
    good = mem.get("good") or []
    bad = mem.get("bad") or []
    if not good and not bad:
        return ""
    parts: list[str] = []
    if good:
        lines = "\n".join(f"- «{(it.get('text') or '').strip()}»" for it in good[:good_limit])
        parts.append(f"IYI HOOK HAFIZASI (bu tarzi yakala):\n{lines}")
    if bad:
        lines = "\n".join(f"- «{(it.get('text') or '').strip()}»" for it in bad[:bad_limit])
        parts.append(f"KOTU HOOK HAFIZASI (bunlara benzer yazma):\n{lines}")
    return "\n" + "\n".join(parts) + "\n"


def public_snapshot() -> dict[str, Any]:
    data = _load()
    niches = data.get("niches") or {}
    summary: dict[str, dict[str, int]] = {}
    for key, row in niches.items():
        if isinstance(row, dict):
            summary[key] = {
                "good": len(row.get("good") or []),
                "bad": len(row.get("bad") or []),
            }
    return {"summary": summary, "niches": niches}
