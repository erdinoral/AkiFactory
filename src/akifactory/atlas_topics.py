"""Enigma Atlas — sitedeki mystery listesinden uretim kuyrugu."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from akifactory import json_io as jio
from akifactory import topic_memory as topic_mem
from akifactory.paths import data_dir

DEFAULT_JSON = data_dir() / "enigma" / "mysteries.json"
CONFIG_FILE = "enigma_atlas_config.json"
PRODUCED_IDS_FILE = "enigma_atlas_produced.json"
NICHE_ID = "tarih_gizem"
MAX_QUEUE = 50
BATCH_CHUNK = 10
_TITLE_KEYS = ("title_tr", "title", "title_en", "title_de", "title_fr", "title_es")


def _config_path() -> Path:
    return data_dir() / CONFIG_FILE


def _produced_ids_path() -> Path:
    return data_dir() / PRODUCED_IDS_FILE


def resolve_json_path() -> Path:
    env = os.environ.get("AKI_ENIGMA_JSON", "").strip()
    if env:
        return Path(env)
    cfg = _config_path()
    if cfg.is_file():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            p = (data.get("json_path") or "").strip()
            if p:
                return Path(p)
        except Exception:
            pass
    return DEFAULT_JSON


def set_json_path(path: str) -> Path:
    p = Path(path.strip())
    cfg = _config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    jio.safe_write_json(
        cfg,
        jio.stamp_schema({"json_path": str(p)}),
    )
    return p


def _title(m: dict[str, Any]) -> str:
    return (
        (m.get("title_tr") or m.get("title") or "").strip()
        or f"Mystery {m.get('id', '?')}"
    )


def _label_variants(label: str) -> list[str]:
    s = (label or "").strip()
    if not s:
        return []
    out = [s]
    en = re.sub(r"\s*\(EN\)\s*$", "", s, flags=re.IGNORECASE).strip()
    if en and en.lower() != s.lower():
        out.append(en)
    return out


def _mystery_labels(m: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for key in _TITLE_KEYS:
        v = (m.get(key) or "").strip()
        if not v:
            continue
        low = v.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(v)
    return out


def load_mysteries_raw() -> list[dict[str, Any]]:
    path = resolve_json_path()
    if not path.is_file():
        raise FileNotFoundError(f"Enigma JSON bulunamadi: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("mysteries.json gecersiz format (liste bekleniyor)")
    out: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        mid = row.get("id")
        title = _title(row)
        if mid is None or len(title) < 2:
            continue
        item = dict(row)
        item["id"] = int(mid)
        item["title"] = title
        item["category"] = (row.get("category") or "").strip()
        item["summary"] = (row.get("summary_tr") or row.get("summary") or "").strip()
        out.append(item)
    out.sort(key=lambda x: x["id"])
    return out


def load_mysteries() -> list[dict[str, Any]]:
    return load_mysteries_raw()


def get_produced_ids() -> set[int]:
    p = _produced_ids_path()
    if not p.is_file():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        ids = data.get("produced_ids") or []
        return {int(x) for x in ids if str(x).isdigit() or isinstance(x, int)}
    except Exception:
        return set()


def _save_produced_ids(ids: set[int]) -> None:
    p = _produced_ids_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(ids)
    jio.safe_write_json(
        p,
        jio.stamp_schema({"produced_ids": ordered}),
    )


def remember_produced_id(mystery_id: int) -> None:
    ids = get_produced_ids()
    ids.add(int(mystery_id))
    _save_produced_ids(ids)


def mystery_matches_label(m: dict[str, Any], label: str) -> bool:
    for lv in _label_variants(label):
        for ml in _mystery_labels(m):
            if topic_mem.topics_match(lv, ml):
                return True
    return False


def resolve_mystery_id(
    label: str,
    mysteries: list[dict[str, Any]] | None = None,
) -> int | None:
    label = (label or "").strip()
    if not label:
        return None
    if mysteries is None:
        try:
            mysteries = load_mysteries_raw()
        except (FileNotFoundError, ValueError):
            return None
    for m in mysteries:
        if mystery_matches_label(m, label):
            return int(m["id"])
    return None


def is_mystery_produced(
    m: dict[str, Any],
    blocked: list[str],
    produced_ids: set[int] | None = None,
) -> bool:
    ids = produced_ids if produced_ids is not None else get_produced_ids()
    if int(m["id"]) in ids:
        return True
    for ml in _mystery_labels(m):
        if any(topic_mem.topics_match(ml, b) for b in blocked):
            return True
    return False


def _remaining_mysteries(
    mysteries: list[dict[str, Any]], niche_id: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    blocked = topic_mem.get_blocked(niche_id or NICHE_ID)
    produced_ids = get_produced_ids()
    remaining: list[dict[str, Any]] = []
    done: list[dict[str, Any]] = []
    for m in mysteries:
        if is_mystery_produced(m, blocked, produced_ids):
            done.append(m)
        else:
            remaining.append(m)
    return remaining, done


def mark_produced_for_label(label: str, *, niche_id: str = NICHE_ID) -> dict[str, Any]:
    """Tek etiket (TR/EN konu) icin mystery ID + topic memory isaretle."""
    label = (label or "").strip()
    if not label:
        return {"ok": False, "label": label, "matched": False}
    mid = resolve_mystery_id(label)
    canonical = label
    if mid is not None:
        remember_produced_id(mid)
        for m in load_mysteries_raw():
            if int(m["id"]) == mid:
                canonical = _title(m)
                break
    topic_mem.remember_produced(niche_id, canonical)
    return {
        "ok": True,
        "label": label,
        "matched": mid is not None,
        "mystery_id": mid,
        "canonical_title": canonical,
    }


def mark_produced_through_index(
    max_index: int,
    *,
    niche_id: str = NICHE_ID,
) -> dict[str, Any]:
    """Site sirasinda 0..max_index arasi tum mystery'leri yapildi isaretle."""
    mysteries = load_mysteries_raw()
    if not mysteries:
        raise ValueError("Mystery listesi bos")
    idx = max(0, min(len(mysteries) - 1, int(max_index)))
    slice_items = mysteries[: idx + 1]
    ids = [int(m["id"]) for m in slice_items]
    return mark_produced_bulk(None, ids, niche_id=niche_id)


def mark_produced_through_id(
    through_id: int,
    *,
    niche_id: str = NICHE_ID,
) -> dict[str, Any]:
    """Verilen mystery ID'ye kadar (dahil) site sirasinda isaretle."""
    mysteries = load_mysteries_raw()
    max_index = -1
    for i, m in enumerate(mysteries):
        if int(m["id"]) == int(through_id):
            max_index = i
            break
    if max_index < 0:
        raise ValueError(f"Mystery ID bulunamadi: {through_id}")
    out = mark_produced_through_index(max_index, niche_id=niche_id)
    out["through_id"] = int(through_id)
    out["through_index"] = max_index
    out["through_title"] = _title(mysteries[max_index])
    return out


def mark_produced_bulk(
    labels: list[str] | None = None,
    mystery_ids: list[int] | None = None,
    *,
    niche_id: str = NICHE_ID,
) -> dict[str, Any]:
    """Toplu isaretleme — baslik listesi ve/veya mystery ID."""
    niche_id = niche_id or NICHE_ID
    matched_ids: set[int] = set(get_produced_ids())
    results: list[dict[str, Any]] = []
    unmatched: list[str] = []

    if mystery_ids:
        for mid in mystery_ids:
            matched_ids.add(int(mid))
            for m in load_mysteries_raw():
                if int(m["id"]) == int(mid):
                    topic_mem.remember_produced(niche_id, _title(m))
                    results.append({"id": int(mid), "title": _title(m), "source": "id"})
                    break

    labels = labels or []
    for raw in labels:
        label = (raw or "").strip()
        if len(label) < 2:
            continue
        mid = resolve_mystery_id(label)
        if mid is not None:
            matched_ids.add(mid)
            canonical = _title(next(m for m in load_mysteries_raw() if m["id"] == mid))
            topic_mem.remember_produced(niche_id, canonical)
            results.append({"id": mid, "title": canonical, "source": "label", "input": label})
        else:
            topic_mem.remember_produced(niche_id, label)
            unmatched.append(label)
            results.append({"id": None, "title": label, "source": "label_only", "input": label})

    _save_produced_ids(matched_ids)
    remaining, done = _remaining_mysteries(load_mysteries_raw(), niche_id)
    return {
        "ok": True,
        "marked": len(results),
        "matched_ids": len([r for r in results if r.get("id")]),
        "unmatched_labels": unmatched,
        "results": results,
        "produced_ids_count": len(matched_ids),
        "atlas_produced": len(done),
        "atlas_remaining": len(remaining),
    }


def sync_produced_from_sources(*, niche_id: str = NICHE_ID) -> dict[str, Any]:
    """Galeri + topic memory'den mystery ID eslestir ve isaretle."""
    labels: list[str] = list(topic_mem.get_blocked(niche_id))
    try:
        from akifactory import gallery as gal_mod

        for item in gal_mod.list_items():
            if (item.get("niche") or "").strip() not in ("", niche_id, "tarih_gizem"):
                continue
            for key in ("subject", "title"):
                v = (item.get(key) or "").strip()
                if v:
                    labels.append(v)
    except Exception:
        pass

    seen: list[str] = []
    for label in labels:
        if not any(topic_mem.topics_match(label, s) for s in seen):
            seen.append(label)

    return mark_produced_bulk(seen, niche_id=niche_id)


def remember_atlas_completion(topic: str, *, niche_id: str = NICHE_ID) -> None:
    """Atlas kuyrugundan biten video — ID + Turkce baslik kaydet."""
    mark_produced_for_label(topic, niche_id=niche_id)


def list_produced_ordered(niche_id: str = NICHE_ID) -> list[dict[str, Any]]:
    """Uretilenler UI — uretim sirasina gore (eskiden yeniye)."""
    niche_id = niche_id or NICHE_ID
    blocked = topic_mem.get_blocked(niche_id)
    chronological = list(reversed(blocked))  # hafiza: yeni basta → eskiden yeniye

    try:
        mysteries = load_mysteries_raw()
    except (FileNotFoundError, ValueError):
        mysteries = []

    by_id = {int(m["id"]): m for m in mysteries}
    out: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    seen_titles: list[str] = []

    for title in chronological:
        mid = resolve_mystery_id(title, mysteries) if mysteries else None
        if mid is not None and mid in seen_ids:
            continue
        if any(topic_mem.topics_match(title, t) for t in seen_titles):
            continue
        if mid is not None:
            m = by_id.get(mid)
            display = _title(m) if m else title
            cat = (m.get("category") or "").strip() if m else ""
            seen_ids.add(mid)
            out.append({"id": mid, "title": display, "category": cat})
        else:
            out.append({"id": None, "title": title, "category": ""})
        seen_titles.append(title)

    # Yalnizca produced_ids'te kalan (hafizada yok) — ID sirasiyla sonda
    for mid in sorted(get_produced_ids()):
        if mid in seen_ids:
            continue
        m = by_id.get(mid)
        if not m:
            continue
        out.append(
            {
                "id": mid,
                "title": _title(m),
                "category": (m.get("category") or "").strip(),
            }
        )
        seen_ids.add(mid)

    return out


def _gallery_index_labels(*, niche_id: str = NICHE_ID) -> list[str]:
    """Galeri index'inden hizli konu listesi (dosya/stat yok)."""
    try:
        from akifactory import gallery as gal_mod

        raw = gal_mod._load_index()
    except Exception:
        return []
    out: list[str] = []
    for e in raw:
        niche = (e.get("niche") or "").strip()
        if niche and niche not in ("", niche_id, "tarih_gizem"):
            continue
        for key in ("subject", "title"):
            v = (e.get(key) or "").strip()
            if v and not any(topic_mem.topics_match(v, x) for x in out):
                out.append(v)
    return out


def _mystery_ids_for_labels(
    labels: list[str],
    mysteries: list[dict[str, Any]],
) -> set[int]:
    ids: set[int] = set()
    for label in labels:
        mid = resolve_mystery_id(label, mysteries)
        if mid is not None:
            ids.add(int(mid))
    return ids


def forget_after_gallery_delete(
    items: list[dict[str, Any]],
    *,
    niche_id: str = NICHE_ID,
) -> dict[str, Any]:
    """Galeriden silinen kayitlari Uretilenler / Atlas isaretinden de dusur."""
    niche_id = niche_id or NICHE_ID
    forgotten_labels: list[str] = []
    released_ids: list[int] = []
    held_ids: list[int] = []

    try:
        mysteries = load_mysteries_raw()
    except (FileNotFoundError, ValueError):
        mysteries = []

    # Silme sonrasi kalan galeri — mysteries bir kez okunur
    remaining_ids = _mystery_ids_for_labels(
        _gallery_index_labels(niche_id=niche_id),
        mysteries,
    )
    produced = get_produced_ids()
    produced_dirty = False

    for item in items or []:
        if not isinstance(item, dict):
            continue
        item_niche = (item.get("niche") or "").strip() or niche_id
        labels: list[str] = []
        for key in ("subject", "title"):
            v = (item.get(key) or "").strip()
            if v and not any(topic_mem.topics_match(v, x) for x in labels):
                labels.append(v)
        for label in labels:
            if topic_mem.forget_produced(item_niche, label):
                forgotten_labels.append(label)
            mid = resolve_mystery_id(label, mysteries)
            if mid is None:
                continue
            if mid in remaining_ids:
                if mid not in held_ids:
                    held_ids.append(mid)
                continue
            if mid in produced:
                produced.discard(mid)
                produced_dirty = True
                if mid not in released_ids:
                    released_ids.append(mid)

    if produced_dirty:
        _save_produced_ids(produced)

    return {
        "forgotten_labels": forgotten_labels,
        "released_ids": released_ids,
        "held_ids": held_ids,
    }


def forget_atlas_topic(topic: str, *, niche_id: str = NICHE_ID) -> bool:
    """Uretilenlerden sil: topic memory + mystery ID isaretini kaldir."""
    topic = (topic or "").strip()
    if not topic:
        return False
    removed_mem = topic_mem.forget_produced(niche_id, topic)
    mid = resolve_mystery_id(topic)
    removed_id = False
    if mid is not None:
        ids = get_produced_ids()
        if mid in ids:
            ids.discard(mid)
            _save_produced_ids(ids)
            removed_id = True
    return removed_mem or removed_id


def catalog(niche_id: str = NICHE_ID) -> dict[str, Any]:
    path = resolve_json_path()
    try:
        mysteries = load_mysteries_raw()
    except (FileNotFoundError, ValueError) as exc:
        return {
            "ok": False,
            "json_path": str(path),
            "exists": path.is_file(),
            "error": str(exc),
            "total": 0,
            "produced": 0,
            "remaining": 0,
            "produced_ids": 0,
            "niche": niche_id,
        }
    remaining, done = _remaining_mysteries(mysteries, niche_id)
    return {
        "ok": True,
        "json_path": str(path),
        "exists": True,
        "total": len(mysteries),
        "produced": len(done),
        "remaining": len(remaining),
        "produced_ids": len(get_produced_ids()),
        "niche": niche_id,
        "error": None,
    }


def preview(count: int = 10, niche_id: str = NICHE_ID) -> dict[str, Any]:
    cat = catalog(niche_id)
    if not cat.get("ok"):
        return {**cat, "count": 0, "next": [], "skipped_produced": []}

    mysteries = load_mysteries_raw()
    remaining, done = _remaining_mysteries(mysteries, niche_id)
    n = max(1, min(MAX_QUEUE, int(count or 10)))
    next_items = [
        {
            "id": m["id"],
            "title": m["title"],
            "category": m.get("category", ""),
        }
        for m in remaining[:n]
    ]
    skipped = [
        {"id": m["id"], "title": m["title"]}
        for m in done[:8]
    ]
    return {
        **cat,
        "count": len(next_items),
        "requested": n,
        "next": next_items,
        "skipped_produced": skipped,
    }


def pick_topics(count: int, niche_id: str = NICHE_ID) -> list[str]:
    prev = preview(count, niche_id)
    if not prev.get("ok"):
        raise FileNotFoundError(prev.get("error") or "Enigma listesi okunamadi")
    topics = [item["title"] for item in prev.get("next") or []]
    if not topics:
        raise ValueError("Uretilecek yeni konu kalmadi")
    return topics


def english_title_for_topic(title: str) -> str:
    """Atlas mystery kaydindaki title_en — Wikipedia EN aramasi icin."""
    needle = (title or "").strip().lower()
    if not needle:
        return ""
    for m in load_mysteries_raw():
        if _title(m).lower() == needle:
            return (m.get("title_en") or "").strip()
    return ""


def chunk_topics(topics: list[str], size: int = BATCH_CHUNK) -> list[list[str]]:
    n = max(1, min(BATCH_CHUNK, int(size or BATCH_CHUNK)))
    return [topics[i : i + n] for i in range(0, len(topics), n)]
