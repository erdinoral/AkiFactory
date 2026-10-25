"""Senaryo kalite kontrolu — zayif metinleri yeniden uretime gonder."""

from __future__ import annotations

import re

from akifactory.script_hooks import (
    is_cliche_hook,
    is_generic_hook,
    is_kids_niche,
    validate_hook,
    hook_relates_to_topic,
    first_sentence,
)
from akifactory.script_topic import (
    contains_debunk_phrase,
    has_off_topic_conflict_drift,
    is_debunk_opening,
    normalize_narrative_topic,
    normalize_text_for_match,
    topic_anchor_phrases,
)
from akifactory.text_utils import has_unexpanded_mo_ms

_MIN_CHARS = 100
_MIN_SENTENCES = 4
_MIN_CHARS_KIDS = 80
_MIN_SENTENCES_KIDS = 3
# Uzun video bolumu (~45-55 sn konusma)
_MIN_LONGFORM_CHARS = 180
_MIN_LONGFORM_SENTENCES = 4

_WEAK_BODY_PHRASES = (
    "bu videoda",
    "bugun size",
    "bugün size",
    "hos geldiniz",
    "hoş geldiniz",
    "kanalima abone",
    "kanalıma abone",
    "like at",
    "yorum yap",
)

# Bos filler — konu baglantisi olmadan dusurulabilir
_FILLER_SENTENCE_PHRASES = (
    "haydi birlikte bakalim",
    "haydi birlikte bakelim",
    "simdi buna bakalim",
    "şimdi buna bakalım",
    "daha fazlasini ogrenmek icin",
    "daha fazlasını öğrenmek için",
    "bir sonraki videoda",
    "bu konuda soylenecek cok sey",
    "bu konuda söylenecek çok şey",
    "inanilmasi zor ama",
    "inanılması zor ama",
    "kimse bunu bilmiyor",
    "herkes bunu biliyor sanir",
    "herkes bunu biliyor sanır",
    # Meta kapanış — belgesel tonunu bozar
    "bu belgesel",
    "bu videoda",
    "bu kısa videoda",
    "bu kisa videoda",
)

# Kalite sorunlari — yeniden uretim / hook kilidi tetikler
_CRITICAL_ISSUES = frozenset(
    {
        "jenerik_hook",
        "klise_hook",
        "acilis_konu_disinda",
        "konu_baglantisi_zayif",
        "konu_disinda",
        "curutucu_acilis",
        "zayif_hook",
        "akademik_dil",
        "film_ozeti",
        "koordinat_spam",
        "yazim_bozuk",
    }
)

# Ders kitabi / akademik anlatim — Shorts icin olumcul
_ACADEMIC_MARKERS = (
    "sorgulanmıştır",
    "sorgulanmistir",
    "değerlendiriliyor",
    "degerlendiriliyor",
    "belirlenmiştir",
    "belirlenmistir",
    "açıklanır",
    "aciklanir",
    "bilimsel tıp",
    "bilimsel tip",
    "çevre bilimindeki",
    "cevre bilimindeki",
    "doğal ekosistem",
    "dogal ekosistem",
    "bilim insanları tarafından",
    "bilim insanlari tarafindan",
    "tanımıyla isimlendirilmiştir",
    "tanimiyla isimlendirilmistir",
    "alışıla gelmişin ötesinde",
    "alisila gelmisin otesinde",
)

_FILM_CAST_MARKERS = (
    "oyuncularla",
    "oyuncuları",
    "oyunculari",
    "oyuncu",
    "aktör",
    "aktor",
    "yönetmen",
    "yonetmen",
    "charlie hunnam",
    "robert pattinson",
    "sienna miller",
    "city of ember",
    "gösterilen ve",
    "gosterilen ve",
    "yılında yayımladığı kitabı",
    "yilinda yayimladigi kitabi",
    # Film/dizi ozeti — tarih/gizem konusunu filmin prömiyerine kaydirma
    "film festival",
    "film festivalleri",
    "new york film",
    "prömiyer",
    "promiyer",
    "premier",
    "gösterime girdi",
    "gosterime girdi",
    "vizyona girdi",
    "filminin",
    "filmiyle",
    "filminde",
    "sinema uyarlaması",
    "sinema uyarlamasi",
    "kitaptan uyarlanan",
    "uyarlanan film",
    "james gray",
)

_COORD_RE = re.compile(
    r"\d{1,3}\s*°\s*[NnSsDdGgEeWw]"
    r"|\d{1,3}\s*[NnSs]\s*(?:ila|ile|-|–|—)\s*\d{1,3}\s*[NnSs]"
    r"|\d{1,3}\s*[EeWw]\s*(?:ile|ila|-|–|—)\s*\d{1,3}\s*[EeWw]"
)

# Sik LLM yazim bozulmalari
_TYPO_RE = re.compile(
    r"\banomal[ıi]\b"
    r"|\bsalına\b"
    r"|\bperçy\b"
    r"|\bbüzülün"
    r"|\bantarktıka\b"
    r"|\bfen olay"
    r"|\bkarakuum\b",
    re.IGNORECASE,
)


def _split_sentences(text: str) -> list[str]:
    """Cumlelere bol — yuzyil noktalari ve satir sonu cumleleri korunur."""
    from akifactory.text_utils import _split_paragraph_sentences, script_paragraphs

    out: list[str] = []
    raw = (text or "").strip()
    if not raw:
        return out
    for para in script_paragraphs(raw):
        for s in _split_paragraph_sentences(para):
            s = s.strip()
            if len(s) >= 8:
                out.append(s)
    # Noktasiz ama satir satir yazilmis metin (model ciktilari)
    if len(out) <= 1:
        lines = [ln.strip() for ln in raw.splitlines() if len(ln.strip()) >= 8]
        if len(lines) >= 2:
            return lines
    if not out:
        out.append(raw)
    return out


def _topic_keywords(topic: str) -> list[str]:
    words = re.findall(r"[\wçğıöşüÇĞİÖŞÜ]+", (topic or "").lower())
    stop = {
        "ve", "bir", "ile", "icin", "için", "the", "de", "da", "mi", "mı",
        "rehberi", "rehber", "gezi", "video", "shorts",
    }
    out: list[str] = []
    for w in words:
        if len(w) < 3 or w in stop:
            continue
        out.append(w)
        if len(w) > 5:
            out.append(w[:5])
    return out


def script_quality_issues(
    script: str,
    topic: str = "",
    *,
    niche_id: str | None = None,
    longform: bool = False,
) -> list[str]:
    issues: list[str] = []
    text = (script or "").strip()
    if not text:
        return ["bos"]

    kids = is_kids_niche(niche_id)
    if longform and not kids:
        min_chars = _MIN_LONGFORM_CHARS
        min_sents = _MIN_LONGFORM_SENTENCES
    else:
        min_chars = _MIN_CHARS_KIDS if kids else _MIN_CHARS
        min_sents = _MIN_SENTENCES_KIDS if kids else _MIN_SENTENCES

    if len(text) < min_chars:
        issues.append("cok_kisa")

    sents = _split_sentences(text)
    if len(sents) < min_sents:
        issues.append("az_cumle")

    low = text.lower()
    if any(p in low for p in _WEAK_BODY_PHRASES):
        issues.append("klise_ifade")

    q_count = text.count("?")
    if q_count >= 2 or (q_count == 1 and not kids):
        issues.append("cok_soru")

    if topic.strip():
        narrative = normalize_narrative_topic(topic)
        low = normalize_text_for_match(text)
        anchors = topic_anchor_phrases(narrative or topic)
        if anchors:
            if not any(a in low for a in anchors):
                issues.append("konu_baglantisi_zayif")
        else:
            kws = _topic_keywords(narrative or topic)
            if kws:
                hits = sum(1 for kw in kws if normalize_text_for_match(kw) in low)
                if hits < 1:
                    issues.append("konu_baglantisi_zayif")
        if has_off_topic_conflict_drift(text, topic):
            issues.append("konu_disinda")
        first = first_sentence(text)
        if not hook_relates_to_topic(first, narrative or topic):
            issues.append("acilis_konu_disinda")

    if not kids:
        if is_cliche_hook(text, niche_id=niche_id):
            issues.append("klise_hook")
        if is_generic_hook(text):
            issues.append("jenerik_hook")
        if is_debunk_opening(text) or contains_debunk_phrase(text):
            issues.append("curutucu_acilis")
        if has_unexpanded_mo_ms(text):
            issues.append("tarih_kisaltmasi")
        if re.search(r"[\u0370-\u03ff]", text):
            issues.append("yabanci_karakter")
        if not validate_hook(text, topic, niche_id=niche_id):
            issues.append("zayif_hook")

        # Shorts icin ders-kitabi / film ozeti / koordinat dump
        academic_hits = sum(1 for m in _ACADEMIC_MARKERS if m in low)
        if academic_hits >= 2:
            issues.append("akademik_dil")
        if any(m in low for m in _FILM_CAST_MARKERS):
            issues.append("film_ozeti")
        if _COORD_RE.search(text):
            issues.append("koordinat_spam")
        if _TYPO_RE.search(text):
            issues.append("yazim_bozuk")

    return issues


def is_script_acceptable(
    script: str,
    topic: str = "",
    *,
    niche_id: str | None = None,
) -> bool:
    return not script_quality_issues(script, topic, niche_id=niche_id)


def has_critical_quality_issues(
    script: str,
    topic: str = "",
    *,
    niche_id: str | None = None,
) -> bool:
    issues = script_quality_issues(script, topic, niche_id=niche_id)
    return any(i in _CRITICAL_ISSUES for i in issues)


def scrub_filler_sentences(script: str, topic: str = "") -> str:
    """Konuyla baglantisiz bos filler cumleleri dusur — en az 3 cumle birak."""
    text = (script or "").strip()
    if not text:
        return text
    sents = _split_sentences(text)
    if len(sents) <= 3:
        return text

    narrative = normalize_narrative_topic(topic) if topic.strip() else topic
    kept: list[str] = []
    for i, s in enumerate(sents):
        low = s.lower()
        is_filler = any(p in low for p in _FILLER_SENTENCE_PHRASES)
        # Film kadrosu / koordinat dump — Shorts anlatimina zarar
        is_film = any(m in low for m in _FILM_CAST_MARKERS)
        is_coord = bool(_COORD_RE.search(s))
        # Ilk cumleyi genel filler diye silme — ama film/meta/koordinat dusur
        if i == 0:
            if is_film or is_coord:
                continue
            if is_filler and any(
                p in low
                for p in (
                    "bu belgesel",
                    "bu videoda",
                    "bu kısa videoda",
                    "bu kisa videoda",
                )
            ):
                continue
            kept.append(s)
            continue
        if is_film or is_coord:
            continue
        if is_filler and (
            any(p in low for p in ("bu belgesel", "bu videoda", "bu kısa videoda", "bu kisa videoda"))
            or not hook_relates_to_topic(s, narrative or topic)
        ):
            continue
        # Ortada tamamen konu disi kisa filler
        if (
            topic.strip()
            and len(s) < 90
            and not hook_relates_to_topic(s, narrative or topic)
            and any(p in low for p in _WEAK_BODY_PHRASES)
        ):
            continue
        kept.append(s)

    if len(kept) < 3:
        return text
    return " ".join(kept)
