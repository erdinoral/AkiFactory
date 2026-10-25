"""Konu → 4–5 somut olgu iskeleti (senaryo oncesi baglama).

Fail-open: iskelet uretilemezse bos doner; mevcut akis bozulmaz.
"""

from __future__ import annotations

import re

from akifactory.ollama_util import chat as ollama_chat
from akifactory.script_hooks import is_kids_niche
from akifactory.script_topic import normalize_narrative_topic, topic_prompt_block

_MIN_BULLETS = 3
_MAX_BULLETS = 5

_SKELETON_SYSTEM = """Sen kisa video icin olgu iskeleti yazarisin.
Tercihen gecerli JSON dondur: {"bullets":["...","..."]} (3-5 madde).
JSON uretemezsen tire (-) ile madde listesi yaz. Giris cumlesi yok.
Uydurma isim/tarih/yer yazma; emin degilsen genel ama dogru kal."""


def parse_skeleton_bullets(raw: str) -> list[str]:
    """LLM ciktisindan JSON veya tire/numara maddelerini cikar."""
    text = (raw or "").strip()
    if not text:
        return []
    # JSON once
    try:
        import json

        fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
        blob = fence.group(1).strip() if fence else text
        data = None
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            m = re.search(r"\{[\s\S]*\}", blob)
            if m:
                data = json.loads(m.group(0))
        if isinstance(data, dict):
            bullets = data.get("bullets") or data.get("facts") or data.get("items")
            if isinstance(bullets, list):
                out = [str(x).strip() for x in bullets if len(str(x).strip()) >= 12]
                return out[:_MAX_BULLETS]
        if isinstance(data, list):
            out = [str(x).strip() for x in data if len(str(x).strip()) >= 12]
            return out[:_MAX_BULLETS]
    except Exception:
        pass

    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        s = re.sub(r"^[-*•–—]+\s*", "", s)
        s = re.sub(r"^\d+[.)]\s*", "", s)
        s = s.strip(" «»\"'")
        if len(s) < 12:
            continue
        low = s.lower()
        if low.startswith(("gorev", "konu:", "nis:", "örnek", "ornek", "bullets")):
            continue
        out.append(s)
        if len(out) >= _MAX_BULLETS:
            break
    return out


def format_skeleton_for_prompt(bullets: list[str], *, topic: str = "") -> str:
    if not bullets:
        return ""
    lines = "\n".join(f"- {b}" for b in bullets[:_MAX_BULLETS])
    topic_line = (topic or "").strip()
    head = f"OLGU ISKELETI (zorunlu — senaryoyu BUNDAN yaz; disina cikma):\n{lines}\n"
    rules = (
        "KURALLAR:\n"
        "- Her cumle iskeletteki bir olguya dayanmali\n"
        "- Iskelette olmayan kisi/yer/tarih UYDURMA\n"
        "- Ilk cumle (hook): konu anahtar kelimesi + iskeletteki carpici olgu\n"
        "- Jenerik gizem YASAK (karanlik kapi, kimse donmedi, bu sirri ilk kez)\n"
        "- Madde listesini oldugu gibi kopyalama; akici konusma metnine cevir\n"
    )
    if topic_line:
        return f"{head}Konu: {topic_line}\n{rules}"
    return head + rules


async def generate_fact_skeleton(
    topic: str,
    *,
    niche_id: str = "genel",
    niche_label: str = "",
    research_context: str = "",
    model: str | None = None,
) -> list[str]:
    """4–5 Turkce olgu maddesi. Basarisizsa []."""
    subj = (topic or "").strip()
    if len(subj) < 3:
        return []
    if is_kids_niche(niche_id):
        return []

    narrative = normalize_narrative_topic(subj)
    research = (research_context or "").strip()
    research_block = ""
    if research:
        research_block = (
            f"\nARASTIRMA NOTU (bunlara sadik kal, celisen uydurma):\n"
            f"{research[:1800]}\n"
        )

    label = (niche_label or niche_id or "genel").strip()
    user = (
        f"{topic_prompt_block(subj)}\n"
        f"Niş: {label}\n"
        f"Anlatim odagi: {narrative or subj}\n"
        f"{research_block}\n"
        "Gorev: Bu konu icin 4 veya 5 SOMUT olgu maddesi yaz.\n"
        'Tercihen JSON: {"bullets":["madde1","madde2","madde3","madde4"]}\n'
        "JSON olmazsa her madde tek satir, tire (-) ile baslasin.\n"
        "Kapsam: kim/ne, ne zaman, nerede, ne oldu, sonuc (uygun olanlar).\n"
        "Sadece bilinen veya yuksek ihtimal dogru bilgiler.\n"
        "Yanitta SADECE JSON veya madde listesi — baska metin yok.\n"
    )
    try:
        raw = await ollama_chat(
            [
                {"role": "system", "content": _SKELETON_SYSTEM},
                {"role": "user", "content": user},
            ],
            think=False,
            model=model,
            timeout=90.0,
            clean_script=False,
            format_json=True,
            options={
                "temperature": 0.35,
                "top_p": 0.85,
                "repeat_penalty": 1.05,
            },
        )
        bullets = parse_skeleton_bullets(raw or "")
        if len(bullets) < _MIN_BULLETS:
            # JSON fail → serbest metin yedek
            raw2 = await ollama_chat(
                [
                    {"role": "system", "content": _SKELETON_SYSTEM},
                    {
                        "role": "user",
                        "content": user
                        + "\nJSON yerine tire maddeleri yaz.\n",
                    },
                ],
                think=False,
                model=model,
                timeout=90.0,
                clean_script=False,
                options={
                    "temperature": 0.35,
                    "top_p": 0.85,
                    "repeat_penalty": 1.05,
                },
            )
            bullets = parse_skeleton_bullets(raw2 or "")
    except Exception:
        return []

    if len(bullets) < _MIN_BULLETS:
        return []
    return bullets[:_MAX_BULLETS]
