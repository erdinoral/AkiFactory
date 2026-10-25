"""Senaryo cevirisi — cift dil uretim icin."""

from __future__ import annotations

from akifactory.ollama_util import chat as ollama_chat
from akifactory.text_utils import clean_turkish_script

_LANG_NAMES = {"tr": "Turkce", "en": "English", "de": "German", "fr": "French"}


async def translate_script(
    script: str,
    *,
    from_lang: str = "tr",
    to_lang: str = "en",
    model: str | None = None,
) -> str:
    text = (script or "").strip()
    if not text or from_lang == to_lang:
        return text
    src = _LANG_NAMES.get(from_lang, from_lang)
    dst = _LANG_NAMES.get(to_lang, to_lang)
    prompt = (
        f"Asagidaki {src} konusma metnini {dst} diline cevir.\n"
        "Kurallar:\n"
        "- Dogal konusma dili, kisa cumleler (altyazi uyumlu)\n"
        "- Yalnizca ceviri metnini yaz; aciklama veya baslik ekleme\n"
        "- Orijinal anlam ve merak/hook tonunu koru\n\n"
        f"METIN:\n{text}"
    )
    content = await ollama_chat(
        [{"role": "user", "content": prompt}],
        model=model,
        think=False,
        timeout=120.0,
        clean_script=True,
    )
    out = clean_turkish_script(content or "").strip()
    return out or text
