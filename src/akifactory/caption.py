"""Sosyal medya caption + hashtag (Ollama).

Faz D: birincil yol publish_review; bu modul ince wrapper / yedek.
"""

from __future__ import annotations

import re

from akifactory.ollama_util import chat as ollama_chat
from akifactory.text_utils import clean_turkish_script

PLATFORM_LABELS = {
    "tiktok": "TikTok",
    "youtube_shorts": "YouTube Shorts",
    "instagram_reels": "Instagram Reels",
    "linkedin": "LinkedIn",
    "custom": "Ozel",
}

LANG_LABELS = {"tr": "Turkce", "en": "English", "de": "Deutsch", "fr": "Francais"}


async def generate_caption(
    topic: str,
    platform: str,
    language: str,
    script_text: str = "",
    *,
    niche_id: str = "genel",
    editor_model: str | None = None,
) -> dict[str, str]:
    """Caption uret — mumkunse publish_review (TR/EN); degilse legacy regex."""
    if (script_text or "").strip():
        try:
            from akifactory.content_studio import publish_review
            from akifactory.llm_profiles import resolve_editor_model
            from akifactory import ollama_util

            installed = await ollama_util.list_installed_models()
            model = (editor_model or "").strip() or resolve_editor_model(
                installed, None
            )
            pack = await publish_review(
                topic=topic,
                script=script_text,
                platform=platform,
                language=language or "tr",
                niche_id=niche_id,
                editor_model=model,
                include_share_tips=False,
            )
            cap = (pack.get("best_caption") or "").strip()
            tags = (pack.get("best_hashtags") or "").strip()
            title = (pack.get("best_title") or "").strip()
            if cap:
                # Galeri legacy: #tag bekliyorsa virgulleri cevir
                if tags and "#" not in tags:
                    parts = [t.strip() for t in tags.split(",") if t.strip()]
                    tags = " ".join(
                        f"#{p.replace(' ', '')}" if not p.startswith("#") else p
                        for p in parts[:20]
                    )
                out = {"caption": cap[:220], "hashtags": tags[:500]}
                if title:
                    out["title"] = title[:120]
                return out
        except Exception:
            pass

    return await _legacy_generate_caption(topic, platform, language, script_text)


async def _legacy_generate_caption(
    topic: str,
    platform: str,
    language: str,
    script_text: str = "",
) -> dict[str, str]:
    plat = PLATFORM_LABELS.get(platform, platform)
    lang = LANG_LABELS.get(language, language)
    script_bit = f"\nVideo metni: {script_text[:800]}" if script_text else ""
    law = ""
    try:
        from akifactory.content_context import constitution_prompt_block

        law = constitution_prompt_block(max_chars=600)
    except Exception:
        pass
    law_bit = f"\n{law}\n" if law else ""
    lang_id = (language or "tr").strip().lower()[:2]
    if lang_id == "en":
        tag_rule = "15 relevant hashtags (#), mostly English"
        lang_lock = "Caption MUST be English only — no Turkish."
    else:
        tag_rule = "15 adet ilgili hashtag (# ile, Turkce + Ingilizce karisik)"
        lang_lock = f"Caption {lang} dilinde olsun."
    prompt = f"""Sen bir sosyal medya uzmanisin.{law_bit}
Asagidaki kisa video icin {plat} platformuna ozel:
1. Dikkat cekici bir caption (max 150 karakter). {lang_lock}
2. {tag_rule}
yaz. Baska hicbir sey yazma, sadece su formatta:
CAPTION: ...
HASHTAGS: #tag1 #tag2 ...

Video konusu: {topic}{script_bit}"""

    content = await ollama_chat(
        [{"role": "user", "content": prompt}],
        think=False,
        timeout=90.0,
        clean_script=False,
    )
    content = clean_turkish_script(content)
    if not content:
        return {"caption": "", "hashtags": ""}

    caption = ""
    hashtags = ""
    cap_m = re.search(r"CAPTION:\s*(.+?)(?=HASHTAGS:|$)", content, re.S | re.I)
    tag_m = re.search(r"HASHTAGS:\s*(.+)", content, re.S | re.I)
    if cap_m:
        caption = cap_m.group(1).strip().splitlines()[0][:200]
    if tag_m:
        hashtags = tag_m.group(1).strip().splitlines()[0][:500]
    return {"caption": caption, "hashtags": hashtags}
