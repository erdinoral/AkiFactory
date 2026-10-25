"""Gorev uretim suresi — baslangic/bitis zaman damgalari."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from akifactory.paths import data_dir

_FILE = data_dir() / "task_timings.json"
_MAX_ENTRIES = 300


def _load() -> dict[str, Any]:
    if not _FILE.is_file():
        return {}
    try:
        raw = json.loads(_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _save(data: dict[str, Any]) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    if len(data) > _MAX_ENTRIES:
        items = sorted(data.items(), key=lambda kv: float((kv[1] or {}).get("started_at") or 0))
        data = dict(items[-_MAX_ENTRIES:])
    _FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def record_start(task_id: str) -> None:
    tid = (task_id or "").strip()
    if not tid:
        return
    data = _load()
    if tid in data and data[tid].get("started_at"):
        return
    data[tid] = {"started_at": time.time(), "finished_at": None}
    _save(data)


def elapsed(task_id: str) -> int | None:
    tid = (task_id or "").strip()
    if not tid:
        return None
    row = _load().get(tid)
    if not row or not row.get("started_at"):
        return None
    end = row.get("finished_at") or time.time()
    return max(0, int(end - float(row["started_at"])))


def finish(task_id: str) -> int | None:
    tid = (task_id or "").strip()
    if not tid:
        return None
    data = _load()
    row = data.get(tid)
    if not row or not row.get("started_at"):
        return None
    now = time.time()
    if not row.get("finished_at"):
        row["finished_at"] = now
        data[tid] = row
        _save(data)
    return max(0, int(float(row["finished_at"]) - float(row["started_at"])))
