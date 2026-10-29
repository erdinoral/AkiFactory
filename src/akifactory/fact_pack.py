"""Typed fact pack — arastirma → yapilandirilmis olgular (Faz B).

Geri al: bu dosya + content_studio / script_prompts baglantilari.
"""

from __future__ import annotations

import json
import re
from typing import Any

from akifactory.ollama_util import chat as ollama_chat

_FACT_PACK_SYSTEM = """Sen kisa video icin olgu paketleyicisisin.
Yalnizca gecerli JSON dondur. Uydurma ekleme; arastirma notuna sadik kal."""


def empty_fact_pack() -> dict[str, Any]:
    return {
        "entities": [],
        "dates": [],
        "places": [],
        "claims": [],
        "uncertain": [],
    }


def fact_pack_to_prompt_block(pack: dict[str, Any], *, topic: str = "") -> str:
    """Writer / skeleton icin metin blogu."""
    if not pack or not any(pack.get(k) for k in ("claims", "entities", "dates", "places")):
        return ""
    lines: list[str] = ["FACT PACK (zorunlu — disina cikma, uydurma yok):"]
    if topic.strip():
        lines.append(f"Konu: {topic.strip()}")
    for key, label in (
        ("entities", "Kim/ne"),
        ("dates", "Ne zaman"),
        ("places", "Nerede"),
        ("claims", "Olgu"),
        ("uncertain", "Belirsiz"),
    ):
        items = [str(x).strip() for x in (pack.get(key) or []) if str(x).strip()]
        if not items:
            continue
        lines.append(f"{label}:")
        for it in items[:8]:
            lines.append(f"- {it}")
    lines.append(
        "KURAL: Listeden yalnizca konuya dogrudan hizmet eden maddeleri kullan, konu disi maddeleri atla; "
        "listede olmayan isim/tarih/sayi uydurma."
    )
    return "\n".join(lines)


def fact_pack_to_brief_text(pack: dict[str, Any]) -> str:
    """Eski research_brief uyumu (fact-check promptlari)."""
    block = fact_pack_to_prompt_block(pack)
    return block.replace("FACT PACK (zorunlu — disina cikma, uydurma yok):", "OLGU OZETI:")


def claims_as_skeleton_bullets(pack: dict[str, Any]) -> list[str]:
    """Skeleton yerine veya yanina kullanilacak maddeler."""
    out: list[str] = []
    for key in ("entities", "dates", "places", "claims"):
        for it in pack.get(key) or []:
            s = str(it).strip()
            if len(s) >= 12:
                out.append(s)
            if len(out) >= 5:
                return out
    return out


def parse_fact_pack_json(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    # Markdown fence
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Ilk { ... } blogu
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    pack = empty_fact_pack()
    for key in pack:
        val = data.get(key)
        if isinstance(val, list):
            pack[key] = [str(x).strip() for x in val if str(x).strip()][:10]
        elif isinstance(val, str) and val.strip():
            pack[key] = [val.strip()]
    if not any(pack.values()):
        return None
    return pack


def pack_from_research_brief(brief: str) -> dict[str, Any]:
    """LLM olmadan brief satirlardan kaba paket (yedek)."""
    pack = empty_fact_pack()
    if not (brief or "").strip():
        return pack
    current = "claims"
    mapping = {
        "kim": "entities",
        "ne zaman": "dates",
        "nerede": "places",
        "ne oldu": "claims",
        "belirsiz": "uncertain",
        "diger": "claims",
    }
    for line in brief.splitlines():
        s = line.strip()
        if not s:
            continue
        low = s.lower().rstrip(":")
        hit = None
        for k, dest in mapping.items():
            if low.startswith(k):
                hit = dest
                break
        if hit:
            current = hit
            rest = re.sub(r"^[^:]+:\s*", "", s).strip()
            if rest and len(rest) > 3:
                pack[current].append(rest)
            continue
        s = re.sub(r"^[-*•–—]+\s*", "", s)
        if len(s) >= 12:
            pack[current].append(s)
    return pack if any(pack.values()) else empty_fact_pack()


async def build_fact_pack(
    topic: str,
    research_brief: str,
    *,
    niche_id: str = "genel",
    model: str | None = None,
) -> dict[str, Any]:
    """Arastirma metninden typed fact pack. Fail-open: kaba parse veya bos."""
    brief = (research_brief or "").strip()
    subj = (topic or "").strip()
    if not brief or len(subj) < 3:
        return pack_from_research_brief(brief) if brief else empty_fact_pack()

    user = (
        f"Konu: {subj}\nNiş: {niche_id}\n\n"
        f"ARASTIRMA NOTU:\n{brief[:2200]}\n\n"
        "Bu nottan JSON uret. Anahtarlar (dizi of string):\n"
        '{"entities":[],"dates":[],"places":[],"claims":[],"uncertain":[]}\n'
        "claims: konuya dogrudan ilgili 3-6 somut olgu (konu soruysa cevabina hizmet edenler). "
        "uncertain: emin olunmayanlar.\n"
        "Konu disi bilgiyi alma; notta olmayan bilgi ekleme. Sadece JSON."
    )
    try:
        raw = await ollama_chat(
            [
                {"role": "system", "content": _FACT_PACK_SYSTEM},
                {"role": "user", "content": user},
            ],
            think=False,
            model=model,
            timeout=90.0,
            clean_script=False,
            format_json=True,
            options={"temperature": 0.2, "top_p": 0.8},
        )
        parsed = parse_fact_pack_json(raw or "")
        if parsed and (parsed.get("claims") or parsed.get("entities")):
            return parsed
    except Exception:
        pass
    return pack_from_research_brief(brief)
