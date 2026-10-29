"""Cift LLM icerik studosu: senaryo + WanGP prompt iyilestirme + yayin paketi."""

from __future__ import annotations

import re
from typing import Any

from akifactory import script_prompts as script_pr
from akifactory import wangp_prompt as wangp_mod
from akifactory import web_search as web_sr
from akifactory.caption import LANG_LABELS, PLATFORM_LABELS
from akifactory.llm_profiles import EDITOR_DEFAULT, writer_model
from akifactory.ollama_util import chat as ollama_chat
from akifactory.ollama_util import release_vram_for_model_swap
from akifactory.script_topic import normalize_narrative_topic, topic_prompt_block
from akifactory.text_utils import clean_turkish_script
from akifactory.turkish_imla import imla_prompt_block

EDITOR_CHAT_OPTIONS: dict[str, float] = {
    "temperature": 0.45,
    "top_p": 0.85,
    "repeat_penalty": 1.12,
}

# Qwen3 thinking — arastirma sentezi + fact-check (yazar/senaryo YAZMAZ)
FACT_CHECK_THINK_OPTIONS: dict[str, float] = {
    "temperature": 0.6,
    "top_p": 0.95,
    "repeat_penalty": 1.15,
}


async def _fact_check_chat(
    messages: list[dict[str, str]],
    *,
    model: str,
    timeout: float = 240.0,
    think: bool = False,
) -> str:
    """Senaryo yeniden yazimi — varsayilan think kapali (thinking metni konusma metnine kariyordu).

    Arastirma ozeti icin think=True verilebilir; bos yanitta think=False yedek.
    """
    resolved = (model or EDITOR_DEFAULT).strip()
    opts = FACT_CHECK_THINK_OPTIONS if think else {**EDITOR_CHAT_OPTIONS, "temperature": 0.35}
    out = await ollama_chat(
        messages,
        model=resolved,
        think=bool(think),
        options=opts,
        timeout=timeout,
        clean_script=False,
    )
    if (out or "").strip():
        return out
    if think:
        return await ollama_chat(
            messages,
            model=resolved,
            think=False,
            options={**EDITOR_CHAT_OPTIONS, "temperature": 0.3},
            timeout=min(timeout, 180.0),
            clean_script=False,
        )
    return ""


# Editor bunlari eklediyse neredeyse her zaman taslak daha iyidir
_EDITOR_REGRESSION_ISSUES = frozenset(
    {
        "film_ozeti",
        "curutucu_acilis",
        "akademik_dil",
        "koordinat_spam",
        "konu_disinda",
    }
)


def _prefer_better_script(
    candidate: str,
    baseline: str,
    *,
    topic: str,
    niche_id: str,
) -> str:
    """Editor/fact-check cikisi taslagi bozduysa eski metni koru."""
    from akifactory import script_quality as script_q

    cand = (candidate or "").strip()
    base = (baseline or "").strip()
    if not cand:
        return base
    if not base or cand == base:
        return cand
    cand_issues = set(script_q.script_quality_issues(cand, topic, niche_id=niche_id))
    base_issues = set(script_q.script_quality_issues(base, topic, niche_id=niche_id))
    if (cand_issues - base_issues) & _EDITOR_REGRESSION_ISSUES:
        return base
    cand_crit = script_q.has_critical_quality_issues(cand, topic, niche_id=niche_id)
    base_crit = script_q.has_critical_quality_issues(base, topic, niche_id=niche_id)
    if cand_crit and not base_crit:
        return base
    # Soft issue sayisiyla fact-check duzeltmesini geri alma — sadece kirik/kesik cikti
    if len(cand) < 80 and len(base) >= 120:
        return base
    return cand

# Sabit konu basliklari — LLM yalnizca tavsiye metnini uretir
SHARE_TIP_CATEGORIES: tuple[str, ...] = (
    "En iyi paylasim saati",
    "En uygun gun",
    "Ilk 30 dakika stratejisi",
    "Ilk yorum ve sabitleme",
    "Caption ve hashtag kullanimi",
    "Capraz platform sirasi",
    "Yeniden paylasim ve boost",
)

_CATEGORY_NORM = {re.sub(r"\s+", " ", c.strip().lower()): c for c in SHARE_TIP_CATEGORIES}

_YOUTUBE_TAG_SUFFIXES = ("enigma", "atlas")


def _format_youtube_tags(raw: str) -> str:
    """YouTube Etiketler alani: virgulle ayrilmis, # yok; sonda enigma, atlas."""
    tags: list[str] = []
    seen: set[str] = set()

    def add(part: str) -> None:
        t = part.strip().lstrip("#").strip()
        if not t:
            return
        key = t.lower()
        if key in seen:
            return
        seen.add(key)
        tags.append(t)

    text = (raw or "").strip()
    if text:
        if "," in text:
            for part in text.split(","):
                add(part)
        else:
            for part in re.split(r"[\s\n]+", text):
                add(part)

    suffix_keys = {s.lower() for s in _YOUTUBE_TAG_SUFFIXES}
    tags = [t for t in tags if t.lower() not in suffix_keys]
    for suffix in _YOUTUBE_TAG_SUFFIXES:
        tags.append(suffix)
    return ", ".join(tags)


def _merge_hashtag_sources(*parts: str) -> str:
    return _format_youtube_tags(" ".join(p for p in parts if p))


_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F9FF"
    "\U00002600-\U000027BF"
    "\U0001FA00-\U0001FAFF"
    "\U00002702-\U000027B0"
    "]+"
    "[\uFE0E\uFE0F\u200D]*",  # variation selector / ZWJ artıkları
    flags=re.UNICODE,
)


def _strip_emojis(text: str) -> str:
    t = _EMOJI_RE.sub("", text or "")
    t = re.sub(r"[\uFE0E\uFE0F\u200D]+", "", t)
    return re.sub(r"\s{2,}", " ", t).strip(" \t-–—|·")

_NICHE_TRAILING_EMOJI = {
    "tarih_gizem": "🕵️",
    "uzay": "🌌",
    "bilim": "🔬",
    "korku": "😱",
    "komedi": "😂",
    "cocuk": "✨",
    "seyahat": "✈️",
    "yemek": "🍽️",
    "spor": "⚡",
    "teknoloji": "🤖",
    "genel": "✨",
}


def _title_quality_score(text: str, topic: str) -> int:
    """Izleyiciyi ceken basliklari odullendir; ansiklopedi/belgesel kuru basligi cezalandir."""
    t = (text or "").strip()
    # Emoji haric uzunluk
    bare = _EMOJI_RE.sub("", t).strip()
    n = len(bare)
    if n < 8 or n > 120:
        return -100
    low = bare.lower()
    bad = (
        "video",
        "izle",
        "merak ettin mi",
        "bu videoda",
        "hos geldiniz",
        "abone ol",
        "like at",
        "kesfettiniz mi",
        "biliyor muydunuz ki",
        "#shorts",
    )
    if any(b in low for b in bad):
        return -40
    # Kuru belgesel / Wikipedia basligi — izleyiciyi cekmez
    dry = (
        "nasıl keşfedildi",
        "nasil kesfedildi",
        "nasıl keşfedildi ve",
        "gerçeğe ulaşıldı",
        "gercege ulasildi",
        "gerçeğe nasıl ulaşıldı",
        "ve gerçeğe",
        "ve gercege",
        "tarihçesi nedir",
        "tarihcesi nedir",
        "hakkında bilgiler",
        "hakkinda bilgiler",
        "nasıl bulundu ve",
        "how was",
        "how were",
        "and the truth",
        "was discovered and",
        "the discovery of",
    )
    if any(d in low for d in dry):
        score_dry = -35
    else:
        score_dry = 0
    topic_words = {w for w in topic.lower().split() if len(w) > 2}
    title_words = {w for w in bare.lower().split() if len(w) > 2}
    overlap = len(topic_words & title_words) if topic_words else 1
    score = overlap * 18 + score_dry
    # Konu kelimesi hic yoksa ciddi ceza (konudan bagimsiz baslik)
    if topic_words and overlap == 0:
        from akifactory.script_topic import normalize_text_for_match, topic_anchor_phrases

        anchors = topic_anchor_phrases(topic) or []
        norm_title = normalize_text_for_match(bare)
        if anchors and not any(
            normalize_text_for_match(a) in norm_title for a in anchors[:6]
        ):
            score -= 50
        else:
            score -= 30
    # Click / merak kalibi — cesitli hook'lar (tek kaliba kilitlenme YOK)
    curiosity = (
        "sırrı nedir",
        "sirri nedir",
        "arkasındaki sır",
        "arkasindaki sir",
        "arkasındaki",
        "arkasindaki",
        "gizemi nedir",
        "ne saklıyor",
        "ne sakliyor",
        "kimse bilmiyor",
        "kimse bilmiyordu",
        "halen çözülemedi",
        "halen cozulemedi",
        "açıklanamayan",
        "aciklanamayan",
        "gerçek mi",
        "gercek mi",
        "yalan mı",
        "yalan mi",
        "mümkün mü",
        "mumkun mu",
        "doğru mu",
        "dogru mu",
        "sırrı",
        "sirri",
        "sır ne",
        "sir ne",
        "gizemi",
        "gizli",
        "şoke",
        "soke",
        "bilim insan",
        "neden",
        "the secret behind",
        "the truth behind",
        "what really",
        "what happened",
        "still unexplained",
        "is it real",
        "real or fake",
        "hidden truth",
        "unexplained",
        "nasıl",
        "nasil",
        "kim",
        "kimler",
        "nerede",
        "hangi",
        "gerçek",
        "gercek",
        "gizem",
        "şok",
        "sok",
        "bilinmeyen",
        "unutulan",
        "yasak",
        "kayip",
        "kayıp",
        "?",
    )
    hits = sum(1 for c in curiosity if c in low)
    if hits:
        score += 10 + min(14, hits * 3)
    # Soru / merak hissi (kalip serbest)
    if "?" in bare and overlap > 0:
        score += 10
    if 28 <= n <= 95:
        score += 8
    elif 20 <= n < 28 or 95 < n <= 110:
        score += 2
    return score


def _format_publish_title(text: str, language: str = "tr") -> str:
    """Baslik: her kelimenin bas harfi buyuk (Title Case). Emoji yok."""
    t = (text or "").strip()
    if not t:
        return t
    base = _strip_emojis(t)
    if not base:
        return ""
    return _title_case_words(base, language)


def _ensure_one_trailing_emoji(
    text: str,
    niche_id: str = "genel",
    *,
    force: bool = False,
) -> str:
    """Aciklama sonunda en fazla tek emoji.

    force=False (varsayilan): model emoji koymadiysa niş emojisi EKLEME —
    alakasız 🕵️/✨ baslik/aciklama sorununu onler.
    """
    t = (text or "").strip()
    if not t:
        return t
    found = list(_EMOJI_RE.finditer(t))
    base = _strip_emojis(t)
    if not base:
        return t if found else ""
    if found:
        # Son emoji (variation dahil ham eslesme)
        return f"{base} {found[-1].group(0).strip()}"
    if not force:
        return base
    fallback = _NICHE_TRAILING_EMOJI.get(niche_id) or _NICHE_TRAILING_EMOJI["genel"]
    return f"{base} {fallback}"


_TR_UPPER = str.maketrans(
    {
        "i": "İ",
        "ı": "I",
        "ğ": "Ğ",
        "ü": "Ü",
        "ş": "Ş",
        "ö": "Ö",
        "ç": "Ç",
    }
)
_TR_LOWER = str.maketrans(
    {
        "I": "ı",
        "İ": "i",
        "Ğ": "ğ",
        "Ü": "ü",
        "Ş": "ş",
        "Ö": "ö",
        "Ç": "ç",
    }
)


def _tr_lower(text: str) -> str:
    return (text or "").translate(_TR_LOWER).lower()


def _tr_upper_char(ch: str) -> str:
    if not ch:
        return ch
    return ch.translate(_TR_UPPER).upper() if len(ch) == 1 else ch


def _lang_code(language: str) -> str:
    return ((language or "tr").strip().lower()[:2] or "tr")


def normalize_topic_for_language(topic: str, language: str) -> str:
    """EN kayitlarda «Konu (EN)» ekini temizle — baslik uretimine karismasin."""
    t = (topic or "").strip()
    if _lang_code(language) == "en":
        t = re.sub(r"\s*\(\s*EN\s*\)\s*$", "", t, flags=re.I).strip()
    return t


def text_looks_turkish(text: str) -> bool:
    """Metinde Turkce karakter veya tipik Turkce ek/kelime var mi?"""
    t = (text or "").strip()
    if not t:
        return False
    if re.search(r"[çğıöşüÇĞİÖŞÜ]", t):
        return True
    # ASCII ama acik Turkce kalibi (EN videoya TR baslik sizintisi)
    low = t.lower()
    markers = (
        " ve ",
        " bir ",
        " bu ",
        " için",
        " icin",
        " değil",
        " degil",
        " mı",
        " mi?",
        " mı?",
        "gizem",
        "tarih",
        "keşf",
        "kesf",
        "yeraltı",
        "yeralti",
        "mağara",
        "magara",
        "şehir",
        "sehir",
        "neden",
        "nasıl",
        "nasil",
        "olan",
        "oldu",
        "yoksa",
    )
    return any(m in f" {low} " or low.startswith(m.strip()) for m in markers)


def english_publish_fallback(topic: str, script: str, niche_id: str = "genel") -> tuple[str, str]:
    """EN yayin icin Turkce sizinti yedegi — senaryodan / ASCII konudan baslik+caption."""
    topic_n = normalize_topic_for_language(topic, "en")
    title = ""
    for chunk in re.split(r"[.\n!?]+", script or ""):
        line = re.sub(r"\s+", " ", chunk).strip()
        if 8 <= len(line) <= 70 and not text_looks_turkish(line):
            title = line
            break
    if not title and topic_n and not text_looks_turkish(topic_n):
        title = topic_n
    if not title:
        ascii_topic = re.sub(r"[^\x20-\x7E]", "", topic_n or "").strip(" -_|")
        title = ascii_topic[:42] if len(ascii_topic) >= 4 else "Hidden History Mystery"
    title = _format_publish_title(title[:100], "en")

    caption = ""
    for para in (script or "").split("\n"):
        para = re.sub(r"\s+", " ", para).strip()
        if 20 <= len(para) <= 160 and not text_looks_turkish(para):
            caption = para
            break
    if not caption:
        bare = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]+$", "", title).strip()
        caption = f"{bare} — watch till the end."
    caption = _ensure_one_trailing_emoji(caption[:160], niche_id, force=False)
    return title, caption


def _title_case_words(text: str, language: str = "tr") -> str:
    """Her kelimenin bas harfini buyuk yap. Emoji dokunulmaz."""
    t = (text or "").strip()
    if not t:
        return t
    emojis = list(_EMOJI_RE.finditer(t))
    trailing = emojis[-1].group(0) if emojis else ""
    base = _EMOJI_RE.sub("", t)
    base = re.sub(r"\s{2,}", " ", base).strip(" \t-–—|·")
    if not base:
        return (trailing or t).strip()

    use_tr = _lang_code(language) == "tr"

    def _cap_word(body: str) -> str:
        if not body:
            return body
        if body[0].isdigit():
            return body
        for sep in ("'", "\u2019", "\u02bc"):
            if sep in body:
                head, _, tail = body.partition(sep)
                if not head:
                    return body
                if use_tr:
                    return (
                        _tr_upper_char(head[0])
                        + _tr_lower(head[1:])
                        + sep
                        + _tr_lower(tail)
                    )
                return head[0].upper() + head[1:].lower() + sep + tail.lower()
        if use_tr:
            return _tr_upper_char(body[0]) + _tr_lower(body[1:])
        return body[0].upper() + body[1:].lower()

    parts: list[str] = []
    for raw in re.split(r"(\s+)", base):
        if not raw or raw.isspace():
            parts.append(raw)
            continue
        m = re.match(r"^([^\wçğıöşüÇĞİÖŞÜ]*)(.*)$", raw, flags=re.UNICODE)
        if not m:
            parts.append(raw)
            continue
        prefix, body = m.group(1), m.group(2)
        if not body:
            parts.append(raw)
            continue
        parts.append(prefix + _cap_word(body))
    out = "".join(parts).strip()
    if trailing:
        return f"{out} {trailing}".strip()
    return out


# YouTube aciklama limiti cok yuksek; yayin ozeti icin rahat butce.
# Eski 420 siniri cumleyi yarida kesiyordu («yuksek mineral or…»).
CAPTION_MAX_CHARS = 750


def _clip_title_at_word(text: str, max_len: int) -> str:
    """Basligi kelime ortasindan kesme (emoji haric)."""
    from akifactory.text_utils import _clip_at_word_boundary, _strip_trailing_emojis

    raw = (text or "").strip()
    if not raw:
        return ""
    em = ""
    m = re.search(
        r"((?:[\U0001F300-\U0001FAFF\u2600-\u27BF]\ufe0f?\s*)+)$",
        raw,
    )
    if m:
        em = m.group(1).strip()
        raw = _strip_trailing_emojis(raw)
    budget = max_len - (len(em) + 1 if em else 0)
    if budget < 8:
        budget = max_len
        em = ""
    clipped = _clip_at_word_boundary(raw, budget)
    if em and clipped:
        return f"{clipped} {em}".strip()
    return clipped


def _clip_caption_complete(text: str, max_len: int = CAPTION_MAX_CHARS) -> str:
    """Aciklamayi kelime/cumle ortasinda kesme — sadece tamamlanmis cumleler."""
    from akifactory.script_quality import _split_sentences
    from akifactory.text_utils import (
        _clip_at_word_boundary,
        _is_incomplete_clause,
        _strip_trailing_emojis,
    )

    raw = (text or "").strip()
    if not raw:
        return ""
    em = ""
    m = re.search(
        r"((?:[\U0001F300-\U0001FAFF\u2600-\u27BF]\ufe0f?\s*)+)$",
        raw,
    )
    if m:
        em = m.group(1).strip()
        raw = _strip_trailing_emojis(raw)
    budget = max_len - (len(em) + 1 if em else 0)
    if budget < 40:
        budget = max_len
        em = ""

    sents = _split_sentences(raw)
    kept: list[str] = []
    for s in sents:
        s = (s or "").strip()
        if not s:
            continue
        if _is_incomplete_clause(s, has_prior_complete=bool(kept)):
            break
        cand = " ".join(kept + [s]).strip()
        if len(cand) > budget:
            break
        kept.append(s)

    if kept:
        out = " ".join(kept).strip()
    else:
        # Tek uzun cumle — kelime sinirinda kes, sonra yarim kuyruk dusur
        out = _clip_at_word_boundary(raw, budget)
        if out and _is_incomplete_clause(out, has_prior_complete=False):
            # Son eksik parca: noktali onceki yoksa yine de kelime siniri yeterli
            parts = out.rsplit(" ", 1)
            if len(parts) == 2 and len(parts[1]) <= 4:
                out = parts[0].rstrip()

    out = out.rstrip(" \t,;:–—-|·")
    if em and out:
        return f"{out} {em}".strip()
    return out


def _pick_best_block(
    items: list[dict[str, str]],
    topic: str,
    *,
    fallback: str,
    max_len: int = 220,
    complete_sentences: bool = False,
) -> tuple[str, list[dict[str, str]]]:
    clip = _clip_caption_complete if complete_sentences else _clip_title_at_word
    if not items:
        return clip(fallback, max_len), []
    ranked = sorted(
        items,
        key=lambda x: _title_quality_score(x.get("text", ""), topic),
        reverse=True,
    )
    best = (ranked[0].get("text") or "").strip() or fallback
    alts = [
        {"rank": i + 1, "text": (it.get("text") or "").strip(), "why": it.get("why", "")}
        for i, it in enumerate(ranked[1:3])
        if (it.get("text") or "").strip()
    ]
    if complete_sentences:
        alts = [
            {**a, "text": _clip_caption_complete(a["text"], max_len)}
            for a in alts
            if a.get("text")
        ]
    return clip(best, max_len), alts


def _parse_publish_json(content: str) -> dict[str, Any] | None:
    """JSON yayin paketi — basarisizsa None (regex yedek)."""
    import json

    text = (content or "").strip()
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None

    def _items(key: str, alt: str) -> list[dict[str, str]]:
        raw = data.get(key) or data.get(alt) or []
        out: list[dict[str, str]] = []
        if isinstance(raw, str) and raw.strip():
            out.append({"rank": 1, "text": raw.strip()[:300], "why": ""})
            return out
        if not isinstance(raw, list):
            return out
        for i, it in enumerate(raw[:3], start=1):
            if isinstance(it, str) and it.strip():
                out.append({"rank": i, "text": it.strip()[:300], "why": ""})
            elif isinstance(it, dict):
                t = str(it.get("text") or it.get("title") or it.get("caption") or "").strip()
                if t:
                    out.append(
                        {
                            "rank": i,
                            "text": t[:300],
                            "why": str(it.get("why") or "")[:200],
                        }
                    )
        return out

    titles = _items("titles", "basliklar")
    captions = _items("captions", "descriptions") or _items("aciklamalar", "captions")
    tags = data.get("hashtags") or data.get("tags") or data.get("youtube_tags") or ""
    if isinstance(tags, list):
        tags = ", ".join(str(x).strip() for x in tags if str(x).strip())
    tags = str(tags).strip()
    hashtag_raw = [{"rank": 1, "text": tags, "why": ""}] if tags else []
    if not titles and not captions:
        return None
    return {"titles": titles, "captions": captions, "hashtag_raw": hashtag_raw}


def _parse_ranked_blocks(content: str, prefix: str, count: int = 3) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for i in range(1, count + 1):
        text_m = re.search(rf"{prefix}_{i}:\s*(.+?)(?={prefix}_{i + 1}:|{prefix}_{i}_NEDEN:|$)", content, re.S | re.I)
        why_m = re.search(rf"{prefix}_{i}_NEDEN:\s*(.+?)(?={prefix}_{i + 1}:|$)", content, re.S | re.I)
        text = ""
        if text_m:
            text = text_m.group(1).strip().splitlines()[0].strip()
        why = ""
        if why_m:
            why = why_m.group(1).strip().splitlines()[0].strip()
        if text:
            items.append({"rank": i, "text": text[:300], "why": why[:200]})
    return items


def _normalize_publish_labels(content: str) -> str:
    out = content.replace("ÖNERİ", "ONERI").replace("Öneri", "ONERI").replace("öneri", "ONERI")
    out = out.replace("ÖNERİ_", "ONERI_").replace("Öneri_", "ONERI_")
    return out


def _parse_share_tips(content: str, count: int = 7) -> list[dict[str, str]]:
    content = _normalize_publish_labels(content or "")
    tips: list[dict[str, str]] = []
    for i in range(1, count + 1):
        tip_m = re.search(
            rf"ONERI_{i}:\s*(.+?)(?=ONERI_{i}_DETAY:|ONERI_{i + 1}:|ONERI_{i + 1}_DETAY:|\Z)",
            content,
            re.S | re.I,
        )
        det_m = re.search(
            rf"ONERI_{i}_DETAY:\s*(.+?)(?=ONERI_{i + 1}:|ONERI_{i + 1}_DETAY:|\Z)",
            content,
            re.S | re.I,
        )
        tip = tip_m.group(1).strip() if tip_m else ""
        detail = det_m.group(1).strip() if det_m else ""
        if tip:
            tip = " ".join(tip.splitlines()).strip()
        if detail:
            detail = " ".join(detail.split()).strip()
        if not tip and not detail:
            alt = re.search(
                rf"(?:^|\n)\s*{i}[.)]\s*(.+?)(?=\n\s*{i + 1}[.)]|\Z)",
                content,
                re.S,
            )
            if alt:
                block = alt.group(1).strip()
                lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
                tip = lines[0][:240]
                detail = " ".join(lines[1:])[:500] if len(lines) > 1 else ""
        if tip or detail:
            tips.append({"order": i, "tip": tip[:240], "detail": detail[:500]})
    return tips


def _norm_tip_label(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _is_category_echo(tip: str) -> bool:
    key = _norm_tip_label(tip)
    if key in _CATEGORY_NORM:
        return True
    return any(key == _norm_tip_label(c) or key.startswith(_norm_tip_label(c)[:12]) for c in SHARE_TIP_CATEGORIES)


def _finalize_share_tips(raw: list[dict[str, str]]) -> list[dict[str, str]]:
    """Kategori basligi + LLM tavsiyesi birlestir; sablon yankisini temizle."""
    by_order = {int(t.get("order") or 0): t for t in raw if t.get("order")}
    out: list[dict[str, str]] = []
    for i, category in enumerate(SHARE_TIP_CATEGORIES, start=1):
        row = by_order.get(i, {})
        tip = str(row.get("tip") or "").strip()
        detail = str(row.get("detail") or "").strip()
        if _is_category_echo(tip):
            tip = ""
        if not tip and detail:
            first = re.split(r"(?<=[.!?])\s+", detail, maxsplit=1)
            tip = (first[0] if first else detail)[:240]
        out.append(
            {
                "order": i,
                "category": category,
                "tip": tip[:240],
                "detail": detail[:500],
            }
        )
    return out


def share_tips_are_placeholders(tips: list[dict[str, str]] | None) -> bool:
    """Eski/sablon yankisi tavsiyeler — yeniden uretilmeli."""
    if not tips:
        return True
    weak = 0
    for t in tips:
        tip = str(t.get("tip") or "").strip()
        detail = str(t.get("detail") or "").strip()
        if _is_category_echo(tip) and not detail:
            weak += 1
        elif not detail and len(tip) < 24:
            weak += 1
    return weak >= max(3, len(tips) // 2)


async def generate_share_tips_tr(
    *,
    topic: str,
    script: str,
    platform: str,
    niche_id: str,
    editor_model: str,
    aspect: str = "9:16",
) -> list[dict[str, str]]:
    """Turkce yayin tavsiyeleri — her kategori icin LLM somut tavsiye uretir."""
    plat = PLATFORM_LABELS.get(platform, platform)
    niche = script_pr.NICHE_LABELS.get(niche_id, niche_id)
    cats = "\n".join(f"{i}. {c}" for i, c in enumerate(SHARE_TIP_CATEGORIES, 1))

    prompt = f"""Sen Turkiye odakli kisa video yayin stratejistisin. Asagidaki videoya OZEL somut yayin tavsiyeleri yaz.

KONU: {topic}
PLATFORM: {plat}
NIS: {niche}
ORAN: {aspect}
Saatleri Turkiye saati (GMT+3) olarak ver.

VIDEO SENARYOSU:
{script[:900]}

Asagidaki 7 konu basligi sabittir — basliklari ONERI satirinda TEKRAR ETME; somut tavsiye yaz:

{cats}

CIKTI FORMATI (baska hicbir sey yok):

ONERI_1: (tek satir, videoya ozel somut tavsiye — ornek: "Salı ve Persembe 19:30-21:00 arasi paylas")
ONERI_1_DETAY: (en az 2 cumle; neden, nasil uygulanir)

ONERI_2: (ornek: "Cuma ve Cumartesi oncelikli, Pazartesi sabahindan kacin")
ONERI_2_DETAY: ...

ONERI_3: ...
ONERI_3_DETAY: ...

ONERI_4: ...
ONERI_4_DETAY: ...

ONERI_5: ...
ONERI_5_DETAY: ...

ONERI_6: ...
ONERI_6_DETAY: ...

ONERI_7: ...
ONERI_7_DETAY: ...

KURALLAR:
- ONERI_N satiri kategori adi OLMAZ ("En iyi paylasim saati" yazma)
- Her DETAY en az 2 cumle, uygulanabilir ve videonun konusuna referans ver
- Turkce; ONERI/ DETAY etiketleri ASCII kalsin"""

    async def _call() -> list[dict[str, str]]:
        content = await ollama_chat(
            [{"role": "user", "content": prompt}],
            model=editor_model,
            think=False,
            options=EDITOR_CHAT_OPTIONS,
            timeout=150.0,
            clean_script=False,
        )
        content = clean_turkish_script(content or "")
        return _finalize_share_tips(_parse_share_tips(content, len(SHARE_TIP_CATEGORIES)))

    tips = await _call()
    if share_tips_are_placeholders(tips):
        retry_prompt = prompt + "\n\nONCEKI YANIT SADECE BASLIKLARI TEKRAR ETTI. Simdi her ONERI satirinda gercek, somut, videoya ozel tavsiye yaz."
        content = await ollama_chat(
            [{"role": "user", "content": retry_prompt}],
            model=editor_model,
            think=False,
            options=EDITOR_CHAT_OPTIONS,
            timeout=150.0,
            clean_script=False,
        )
        tips = _finalize_share_tips(_parse_share_tips(clean_turkish_script(content or ""), len(SHARE_TIP_CATEGORIES)))
    return tips


async def refine_script(
    draft: str,
    *,
    topic: str,
    platform: str,
    niche_id: str,
    editor_model: str,
) -> str:
    plat = PLATFORM_LABELS.get(platform, platform)
    niche = script_pr.NICHE_LABELS.get(niche_id, niche_id)
    if script_pr.is_kids_niche(niche_id):
        prompt = f"""Sen cocuk kanali icin deneyimli bir kisa video editorusun. Asagidaki TASLAK senaryoyu iyilestir.

KONU: {topic}
PLATFORM: {plat}
NIS: {niche}

TASLAK:
{draft.strip()}

KURALLAR:
- 6-10 yas icin basit kelimeler; kisa cumleler (4-12 kelime)
- Sicak, neseli ton: Vay be, Haydi bakalim, Biliyor musun kullanabilirsin
- Konuyu oyun gibi anlat; somut ornekler (hayvan, renk, hareket)
- Korku, siddet, karmasik terim yok
- Sesli okununca en fazla 55 saniye (~650 karakter)
- Hook/Govde etiketi yazma; sadece duz metin senaryo

{imla_prompt_block()}

Yanitinda SADECE iyilestirilmis senaryo metni olsun."""
    else:
        topic_block = topic_prompt_block(topic, niche_id=niche_id)
        prompt = f"""Sen deneyimli bir kisa video editorusun. Asagidaki TASLAK senaryoyu iyilestir.

{topic_block}
PLATFORM: {plat}
NIS: {niche}

TASLAK:
{draft.strip()}

KURALLAR:
- Turkce konusma dili; c, g, i, o, s, u karakterleri dogru
- Konuyu bastan sona anlat; olay akisi ve baglama olsun
- Cumle uzunluklarini karistir (5-18 kelime); hepsi ayni boyda olmasin
- Ilk cumle anlatim odagiyla ilgili; tarih veya olgu ile gir, SORU sorma
- Video basligini HAYIR/EVET ile curutme; «gecerli degil» deme
- Metin bilgi anlatsin: ne oldu, kim, ne zaman, neden onemli
- Sesli okununca en fazla 55 saniye (~650 karakter, 6-10 cumle)
- Soru cumlesi yazma ("Peki", "Gercekten mi", "Biliyor muydunuz" yasak)
- "Biliyor muydunuz", "Bu videoda", "Hos geldiniz" yasak
- Hook/Govde/Kapanis etiketi yazma
- Markdown yok; sadece duz metin senaryo

{imla_prompt_block()}

Yanitinda SADECE iyilestirilmis senaryo metni olsun."""

    refined = await ollama_chat(
        [{"role": "user", "content": prompt}],
        model=editor_model,
        think=False,
        options=EDITOR_CHAT_OPTIONS,
        timeout=120.0,
    )
    from akifactory.text_utils import enforce_spoken_script_limits

    return enforce_spoken_script_limits(refined.strip() or draft.strip())


def _editor_style_rules(*, kids: bool) -> str:
    if kids:
        return """- 6-10 yas icin basit kelimeler; kisa cumleler (4-12 kelime)
- Sicak, neseli ton; korku/siddet yok
- Sesli okununca en fazla 55 saniye (~650 karakter)
- Hook/Govde etiketi yok; sadece duz metin"""
    return """- Turkce konusma dili; c, g, i, o, s, u karakterleri dogru
- Konuyu bastan sona anlat; olay akisi ve baglama olsun
- Cumle uzunluklarini karistir (5-18 kelime)
- Ilk cumle konuyla dogrudan ilgili; tarih veya olgu ile gir, SORU sorma
- Video basligini DOGRULAMA/YANLISLAMA: HAYIR/EVET, dogru/yanlis, «bu ifade gecerli/gecersiz», «gecersizdir» YASAK — gercek olayi anlat
- Sesli okununca en fazla 55 saniye (~650 karakter, 6-10 cumle)
- Soru cumlesi yok; "Biliyor muydunuz", "Bu videoda", "Hos geldiniz" yasak
- Ders kitabi dili YASAK: «sorgulanmistir», «degerlendiriliyor», «aciklanir», «bilimsel tip dilinde»
- Film/dizi kadrosu, oyuncu adi, «kitaptan uyarlanan film» ozeti YASAK
- Enlem/boylam (53°N…) yazma; yer adi yeter
- Markdown yok; sadece duz metin senaryo"""


def _niche_editor_hint(niche_id: str, *, web: bool = False) -> str:
    """Nis bazli editor talimatlari — polish ve web dogrulama."""
    n = (niche_id or "genel").strip().lower()
    hints: dict[str, str] = {
        "tarih_gizem": (
            "- Tarih/gizem: HIKAYE ANLATICISI ol — sir perdesini arala; yargic/skeptic DEGIL\n"
            "- Yanlis yil/isim/yer DUZELT; ama «kanit yok / yoktu / kanitlanamamis / sadece efsane» ekleme veya birakma\n"
            "- Atlantis vb.: kim anlatti (or. Platon), ne denildi, ne arandi — efsaneyi anlat, varligini mahkemede yargilama\n"
            "- Basligi dogru/yanlis diye cevaplama; «gecersiz/gecerli» deme\n"
            "- Konusma dili; «sorgulanmistir / degerlendiriliyor / bilimsel tip dilinde» YASAK\n"
            "- Film/festival/prömiyer/oyuncu/yonetmen YASAK — tarihi olayi/efsaneyi anlat (or. Z Sehri = Fawcett 1925)\n"
            "- Enlem/boylam koordinat dump YASAK; yer adi yeter\n"
            "- «Bu belgesel…» meta kapanis YASAK; meragi koruyarak bitir\n"
        ),
        "teknoloji": (
            "- Teknoloji: urun/sirket/ozellik adlari dogru; abartili pazarlama dili yok\n"
        ),
        "uzay": (
            "- Uzay: gok cismi, gorev, tarih; bilimsel iddia abartma\n"
        ),
        "tarihi_insanlar": (
            "- Tarihi kisi: dogum/olum yili, unvan, donem; yanlis atfetme\n"
        ),
        "tarihi_olaylar": (
            "- Tarihi olay: tarih, yer, taraflar, sonuc; kronoloji tutarli\n"
        ),
        "savaslar": (
            "- Savas: tarih, cephe, komutan, sonuc; sayilari kaynakla uyumlu tut\n"
        ),
        "yeme_icme": (
            "- Yeme-icme: yemek adi, malzeme, koken; tarif uydurma\n"
        ),
        "oyun": (
            "- Oyun: oyun adi, platform, yapimci; spoiler abartma\n"
        ),
        "muzik": (
            "- Muzik: sanatci, sarki/album, yil; soylenti ekleme\n"
        ),
        "sanat": (
            "- Sanat: eser, sanatci, donem, akim; yorumu kisa tut\n"
        ),
        "seyahat": (
            "- Seyahat: destinasyon, gezilecek yer, pratik bilgi (para/butce), yerel atmosfer\n"
        ),
        "genel": (
            "- Genel: konuyla ilgili somut bilgi; bos genel cumle kaldir\n"
        ),
    }
    base = hints.get(n, hints["genel"])
    if web:
        return base + "- Web kaynagi yoksa emin olmadigin bilgiyi ekleme\n"
    return base


async def expand_short_script(
    script: str,
    *,
    topic: str,
    niche_id: str = "genel",
    writer_model: str | None = None,
) -> str:
    """az_cumle / cok_kisa — mevcut dogru bilgiyi koruyarak 4-8 cumleye genislet."""
    from akifactory.llm_profiles import writer_model as resolve_writer_default
    from akifactory.ollama_util import chat as ollama_chat
    from akifactory.text_utils import enforce_spoken_script_limits

    base = (script or "").strip()
    if not base:
        return base
    niche = script_pr.NICHE_LABELS.get(niche_id, niche_id)
    prompt = f"""Asagidaki kisa video senaryosu cok kisa. EN AZ 4, hedef 5-7 cumle olacak sekilde genislet.

KONU: {topic.strip()}
NIS: {niche}

MEVCUT METIN:
{base}

KURALLAR:
- Mevcut dogru bilgileri koru; somut detay ekle (tarih, isim, yer, sebep, sonuc)
- Ilk cumlede konu anahtar kelimesi gecsin; soru cumlesi yok
- ~30-55 saniye konusma (~250-650 karakter); Turkce konusma dili
- Markdown, baslik, madde isareti yok
- Yanitinda SADECE genisletilmis senaryo metni olsun"""

    expanded = await ollama_chat(
        [{"role": "user", "content": prompt}],
        model=writer_model or resolve_writer_default(),
        think=False,
        timeout=120.0,
    )
    out = enforce_spoken_script_limits((expanded or base).strip())
    return out or base


async def polish_script(
    script: str,
    *,
    topic: str,
    platform: str,
    niche_id: str,
    editor_model: str,
) -> str:
    """Tek gecis senaryo guclendirme — akis, konu baglantisi, klise temizligi."""
    from akifactory.text_utils import enforce_spoken_script_limits

    base = (script or "").strip()
    if not base or len(base) < 40:
        return base

    plat = PLATFORM_LABELS.get(platform, platform)
    niche = script_pr.NICHE_LABELS.get(niche_id, niche_id)
    kids = script_pr.is_kids_niche(niche_id)
    style = _editor_style_rules(kids=kids)
    niche_extra = _niche_editor_hint(niche_id, web=False)

    prompt = f"""Sen kisa video senaryo editörüsün. Metni guclendir — bastan yazma, iyilestir.

{topic_prompt_block(topic, niche_id=niche_id)}
PLATFORM: {plat}
NIS: {niche}

MEVCUT SENARYO:
{base}

GOREV:
1) Konuyla zayif baglantili cumleleri konuya cek veya kaldir
2) Klise acilis ve "Bu videoda / Biliyor muydunuz" kalıplarini temizle
3) Olay akisini duzelt; cumle uzunluklarini karistir
4) Somut bilgi ekle (tarih, yer, isim, rakam) ama uydurma
5) Ders kitabi dilini konusma diline cevir («sorgulanmistir» → dogal cumle)
6) Film kadrosu / oyuncu adi / «kitaptan film» ozetini SIL — konunun kendisini anlat
7) Enlem/boylam koordinat listesini SIL; yer adi yeter
8) Stil:
{style}{niche_extra}

Yanitinda SADECE iyilestirilmis tam senaryo metni olsun."""

    out = await ollama_chat(
        [{"role": "user", "content": prompt}],
        model=editor_model,
        think=False,
        options={**EDITOR_CHAT_OPTIONS, "temperature": 0.4},
        timeout=120.0,
    )
    return enforce_spoken_script_limits((out or "").strip() or base)


async def fix_debunk_opening_if_needed(
    script: str,
    *,
    topic: str,
    platform: str,
    niche_id: str,
    editor_model: str,
    research_brief: str = "",
) -> str:
    """Baslik curutme acilisini (Hayir/Evet) tek geciste duzelt."""
    from akifactory.script_topic import is_debunk_opening
    from akifactory.text_utils import enforce_spoken_script_limits

    base = (script or "").strip()
    if not base or not is_debunk_opening(base):
        return base

    plat = PLATFORM_LABELS.get(platform, platform)
    niche = script_pr.NICHE_LABELS.get(niche_id, niche_id)
    kids = script_pr.is_kids_niche(niche_id)
    style = _editor_style_rules(kids=kids)
    brief_block = ""
    if (research_brief or "").strip():
        brief_block = f"\nARASTIRMA NOTU:\n{research_brief.strip()}\n"

    prompt = f"""Sen kisa video senaryo editörüsün. Asagidaki metnin ILK CUMLESI video basligini curutuyor — bunu duzelt.

{topic_prompt_block(topic, niche_id=niche_id)}
PLATFORM: {plat}
NIS: {niche}
{brief_block}
MEVCUT SENARYO (HATALI ACILIS):
{base}

GOREV:
1) «Hayir», «Evet», «bu ifade gecerli/gecersiz», «gecersizdir», «gecersiz degildir» tarzı curutucu/onaylayici acilisi KALDIR
2) Ilk cumleyi anlatim odagina gore yeniden yaz: somut tarih, yer, kisi veya olgu ile gir
3) Geri kalan metni konuya uygun tut; gereksiz genel bilgi yerine konuya ozgu detay
4) Stil:
{style}

Yanitinda SADECE duzeltilmis tam senaryo metni olsun."""

    out = await ollama_chat(
        [{"role": "user", "content": prompt}],
        model=editor_model,
        think=False,
        options={**EDITOR_CHAT_OPTIONS, "temperature": 0.35},
        timeout=120.0,
    )
    fixed = enforce_spoken_script_limits((out or "").strip() or base)
    if is_debunk_opening(fixed):
        return base
    return fixed


def should_use_web_research(niche_id: str, web_verify: bool) -> bool:
    return bool(web_verify) and not script_pr.is_kids_niche(niche_id)


_BRIEF_IRRELEVANT = "ALAKASIZ"


async def _synthesize_research_brief(
    topic: str,
    raw_sources: str,
    *,
    niche_id: str,
    model: str | None = None,
    focus: str = "",
) -> str:
    """Wiki + DDG ham kaynaklarini tek tutarli arastirma notuna donustur."""
    raw = (raw_sources or "").strip()
    if not raw:
        return ""
    niche = script_pr.NICHE_LABELS.get(niche_id, niche_id)
    focus_block = ""
    if (focus or "").strip():
        focus_block = (
            f"\nODAK: Yalnizca «{(focus or '').strip()}» ile dogrudan ilgili bilgileri yaz.\n"
            "Alakasiz kisi/olaylari dahil etme (kaynakta dogrudan bag yoksa).\n"
        )
    mystery = (niche_id or "").strip().lower() == "tarih_gizem"
    mystery_rules = ""
    if mystery:
        mystery_rules = """
GIZEM NIS EK:
- Bu konu efsane/gizem olabilir. «Yoktu / kanit yok / uydurma» diye SONUC yazma.
- NE OLDU alanina efsanenin / anlatinin hikaye ozetini yaz (kim anlatti, ne denildi, ne arandi).
- BELIRSIZ'e «kanitlanamamis» yazma; bunun yerine anlatidaki belirsiz detaylari yaz (yer tartismasi vb.).
- Amac: senaryo yazarina HIKAYE malzemesi vermek, skeptic karar vermek degil.
"""
    prompt = f"""Sen arastirma editorusun. Asagidaki web kaynaklarini oku ve TEK bir arastirma ozeti yaz.

KONU: {topic}
NIS: {niche}
{focus_block}
HAM KAYNAKLAR (Wikipedia + DuckDuckGo):
{raw}

KURALLAR:
- Asagidaki SABLON formatinda yaz; bos alan icin "bilinmiyor" yaz
- Yalnizca KONU'ya dogrudan ilgili bilgileri al (konu soruysa cevabina hizmet edenleri);
  baska yer/kisi/olay, sayfa ayrimi, adin kokeni gibi konu disi bilgileri ALMA
- Kaynaklarin hicbiri konuyla ilgili degilse sablon yerine yalnizca {_BRIEF_IRRELEVANT} yaz
- Sadece kaynaklarda gecen somut bilgileri yaz
- Celisen bilgi varsa en guvenilir olani sec veya BELIRSIZ'e yaz
- Spekulasyon veya kaynakta olmayan bilgi EKLEME
- Turkce yaz; anlatim degil, ham bilgi paketi
- Yanitinda SADECE sablon olsun
{mystery_rules}
SABLON:
KONUYA CEVAP: (konu neden/nasil sorusuysa kaynaklara gore sebepler/surec — 2-4 madde; degilse bilinmiyor)
KIM: (kisi/kurum / efsaneyi anlatan — yoksa bilinmiyor)
NE ZAMAN: (tarih/yil — yoksa bilinmiyor)
NEREDE: (yer/ulke/sehir — yoksa bilinmiyor)
NE OLDU: (olay/efsane ozeti/sonuc — 2-4 cumle; gizemde hikaye ozeti)
BELIRSIZ: (tartismali detaylar — «yoktu» deme)
DIGER:
- (ek somut bilgi maddeleri)"""

    out = await _fact_check_chat(
        [{"role": "user", "content": prompt}],
        model=model or EDITOR_DEFAULT,
        timeout=120.0,
    )
    brief = (out or "").strip()
    if not brief:
        return raw[:1100]
    if brief.upper().startswith(_BRIEF_IRRELEVANT):
        return _BRIEF_IRRELEVANT
    return brief[:1200]


async def apply_research_fact_check(
    script: str,
    *,
    topic: str,
    research_brief: str,
    platform: str,
    niche_id: str,
    lang_id: str,
    editor_model: str,
    max_chars: int | None = None,
) -> str:
    """Hazir arastirma notuna gore senaryoyu duzelt."""
    if not (script or "").strip() or not (research_brief or "").strip():
        return (script or "").strip()
    if not should_use_web_research(niche_id, True):
        return (script or "").strip()
    await release_vram_for_model_swap()
    return await editor_research_verify_fix(
        script,
        topic=topic,
        research_brief=research_brief,
        platform=platform,
        niche_id=niche_id,
        lang_id=lang_id,
        editor_model=editor_model,
        max_chars=max_chars,
    )


async def fetch_topic_research(
    topic: str,
    *,
    lang_id: str = "tr",
    niche_id: str = "genel",
    model: str | None = None,
    extra_queries: list[str] | None = None,
    focus: str = "",
) -> tuple[str, int]:
    """Video oncesi Wiki + DDG arastirmasi; LLM ile harmanlanmis ozet."""
    subj = (topic or "").strip()
    if not subj:
        return "", 0
    search_topic = normalize_narrative_topic(subj) or subj
    merged_extra = list(extra_queries or [])
    for q in web_sr.topic_research_extra_queries(search_topic, niche_id):
        if q not in merged_extra:
            merged_extra.append(q)
    snippets = await web_sr.gather_fact_context(
        search_topic, "", lang_id=lang_id, niche_id=niche_id, extra_queries=merged_extra
    )
    if not snippets:
        return "", 0
    raw = web_sr.format_research_for_writer(snippets)
    brief = await _synthesize_research_brief(
        search_topic, raw, niche_id=niche_id, model=model, focus=focus
    )
    if brief == _BRIEF_IRRELEVANT:
        # Alakasiz kaynak senaryoyu konu disina cekiyor; yazar konuyu kendisi anlatsin
        return "", 0
    out = brief or raw[:1200]
    try:
        from akifactory.fact_pack import build_fact_pack, fact_pack_to_prompt_block

        pack = await build_fact_pack(
            search_topic, out, niche_id=niche_id, model=model
        )
        block = fact_pack_to_prompt_block(pack, topic=search_topic)
        if block:
            out = f"{out.rstrip()}\n\n{block}"
    except Exception:
        pass
    return out, len(snippets)


async def fetch_chapter_research(
    main_subject: str,
    chapter_title: str,
    *,
    lang_id: str = "tr",
    niche_id: str = "genel",
    model: str | None = None,
) -> tuple[str, int]:
    """Uzun video bolumu icin odakli arastirma notu."""
    main = (main_subject or "").strip()
    title = (chapter_title or "").strip()
    if not main or not title:
        return "", 0
    extras = web_sr.chapter_focus_queries(main, title, niche_id)
    return await fetch_topic_research(
        f"{main} — {title}",
        lang_id=lang_id,
        niche_id=niche_id,
        model=model,
        extra_queries=extras,
        focus=title,
    )


async def finalize_script(
    script_text: str,
    *,
    topic: str,
    platform: str,
    niche_id: str,
    editor_model: str,
    dual_llm: bool = False,
    strengthen: bool = True,
    web_verify: bool = True,
    research_brief: str = "",
    lang_id: str = "tr",
) -> str:
    """Hook guclendirme + editor cilasi + arastirma notu ile fact-check."""
    from akifactory import script_hooks as script_hk
    from akifactory import script_quality as script_q

    text = (script_text or "").strip()
    if not text:
        return ""

    if strengthen:
        if (
            not script_hk.validate_hook(text, topic, niche_id=niche_id)
            or script_hk.is_cliche_hook(text, niche_id=niche_id)
            or (script_hk.is_generic_hook(text) and not script_pr.is_kids_niche(niche_id))
        ):
            text = (await script_hk.strengthen_hook(text, topic, niche_id=niche_id)).strip()

        needs_polish = not dual_llm or not script_q.is_script_acceptable(
            text, topic, niche_id=niche_id
        )
        if needs_polish and text:
            before_polish = text
            text = (
                await polish_script(
                    text,
                    topic=topic,
                    platform=platform,
                    niche_id=niche_id,
                    editor_model=editor_model,
                )
            ).strip()
            text = _prefer_better_script(
                text, before_polish, topic=topic, niche_id=niche_id
            )

        # Editor cilasindan sonra tek QC kapisi (Faz D)
        # Dual path zaten fact-check etti — kabul edilebilir metni tekrar LLM ile bozma
        if text and not script_pr.is_kids_niche(niche_id):
            if dual_llm and script_q.is_script_acceptable(text, topic, niche_id=niche_id):
                text = script_q.scrub_filler_sentences(text, topic)
            else:
                try:
                    from akifactory.script_qc import orchestrate_script_qc

                    qc = await orchestrate_script_qc(
                        text, topic, niche_id=niche_id, stage="finalize"
                    )
                    text = qc["text"]
                except Exception:
                    text = script_q.scrub_filler_sentences(text, topic)
                    if script_q.has_critical_quality_issues(text, topic, niche_id=niche_id):
                        text = (
                            await script_hk.strengthen_hook(text, topic, niche_id=niche_id)
                        ).strip()

    brief = (research_brief or "").strip()
    use_web = should_use_web_research(niche_id, web_verify)

    if use_web and brief and text:
        before_fc = text
        text = await apply_research_fact_check(
            text,
            topic=topic,
            research_brief=brief,
            platform=platform,
            niche_id=niche_id,
            lang_id=lang_id,
            editor_model=editor_model,
        )
        text = _prefer_better_script(
            text, before_fc, topic=topic, niche_id=niche_id
        )
    elif use_web and not brief and text:
        # Dual dahil: arastirma notu yoksa canli Wiki/DDG dogrulama (eskiden dual atlanirdi)
        before_fc = text
        text, _ = await editor_web_verify_fix(
            text,
            topic=topic,
            platform=platform,
            niche_id=niche_id,
            lang_id=lang_id,
            editor_model=editor_model,
        )
        text = _prefer_better_script(
            text, before_fc, topic=topic, niche_id=niche_id
        )

    if text and not script_pr.is_kids_niche(niche_id):
        from akifactory.script_topic import (
            contains_debunk_phrase,
            is_debunk_opening,
            scrub_debunk_content,
            scrub_off_topic_conflict,
        )

        text = scrub_debunk_content(text)
        text = scrub_off_topic_conflict(text, topic)
        if is_debunk_opening(text) or contains_debunk_phrase(text):
            text = (
                await fix_debunk_opening_if_needed(
                    text,
                    topic=topic,
                    platform=platform,
                    niche_id=niche_id,
                    editor_model=editor_model,
                    research_brief=brief,
                )
            ).strip()
            text = scrub_debunk_content(text)

        # Fact-check sonrasi akademik/film/koordinat kalintisi → bir kez polish
        if script_q.has_critical_quality_issues(text, topic, niche_id=niche_id):
            before_late = text
            text = script_q.scrub_filler_sentences(text, topic)
            text = (
                await polish_script(
                    text,
                    topic=topic,
                    platform=platform,
                    niche_id=niche_id,
                    editor_model=editor_model,
                )
            ).strip()
            text = scrub_debunk_content(text)
            text = script_q.scrub_filler_sentences(text, topic)
            text = _prefer_better_script(
                text, before_late, topic=topic, niche_id=niche_id
            )

    if (lang_id or "tr").strip().lower()[:2] == "tr" and text:
        from akifactory.text_utils import prepare_video_script

        text = prepare_video_script(text, niche_id=niche_id)

    if strengthen and text:
        try:
            from akifactory import hook_memory as hook_mem_mod

            hook = script_hk.first_sentence(text)
            if script_hk.validate_hook(text, topic, niche_id=niche_id) and hook:
                hook_mem_mod.remember_auto(niche_id, hook, topic, good=True)
        except Exception:
            pass

    return text


async def editor_web_verify_fix(
    script: str,
    *,
    topic: str,
    platform: str,
    niche_id: str,
    lang_id: str,
    editor_model: str,
) -> tuple[str, int]:
    """Web kaynaklariyla dogrula; hatalari editor kendisi duzeltir (tek gecis, geri gonderme yok)."""
    from akifactory.text_utils import enforce_spoken_script_limits

    base = (script or "").strip()
    if not base:
        return "", 0

    snippets = await web_sr.gather_fact_context(
        topic, base, lang_id=lang_id, niche_id=niche_id
    )
    web_block = web_sr.format_context_for_editor(snippets)
    await release_vram_for_model_swap()
    plat = PLATFORM_LABELS.get(platform, platform)
    niche = script_pr.NICHE_LABELS.get(niche_id, niche_id)
    kids = script_pr.is_kids_niche(niche_id)
    style = _editor_style_rules(kids=kids)
    niche_web = _niche_editor_hint(niche_id, web=True)

    from akifactory.script_topic import MYSTERY_STORYTELLING_RULES

    mystery_block = (
        f"\n{MYSTERY_STORYTELLING_RULES}\n"
        if (niche_id or "").strip().lower() == "tarih_gizem"
        else ""
    )
    prompt = f"""Sen SON KALE editörsün. Gorevin: senaryoyu web kaynaklarina gore kontrol et ve KENDIN duzelt.

{topic_prompt_block(topic, niche_id=niche_id)}
PLATFORM: {plat}
NIS: {niche}
DIL: {lang_id}

MEVCUT SENARYO:
{base}

WEB KAYNAKLARI (dogrulama icin):
{web_block}

GOREV:
1) Yanlis yil, yer, kisi, isim hatalarini web kaynaklarina gore DUZELT
2) Eksik ama kritik bir hikaye detayi varsa KISA ekle (55 sn limiti icinde kal) — yalnizca konuya dogrudan aitse
3) Kaynakta net olmayan yeni ulke/kisi/tarih UYDURMA; abartma; konu disi kaynak bilgisini senaryoya TASIMA
4) Stil kurallari:
{style}
5) Nis odak:
{niche_web}
{mystery_block}
ONEMLI:
- ASLA "hatali", "yeniden yazilmali", "uretime uygun degil" deme
- Video basligini HAYIR/EVET ile curutme; «kanit yok / yoktu / kanitlanamamis / sadece efsane» EKLEME
- Gizem konularinda hikaye anlatimini bozma — sir perdesini koru
- Ilk cumle ASLA «Hayir/Evet/bu ifade gecerli-gecersiz» ile baslamasin
- Geri gonderme yok; HER ZAMAN duzeltilmis TAM senaryo metnini yaz
- Yanitinda SADECE final senaryo metni olsun (aciklama, madde, etiket yok)"""

    fixed = await _fact_check_chat(
        [{"role": "user", "content": prompt}],
        model=editor_model,
        timeout=180.0,
        think=False,
    )
    out = enforce_spoken_script_limits((fixed or "").strip() or base)
    out = _prefer_better_script(out, base, topic=topic, niche_id=niche_id)
    return out, len(snippets)


async def editor_research_verify_fix(
    script: str,
    *,
    topic: str,
    research_brief: str,
    platform: str,
    niche_id: str,
    lang_id: str,
    editor_model: str,
    max_chars: int | None = None,
) -> str:
    """Hazir arastirma notuna gore senaryodaki olgusal hatalari duzelt."""
    from akifactory.text_utils import enforce_longform_chapter_limits, enforce_spoken_script_limits

    base = (script or "").strip()
    brief = (research_brief or "").strip()
    if not base or not brief:
        return base

    plat = PLATFORM_LABELS.get(platform, platform)
    niche = script_pr.NICHE_LABELS.get(niche_id, niche_id)
    kids = script_pr.is_kids_niche(niche_id)
    style = _editor_style_rules(kids=kids)
    niche_web = _niche_editor_hint(niche_id, web=True)

    from akifactory.script_topic import MYSTERY_STORYTELLING_RULES

    mystery_block = (
        f"\n{MYSTERY_STORYTELLING_RULES}\n"
        if (niche_id or "").strip().lower() == "tarih_gizem"
        else ""
    )
    prompt = f"""Sen SON KALE fact-check editörsün. Gorevin: senaryoyu ARASTIRMA NOTUNA gore kontrol et ve KENDIN duzelt.

{topic_prompt_block(topic, niche_id=niche_id)}
PLATFORM: {plat}
NIS: {niche}
DIL: {lang_id}

MEVCUT SENARYO:
{base}

ARASTIRMA NOTU (Wikipedia + DuckDuckGo — TEK dogruluk kaynagi):
{brief}

Yapilacaklar:
1) Arastirma notu ile celisen yanlis yil, yer, kisi, isim bilgilerini DUZELT
2) Arastirma notunda OLMAYAN ulke/sehir/kisi/tarih UYDURMA — sil veya duzelt
3) Notta net bilgi varken yanlis alternatif (or. baska ulke, baska kesif yili) KALDIR
4) Eksik ama kritik hikaye detayi notta varsa KISA ekle — yalnizca konuya dogrudan aitse
4b) Senaryo konudan saptiysa (konu disi yer/kisi/olay anlatiyorsa) o kismi SIL ve konuya don; nottaki konu disi bilgiyi senaryoya TASIMA
5) Stil kurallari:
{style}
6) Nis odak:
{niche_web}
{mystery_block}
ONEMLI:
- Video basligini HAYIR/EVET ile curutme; «gecerli degil», «ilgisi yok», «kanit yok», «yoktu», «kanitlanamamis» deme
- Gizem/efsane: nottaki hikaye malzemesini koru; skeptic kapanisa CEVIRME
- Anlatim odagi disinda baska tarih/catisma/siyasi olay EKLEME veya BIRAKMA (or. Tas Devri konusunda PKK, 1984 catismasi SIL)
- Ilk cumle ASLA «Hayir/Evet/bu ifade gecerli-gecersiz» ile baslamasin
- Tarih kisaltmasi kullanma: MÖ/MS yerine Milattan Önce / Milattan Sonra yaz (ornek: Milattan Önce 605te)
- Geri gonderme yok; HER ZAMAN duzeltilmis TAM senaryo metnini yaz
- Yanitinda SADECE final senaryo metni olsun — kurallari/talimatlari tartisma veya alinti yapma"""

    fixed = await _fact_check_chat(
        [{"role": "user", "content": prompt}],
        model=editor_model,
        timeout=180.0,
        think=False,
    )
    out = (fixed or "").strip() or base
    if max_chars and max_chars > 400:
        out = enforce_longform_chapter_limits(out, max_chars=max_chars)
    else:
        out = enforce_spoken_script_limits(out)
    return _prefer_better_script(out, base, topic=topic, niche_id=niche_id)


async def two_pass_script(
    *,
    subject: str,
    lang_id: str = "tr",
    platform_id: str = "tiktok",
    niche_id: str = "genel",
    paragraph_number: int = 1,
    writer_model_name: str | None = None,
    editor_model: str,
    web_verify: bool = True,
    experimental_template: bool = False,
) -> dict[str, Any]:
    skip_web = not should_use_web_research(niche_id, web_verify)
    research_brief = ""
    web_sources = 0
    if not skip_web:
        research_brief, web_sources = await fetch_topic_research(
            subject,
            lang_id=lang_id,
            niche_id=niche_id,
            model=editor_model,
        )
        await release_vram_for_model_swap()
    draft = await script_pr.generate_script_text(
        subject=subject,
        lang_id=lang_id,
        platform_id=platform_id,
        niche_id=niche_id,
        paragraph_number=paragraph_number,
        experimental_template=experimental_template,
        research_context=research_brief,
        writer_model=writer_model_name,
    )
    if not draft:
        return {
            "script": "",
            "draft": "",
            "writer_model": writer_model_name or writer_model(),
            "editor_model": editor_model,
        }
    from akifactory import script_quality as script_q

    writer_tag = (writer_model_name or writer_model() or "").strip()
    editor_tag = (editor_model or "").strip()
    same_model = bool(writer_tag) and writer_tag.lower() == editor_tag.lower()
    # Iyi taslak veya tek-model pipeline: rewrite atla (ayni model parafrazı bozar)
    draft_ok = script_q.is_script_acceptable(draft, subject, niche_id=niche_id)
    if draft_ok or same_model:
        refined = draft
    else:
        await release_vram_for_model_swap()
        refined = await refine_script(
            draft,
            topic=subject,
            platform=platform_id,
            niche_id=niche_id,
            editor_model=editor_model,
        )
        refined = _prefer_better_script(
            refined, draft, topic=subject, niche_id=niche_id
        )
    final = refined
    fact_checked = False
    if not skip_web and final:
        await release_vram_for_model_swap()
        before_fc = final
        if research_brief:
            final = await apply_research_fact_check(
                final,
                topic=subject,
                research_brief=research_brief,
                platform=platform_id,
                niche_id=niche_id,
                lang_id=lang_id,
                editor_model=editor_model,
            )
            fact_checked = True
        else:
            # Wiki/DDG bos geldiyse bile canli dogrulama dene (halusinasyonu kes)
            final, live_n = await editor_web_verify_fix(
                final,
                topic=subject,
                platform=platform_id,
                niche_id=niche_id,
                lang_id=lang_id,
                editor_model=editor_model,
            )
            if live_n > 0:
                web_sources = max(web_sources, live_n)
            fact_checked = True
        # Fact-check sonrasi: yalnizca film/curutme/akademik regresyonunda onceki metne don
        final = _prefer_better_script(
            final, before_fc, topic=subject, niche_id=niche_id
        )
    return {
        "script": final,
        "draft": draft,
        "refined": refined,
        "writer_model": writer_model_name or writer_model(),
        "editor_model": editor_model,
        "dual_llm": True,
        "web_verified": bool(fact_checked and (web_sources > 0 or research_brief)),
        "web_sources": web_sources,
        "research_brief": research_brief,
    }


async def refine_wangp_pack(
    pack: dict[str, Any],
    *,
    topic: str,
    script: str,
    editor_model: str,
) -> dict[str, Any]:
    scenes = pack.get("scenes") or []
    if not scenes:
        return pack
    block = pack.get("prompt_block") or "\n".join(scenes)
    prompt = f"""Sen MiniMax H3 yonetmeni / sinematografsin. Asagidaki SCENE senaryolarini iyilestir.

KONU: {topic}
SENARYO (Türkçe anlatim):
{script[:900]}

MEVCUT SCENE BLOKLARI:
{block}

KURALLAR (H3 GOLD STANDARD):
- Ingilizce kal; keyword soup YASAK — continuous-shot sahne senaryosu yaz
- Her SCENE: World open → beat chain → Camera → Atmosphere → Diegetic SFX → Technical → Lock
- SCENE_2+: "Continue directly from the previous shot." + same subjects/location/props
- no BGM / no generated music / no dialogue / One continuous shot, no cuts
- Belgesel/gizem: observational camera, natural light
- Her SCENE ~900+ karakter, 6–10 kisa paragraf

CIKTI FORMATI:
SCENE_1:
...

SCENE_2:
...

NOTES:
(Turkce kisa MiniMax H3 kullanim notu)"""

    content = await ollama_chat(
        [{"role": "user", "content": prompt}],
        model=editor_model,
        think=False,
        options=EDITOR_CHAT_OPTIONS,
        timeout=180.0,
        clean_script=False,
    )
    if not content:
        return pack
    new_scenes = wangp_mod._parse_scenes(content)  # noqa: SLF001
    if not new_scenes:
        return pack
    line_mode = str(pack.get("line_mode") or "sliding_window")
    out = dict(pack)
    out["scenes"] = new_scenes
    out["prompt_block"] = wangp_mod._format_prompt_block(new_scenes, line_mode)  # noqa: SLF001
    out["prompt"] = out["prompt_block"]
    neg = wangp_mod._parse_negative(content)  # noqa: SLF001
    if neg:
        out["negative_prompt"] = neg
    notes = wangp_mod._parse_wgp_notes(content)  # noqa: SLF001
    if notes:
        out["wgp_notes"] = notes
    out["engine"] = "minimax_h3"
    out["refined_by_editor"] = True
    return out


async def two_pass_wangp(
    *,
    topic: str,
    script: str,
    niche_id: str,
    scene_count: int,
    style: str,
    line_mode: str,
    aspect: str,
    editor_model: str,
) -> dict[str, Any]:
    draft = await wangp_mod.generate_wangp_prompt(
        topic=topic,
        niche_id=niche_id,
        scene_count=scene_count,
        style=style,
        line_mode=line_mode,
        aspect=aspect,
        script=script,
    )
    if not draft.get("scenes"):
        return draft
    refined = await refine_wangp_pack(
        draft,
        topic=topic,
        script=script,
        editor_model=editor_model,
    )
    refined["writer_model"] = writer_model()
    refined["editor_model"] = editor_model
    return refined


async def publish_review(
    *,
    topic: str,
    script: str,
    platform: str,
    language: str,
    niche_id: str,
    editor_model: str,
    aspect: str = "9:16",
    include_share_tips: bool = True,
) -> dict[str, Any]:
    plat = PLATFORM_LABELS.get(platform, platform)
    lang_id = _lang_code(language)
    lang = LANG_LABELS.get(lang_id, LANG_LABELS.get(language, language))
    niche = script_pr.NICHE_LABELS.get(niche_id, niche_id)
    topic = normalize_topic_for_language(topic, lang_id)

    law = ""
    try:
        from akifactory.content_context import content_law_blocks

        law = content_law_blocks(niche_id)
    except Exception:
        pass
    law_bit = f"\n{law}\n" if law else ""

    if lang_id == "en":
        lang_rules = """
CRITICAL LANGUAGE RULES:
- Output language: ENGLISH only for titles AND captions.
- FORBIDDEN: Turkish words, Turkish characters (ç ğ ı ö ş ü), mixed TR/EN titles.
- TITLE CASE: Capitalize Every Word In The Title.
- Curiosity / mystery hooks — NOT dry documentary. Vary the hook each time.
- Example hooks (not mandatory): "What's The Secret Behind…?", "What Really Happened…?", "The Hidden Truth Of…", "Is … Real?"
- BAD example: "How Was Blood Falls Discovered In 2014 And How Was The Truth Reached"
- Caption: 2-4 COMPLETE engaging ENGLISH sentences (max ~700 chars). Never cut mid-word.
- Caption = curiosity hook only; full script is attached separately.
"""
        title_example = "What's The Secret Behind Blood Falls? Antarctica's Red Mystery"
        title_bad = (
            "How Was Blood Falls Discovered In 2014 And How Was The Truth Reached"
        )
        caption_example = (
            "For years people thought Antarctica's Blood Falls was literal blood "
            "pouring from the ice. The real source was stranger — and it rewrote "
            "what we thought we knew about life under the glacier."
        )
    else:
        lang_rules = """
DIL KURALLARI:
- Baslik ve aciklama TAMAMEN Turkce olsun.
- BASLIK TITLE CASE: Her Kelimenin Bas Harfi Buyuk Olsun.
- Baslikta EMOJI KULLANMA.
- SHORTS basligi: izleyiciyi CEKEN merak kalibi — tek bir kaliba KILITLENME.
- Ornek kalıplar (cesitlendir; hepsini ayni anda kullanma): "… Sirri Nedir?", "… Arkasindaki Sir Ne?", "… Ne Sakliyor?", "… Gercek Mi?", "Neden …?", "Kimse Bilmiyor: …"
- IYI ornek: "Kan Selalesi'nin Sirri Nedir? Antarktika'Daki Kirmizi Gizem"
- KOTU ornek (YASAK): "Kan Selalesi 2014'Te Nasil Kesfedildi Ve Gercege Ulasildi"
- Aciklama: 2-4 TAM cumle, merak; cumleyi yarida BIRAKMA.
"""
        title_example = (
            "Kan Şelalesi'nin Sırrı Nedir? Antarktika'daki Kırmızı Gizem"
        )
        title_bad = "Kan Şelalesi 2014'Te Nasıl Keşfedildi Ve Gerçeğe Ulaşıldı"
        caption_example = (
            "Yüzyıllardır Antarktika'da kırmızı akan bu şelalenin kan olduğu "
            "sanılıyordu. Gerçek kaynak çok daha garip çıktı — ve buzulun "
            "altındaki yaşam hakkındaki bildiklerimizi sarstı."
        )

    prompt = f"""Sen viral Shorts/TikTok baslik uzmanisin. Izleyiciyi baslikla videoya CEK.
{law_bit}
KONU: {topic}
PLATFORM: {plat}
DIL: {lang} ({lang_id})
NIS: {niche}
ORAN: {aspect}
{lang_rules}
VIDEO SENARYOSU:
{script[:1400]}

ZORUNLU — KONU BAGLANTISI:
- Baslik ve aciklama MUTLAKA bu konuyu adlandirsin: "{topic}"
- Konunun ana ozel adini / yerini / olayini baslikta gecir (konudan bagimsiz genel tarih soylemi YASAK)
- Aciklama, senaryodaki somut bilgiye dayansin; baska konuya sapma
- EN dilinde aciklama ve baslik ASLA Turkce olmasin

BASLIK STILI (KRITIK):
- Title Case: Her Kelimenin Bas Harfi Buyuk
- Amac: merak + gerilim — ansiklopedi / belgesel ozeti DEGIL
- CESITLILIK: 3 baslikta AYNI kalibi tekrarlama. Her baslikta farkli merak acisi dene.
- Ornek acilar (sadece ilham; zorunlu degil): sirri nedir, arkasindaki sir, ne sakliyor, neden, kimse bilmiyor, gercek mi, gizemi
- EN ornek acilar: what's the secret, the truth behind, what really happened, still unexplained, is it real
- KOTU kalip YASAK: "X yilda nasil kesfedildi", "gercege ulasildi", kuru belgesel cumlesi
- En az 2 baslik soru (?) veya net merak ifadesi icersin
- IYI ornek (tek ornek, kopyalama zorunlu degil): "{title_example}"
- KOTU ornek (ASLA): "{title_bad}"

Tercihen gecerli JSON dondur:
{{"titles":[{{"text":"...","why":"..."}}],"captions":[{{"text":"...","why":"..."}}],"hashtags":"etiket1, etiket2"}}
- titles: 3 alternatif — ILGI CEKICI / MERAK (ideal 35-90 karakter), TITLE CASE, BIRBIRINDEN FARKLI
  * Izleyiciyi yakala: sirr, gizem, neden, sakli gercek, sok detay
  * Genel/klise YASAK: "merak ettin mi", "bu videoda", "biliyor muydunuz"
  * BASLIKTA EMOJI YOK
- captions (aciklama): 3 alternatif — 2-4 TAM cumle, merak + baglam (max ~700 karakter, {lang})
  * Ilk cumle hook; sonra izleyiciyi videoya ceken 1-2 cumle
  * Cumle yarim YASAK
  * Son cumle nokta/soru/unlem ile bitsin
  * Emoji istege bagli ve SADECE konuyla ilgiliyse
  * "Abone ol / like at / link bio" YASAK
  * Tum senaryoyu aciklamaya YAZMA — senaryo ayri eklenir
  * IYI aciklama ornegi: "{caption_example}"
- hashtags: 15-20 etiket, virgul ile, # KULLANMA — en az 3 etiket dogrudan konuya ait olsun

JSON olmazsa eski format:
BASLIK_1: ...
BASLIK_1_NEDEN: ...
ACIKLAMA_1: ...
HASHTAG_1: ...

Baslik ornegi: "{title_example}"
Generic/sacma/konu-disi baslik kullanma."""

    async def _once(*, force_text: bool = False, extra: str = "") -> str:
        suffix = ""
        if force_text:
            suffix += "\nSadece etiketli format yaz.\n"
        if extra:
            suffix += f"\n{extra}\n"
        return await ollama_chat(
            [{"role": "user", "content": prompt + suffix}],
            model=editor_model,
            think=False,
            options=EDITOR_CHAT_OPTIONS,
            timeout=150.0,
            clean_script=False,
            format_json=not force_text,
        )

    def _parse_bundle(raw: str) -> tuple[list, list, list]:
        parsed = _parse_publish_json(raw)
        if parsed:
            return parsed["titles"], parsed["captions"], parsed["hashtag_raw"]
        return (
            _parse_ranked_blocks(raw, "BASLIK", 3),
            _parse_ranked_blocks(raw, "ACIKLAMA", 3),
            _parse_ranked_blocks(raw, "HASHTAG", 1),
        )

    content = clean_turkish_script((await _once()) or "")
    titles, descriptions, hashtag_raw = _parse_bundle(content)
    if not titles and not descriptions:
        content2 = clean_turkish_script((await _once(force_text=True)) or "")
        titles, descriptions, hashtag_raw = _parse_bundle(content2)

    best_caption, caption_alts = _pick_best_block(
        descriptions,
        topic,
        fallback=(descriptions[0]["text"] if descriptions else ""),
        max_len=CAPTION_MAX_CHARS,
        complete_sentences=True,
    )
    best_title, title_alts = _pick_best_block(
        titles,
        topic,
        fallback=(titles[0]["text"] if titles else topic[:90]),
        max_len=100,
    )

    # Caption QC + bir retry (TR)
    if lang_id == "tr":
        try:
            from akifactory.script_qc import caption_quality_issues

            if caption_quality_issues(best_caption, topic, max_len=CAPTION_MAX_CHARS):
                content_r = clean_turkish_script((await _once(force_text=True)) or "")
                _, desc_r, _ = _parse_bundle(content_r)
                if desc_r:
                    cand, alts = _pick_best_block(
                        desc_r,
                        topic,
                        fallback=desc_r[0]["text"],
                        max_len=CAPTION_MAX_CHARS,
                        complete_sentences=True,
                    )
                    if not caption_quality_issues(
                        cand, topic, max_len=CAPTION_MAX_CHARS
                    ) or len(cand) > len(best_caption):
                        best_caption, caption_alts = cand, alts
                        descriptions = desc_r
        except Exception:
            pass

    # EN: Turkce sizinti varsa bir kez daha zorla Ingilizce uret
    if lang_id == "en" and (
        text_looks_turkish(best_title) or text_looks_turkish(best_caption)
    ):
        content_en = clean_turkish_script(
            (
                await _once(
                    force_text=True,
                    extra=(
                        "REWRITE IN ENGLISH ONLY. Titles and captions must be English. "
                        "Do not use any Turkish words or letters çğışöü."
                    ),
                )
            )
            or ""
        )
        titles_en, desc_en, tags_en = _parse_bundle(content_en)
        if titles_en:
            cand_t, alts_t = _pick_best_block(
                titles_en,
                topic,
                fallback=titles_en[0]["text"][:100],
                max_len=100,
            )
            if not text_looks_turkish(cand_t):
                best_title, title_alts = cand_t, alts_t
                titles = titles_en
        if desc_en:
            cand_c, alts_c = _pick_best_block(
                desc_en,
                topic,
                fallback=desc_en[0]["text"],
                max_len=CAPTION_MAX_CHARS,
                complete_sentences=True,
            )
            if not text_looks_turkish(cand_c):
                best_caption, caption_alts = cand_c, alts_c
                descriptions = desc_en
        if tags_en:
            hashtag_raw = tags_en

    # Baslik: emoji yok; aciklama: model koyduysa tek emoji, yoksa ekleme
    best_title = _format_publish_title(best_title, lang_id)
    best_caption = _clip_caption_complete(
        _ensure_one_trailing_emoji(best_caption, niche_id, force=False),
        CAPTION_MAX_CHARS,
    )
    # Baslik-taklidi aciklama (ornegin "Derinkuyu ... 1 🕵️") — senaryodan yedek
    from akifactory.script_qc import caption_quality_issues

    if caption_quality_issues(best_caption, topic, max_len=CAPTION_MAX_CHARS):
        # Alternatiflerden temiz bir tane sec
        fixed = ""
        for alt in caption_alts:
            cand = _clip_caption_complete(
                _ensure_one_trailing_emoji(
                    str(alt.get("text") or ""), niche_id, force=False
                ),
                CAPTION_MAX_CHARS,
            )
            if cand and not caption_quality_issues(
                cand, topic, max_len=CAPTION_MAX_CHARS
            ):
                fixed = cand
                break
        if not fixed:
            # Senaryonun ilk 2-3 cumlesinden merak ozeti (tam cumle)
            from akifactory.script_quality import _split_sentences

            sents = _split_sentences((script or "").strip())
            if sents:
                fixed = _clip_caption_complete(
                    " ".join(sents[:3]).strip(), CAPTION_MAX_CHARS
                )
            if not fixed:
                fixed = _clip_caption_complete(
                    _strip_emojis(best_caption) or (topic or "").strip(),
                    CAPTION_MAX_CHARS,
                )
        best_caption = _ensure_one_trailing_emoji(fixed, niche_id, force=False)
        if descriptions:
            descriptions[0] = {**descriptions[0], "text": best_caption}
    for alt in title_alts:
        alt["text"] = _format_publish_title(alt.get("text") or "", lang_id)
    for alt in caption_alts:
        alt["text"] = _clip_caption_complete(
            _ensure_one_trailing_emoji(alt.get("text") or "", niche_id, force=False),
            CAPTION_MAX_CHARS,
        )
    if lang_id == "tr":
        # Model bazen tek tuk kelimeyi ASCII yazar (Sinirlari, Sakliyor)
        from akifactory.turkish_imla import apply_deasciify

        best_title = apply_deasciify(best_title)
        best_caption = apply_deasciify(best_caption)
        for alt in (*title_alts, *caption_alts):
            alt["text"] = apply_deasciify(alt.get("text") or "")

    youtube_tags = _format_youtube_tags(hashtag_raw[0]["text"]) if hashtag_raw else ""
    hashtag_sets = (
        [{"rank": 1, "text": youtube_tags, "why": hashtag_raw[0].get("why", "")}]
        if youtube_tags
        else []
    )

    share_tips: list[dict[str, str]] = []
    if include_share_tips and lang_id == "tr":
        share_tips = await generate_share_tips_tr(
            topic=topic,
            script=script,
            platform=platform,
            niche_id=niche_id,
            editor_model=editor_model,
            aspect=aspect,
        )

    return {
        "titles": [{"rank": 1, "text": best_title, "why": titles[0].get("why", "") if titles else ""}],
        "descriptions": [{"rank": 1, "text": best_caption, "why": descriptions[0].get("why", "") if descriptions else ""}],
        "title_alternatives": title_alts,
        "caption_alternatives": caption_alts,
        "hashtag_sets": hashtag_sets,
        "youtube_tags": youtube_tags,
        "share_tips": share_tips,
        "best_title": best_title,
        "best_caption": best_caption,
        "best_hashtags": youtube_tags,
        "editor_model": editor_model,
    }


def _normalize_wangp_pack(wangp: dict[str, Any] | None) -> dict[str, Any] | None:
    """Galeri UI `prompt` alanini da bekler — prompt_block ile esitle."""
    if not wangp:
        return wangp
    out = dict(wangp)
    block = (out.get("prompt_block") or out.get("prompt") or "").strip()
    if block:
        out["prompt_block"] = block
        out["prompt"] = block
    return out


async def full_post_production(
    *,
    topic: str,
    script: str,
    platform: str,
    language: str,
    niche_id: str,
    editor_model: str,
    aspect: str = "9:16",
    include_wangp: bool = False,
    include_fooocus: bool = False,
    include_share_tips: bool = True,
    wangp_style: str = "dark_mystery",
    wangp_line_mode: str = "sliding_window",
    scene_count: int = 5,
    fooocus_style: str = "photorealistic",
    fooocus_purpose: str = "thumbnail",
) -> dict[str, Any]:
    review = await publish_review(
        topic=topic,
        script=script,
        platform=platform,
        language=language,
        niche_id=niche_id,
        editor_model=editor_model,
        aspect=aspect,
        include_share_tips=include_share_tips,
    )
    if include_wangp:
        wangp = await two_pass_wangp(
            topic=topic,
            script=script,
            niche_id=niche_id,
            scene_count=scene_count,
            style=wangp_style,
            line_mode=wangp_line_mode,
            aspect=aspect,
            editor_model=editor_model,
        )
        review["wangp"] = _normalize_wangp_pack(wangp)
    if include_fooocus:
        try:
            from akifactory import fooocus_prompt as fooocus_mod

            fooocus = await fooocus_mod.generate_fooocus_prompt_for_gallery(
                subject=topic,
                title=review.get("best_title") or topic,
                script=script,
                publish_pack=review,
                niche_id=niche_id,
                style=fooocus_style,
                aspect=aspect,
                purpose=fooocus_purpose,
                variant_count=1,
            )
            if fooocus.get("prompt"):
                review["fooocus"] = fooocus
        except Exception:
            pass
    return review
