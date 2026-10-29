"""Video konusu (hook/baslik) ile senaryo anlatim odagi — debunk onleme."""

from __future__ import annotations

import re

# Soru / clickbait kuyruk kalıplari — anlatim odagina indirgenir
_QUESTION_TAIL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(.+?)\s+çözüldü\s+mü\??$", re.IGNORECASE),
    re.compile(r"^(.+?)\s+cozuldu\s+mu\??$", re.IGNORECASE),
    re.compile(r"^(.+?)\s+(?:gerçek|dogru)\s+(?:mi|mı|mudur|midir)\??$", re.IGNORECASE),
    re.compile(r"^(.+?)\s+(?:doğru|dogru)\s+mu\??$", re.IGNORECASE),
    re.compile(r"^(.+?)\s+(?:kanıtlandı|kanitlandi|ispatlandı|ispatlandi)\s+(?:mi|mı)\??$", re.IGNORECASE),
    re.compile(r"^(.+?)\s+(?:doğrulandı|dogrulandi)\s+(?:mi|mı)\??$", re.IGNORECASE),
    re.compile(r"^(.+?)\s+(?:açıklandı|aciklandi)\s+(?:mi|mı)\??$", re.IGNORECASE),
    re.compile(r"^(.+?)\s+(?:bulundu|ortaya\s+çıktı|ortaya\s+cikti)\s+(?:mi|mı)\??$", re.IGNORECASE),
    re.compile(r"^(.+?)\s+nelerdir\??$", re.IGNORECASE),
    re.compile(r"^(.+?)\s+nedir\??$", re.IGNORECASE),
    re.compile(r"^(.+?)\s+ne\s+dir\??$", re.IGNORECASE),
)

_DEBUNK_OPENING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(?:hayır|hayir|evet)\b", re.IGNORECASE),
    re.compile(r"^bu\s+(?:ifade|iddia|söylem|soylem|baslik|basligi|başlık|video\s+basligi)", re.IGNORECASE),
    re.compile(r"geçerli\s+değildir|gecerli\s+degildir", re.IGNORECASE),
    re.compile(r"geçersizdir|gecersizdir|geçersiz\s+değildir|gecersiz\s+degildir", re.IGNORECASE),
    re.compile(r"hiç\s+geçerli\s+değil|hic\s+gecerli\s+degil", re.IGNORECASE),
    re.compile(r"tarihsel\s+kaynaklarda.*(?:geçmez|gecmez|yok|doğru\s+değil|dogru\s+degil)", re.IGNORECASE),
    re.compile(r"doğrultusunda\s+hiç\s+geçerli", re.IGNORECASE),
)

# Metnin herhangi bir yerinde — fact-check sonrasi sik kacar
_DEBUNK_ANYWHERE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"hayır,?\s+bu\s+ifade", re.IGNORECASE),
    re.compile(r"hayir,?\s+bu\s+ifade", re.IGNORECASE),
    re.compile(r"evet,?\s+bu\s+ifade", re.IGNORECASE),
    re.compile(r"bu\s+ifade\s+geçerli\s+değil", re.IGNORECASE),
    re.compile(r"bu\s+ifade\s+gecerli\s+degil", re.IGNORECASE),
    re.compile(r"bu\s+ifade\s+geçersiz", re.IGNORECASE),
    re.compile(r"bu\s+ifade\s+gecersiz", re.IGNORECASE),
    re.compile(r"bu\s+iddia\s+geçersiz", re.IGNORECASE),
    re.compile(r"bu\s+iddia\s+gecersiz", re.IGNORECASE),
    re.compile(r"bu\s+iddia\s+geçerli\s+değil", re.IGNORECASE),
    re.compile(r"bu\s+iddia\s+gecerli\s+degil", re.IGNORECASE),
    re.compile(r"geçerli\s+değildir", re.IGNORECASE),
    re.compile(r"gecerli\s+degildir", re.IGNORECASE),
    re.compile(r"geçersizdir", re.IGNORECASE),
    re.compile(r"gecersizdir", re.IGNORECASE),
    re.compile(r"geçersiz\s+değildir", re.IGNORECASE),
    re.compile(r"gecersiz\s+degildir", re.IGNORECASE),
    re.compile(r"geçersiz\s+değil", re.IGNORECASE),
    re.compile(r"gecersiz\s+degil", re.IGNORECASE),
    re.compile(r"hiç\s+geçerli\s+değil", re.IGNORECASE),
    re.compile(r"hic\s+gecerli\s+degil", re.IGNORECASE),
    re.compile(r"video\s+basligi\s+geçerli\s+değil", re.IGNORECASE),
    re.compile(r"video\s+basligi\s+gecerli\s+degil", re.IGNORECASE),
    re.compile(r"video\s+basligi\s+geçersiz", re.IGNORECASE),
    re.compile(r"video\s+basligi\s+gecersiz", re.IGNORECASE),
    re.compile(r"başlık\s+geçersiz", re.IGNORECASE),
    re.compile(r"baslik\s+gecersiz", re.IGNORECASE),
    re.compile(r"gerçekten\s+meydana\s+gelmiş\s+bir\s+olaydır", re.IGNORECASE),
    re.compile(r"gercekten\s+meydana\s+gelmis\s+bir\s+olaydir", re.IGNORECASE),
    re.compile(r"bu\s+(?:doğru|dogru)\s+(?:bir\s+)?(?:ifade|iddia|baslik|başlık)", re.IGNORECASE),
    re.compile(r"bu\s+(?:yanlış|yanlis)\s+(?:bir\s+)?(?:ifade|iddia|baslik|başlık)", re.IGNORECASE),
    re.compile(r"bu\s+(?:doğru|dogru)\s+değil", re.IGNORECASE),
    re.compile(r"bu\s+(?:doğru|dogru)\s+degil", re.IGNORECASE),
    re.compile(r"(?:ifade|iddia|baslik|başlık)\s+(?:doğru|dogru|yanlış|yanlis)", re.IGNORECASE),
    re.compile(r"doğrudan\s+ilişkisi\s+yok", re.IGNORECASE),
    re.compile(r"dogrudan\s+iliskisi\s+yok", re.IGNORECASE),
    re.compile(r"doğrudan\s+alakası\s+yok", re.IGNORECASE),
    re.compile(r"dogrudan\s+alakasi\s+yok", re.IGNORECASE),
    re.compile(r"ilgisi\s+yok", re.IGNORECASE),
    re.compile(r"alakası\s+yok", re.IGNORECASE),
    re.compile(r"alakasi\s+yok", re.IGNORECASE),
    re.compile(r"birbiriyle\s+ilgisi\s+yok", re.IGNORECASE),
    # Gizem icerigini olduren «kanit yok / desteklenmemis» dersi
    re.compile(r"bilimsel\s+kanıt\s+yok", re.IGNORECASE),
    re.compile(r"bilimsel\s+kanit\s+yok", re.IGNORECASE),
    re.compile(r"kanıtlarla\s+desteklenmemiş", re.IGNORECASE),
    re.compile(r"kanitlarla\s+desteklenmemis", re.IGNORECASE),
    re.compile(r"hiç\s+bilimsel\s+(?:kanıt|kanit|delil)", re.IGNORECASE),
    re.compile(r"hic\s+bilimsel\s+(?:kanıt|kanit|delil)", re.IGNORECASE),
    re.compile(r"kesin\s+bilgi\s+yoktur", re.IGNORECASE),
    re.compile(r"doğrulayan\s+(?:belge|kaynak|delil)", re.IGNORECASE),
    re.compile(r"dogrulayan\s+(?:belge|kaynak|delil)", re.IGNORECASE),
    re.compile(r"(?:belge|kaynak|delil).*(?:yoktur|yok|bulunamadı|bulunamadi)", re.IGNORECASE),
    re.compile(r"kaynaklarda\s+bu\s+bilgiyi\s+doğrulayan", re.IGNORECASE),
    re.compile(r"kaynaklarda\s+bu\s+bilgiyi\s+dogrulayan", re.IGNORECASE),
    re.compile(r"kanıtlanmamıştır|kanitlanmamistir", re.IGNORECASE),
    re.compile(r"desteklenmemiştir|desteklenmemistir", re.IGNORECASE),
    re.compile(r"spekülasyon|spekulasyon", re.IGNORECASE),
    # Gizem olduren skeptic kapanislar (Atlantis vb.)
    re.compile(r"kanıtlanamamış|kanitlanamamis", re.IGNORECASE),
    re.compile(r"kanıt\s+bulunamamış|kanit\s+bulunamamis", re.IGNORECASE),
    re.compile(r"ispatlanmamıştır|ispatlanmamistir", re.IGNORECASE),
    re.compile(r"ispatlanamamış|ispatlanamamis", re.IGNORECASE),
    re.compile(r"var\s+olmadığı|var\s+olmadigi", re.IGNORECASE),
    re.compile(r"hiç\s+var\s+olmadı|hic\s+var\s+olmadi", re.IGNORECASE),
    re.compile(r"gerçek\s+değildir|gercek\s+degildir", re.IGNORECASE),
    re.compile(r"efsane(?:den)?\s+ibaret", re.IGNORECASE),
    re.compile(r"sadece\s+bir\s+efsane", re.IGNORECASE),
    re.compile(r"yalnızca\s+bir\s+efsane|yalnizca\s+bir\s+efsane", re.IGNORECASE),
    re.compile(r"uydurm(?:a|adır|adir)", re.IGNORECASE),
    re.compile(r"mit(?:ten)?\s+ibaret", re.IGNORECASE),
    re.compile(r"bilimsel\s+olarak\s+(?:kanıtlan|ispatlan|desteklen)", re.IGNORECASE),
    re.compile(r"kanıtı\s+yok|kaniti\s+yok", re.IGNORECASE),
    re.compile(r"delil\s+yok", re.IGNORECASE),
    re.compile(r"kanıtlanmamış|kanitlanmamis", re.IGNORECASE),
    re.compile(r"doğrulanamamış|dogrulanamamis", re.IGNORECASE),
    re.compile(r"hiçbir\s+(?:kanıt|kanit|delil)", re.IGNORECASE),
    re.compile(r"hicbir\s+(?:kanıt|kanit|delil)", re.IGNORECASE),
    re.compile(r"böyle\s+bir\s+yer\s+yok|boyle\s+bir\s+yer\s+yok", re.IGNORECASE),
    re.compile(r"(?:bir\s+)?yer\s+yoktu", re.IGNORECASE),
    re.compile(r"aslında\s+yoktu|aslinda\s+yoktu", re.IGNORECASE),
    re.compile(r"hiç\s+olmamıştır|hic\s+olmamistir", re.IGNORECASE),
    re.compile(r"gerçeği\s+yok|gercegi\s+yok", re.IGNORECASE),
)

TOPIC_NARRATIVE_RULES = """KONU SATIRI (onemli):
- «Video konusu» alani SADECE baslik/hook'tur (soru, iddia, «cozuldu mu»). Konuyu ANLAT — basligi dogrulama/yanlisla.
- ASLA basliga cevap verme: «evet», «hayir», «dogru», «yanlis», «bu ifade gecerli/gecersiz», «gecersizdir», «gecersiz degildir», «gercekten meydana gelmis bir olaydir» YASAK.
- Basligi okuyup dogru mu yanlis mi tartisma; izleyiciye olayi / efsaneyi anlat.
- Yalnizca anlatim odagindaki konuyu anlat; baska tarih/catisma/siyasi olay EKLEME (or. konu Tas Devri ise PKK, 1984 catismasi yazma).
- Baslik «neden / nasil» sorusuysa videonun omurgasi o sorunun sebepleri / sureci olsun; konunun genel ansiklopedik bilgisiyle (adinin kokeni, mitoloji, alakasiz yer/kisi) dolgu yapma.
- Gizem/efsane konularinda (Atlantis, kayip sehir, lanet…): HIKAYE ANLATICISI ol — sir perdesini arala; «kanit yok / yoktu / kanitlanamamis» diye bitirme.
- Dogru bilgiye yakin kal (kim anlatti, hangi yil, hangi yer, ne denildi); ama varligini mahkemede yargilama.
- Ilk cumle somut tarih, yer, olgu veya kisi ile gir; soru isareti kullanma; meta yorum yazma."""

# Tarih/gizem — fact-check ve yazar icin ortak hikaye kurali
MYSTERY_STORYTELLING_RULES = """GIZEM / EFSANE ANLATIMI (kritik):
- Sen yargic veya skeptic DEGILSIN; sir perdesini aralayan hikaye anlaticisisin.
- Atlantis, kayip uygarlik, lanet, cozulmemis olay: efsaneyi ve tarihsel anlatilari (kim yazdi, ne dedi, ne arandi) anlat.
- YASAK kapanislar: «kanit yok», «kanitlanamamistir», «var olmadigi», «sadece efsane», «uydurma», «bilimsel olarak ispatlanmadi», «boyle bir yer yok».
- Dogru bilgi = efsanenin kaynaklari ve detaylari (or. Platon Kritias, yil, ada betimi, sonraki arayislar) — «yoktu» demek DEGIL.
- Meraki koru; son cumlede bilinmeyeni birak, curutme."""

# Konu antik/on-tarih ise modern catisma terimleri yasak
_ANCIENT_TOPIC_RE = re.compile(
    r"taş\s*devri|tas\s*devri|paleolitik|neolitik|magara\s*resim|"
    r"prehistory|stone\s*age|antik\s*çağ|antik\s*cag|mağara|magara",
    re.IGNORECASE,
)
_MODERN_CONFLICT_TERMS: tuple[str, ...] = (
    "pkk",
    "türkiye-pkk",
    "turkiye-pkk",
    "çatışma",
    "catisma",
    "terör",
    "teror",
    "ateşkes",
    "ateskes",
    "silahlı çatışma",
    "silahli catisma",
    "güneydoğu anadolu",
    "guneydogu anadolu",
    "can kaybına",
    "can kaybina",
)


def normalize_narrative_topic(topic: str) -> str:
    """Clickbait/soru basligini anlatim odagina indirger."""
    raw = (topic or "").strip()
    if not raw:
        return raw
    t = raw
    for pat in _QUESTION_TAIL_PATTERNS:
        m = pat.match(t)
        if m:
            t = m.group(1).strip()
            break
    else:
        if t.endswith("?"):
            t = t[:-1].strip()
        t = re.sub(r"\s+(?:mi|mı|mu|mü)\s*$", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s+nelerdir$", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s+nedir$", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s+ne\s+dir$", "", t, flags=re.IGNORECASE)
    return t.strip() or raw


def is_ancient_history_topic(topic: str) -> bool:
    blob = f"{topic} {normalize_narrative_topic(topic)}"
    return bool(_ANCIENT_TOPIC_RE.search(blob))


def has_off_topic_conflict_drift(script: str, topic: str) -> bool:
    """Antik/on-tarih konusunda modern catisma/siyasi icerik."""
    if not is_ancient_history_topic(topic):
        return False
    low = (script or "").lower()
    return any(term in low for term in _MODERN_CONFLICT_TERMS)


def topic_search_focus(topic: str) -> str:
    """Web aramasi ve kalite kontrolu icin odak cumlesi."""
    return normalize_narrative_topic(topic) or (topic or "").strip()


def normalize_text_for_match(text: str) -> str:
    """ASCII/Turkce farkini yok sayarak eslestirme."""
    raw = (text or "").strip()
    if not raw:
        return ""
    try:
        from turkish.deasciifier import Deasciifier

        raw = Deasciifier(raw).convert_to_turkish()
    except Exception:
        pass
    return raw.lower()


def topic_anchor_phrases(topic: str) -> list[str]:
    """Konu tipine gore zorunlu anlatim ifadeleri (bos = genel kelime kontrolu)."""
    blob = normalize_text_for_match(f"{topic} {normalize_narrative_topic(topic)}")
    if _ANCIENT_TOPIC_RE.search(blob):
        return [
            "taş devri",
            "tas devri",
            "paleolitik",
            "neolitik",
            "mağara",
            "magara",
            "prehistory",
            "stone age",
            "taş alet",
            "tas alet",
        ]
    return []


def is_question_form_topic(topic: str) -> bool:
    t = (topic or "").strip()
    if not t:
        return False
    if t.endswith("?"):
        return True
    if normalize_narrative_topic(t) != t:
        return True
    return bool(re.search(r"\s+(?:mi|mı|mu|mü)\s*$", t, re.IGNORECASE))


def is_debunk_opening(script: str) -> bool:
    """Ilk cumlede curutucu ifade var mi (ikinci cumleye bakmaz)."""
    first = _first_sentence(script)
    if not first:
        return False
    low = first.lower()
    if any(p.search(low) for p in _DEBUNK_OPENING_PATTERNS):
        return True
    return contains_debunk_phrase(first)


def _first_sentence(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    parts = re.split(r"(?<=[.!?…])\s+", t, maxsplit=1)
    return (parts[0] if parts else t).strip()


def contains_debunk_phrase(script: str) -> bool:
    low = (script or "").lower()
    if not low:
        return False
    return any(p.search(low) for p in _DEBUNK_ANYWHERE_PATTERNS)


def _sentence_is_debunk(sentence: str) -> bool:
    low = (sentence or "").strip().lower()
    if not low:
        return False
    if any(p.search(low) for p in _DEBUNK_ANYWHERE_PATTERNS):
        return True
    return any(p.search(low) for p in _DEBUNK_OPENING_PATTERNS)


def _trim_inline_debunk(sentence: str) -> str:
    s = (sentence or "").strip()
    if not s:
        return s
    patterns = (
        r"[,;]?\s*(?:hayır|hayir|evet),?\s+bu\s+ifade\s+geçerli\s+değildir\.?",
        r"[,;]?\s*bu\s+ifade\s+geçerli\s+değildir\.?",
        r"[,;]?\s*(?:hayır|hayir|evet),?\s+bu\s+ifade\s+geçerli\s+değil\.?",
        r"[,;]?\s*bu\s+ifade\s+geçerli\s+değil\.?",
        r"[,;]?\s*(?:hayır|hayir|evet),?\s+bu\s+ifade\s+geçersizdir\.?",
        r"[,;]?\s*bu\s+ifade\s+geçersizdir\.?",
        r"[,;]?\s*bu\s+ifade\s+geçersiz\s+değildir\.?",
        r"[,;]?\s*bu\s+ifade\s+gecersizdir\.?",
        r"[,;]?\s*bu\s+ifade\s+gecersiz\s+degildir\.?",
        r"[,;]?\s*bu\s+iddia\s+geçersizdir\.?",
        r"[,;]?\s*bu\s+iddia\s+gecersizdir\.?",
        r"[,;]?\s*gerçekten\s+meydana\s+gelmiş\s+bir\s+olaydır\.?",
        r"[,;]?\s*gercekten\s+meydana\s+gelmis\s+bir\s+olaydir\.?",
        r"[,;]?\s*doğrudan\s+ilişkisi\s+yok[^.]*\.?",
        r"[,;]?\s*dogrudan\s+iliskisi\s+yok[^.]*\.?",
        r"[,;]?\s*ilgisi\s+yok[^.]*\.?",
        r"[,;]?\s*bilimsel\s+kanıt\s+yok(?:tur)?\.?",
        r"[,;]?\s*bilimsel\s+kanit\s+yok(?:tur)?\.?",
        r"[,;]?\s*kanıtlanamamıştır\.?",
        r"[,;]?\s*kanitlanamamistir\.?",
        r"[,;]?\s*kanıtlanmamıştır\.?",
        r"[,;]?\s*kanitlanmamistir\.?",
        r"[,;]?\s*sadece\s+bir\s+efsane(?:dir)?\.?",
        r"[,;]?\s*efsane(?:den)?\s+ibaret(?:tir)?\.?",
    )
    for pat in patterns:
        s = re.sub(pat, "", s, flags=re.IGNORECASE)
    # Nokta/unlem koru — strip(".") cumleleri birlestirince az_cumle hatasina yol acar
    return _preserve_sentence_end(s.strip(" ,;"))


def _preserve_sentence_end(sentence: str) -> str:
    """Cumle sonu noktalamasini koru / yoksa nokta ekle."""
    s = (sentence or "").strip()
    if not s:
        return s
    if s[-1] in ".!?…":
        return s
    return s + "."


def scrub_debunk_phrases(script: str) -> str:
    """Curutucu cumleleri ve inline ifadeleri metinden cikar."""
    text = (script or "").strip()
    if not text or not contains_debunk_phrase(text):
        return text

    kept: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        for sent in re.split(r"(?<=[.!?…])\s+", para):
            s = sent.strip()
            if not s:
                continue
            trimmed = _trim_inline_debunk(s)
            if trimmed and len(trimmed) >= 12 and not _sentence_is_debunk(trimmed):
                kept.append(_preserve_sentence_end(trimmed))
                continue
            if _sentence_is_debunk(s):
                continue
            if s:
                kept.append(_preserve_sentence_end(s))
    out = " ".join(kept).strip()
    # Tum cumleler curutucuysa bos don (eski metne geri SARMA — ust katman duzeltir)
    return out


def scrub_debunk_content(script: str, *, max_drop: int = 2) -> str:
    """Inline curutucu + acilis temizligi."""
    text = scrub_debunk_phrases(script)
    return scrub_debunk_opening(text, max_drop=max_drop)


def _split_for_scrub(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"(?<=[.!?…])\s+", (text or "").strip()) if p.strip()]
    if len(parts) <= 1 and "," in (text or ""):
        parts = [
            _preserve_sentence_end(p.strip(" ,;"))
            for p in re.split(r",\s+", (text or "").strip())
            if p.strip(" ,;")
        ]
    return parts


def scrub_off_topic_conflict(script: str, topic: str) -> str:
    """Antik konuda modern catisma cumlelerini sil."""
    if not is_ancient_history_topic(topic) or not (script or "").strip():
        return (script or "").strip()
    kept: list[str] = []
    for para in re.split(r"\n\s*\n", (script or "").strip()):
        for sent in _split_for_scrub(para.strip()):
            s = sent.strip().lstrip(" ,;")
            if not s or len(s) < 8:
                continue
            if has_off_topic_conflict_drift(s, topic):
                continue
            kept.append(_preserve_sentence_end(s))
    return " ".join(kept).strip()


def scrub_debunk_opening(script: str, *, max_drop: int = 2) -> str:
    """Curutucu acilis cumlelerini deterministik sil (LLM beklemeden)."""
    text = (script or "").strip()
    if not text:
        return text
    dropped = 0
    while dropped < max_drop and is_debunk_opening(text):
        parts = re.split(r"(?<=[.!?…])\s+", text, maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            break
        text = parts[1].strip()
        dropped += 1
    return text


def topic_prompt_block(topic: str, *, niche_id: str | None = None) -> str:
    """LLM promptlarina eklenecek konu + anlatim blogu."""
    subj = (topic or "").strip()
    narrative = normalize_narrative_topic(subj)
    lines = [TOPIC_NARRATIVE_RULES, f"Video konusu (baslik): {subj}"]
    if narrative != subj:
        lines.append(f"Anlatim odagi (buna gore yaz): {narrative}")
    if (niche_id or "").strip().lower() == "tarih_gizem":
        lines.append(MYSTERY_STORYTELLING_RULES)
    return "\n".join(lines)
