"""LLM ile nis bazli yeni hook ornegi uretimi."""

from __future__ import annotations

from akifactory.ollama_util import chat as ollama_chat
from akifactory.script_prompts import NICHE_LABELS, NICHE_SUGGEST_HINTS, resolve_niche
from akifactory.text_utils import clean_turkish_script


async def generate_hook_example(
    niche_id: str,
    *,
    exclude: list[str] | None = None,
) -> str:
    from akifactory import hook_memory as hook_mem_mod

    niche = resolve_niche(niche_id)
    label = NICHE_LABELS.get(niche, niche)
    hint = NICHE_SUGGEST_HINTS.get(niche, "ilgi cekici konular")
    exclude_norm = {(t or "").strip().lower() for t in (exclude or []) if (t or "").strip()}
    mem_block = hook_mem_mod.prompt_block(niche, good_limit=8, bad_limit=8)
    avoid = "\n".join(f"- {(t or '').strip()}" for t in (exclude or [])[:40] if (t or "").strip())
    avoid_block = f"\nASLA TEKRARLAMA (bu cumleler ve cok benzerleri):\n{avoid}\n" if avoid else ""

    prompt = f"""Sen {label} nisinde kisa video acilis cumlesi (hook) yazarisin.

GOREV: Tek bir acilis cumlesi yaz — merak uyandirici, dogal konusma Turkcesi.
Niş odagi: {hint}
{mem_block}{avoid_block}
KURALLAR:
- Tek cumle; 12-28 kelime
- Tarih, sayi, yer veya somut olgu kullan
- Soru isareti YOK; Biliyor muydunuz, Peki, Bu videoda YASAK
- Turkce karakterler: ç, ğ, ı, ö, ş, ü
- Sadece cumleyi yaz; aciklama veya etiket yazma
"""

    last = ""
    for _ in range(4):
        raw = await ollama_chat([{"role": "user", "content": prompt}], think=False, timeout=90.0)
        line = (raw or "").strip().splitlines()[0] if raw else ""
        hook = clean_turkish_script(line).strip().strip("\"'«»")
        last = hook
        if len(hook) < 12:
            continue
        if hook.lower() in exclude_norm:
            continue
        if any(hook.lower() in ex or ex in hook.lower() for ex in exclude_norm if len(ex) > 10):
            continue
        return hook[:500]
    if len(last) >= 12:
        return last[:500]
    raise RuntimeError("Yeni hook uretilemedi — Ollama calisiyor mu kontrol edin")
