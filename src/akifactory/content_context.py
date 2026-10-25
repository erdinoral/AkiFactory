"""Icerik anayasasi + nis baglami — LLM prompt enjeksiyonu (Faz A).

Geri al: bu modul + data/content_constitution.md + data/niche_context/
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from akifactory.paths import data_dir

_CONSTITUTION = "content_constitution.md"
_NICHE_DIR = "niche_context"


def constitution_path() -> Path:
    return data_dir() / _CONSTITUTION


def niche_context_path(niche_id: str) -> Path:
    key = (niche_id or "genel").strip().lower() or "genel"
    return data_dir() / _NICHE_DIR / f"{key}.md"


@lru_cache(maxsize=8)
def load_constitution(*, max_chars: int = 1800) -> str:
    p = constitution_path()
    if not p.is_file():
        return ""
    try:
        text = p.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if len(text) > max_chars:
        return text[: max_chars - 20].rstrip() + "\n…"
    return text


@lru_cache(maxsize=32)
def load_niche_context(niche_id: str, *, max_chars: int = 1200) -> str:
    p = niche_context_path(niche_id)
    if not p.is_file():
        p = niche_context_path("genel")
    if not p.is_file():
        return ""
    try:
        text = p.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if len(text) > max_chars:
        return text[: max_chars - 20].rstrip() + "\n…"
    return text


def constitution_prompt_block(*, max_chars: int = 1600) -> str:
    body = load_constitution(max_chars=max_chars)
    if not body:
        return ""
    return "İÇERİK ANAYASASI (zorunlu):\n" + body


def niche_context_prompt_block(niche_id: str, *, max_chars: int = 1000) -> str:
    body = load_niche_context(niche_id, max_chars=max_chars)
    if not body:
        return ""
    return f"NİŞ BAĞLAMI ({(niche_id or 'genel').strip()}):\n" + body


def content_law_blocks(niche_id: str = "genel") -> str:
    """System prompt sonuna eklenecek birlesik blok."""
    parts = [
        constitution_prompt_block(),
        niche_context_prompt_block(niche_id),
    ]
    return "\n\n".join(p for p in parts if p)


def reload_content_context() -> None:
    load_constitution.cache_clear()
    load_niche_context.cache_clear()
