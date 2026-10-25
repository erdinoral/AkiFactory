"""Fooocus (SDXL) icin gorsel prompt uretimi (Ollama)."""

from __future__ import annotations

import re

from akifactory.ollama_util import chat as ollama_chat
from akifactory.ollama_util import creative_chat_options
from akifactory.wangp_prompt import _diversity_block

NICHE_MOOD: dict[str, str] = {
    "tarih_gizem": "investigative documentary mystery mood",
    "teknoloji": "modern tech documentary tone",
    "uzay": "NASA-style cosmic realism mood",
    "tarihi_insanlar": "period-accurate historical portrait mood",
    "tarihi_olaylar": "archival historical reenactment tone",
    "savaslar": "dramatic war documentary mood",
    "yeme_icme": "warm appetizing food photography mood",
    "cocuk_eglence": "bright child-friendly cheerful mood",
    "oyun": "dynamic game-inspired cinematic mood",
    "muzik": "concert performance energy mood",
    "sanat": "museum gallery artistic mood",
    "seyahat": "travel vlog golden-hour wanderlust mood",
    "genel": "cinematic realism, clear subject focus",
}

STYLE_LABELS = {
    "photorealistic": "Fotogercekci / belgesel",
    "cinematic": "Sinematik film karesi",
    "dark_mystery": "Karanlik gizem",
    "illustration": "Dijital illüstrasyon",
    "epic_history": "Epik tarih / dramatik",
}

PURPOSE_LABELS = {
    "thumbnail": "Kapak / thumbnail (tek guclu kare)",
    "scene": "Video sahnesi / B-roll karesi",
    "cover": "Kanal kapak gorseli",
}

DEFAULT_NEGATIVE = (
    "worst quality, low quality, normal quality, lowres, blurry, text, watermark, "
    "logo, signature, username, bad anatomy, bad hands, missing fingers, extra digits, "
    "deformed, ugly, duplicate, morbid, mutilated, out of frame, jpeg artifacts, "
    "oversaturated, cartoon, anime, 3d render"
)

_GENERIC_TEMPLATE_PHRASES = (
    "ancient ruins",
    "dusty archives",
    "mysterious artifacts",
    "dim torchlight",
)


def _is_generic_niche_template(positive: str) -> bool:
    low = positive.lower()
    return sum(1 for phrase in _GENERIC_TEMPLATE_PHRASES if phrase in low) >= 2


def _build_user_prompt(
    *,
    topic: str,
    niche_id: str,
    style: str,
    aspect: str,
    purpose: str,
    variant_count: int,
    from_gallery: bool = False,
) -> str:
    mood = NICHE_MOOD.get(niche_id, NICHE_MOOD["genel"])
    style_label = STYLE_LABELS.get(style, style)
    purpose_label = PURPOSE_LABELS.get(purpose, purpose)
    framing = {
        "9:16": "vertical portrait 9:16, mobile thumbnail composition",
        "16:9": "widescreen 16:9 cinematic composition",
        "1:1": "square 1:1 centered composition",
    }.get(aspect, "vertical 9:16 composition")

    variants_hint = ""
    if variant_count > 1:
        variants_hint = f"""
VARIANTS:
({variant_count - 1} adet alternatif POSITIVE prompt — her biri farkli kompozisyon/isik, tek satir; konu ayni kalmali)"""

    gallery_rules = ""
    if from_gallery:
        gallery_rules = """
- Bu prompt, URETILMIS videonun basligi ve senaryosuyla DOGRUDAN uyumlu olmali
- Videodaki ana sahne, nesne veya atmosferi tek karede ozetle; alakasiz stok gorsel yasak
- Basliktaki merak/hook duygusunu gorselde yansit"""

    topic_label = "Galeri videosu baglami" if from_gallery else "Konu"

    return f"""{topic_label} (Turkce — BU METIN GORSELIN ANA KONUSU):
{topic}

GOREV: Fooocus (SDXL) icin Ingilizce GORSEL prompt yaz.
Kullanici bunu Fooocus uygulamasindaki Prompt kutusuna yapistiracak; burada gorsel URETILMEYECEK.

AMAC: {purpose_label}
PLATFORM ORANI: {framing}
ATMOSFER IPUCU (yalnizca ruh hali — sahne icerigi DEGIL): {mood}
STIL: {style_label}

KONU SADAKATI (EN ONEMLI — IHLAL YASAK):
1. Turkce konuyu oku; ana nesne, olay, yer veya kisi kim? Bunu Ingilizce somut gorsel taglere cevir.
2. POSITIVE promptun ILK YARISI konuya ozel olmali (ornek konu "Voynich El Yazmasi" → voynich manuscript, medieval encrypted codex, undeciphered botanical illustrations on aged parchment, mysterious cipher symbols).
3. Konuda GECMEYEN jenerik sahneler YASAK: ancient ruins, generic temple, random dusty archive, torchlit corridor — ancak konu bunlari acikca iceriyorsa kullan.
4. ATMOSFER IPUCU satirini prompta KOPYALAMA veya yapistirma; sadece isik/ruh tonu icin ilham al.
5. Niş sablonu veya onceki ornek cumleleri birebir TEKRARLAMA.

ORNEK:
Konu: Voynich El Yazmasi
YANLIS: ancient ruins, dim torchlight, dusty archives, mysterious artifacts
DOGRU: voynich manuscript open on oak desk, medieval codex with strange botanical illustrations, yellowed parchment pages, undeciphered cipher text, candlelit Renaissance scriptorium, scholar's magnifying glass

KURALLAR:
- POSITIVE: Ingilizce, virgulle ayrilmis SDXL/SD tagleri (Fooocus format)
- Somut konu nesneleri + kamera acisi + isik + atmosfer + {framing}
- Kalite: masterpiece, best quality, highly detailed (abartma)
- Metin, altyazi, watermark, logo isteme
- Markdown, numara, madde isareti kullanma
- Dusunme metni yazma
- Max ~80 kelime POSITIVE
- Her uretimde FARKLI kompozisyon, kamera ve isik kullan; konu sabit kalir
{gallery_rules}
{_diversity_block()}

CIKTI FORMATI (aynen bu basliklar):
POSITIVE:
(tek blok virgullu tagler)

NEGATIVE:
(tek satir negatif tagler)

FOOOCUS_AYAR:
(Turkce 2-4 cumle: Prompt alanina yapistir, Performance/Speed secimi, aspect {aspect}, sharpness 2, CFG 4-7 onerisi){variants_hint}"""


def _parse_positive(content: str) -> str:
    m = re.search(r"POSITIVE:\s*(.+?)(?=NEGATIVE:|VARIANTS:|FOOOCUS_AYAR:|$)", content, re.S | re.I)
    if not m:
        return ""
    lines = [ln.strip() for ln in m.group(1).strip().splitlines() if ln.strip()]
    text = " ".join(lines)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1200]


def _parse_negative(content: str) -> str:
    m = re.search(r"NEGATIVE:\s*(.+?)(?=FOOOCUS_AYAR:|VARIANTS:|$)", content, re.S | re.I)
    if not m:
        return DEFAULT_NEGATIVE
    text = m.group(1).strip().splitlines()[0].strip()
    return text[:500] if text else DEFAULT_NEGATIVE


def _parse_notes(content: str) -> str:
    m = re.search(r"FOOOCUS_AYAR:\s*(.+)", content, re.S | re.I)
    if not m:
        return ""
    return m.group(1).strip()[:800]


def _parse_variants(content: str) -> list[str]:
    m = re.search(r"VARIANTS:\s*(.+?)(?=FOOOCUS_AYAR:|$)", content, re.S | re.I)
    if not m:
        return []
    out: list[str] = []
    for line in m.group(1).strip().splitlines():
        line = re.sub(r"^\d+[\).\-\s]+", "", line.strip())
        line = line.strip("-•* ")
        if line and len(line) > 15:
            out.append(line[:600])
    return out[:3]


def _resolve_gallery_title(
    *,
    title: str = "",
    publish_pack: dict | None = None,
) -> str:
    pack = publish_pack or {}
    t = (title or pack.get("best_title") or "").strip()
    if t:
        return t
    titles = pack.get("titles") or []
    if titles and isinstance(titles[0], dict):
        return str(titles[0].get("text") or "").strip()
    return ""


def build_gallery_topic(
    *,
    subject: str = "",
    title: str = "",
    script: str = "",
    publish_pack: dict | None = None,
) -> str:
    """Video basligi + senaryo baglami — Fooocus icin."""
    pack = publish_pack or {}
    resolved_title = _resolve_gallery_title(title=title, publish_pack=pack)
    subject = (subject or "").strip()
    script = (script or "").strip()
    lines: list[str] = []
    if subject:
        lines.append(f"Video konusu: {subject}")
    if resolved_title:
        lines.append(f"Video basligi: {resolved_title}")
    alt = pack.get("title_alternatives") or []
    if alt and isinstance(alt[0], dict):
        alt_txt = str(alt[0].get("text") or "").strip()
        if alt_txt and alt_txt != resolved_title:
            lines.append(f"Alternatif baslik: {alt_txt}")
    if script:
        excerpt = script[:900] + ("…" if len(script) > 900 else "")
        lines.append(f"Senaryo (videodaki anlatim):\n{excerpt}")
    return "\n".join(lines).strip() or subject or resolved_title or "Video"


def _normalize_aspect(aspect: str | None) -> str:
    a = (aspect or "9:16").strip()
    return a if a in ("9:16", "16:9", "1:1") else "9:16"


async def _run_fooocus(
    *,
    topic: str,
    niche_id: str,
    style: str,
    aspect: str,
    purpose: str,
    variant_count: int,
    from_gallery: bool = False,
) -> dict[str, str | list[str]]:
    variant_count = max(1, min(3, int(variant_count)))
    base_prompt = _build_user_prompt(
        topic=topic.strip(),
        niche_id=niche_id,
        style=style,
        aspect=aspect,
        purpose=purpose,
        variant_count=variant_count,
        from_gallery=from_gallery,
    )
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "You write Fooocus SDXL image prompts in English. "
                "The user's Turkish topic is the mandatory visual subject. "
                "Never output generic niche stock scenes (ruins, archives, temples) "
                "unless the topic explicitly mentions them. "
                "Translate the specific subject into concrete visual tags first."
            ),
        },
    ]
    content = ""
    positive = ""
    negative = DEFAULT_NEGATIVE
    notes = ""
    variants: list[str] = []

    for attempt in range(2):
        user_prompt = base_prompt
        if attempt > 0:
            user_prompt += (
                "\n\nUYARI: Onceki cevap konudan bagimsiz jenerik tarih/gizem sablonu kullandi. "
                "Yalnizca yukaridaki Turkce konunun somut gorselini yaz."
            )
        messages = messages[:1] + [{"role": "user", "content": user_prompt}]
        content = await ollama_chat(
            messages,
            think=False,
            timeout=120.0,
            clean_script=False,
            options=creative_chat_options(),
        )
        content = (content or "").strip()
        positive = _parse_positive(content)
        negative = _parse_negative(content)
        notes = _parse_notes(content)
        variants = _parse_variants(content)
        if positive and not _is_generic_niche_template(positive):
            break

    if not positive and content:
        for line in content.splitlines():
            line = line.strip()
            if line and not re.match(r"^(POSITIVE|NEGATIVE|VARIANTS|FOOOCUS_AYAR)", line, re.I):
                if len(line) > 20:
                    positive = line[:1200]
                    break

    return {
        "prompt": positive,
        "negative_prompt": negative,
        "fooocus_notes": notes,
        "variants": variants,
        "style": style,
        "aspect": aspect,
        "purpose": purpose,
    }


async def generate_fooocus_prompt(
    *,
    topic: str,
    niche_id: str = "tarih_gizem",
    style: str = "photorealistic",
    aspect: str = "9:16",
    purpose: str = "thumbnail",
    variant_count: int = 1,
) -> dict[str, str | list[str]]:
    return await _run_fooocus(
        topic=topic,
        niche_id=niche_id,
        style=style,
        aspect=aspect,
        purpose=purpose,
        variant_count=variant_count,
        from_gallery=False,
    )


async def generate_fooocus_prompt_for_gallery(
    *,
    subject: str = "",
    title: str = "",
    script: str = "",
    publish_pack: dict | None = None,
    niche_id: str = "tarih_gizem",
    style: str = "photorealistic",
    aspect: str = "9:16",
    purpose: str = "thumbnail",
    variant_count: int = 1,
) -> dict[str, str | list[str]]:
    topic = build_gallery_topic(
        subject=subject,
        title=title,
        script=script,
        publish_pack=publish_pack,
    )
    if len(topic) < 4:
        raise ValueError("Video konusu veya senaryo yok — Fooocus promptu uretilemez")
    return await _run_fooocus(
        topic=topic,
        niche_id=niche_id,
        style=style,
        aspect=_normalize_aspect(aspect),
        purpose=purpose,
        variant_count=variant_count,
        from_gallery=True,
    )
