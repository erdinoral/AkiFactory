"""Konu onerisi tekrar engeli — uretilmis konular kalici, onerilenler kisa sureli (son 40)."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from akifactory import json_io as jio
from akifactory.paths import data_dir

MEMORY_FILE = "topic_memory.json"
MAX_PER_NICHE = 250
MAX_SUGGESTED_PER_NICHE = 40


def _path() -> Path:
    return data_dir() / MEMORY_FILE


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
    jio.safe_write_json(p, jio.stamp_schema(data))


def normalize_topic(text: str) -> str:
    s = (text or "").strip().lower()
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def topics_match(a: str, b: str) -> bool:
    na, nb = normalize_topic(a), normalize_topic(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(shorter) < 8:
        return na == nb
    if shorter in longer and len(shorter) / max(len(longer), 1) >= 0.72:
        return True
    return False


def similarity_ratio(a: str, b: str) -> float:
    """0–1 benzerlik (difflib)."""
    from difflib import SequenceMatcher

    na, nb = normalize_topic(a), normalize_topic(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def find_similar(
    topic: str,
    niche_id: str = "genel",
    *,
    threshold: float = 0.72,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Uretilmis konular arasinda benzer olanlari bul (engellemez)."""
    blocked = get_blocked(niche_id)
    hits: list[dict[str, Any]] = []
    for b in blocked:
        if topics_match(topic, b):
            hits.append({"topic": b, "score": 1.0, "match": "exact"})
            continue
        score = similarity_ratio(topic, b)
        if score >= threshold:
            hits.append({"topic": b, "score": round(score, 3), "match": "similar"})
    hits.sort(key=lambda x: x["score"], reverse=True)
    return hits[:limit]


def similarity_warning(topic: str, niche_id: str = "genel") -> str | None:
    hits = find_similar(topic, niche_id)
    if not hits:
        return None
    top = hits[0]
    return (
        f"Benzer konu daha once uretilmis: «{top['topic']}» "
        f"(benzerlik {int(top['score'] * 100)}%). Istersen yine de uretebilirsin."
    )

def _produced_list(data: dict[str, Any], niche_id: str) -> list[str]:
    niches = data.setdefault("niches", {})
    key = (niche_id or "genel").strip() or "genel"
    raw = niches.get(key)
    if isinstance(raw, list):
        return list(raw)
    if isinstance(raw, dict):
        return list(raw.get("produced") or [])
    return []


def _set_produced_list(data: dict[str, Any], niche_id: str, items: list[str]) -> None:
    niches = data.setdefault("niches", {})
    key = (niche_id or "genel").strip() or "genel"
    prev = niches.get(key) if isinstance(niches.get(key), dict) else {}
    niches[key] = {
        "produced": items[:MAX_PER_NICHE],
        "suggested": list(prev.get("suggested") or [])[:MAX_SUGGESTED_PER_NICHE],
    }


def get_recent_suggested(niche_id: str) -> list[str]:
    """Son onerilen (henuz uretilmemis) konular — ayni oneri tekrar gelmesin."""
    raw = _load().get("niches", {}).get((niche_id or "genel").strip() or "genel")
    if isinstance(raw, dict):
        return list(raw.get("suggested") or [])
    return []


def remember_suggested(niche_id: str, topics: list[str]) -> None:
    fresh = [(t or "").strip()[:200] for t in topics if len((t or "").strip()) >= 3]
    if not fresh:
        return
    data = _load()
    niches = data.setdefault("niches", {})
    key = (niche_id or "genel").strip() or "genel"
    produced = _produced_list(data, key)
    old = get_recent_suggested(key)
    merged = fresh + [t for t in old if not any(topics_match(t, f) for f in fresh)]
    niches[key] = {
        "produced": produced[:MAX_PER_NICHE],
        "suggested": merged[:MAX_SUGGESTED_PER_NICHE],
    }
    _save(data)


def get_blocked(niche_id: str) -> list[str]:
    """Yalnizca bu niste daha once video uretilmis konular."""
    items = _produced_list(_load(), niche_id)
    seen: list[str] = []
    for topic in items:
        if not any(topics_match(topic, s) for s in seen):
            seen.append(topic)
    return seen


_GENERIC_HEAD_WORDS = frozenset(
    "kayip gizem gizemi gizemli antik sirri sirlari efsane efsanesi lanetli lanet "
    "bilinmeyen cozulemeyen cozulmemis gizli eski buyuk ilk son".split()
)


def topics_close(a: str, b: str) -> bool:
    """Oneri tekrarini yakalamak icin gevsek eslesme (ek farki, ayni ozel isim)."""
    if topics_match(a, b):
        return True
    if similarity_ratio(a, b) >= 0.8:
        return True
    return _head_key(a) != "" and _head_key(a) == _head_key(b)


def _head_key(text: str) -> str:
    """Ozel isim anahtari: ilk kelime; kisaysa ilk iki kelime ('nan madol')."""
    words = normalize_topic(text).replace("ı", "i").split()
    if not words or words[0] in _GENERIC_HEAD_WORDS:
        return ""
    if len(words[0]) >= 5:
        return words[0]
    if len(words) >= 2 and words[1] not in _GENERIC_HEAD_WORDS:
        key = f"{words[0]} {words[1]}"
        return key if len(key) >= 6 else ""
    return ""


def filter_new(
    candidates: list[str],
    blocked: list[str] | None = None,
    *,
    loose: bool = False,
) -> list[str]:
    blocked = blocked or []
    match = topics_close if loose else topics_match
    out: list[str] = []
    for raw in candidates:
        topic = (raw or "").strip()
        if len(topic) < 3:
            continue
        if any(match(topic, b) for b in blocked):
            continue
        if any(match(topic, x) for x in out):
            continue
        out.append(topic)
    return out


def remember_produced(niche_id: str, topic: str) -> None:
    topic = (topic or "").strip()
    if len(topic) < 3:
        return
    data = _load()
    items = _produced_list(data, niche_id)
    if any(topics_match(topic, existing) for existing in items):
        return
    items.insert(0, topic[:500])
    _set_produced_list(data, niche_id, items)
    _save(data)


def forget_produced(niche_id: str, topic: str) -> bool:
    """Uretilmis konuyu hafizadan sil — tekrar uretilebilir/onerilebilir olur."""
    topic = (topic or "").strip()
    if not topic:
        return False
    data = _load()
    items = _produced_list(data, niche_id)
    kept = [t for t in items if not topics_match(topic, t)]
    if len(kept) == len(items):
        return False
    _set_produced_list(data, niche_id, kept)
    _save(data)
    return True


def stats(niche_id: str) -> dict[str, int]:
    produced = get_blocked(niche_id)
    return {"produced": len(produced), "blocked": len(produced)}
