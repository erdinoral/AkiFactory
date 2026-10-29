"""Turkce senaryo metni temizleme ve TTS/altyazi hazirligi."""

from __future__ import annotations

import re
import unicodedata

_T_OPEN = chr(60) + "think" + chr(62)
_T_CLOSE = chr(60) + "/think" + chr(62)

_THINK_PATTERNS = (
    re.escape(_T_OPEN) + r".*?" + re.escape(_T_CLOSE),
    r"<think>.*?</think>",
    r"<thinking>.*?</thinking>",
)

_PREFIX_PATTERNS = (
    r"^(İşte|Iste|Tabii|Elbette|Senaryo:|Sure|Here is|Here's|Okay,|Tamam,).*?\n",
    r"^(İşte|Iste|Tabii|Elbette)\s+.*?:\s*",
)

_STRUCT_LABEL_ONLY = re.compile(
    r"^(?:\*\*)?(?:Hook|HOOK|Gövde|Govde|Kapanış|Kapanis|Giriş|Giris|Giris|"
    r"İlk\s*cümle|Ilk\s*cumle|Son\s*cümle|Son\s*cumle|"
    r"YAPI|NIŞ|Niş|Nis|Stil|Talimat|"
    r"Drafting|Thinking|Draft|Outline|Plan|Düşünce|Dusunce|Taslak|"
    r"ÖRNEK\s*KONU|ORNEK\s*KONU|ÖRNEK\s*SENARYO|ORNEK\s*SENARYO)"
    r"(?:\*\*)?\s*[:：\-–—]?\s*$",
    re.IGNORECASE,
)

# Etiket oneki sil — icerik kalsin (ornegin "Drafting: Madenci ..." → "Madenci ...")
# Markdown: **Drafting:** / **Thinking:**
_STRUCT_LABEL_PREFIX = re.compile(
    r"^(?:\*\*\s*)?(?:Hook|HOOK|Gövde|Govde|Kapanış|Kapanis|Giriş|Giris|"
    r"İlk\s*cümle|Ilk\s*cumle|Son\s*cümle|Son\s*cumle|"
    r"Drafting|Thinking|Draft|Outline|Plan|Düşünce|Dusunce|Taslak)"
    r"(?:\s*\*\*)?\s*[:：]\s*(?:\*\*\s*)?",
    re.IGNORECASE,
)

# Model prompt kurallarini / thinking'i senaryoya yazdiginda kes
_PROMPT_LEAK_CUT_RE = re.compile(
    r"(?:"
    r'["\u201c\u201d]\s*vs\s*["\u201c\u201d]'
    r"|Instruction\s+says"
    r"|Usually\s+Turkish\s+script"
    r"|This\s+is\s+strict\s+formatting"
    r"|strict\s+formatting\s+(?:ınstruction|instruction)"
    r"|compliance\s+with\s+specific"
    r"|from\s+prompt\s*\("
    r"|GÖREV\s*(?:section|bölüm|bolum)?"
    r"|Okay\s+[İIıi]\s+will\b"
    r"|Wait:\s*(?:Instruction|Instruction\s+says)?"
    r"|I\s+will\s+write\s+out\s+the\s+dates"
    r"|büt\s+ınstruction|but\s+instruction"
    r"|-\s*MO,?\s*Milattan"
    r"|MO,?\s*Milattan\s+(?:Önce|Sonra).*YAZMA"
    r"|YAZMA\s*[—\-–]\s*Milad"
    r"|Talimat\s+diyor"
    r"|Prompt(?:ta|daki)?\s+(?:kural|diyor|says)"
    r")",
    re.IGNORECASE,
)

_PROMPT_LEAK_LINE_RE = re.compile(
    r"(?:"
    r"Instruction\s+says"
    r"|Usually\s+Turkish"
    r"|strict\s+formatting"
    r"|from\s+prompt"
    r"|GÖREV"
    r"|YAZMA\s*[—\-–]"
    r"|Miladan\s+Önce\s*/\s*Milatan"
    r"|Wait:\s*Instruction"
    r"|Okay\s+[İIıi]\s+will"
    r"|I\s+need\s+to\b"
    r"|I\s+should\b"
    r"|Let\s+me\s+(?:think|check|write|draft)"
    r"|The\s+user\s+(?:asks|wants|said)"
    r"|Kullanıcı\s+(?:istiyor|diyor|sordu)"
    r"|Drafting\s*:"
    r"|Thinking\s*:"
    r"|^\s*\*\*(?:Drafting|Thinking|Outline|Plan)\*\*"
    r")",
    re.IGNORECASE,
)


def _strip_struct_labels(text: str) -> str:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            lines.append("")
            continue
        if _STRUCT_LABEL_ONLY.match(line):
            continue
        line = _STRUCT_LABEL_PREFIX.sub("", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _looks_like_prompt_meta(chunk: str) -> bool:
    """Paragraf prompt/thinking yorumu mu? (Ingilizce kural tartismasi vb.)"""
    t = (chunk or "").strip()
    if not t:
        return False
    if _PROMPT_LEAK_LINE_RE.search(t):
        return True
    # Cok Ingilizce + Turkce anlatim karakteri yok → meta
    letters = re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü]", t)
    if len(letters) < 12:
        return False
    ascii_latin = sum(1 for c in letters if "A" <= c <= "Z" or "a" <= c <= "z")
    tr_chars = len(_TURKISH_CHARS.findall(t))
    if ascii_latin / max(1, len(letters)) >= 0.72 and tr_chars == 0:
        en_markers = (
            " instruction",
            " prompt",
            " forbidden",
            " compliance",
            " formatting",
            " usually ",
            " specifically ",
            " ambiguity",
            " rewrite",
            " according to",
        )
        low = f" {t.lower()} "
        if any(m in low for m in en_markers):
            return True
    return False


def _strip_prompt_leakage(text: str) -> str:
    """Senaryoya sizan prompt/thinking yorumlarini kes."""
    out = (text or "").strip()
    if not out:
        return ""

    m = _PROMPT_LEAK_CUT_RE.search(out)
    if m:
        out = out[: m.start()].rstrip(' \t\n\r"\'«»“”')

    kept: list[str] = []
    for para in re.split(r"\n{2,}", out):
        para = para.strip()
        if not para:
            continue
        if _looks_like_prompt_meta(para):
            # Ilk gercek anlatimdan sonra meta gelirse dur
            if kept:
                break
            continue
        lines_ok: list[str] = []
        for line in para.splitlines():
            ln = line.strip()
            if not ln:
                continue
            if _PROMPT_LEAK_LINE_RE.search(ln) or _looks_like_prompt_meta(ln):
                if lines_ok or kept:
                    # Satir ortasinda sizinti — buraya kadarini al, kes
                    if lines_ok:
                        kept.append("\n".join(lines_ok))
                    return "\n\n".join(kept).strip()
                continue
            # Cumle icinde kesim noktasi
            cm = _PROMPT_LEAK_CUT_RE.search(ln)
            if cm:
                head = ln[: cm.start()].rstrip(' \t"\'«»“”')
                if head:
                    lines_ok.append(head)
                if lines_ok:
                    kept.append("\n".join(lines_ok))
                return "\n\n".join(kept).strip()
            lines_ok.append(ln)
        if lines_ok:
            kept.append("\n".join(lines_ok))
    return "\n\n".join(kept).strip()


def clean_turkish_script(text: str) -> str:
    if not text:
        return ""
    out = text.strip()
    for pat in _THINK_PATTERNS:
        out = re.sub(pat, "", out, flags=re.DOTALL | re.IGNORECASE)
    for pat in _PREFIX_PATTERNS:
        out = re.sub(pat, "", out, flags=re.IGNORECASE | re.MULTILINE)
    out = _strip_struct_labels(out)
    out = _strip_prompt_leakage(out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = re.sub(r"[ \t]+\n", "\n", out)
    return out.strip()


_TURKISH_CHARS = re.compile(r"[çğıöşüÇĞİÖŞÜ]")

# "15. yuzyil" / "1. yuzyila" gibi ifadelerde nokta cumle sonu degil
_CENTURY_RE = re.compile(
    r"(\d{1,2})\.\s+(yüzyıl\w*|yuzyil\w*|Yüzyıl\w*)",
    re.IGNORECASE,
)

_SENTENCE_END = frozenset(".!?…")


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text or "")


# 8'i, 1922'de, 12'den -> 8i, 1922de, 12den (Edge TTS kesmeyi "sekiz-i" diye okur)
_NUMBER_APOSTROPHE_RE = re.compile(
    r"(\d+)[''´`ʼ]([a-zA-ZıIUüÜöÖşŞçÇğĞ])"
)


def _fix_number_apostrophes_for_tts(text: str) -> str:
    """Sayi + ek birlesimlerinde kesme isaretini kaldir — TTS akiciligi."""
    return _NUMBER_APOSTROPHE_RE.sub(r"\1\2", text)


_DATE_SUFFIX = r"(?:['\u2019]?(?:te|ta|de|da|den|dan|nin|nın|nun|nün|in|ın|un|ün))"
_DATE_SUFFIX_OPT = rf"({_DATE_SUFFIX})?"
_MO_MS_DATE_RE = re.compile(
    rf"(?<!\w)(?:MO|MÖ|M\.O\.|M\.Ö\.)\s*(\d{{1,4}}){_DATE_SUFFIX_OPT}",
    re.IGNORECASE,
)
_MS_DATE_RE = re.compile(
    rf"(?<!\w)(?:MS|M\.S\.)\s*(\d{{1,4}}){_DATE_SUFFIX_OPT}",
    re.IGNORECASE,
)
_MO_MS_RANGE_RE = re.compile(
    r"(?<!\w)(?:MO|MÖ|M\.O\.|M\.Ö\.)\s*(\d{1,4})\s*(?:ile|[-–—])\s*(\d{1,4})",
    re.IGNORECASE,
)


def _expand_mo_ms_dates(text: str) -> str:
    """MO/MÖ/MS -> Milattan Önce/Sonra (TTS tek harf okumasini onler)."""

    def _bce(m: re.Match[str]) -> str:
        year = m.group(1)
        suf = (m.group(2) or "").lstrip("'\u2019")
        return f"Milattan Önce {year}{suf}"

    def _ce(m: re.Match[str]) -> str:
        year = m.group(1)
        suf = (m.group(2) or "").lstrip("'\u2019")
        return f"Milattan Sonra {year}{suf}"

    out = _MO_MS_RANGE_RE.sub(r"Milattan Önce \1 ile \2", text)
    out = _MO_MS_DATE_RE.sub(_bce, out)
    out = _MS_DATE_RE.sub(_ce, out)
    return out


def has_unexpanded_mo_ms(text: str) -> bool:
    """Kalite kontrolu — hâlâ MO/MÖ/MS kisaltmasi var mi."""
    t = text or ""
    if not t.strip():
        return False
    if _MO_MS_DATE_RE.search(t) or _MS_DATE_RE.search(t) or _MO_MS_RANGE_RE.search(t):
        return True
    return bool(re.search(r"(?<!\w)(?:MO|MÖ|MS)\s*\d", t, re.IGNORECASE))


_ROMAN_ORDINAL_TTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<!\w)VIII\.\s*", re.IGNORECASE), "sekizinci "),
    (re.compile(r"(?<!\w)VII\.\s*", re.IGNORECASE), "yedinci "),
    (re.compile(r"(?<!\w)XIII\.\s*", re.IGNORECASE), "on üçüncü "),
    (re.compile(r"(?<!\w)XII\.\s*", re.IGNORECASE), "on ikinci "),
    (re.compile(r"(?<!\w)XI\.\s*", re.IGNORECASE), "on birinci "),
    (re.compile(r"(?<!\w)III\.\s*", re.IGNORECASE), "üçüncü "),
    (re.compile(r"(?<!\w)II\.\s*", re.IGNORECASE), "ikinci "),
    (re.compile(r"(?<!\w)Iİ\.\s*", re.IGNORECASE), "ikinci "),
    (re.compile(r"(?<!\w)IV\.\s*", re.IGNORECASE), "dördüncü "),
    (re.compile(r"(?<!\w)VI\.\s*", re.IGNORECASE), "altıncı "),
    (re.compile(r"(?<!\w)IX\.\s*", re.IGNORECASE), "dokuzuncu "),
    (re.compile(r"(?<!\w)X\.\s*", re.IGNORECASE), "onuncu "),
    (re.compile(r"(?<!\w)V\.\s*", re.IGNORECASE), "beşinci "),
    (re.compile(r"(?<!\w)I\.\s*", re.IGNORECASE), "birinci "),
)


def _expand_roman_ordinals_for_tts(text: str) -> str:
    out = text or ""
    for pattern, spoken in _ROMAN_ORDINAL_TTS:
        out = pattern.sub(spoken, out)
    return out


def _strip_foreign_script_chars(text: str) -> str:
    """Yunan/Kiril vb. — TTS ve Shorts icin kaldir."""
    out = re.sub(r"[\u0370-\u03ff\u0400-\u04ff]+", "", text)
    out = re.sub(r"\(\s*\)", "", out)
    return re.sub(r"\s{2,}", " ", out).strip()


def _fix_turkish_tts_words(text: str) -> str:
    """TTS telaffuzu ve yazim — Turkce karakterleri korur."""
    out = _nfc(text)
    # ASCII klavye kalintilari (yalnizca Turkce harf yoksa dokunma riski dusuk)
    out = re.sub(r"(?i)\bvoynik\b", "Voyniç", out)
    out = re.sub(r"(?i)\bşuan\b", "şu an", out)
    out = re.sub(r"(?i)\bsuan\b", "şu an", out)
    out = re.sub(r"(?i)\bcozulemeyen\b", "çözülemeyen", out)
    out = re.sub(r"(?i)\byazmasi\b", "yazması", out)
    # 15. yuzyil -> 15. yuzyil (nokta korunur; TTS icin kesme yok)
    out = _CENTURY_RE.sub(r"\1. \2", out)
    out = _fix_number_apostrophes_for_tts(out)
    out = _expand_mo_ms_dates(out)
    out = _expand_roman_ordinals_for_tts(out)
    out = _expand_spoken_abbreviations(out)
    try:
        from akifactory.turkish_imla import apply_context_spelling_repairs

        out = apply_context_spelling_repairs(out)
    except Exception:
        pass
    out = _apply_tts_word_substitutions(out)
    return out


# Edge TTS â/î/û okumaz veya yanlis okur — dogal alternatif kelime (TTS + altyazi + senaryo).
_TTS_WORD_SUBSTITUTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\bhâlâ\b"), "halen"),
    (re.compile(r"(?i)\bhalâ\b"), "halen"),
    (
        re.compile(r"(?i)\bhala\b(?!\s*(?:ışığ|ışığı|isig|isigi))"),
        "halen",
    ),
    (re.compile(r"(?i)\bhâl\b"), "durum"),
    (re.compile(r"(?i)\bkâr\b"), "kazanç"),
    (re.compile(r"(?i)\bâdet\b"), "genelde"),
    (re.compile(r"(?i)\blâkin\b"), "ama"),
    (re.compile(r"(?i)\blakin\b"), "ama"),
    (re.compile(r"(?i)\bîmkan\b"), "olanak"),
    (re.compile(r"(?i)\bimkân\b"), "olanak"),
    (re.compile(r"(?i)\bâlem\b"), "dünya"),
    # LLM/TTS bozulmalari
    (re.compile(r"(?i)\bbüzülün(?:dan|den)\b"), "buzulundan"),
    (re.compile(r"(?i)\bbüzül(?:u|ü)n(?:dan|den)\b"), "buzulundan"),
    (re.compile(r"(?i)\bbuzulun(?:dan|den)\b"), "buzulundan"),
    (re.compile(r"(?i)\bantarktıka\b"), "Antarktika"),
    (re.compile(r"(?i)\bantarktika\b"), "Antarktika"),
    (re.compile(r"(?i)\bfen olayını\b"), "fenomeni"),
    (re.compile(r"(?i)\bfen olayini\b"), "fenomeni"),
    (re.compile(r"(?i)\bfen olayı\b"), "fenomen"),
    (re.compile(r"(?i)\bfen olayi\b"), "fenomen"),
    (re.compile(r"(?i)\banomal[ıi]\b"), "anomali"),
    (re.compile(r"(?i)\bdunaliella\s+salına\b"), "Dunaliella salina"),
    (re.compile(r"(?i)\bsalına\b"), "salina"),
    (re.compile(r"(?i)\bperçy\b"), "Percy"),
    (re.compile(r"(?i)\bkarakuum\b"), "Karakum"),
    (re.compile(r"(?i)\bdoğal fen\b"), "doğal fenomen"),
    (re.compile(r"(?i)\bdogal fen\b"), "doğal fenomen"),
)


def _apply_tts_word_substitutions(text: str) -> str:
    out = text
    for pattern, replacement in _TTS_WORD_SUBSTITUTIONS:
        out = pattern.sub(replacement, out)
    return out


# TTS tek harf okumasini onler — MÖ -> Milattan Önce, Dr. -> Doktor vb.
_ABBR_SUFFIX = (
    r"(?:"
    r"['\u2019](?:den|dan|de|da|nin|nın|nun|nün|in|ın|un|ün|"
    r"ler|lar|lerde|larda|leri|ları|e|a|i|ı|u|ü)"
    r"|['\u2019](?:de|da)"
    r")?"
)

_SPOKEN_ABBREV_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(rf"(?<!\w)M\s*\.\s*Ö\s*\.?({_ABBR_SUFFIX})(?!\w)", re.IGNORECASE),
        "Milattan Önce",
    ),
    (
        re.compile(rf"(?<!\w)MÖ({_ABBR_SUFFIX})(?!\w)", re.IGNORECASE),
        "Milattan Önce",
    ),
    (
        re.compile(rf"(?<!\w)M\s*\.\s*O\s*\.?({_ABBR_SUFFIX})(?!\w)", re.IGNORECASE),
        "Milattan Önce",
    ),
    (
        re.compile(rf"(?<!\w)İ\s*\.\s*Ö\s*\.?({_ABBR_SUFFIX})(?!\w)", re.IGNORECASE),
        "Milattan Önce",
    ),
    (
        re.compile(rf"(?<!\w)I\s*\.\s*O\s*\.?({_ABBR_SUFFIX})(?!\w)", re.IGNORECASE),
        "Milattan Önce",
    ),
    (
        re.compile(rf"(?<!\w)M\s*\.\s*S\s*\.?({_ABBR_SUFFIX})(?!\w)", re.IGNORECASE),
        "Milattan Sonra",
    ),
    (
        re.compile(rf"(?<!\w)MS({_ABBR_SUFFIX})(?!\w)", re.IGNORECASE),
        "Milattan Sonra",
    ),
    (
        re.compile(rf"(?<!\w)İ\s*\.\s*S\s*\.?({_ABBR_SUFFIX})(?!\w)", re.IGNORECASE),
        "Milattan Sonra",
    ),
    (
        re.compile(rf"(?<!\w)I\s*\.\s*S\s*\.?({_ABBR_SUFFIX})(?!\w)", re.IGNORECASE),
        "Milattan Sonra",
    ),
    (re.compile(r"(?<!\w)B\.?\s*C\.?\s*E\.?(?!\w)", re.IGNORECASE), "Milattan Önce"),
    (re.compile(r"(?<!\w)B\.?\s*C\.?(?!\w)", re.IGNORECASE), "Milattan Önce"),
    (re.compile(r"(?<!\w)A\.?\s*D\.?(?!\w)", re.IGNORECASE), "Milattan Sonra"),
    (re.compile(r"(?<!\w)C\.?\s*E\.?(?!\w)", re.IGNORECASE), "Milattan Sonra"),
    (re.compile(r"(?<!\w)Prof\.(?!\w)", re.IGNORECASE), "Profesör"),
    (re.compile(r"(?<!\w)Doç\.(?!\w)", re.IGNORECASE), "Doçent"),
    (re.compile(r"(?<!\w)Dr\.(?!\w)", re.IGNORECASE), "Doktor"),
    (re.compile(r"(?<!\w)Av\.(?!\w)", re.IGNORECASE), "Avukat"),
    (re.compile(r"(?<!\w)vb\.(?!\w)", re.IGNORECASE), "ve benzeri"),
    (re.compile(r"(?<!\w)vs\.(?!\w)", re.IGNORECASE), "ve saire"),
    (re.compile(r"(?<!\w)örn\.(?!\w)", re.IGNORECASE), "örneğin"),
    (re.compile(r"(?<!\w)yy\.(?!\w)", re.IGNORECASE), "yüzyıl"),
    (re.compile(r"(?<!\w)y\.?\s*y\.?(?!\w)", re.IGNORECASE), "yüzyıl"),
    (re.compile(r"(?<!\w)km/h(?!\w)", re.IGNORECASE), "kilometre saat"),
    (re.compile(r"(?<!\w)km(?!\w)", re.IGNORECASE), "kilometre"),
    (re.compile(r"(?<!\w)cm(?!\w)", re.IGNORECASE), "santimetre"),
    (re.compile(r"(?<!\w)mm(?!\w)", re.IGNORECASE), "milimetre"),
    (re.compile(r"(?<!\w)kg(?!\w)", re.IGNORECASE), "kilogram"),
    (re.compile(r"(?<!\w)gr(?!\w)", re.IGNORECASE), "gram"),
    (re.compile(r"(?<!\w)m²(?!\w)", re.IGNORECASE), "metrekare"),
    (re.compile(r"(?<!\w)km²(?!\w)", re.IGNORECASE), "kilometrekare"),
    (re.compile(r"(?<!\w)No\.(?!\w)", re.IGNORECASE), "numara"),
    (re.compile(r"(?<!\w)cad\.(?!\w)", re.IGNORECASE), "caddesi"),
    (re.compile(r"(?<!\w)sok\.(?!\w)", re.IGNORECASE), "sokak"),
    (re.compile(r"(?<!\w)bul\.(?!\w)", re.IGNORECASE), "bulvar"),
    (re.compile(r"(?<!\w)°C(?!\w)"), "derece Celsius"),
    (re.compile(r"(?<!\w)°F(?!\w)"), "derece Fahrenheit"),
)


def expand_spoken_abbreviations(text: str) -> str:
    """Kisaltmalari TTS'in okuyacagi uzun Turkce karsiliklara cevir."""
    if not (text or "").strip():
        return text or ""
    out = text
    for pattern, spoken in _SPOKEN_ABBREV_RULES:
        if pattern.groups:
            out = pattern.sub(lambda m, s=spoken: s + (m.group(1) or ""), out)
        else:
            out = pattern.sub(spoken, out)
    return out


def _expand_spoken_abbreviations(text: str) -> str:
    return expand_spoken_abbreviations(text)


def script_paragraphs(text: str) -> list[str]:
    """Bos satir veya satir sonlarindan paragraf birlestir."""
    paras: list[str] = []
    buf: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if buf:
                paras.append(" ".join(buf))
                buf = []
            continue
        buf.append(line)
    if buf:
        paras.append(" ".join(buf))
    if not paras and text.strip():
        paras = [text.strip()]
    return paras


def _is_century_dot(text: str, dot_index: int) -> bool:
    if dot_index <= 0 or text[dot_index] != ".":
        return False
    if not text[dot_index - 1].isdigit():
        return False
    tail = text[dot_index + 1 : dot_index + 24].lstrip().lower()
    return tail.startswith(("yüzyıl", "yuzyil", "yüzyılın", "yuzyilin", "yüzyıla", "yuzyila"))


def _split_paragraph_sentences(paragraph: str) -> list[str]:
    """Paragraf icinde cumle bol — yuzyil noktasi ve 1,000 korunur."""
    result: list[str] = []
    buf: list[str] = []
    s = paragraph.strip()
    for i, char in enumerate(s):
        prev = s[i - 1] if i > 0 else ""
        nxt = s[i + 1] if i + 1 < len(s) else ""
        if char == "." and prev.isdigit() and nxt.isdigit():
            buf.append(char)
            continue
        if char == "," and prev.isdigit() and nxt.isdigit():
            buf.append(char)
            continue
        if char == "." and _is_century_dot(s, i):
            buf.append(char)
            continue
        if char not in _SENTENCE_END:
            buf.append(char)
            continue
        chunk = ("".join(buf).strip() + char).strip()
        if chunk:
            result.append(chunk)
        buf = []
    tail = "".join(buf).strip()
    if tail:
        result.append(tail)
    return result


def turkish_genitive(phrase: str) -> str:
    """Basit iyelik: 'Voynich el yazması' -> 'Voynich el yazmasının'."""
    p = (phrase or "").strip().rstrip(".")
    if not p:
        return p
    if re.search(r"['\u2019]", p):
        return p
    last_vowel = None
    for ch in reversed(p):
        c = ch.lower()
        if c in "aeiouöüı":
            last_vowel = c
            break
    harmony = {
        "a": "ın",
        "ı": "ın",
        "o": "un",
        "u": "un",
        "e": "in",
        "i": "in",
        "ö": "ün",
        "ü": "ün",
    }
    suffix = harmony.get(last_vowel or "a", "ın")
    if p[-1].lower() in "aeiouöüı":
        return f"{p}n{suffix}"
    return f"{p}{suffix}"


def normalize_chapter_title(title: str, main: str) -> str:
    """Alt baslik — ana konu tekrarini ve ayri konu gibi duran on eki temizler."""
    t = (title or "").strip()
    m = (main or "").strip()
    if not t:
        return t
    if m:
        low_t, low_m = t.lower(), m.lower()
        if low_t == low_m:
            return "Giris ve merak uyandiran acilis"
        for sep in (" — ", " - ", ": ", " | "):
            if low_t.startswith(low_m + sep.lower()) or low_t.startswith(low_m + sep[0]):
                idx = t.lower().find(sep.strip()[0], len(m) - 1)
                if idx > 0:
                    t = t[idx:].lstrip(" -—:|")
                    break
        if t.lower().startswith(low_m):
            t = t[len(m) :].lstrip(" -—:|")
    return t.strip() or "Devam"


def full_chapter_heading(main: str, sub: str) -> str:
    """Kisa alt basligi ana konuya bagla: 'tarihçesi' -> 'Voynich el yazmasının tarihçesi'."""
    m = (main or "").strip()
    s = normalize_chapter_title((sub or "").strip(), m)
    if not s:
        return m
    if not m:
        return s
    low_s, low_m = s.lower(), m.lower()
    if low_s.startswith(low_m):
        return s
    if low_m in low_s and len(s) > len(m) + 4:
        return s
    return f"{turkish_genitive(m)} {s}"


_TITLE_ECHO_META = (
    "hakkında",
    "hakkinda",
    "konusu",
    "basligi",
    "başlığı",
    "bolumu",
    "bölümü",
    "kismi",
    "kısmı",
    "baslik",
    "başlık",
    "bolum",
    "bölüm",
    "sirada",
    "sırada",
    "gelelim",
    "devam edelim",
)


def scrub_longform_chapter_narration(
    script: str,
    *,
    main_subject: str,
    chapter_title: str,
    all_chapter_titles: list[str] | None = None,
) -> str:
    """Alt baslik / plan maddesi okumasini senaryo metninden temizle."""
    out = (script or "").strip()
    if not out:
        return out

    main = (main_subject or "").strip()
    title = (chapter_title or "").strip()
    display = full_chapter_heading(main, title)
    refs: list[str] = []
    for raw in [display, title, main]:
        val = (raw or "").strip()
        if val and val.lower() not in {r.lower() for r in refs}:
            refs.append(val)
    for raw in all_chapter_titles or []:
        val = full_chapter_heading(main, (raw or "").strip())
        if val and val.lower() not in {r.lower() for r in refs}:
            refs.append(val)

    sentences: list[str] = []
    for para in script_paragraphs(out):
        sentences.extend(_split_paragraph_sentences(para))
    if not sentences:
        return out

    def is_title_echo(sentence: str) -> bool:
        low = sentence.lower().strip()
        if re.match(r"^\d+[\.)]\s", low):
            return True
        if low.startswith(("bu bolumde", "bu bölümde", "simdi ", "şimdi ")):
            return True
        hits = 0
        for ref in refs:
            ref_low = ref.lower().strip()
            if len(ref_low) < 6:
                continue
            if low == ref_low:
                return True
            if low.startswith(ref_low) and len(low) <= len(ref_low) + 28:
                return True
            if ref_low in low and len(low) <= len(ref_low) + 40:
                if any(w in low for w in _TITLE_ECHO_META):
                    return True
            if ref_low in low:
                hits += 1
        return hits >= 2

    cleaned: list[str] = []
    for idx, sent in enumerate(sentences):
        if idx < 3 and is_title_echo(sent):
            continue
        cleaned.append(sent)
    if not cleaned:
        return out
    return " ".join(cleaned)


# TikTok / Shorts: ekranda tek seferde gorunecek max karakter (yaklasik 2-6 kelime)
_MAX_SUBTITLE_CHARS = 72


def _split_long_phrase(phrase: str, *, max_chars: int = _MAX_SUBTITLE_CHARS) -> list[str]:
    """Uzun cumle veya satiri okunabilir altyazi parcalarina bol."""
    phrase = phrase.strip()
    if not phrase:
        return []
    if len(phrase) <= max_chars:
        return [phrase]

    # Once virgul / noktalı virgul gibi kisa duraklardan bol
    parts = re.split(r"(?<=[,;])\s+", phrase)
    if len(parts) > 1:
        out: list[str] = []
        for part in parts:
            out.extend(_split_long_phrase(part, max_chars=max_chars))
        return out

    words = phrase.split()
    if not words:
        return [phrase]

    # "19. yüzyıl" / "1. yüzyıla" — noktali sira ile sonraki kelimeyi ayirma
    merged: list[str] = []
    i = 0
    while i < len(words):
        w = words[i]
        if (
            i + 1 < len(words)
            and re.fullmatch(r"\d{1,2}\.", w)
            and re.match(r"(?i)y[uü]zy[iı]l", words[i + 1])
        ):
            merged.append(f"{w} {words[i + 1]}")
            i += 2
            continue
        merged.append(w)
        i += 1
    words = merged

    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for word in words:
        add = len(word) + (1 if buf else 0)
        if buf and buf_len + add > max_chars:
            chunks.append(" ".join(buf))
            buf = [word]
            buf_len = len(word)
        else:
            buf.append(word)
            buf_len += add
    if buf:
        chunks.append(" ".join(buf))
    return chunks


def _split_line_for_subtitle(line: str) -> list[str]:
    """Tek satiri altyazi segmentlerine ayir."""
    line = line.strip()
    if not line:
        return []

    segments: list[str] = []
    for sent in _split_paragraph_sentences(line):
        sent = sent.strip()
        if not sent:
            continue
        segments.extend(_split_long_phrase(sent))
    if not segments:
        segments.extend(_split_long_phrase(line))
    return segments


def split_script_lines(text: str) -> list[str]:
    """
    Altyazi / zamanlama satirlari.

    - Kullanicinin satir sonlari korunur (her satir ayri altyazi adayi).
    - Satir icinde birden fazla cumle varsa otomatik bolunur.
    - Uzun parcalar kelime grubuna bolunur (TikTok tarzi).
    """
    if not (text or "").strip():
        return []

    out = clean_turkish_script(text)
    out = _fix_turkish_tts_words(out)

    lines: list[str] = []
    for raw in out.splitlines():
        line = raw.strip()
        if not line:
            continue
        lines.extend(_split_line_for_subtitle(line))
    return [ln for ln in lines if ln.strip()]


def prepare_video_script(text: str, *, niche_id: str = "") -> str:
    """Manuel veya AI senaryo — TTS ve altyazi oncesi normalize."""
    if not text:
        return ""
    out = clean_turkish_script(text)
    try:
        from akifactory.turkish_imla import apply_turkish_imla

        out = apply_turkish_imla(out)
    except Exception:
        pass
    out = _strip_foreign_script_chars(out)
    out = _fix_turkish_tts_words(out)
    allow_questions = False
    if niche_id:
        try:
            from akifactory.script_hooks import is_kids_niche

            allow_questions = is_kids_niche(niche_id)
        except Exception:
            allow_questions = False
    out = enforce_spoken_script_limits(out, allow_questions=allow_questions)
    paras = script_paragraphs(out)
    return "\n\n".join(paras)


def prepare_script_for_engine(
    text: str,
    lang_id: str = "tr",
    *,
    follow_cta: bool = False,
    niche_id: str = "",
) -> str:
    """Motor payload — dili koru; bosaltma."""
    raw = (text or "").strip()
    if not raw:
        return ""
    lang = (lang_id or "tr").strip().lower()[:2]
    if lang == "en":
        # Sizinti temizligi; bos kalirsa ham (sizintili) metni geri koyma
        out = (clean_turkish_script(raw) or "").strip()
    else:
        out = (prepare_video_script(raw, niche_id=niche_id) or "").strip()
        if not out:
            out = (clean_turkish_script(raw) or "").strip()
        if lang == "tr" and out:
            try:
                from akifactory.script_topic import scrub_debunk_content

                out = scrub_debunk_content(out)
            except Exception:
                pass

    if follow_cta and out:
        try:
            from akifactory.script_hooks import is_kids_niche

            if not is_kids_niche(niche_id):
                out = append_follow_cta(out, lang_id=lang)
        except Exception:
            out = append_follow_cta(out, lang_id=lang)
    return out.strip()


# ~12 karakter/sn konusma; 55 sn hedef
MAX_SPOKEN_SCRIPT_CHARS = 680

FOLLOW_CTA_TR = "Daha fazlası için takip etmeyi unutmayın."
FOLLOW_CTA_EN = "Follow for more stories like this."

_FOLLOW_CTA_MARKERS = (
    "takip etmeyi unutma",
    "takip etmeyi unutmayın",
    "takip etmeyi unutmayin",
    "daha fazlası için takip",
    "daha fazlasi icin takip",
    "follow for more",
    "don't forget to follow",
    "dont forget to follow",
)


def has_follow_cta(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in _FOLLOW_CTA_MARKERS)


def follow_cta_for_lang(lang_id: str) -> str:
    lang = (lang_id or "tr").strip().lower()[:2]
    return FOLLOW_CTA_EN if lang == "en" else FOLLOW_CTA_TR


def append_follow_cta(
    text: str,
    *,
    lang_id: str = "tr",
    max_chars: int = MAX_SPOKEN_SCRIPT_CHARS,
) -> str:
    """Kisa video senaryosu sonuna yumusak takip cagrisi ekle."""
    out = (text or "").strip()
    if not out or has_follow_cta(out):
        return out

    cta = follow_cta_for_lang(lang_id)
    merged = f"{out} {cta}".strip()
    if len(merged) <= max_chars:
        return merged

    sentences: list[str] = []
    for para in script_paragraphs(out):
        for sent in _split_paragraph_sentences(para):
            s = sent.strip()
            if s:
                sentences.append(s)

    while sentences:
        # CTA oncesi yarim cumle birakma
        while sentences and _is_incomplete_clause(
            sentences[-1], has_prior_complete=len(sentences) > 1
        ):
            sentences.pop()
        if not sentences:
            break
        body = " ".join(sentences).strip()
        candidate = f"{body} {cta}".strip()
        if len(candidate) <= max_chars:
            return candidate
        sentences.pop()

    room = max_chars - len(cta) - 1
    if room < 40:
        return _clip_at_word_boundary(out, max_chars)
    body = _clip_at_word_boundary(out, room)
    if not body:
        return _clip_at_word_boundary(out, max_chars)
    if body[-1] not in ".!?…":
        body = body.rstrip(",;: ") + "."
    return f"{body} {cta}"
# Uzun video bolumu (~50 sn)
MAX_LONGFORM_CHAPTER_CHARS = 720
# Tek parca ~10 dk
MAX_LONGFORM_FULL_SCRIPT_CHARS = 9000

_QUESTION_START = re.compile(
    r"^(?:peki|sence|acaba|gerçekten mi|gercekten mi|neden|nasıl|nasil|"
    r"nerede|nereden|ne zaman|hangi|kim|kaç|kac|"
    r"biliyor musun|biliyor muydun|duydun mu|inanır mısın|inanir misin)\b",
    re.IGNORECASE,
)
_QUESTION_END = re.compile(
    r"\s+(?:"
    r"mi|mı|mu|mü|"
    r"mıdır|midir|mudur|müdür|"
    r"misin|mısın|musun|müsün|"
    r"miyiz|miyiz|"
    r"miydi|miydi"
    r")\s*[.!?…]?\s*$",
    re.IGNORECASE,
)
_QUESTION_MI_VERB = re.compile(
    r"\s+(?:mi|mı|mu|mü)\s+[a-zçğıöşüA-ZÇĞİÖŞÜ]+\s*[.!?…]?\s*$",
    re.IGNORECASE,
)
_QUESTION_FRAGMENTS = (
    " biliyor muydun",
    " biliyor musun",
    " duydun mu",
    " inanır mısın",
    " inanir misin",
    " gerçekten mi",
    " gercekten mi",
)


def _is_question_like_sentence(sentence: str) -> bool:
    t = (sentence or "").strip()
    if not t:
        return False
    if "?" in t:
        return True
    low = t.lower()
    if _QUESTION_START.search(low):
        return True
    if _QUESTION_END.search(t):
        return True
    if _QUESTION_MI_VERB.search(t):
        return True
    return any(frag in low for frag in _QUESTION_FRAGMENTS)


def _ensure_question_mark(sentence: str) -> str:
    t = (sentence or "").strip()
    if not t:
        return t
    if t.endswith("?"):
        return t
    core = t.rstrip(".!…").rstrip()
    return f"{core}?" if core else t


def _strip_trailing_emojis(text: str) -> str:
    return re.sub(
        r"(?:[\U0001F300-\U0001FAFF\u2600-\u27BF]\ufe0f?\s*)+$",
        "",
        (text or "").rstrip(),
    ).rstrip()


def _clip_at_word_boundary(text: str, max_chars: int) -> str:
    """Karakter sinirinda kelime ortasindan kesme — son kelimeyi dusur."""
    t = (text or "").strip()
    if max_chars <= 0 or not t:
        return ""
    if len(t) <= max_chars:
        return t
    cut = t[:max_chars].rstrip()
    if " " in cut:
        # Ortada kesildiyse veya son parca cok kisaysa son kelimeyi at
        mid_cut = max_chars < len(t) and (t[max_chars].isalnum() if max_chars < len(t) else False)
        head, _, last = cut.rpartition(" ")
        last_alnum = re.sub(r"[^\wçğıöşüÇĞİÖŞÜ]", "", last, flags=re.UNICODE)
        if mid_cut or len(last_alnum) <= 2:
            cut = head.rstrip()
    return cut.rstrip(" \t,;:–—-|·")


def _is_incomplete_clause(sentence: str, *, has_prior_complete: bool = False) -> bool:
    """Cumle bitmemis / yari kesilmis mi? (ornegin '... tumu M')"""
    t = _strip_trailing_emojis((sentence or "").strip())
    if not t:
        return True
    if t[-1] in ".!?…":
        return False
    words = t.split()
    if not words:
        return True
    last = re.sub(r"[^\wçğıöşüÇĞİÖŞÜ]+$", "", words[-1], flags=re.UNICODE)
    if len(last) <= 2:
        return True
    if t[-1] in ",;:":
        return True
    if re.search(
        r"\b(?:ve|ile|olup|olan|için|icin|veya|ama|fakat|ki|the|and|of|or|a|an)\s*$",
        t,
        re.IGNORECASE,
    ):
        return True
    # Onceki tamamlanmis cumleler varken noktasiz kuyruk = yarim uretim
    if has_prior_complete:
        return True
    return False


def repair_script_narration(text: str) -> str:
    """Yarim/bozuk cumleleri dusur; anlatim kopuklugunu hafifce toparla.

    Mevcut pipeline'i bozmaz — enforce_spoken_script_limits oncesi/sonrasi guvenli.
    """
    out = clean_turkish_script(text)
    if not out:
        return ""

    sentences: list[str] = []
    for para in script_paragraphs(out):
        for sent in _split_paragraph_sentences(para):
            s = sent.strip()
            if s:
                sentences.append(s)
    if not sentences:
        return out

    kept: list[str] = []
    for s in sentences:
        words = s.split()
        # Cok kisa / tek kelimelik fragment
        if len(words) < 3 and len(_strip_trailing_emojis(s)) < 28:
            continue
        # Son token tek harf / iki harf kesik ("tumu M.")
        last = re.sub(r"[^\wçğıöşüÇĞİÖŞÜ]+$", "", words[-1], flags=re.UNICODE)
        if len(last) <= 1:
            continue
        if _is_incomplete_clause(s, has_prior_complete=bool(kept)):
            continue
        # Noktasiz birakma
        if s[-1] not in ".!?…":
            s = s.rstrip(" ,;:") + "."
        kept.append(s)

    if not kept:
        # Hicbir sey kalmadiysa en uzun cumleyi kurtar
        best = max(sentences, key=len)
        clipped = _clip_at_word_boundary(best, max(80, len(best)))
        if clipped and clipped[-1] not in ".!?…":
            clipped = clipped.rstrip(",;: ") + "."
        return clipped

    return " ".join(kept)


def enforce_spoken_script_limits(
    text: str,
    *,
    max_chars: int = MAX_SPOKEN_SCRIPT_CHARS,
    allow_questions: bool = False,
) -> str:
    """Kisa video: soru cumlelerini kaldir; sure sinirinda TAM cumlede kes."""
    out = repair_script_narration(text)
    if not out:
        return ""

    sentences: list[str] = []
    for para in script_paragraphs(out):
        for sent in _split_paragraph_sentences(para):
            s = sent.strip()
            if not s:
                continue
            if _is_question_like_sentence(s):
                if allow_questions:
                    sentences.append(_ensure_question_mark(s))
                continue
            sentences.append(s)

    if not sentences:
        clipped = _clip_at_word_boundary(out, max_chars)
        return clipped

    lines: list[str] = []
    total = 0
    for s in sentences:
        add = len(s) + (1 if lines else 0)
        if total + add > max_chars:
            if lines:
                break
            # Tek cumle limiti asiyorsa kelime sinirinda kirp + nokta
            clipped = _clip_at_word_boundary(s, max_chars)
            if clipped and clipped[-1] not in ".!?…":
                clipped = clipped.rstrip(",;: ") + "."
            return clipped
        lines.append(s)
        total += add

    # Yarim kalmis son cumleyi at (LLM kesmesi / sure kirpma)
    while lines and _is_incomplete_clause(
        lines[-1], has_prior_complete=len(lines) > 1
    ):
        lines.pop()

    if not lines:
        clipped = _clip_at_word_boundary(sentences[0], max_chars)
        if clipped and clipped[-1] not in ".!?…":
            clipped = clipped.rstrip(",;: ") + "."
        return clipped

    return " ".join(lines)


def enforce_longform_chapter_limits(
    text: str,
    *,
    max_chars: int = MAX_LONGFORM_CHAPTER_CHARS,
    allow_questions: bool = False,
) -> str:
    return enforce_spoken_script_limits(
        text, max_chars=max_chars, allow_questions=allow_questions
    )


def enforce_longform_full_script_limits(
    text: str,
    *,
    max_chars: int = MAX_LONGFORM_FULL_SCRIPT_CHARS,
) -> str:
    """Uzun video — tum bolumler birlestirilmis tek senaryo."""
    out = clean_turkish_script(text)
    if not out or len(out) <= max_chars:
        return out
    paras = script_paragraphs(out)
    trimmed: list[str] = []
    total = 0
    for para in paras:
        add = len(para) + (2 if trimmed else 0)
        if total + add > max_chars and trimmed:
            break
        trimmed.append(para)
        total += add
    return "\n\n".join(trimmed).strip()


def has_turkish_chars(text: str) -> bool:
    return bool(_TURKISH_CHARS.search(text or ""))
