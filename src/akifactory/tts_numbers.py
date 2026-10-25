"""Turkce TTS icin rakam → yazi (altyazi metnini degistirmez).

Ornek:
  2600de → iki bin alti yuz de
  40.000 → kırk bin          (binlik ayirici nokta — «nokta sifir» DEGIL)
  1.250.000 → bir milyon iki yüz elli bin
  3,5 → üç virgül beş
  3000'lerden → uc bin lerden
  1. yuzyil → birinci yuzyil
  %50 → yuzde elli
"""

from __future__ import annotations

import re

_ONES = (
    "",
    "bir",
    "iki",
    "üç",
    "dört",
    "beş",
    "altı",
    "yedi",
    "sekiz",
    "dokuz",
)
_TENS = (
    "",
    "on",
    "yirmi",
    "otuz",
    "kırk",
    "elli",
    "altmış",
    "yetmiş",
    "seksen",
    "doksan",
)
_SCALES = (
    (1_000_000_000, "milyar"),
    (1_000_000, "milyon"),
    (1_000, "bin"),
)

_ORDINAL_1_20 = {
    1: "birinci",
    2: "ikinci",
    3: "üçüncü",
    4: "dördüncü",
    5: "beşinci",
    6: "altıncı",
    7: "yedinci",
    8: "sekizinci",
    9: "dokuzuncu",
    10: "onuncu",
    11: "on birinci",
    12: "on ikinci",
    13: "on üçüncü",
    14: "on dördüncü",
    15: "on beşinci",
    16: "on altıncı",
    17: "on yedinci",
    18: "on sekizinci",
    19: "on dokuzuncu",
    20: "yirminci",
}

# Ekler: 2600de, 1922'de, 3000'lerden, 2000'li
_TR_SUFFIX = (
    r"(?:['\u2018\u2019´`ʼ]?)(?:"
    r"de|da|te|ta|den|dan|"
    r"nin|nın|nun|nün|in|ın|un|ün|"
    r"li|lı|lu|lü|"
    r"ler|lar|lerden|lardan|leri|ları|"
    r"ye|ya|yi|yı|yu|yü|"
    r"ne|na|ni|nı|nu|nü"
    r")?"
)

# 40.000 / 1.250.000,5 / 3,14 / 42 / 3.14 (kisa ondalik)
_NUM_CORE = (
    r"(?:"
    r"\d{1,3}(?:[.\u00a0\u202f ]\d{3})+(?:,\d+)?"
    r"|\d+,\d+"
    r"|\d+\.\d{1,2}"
    r"|\d+"
    r")"
)

_NUM_WITH_SUFFIX_RE = re.compile(
    rf"(?<![\w])(?:%\s*)?(?P<num>{_NUM_CORE})(?P<suf>{_TR_SUFFIX})?(?:\s*%)?(?![\w])"
)

_ORDINAL_DOT_RE = re.compile(
    r"(?<![\w])(?P<n>\d{1,2})\.\s*(?P<tail>yüzyıl\w*|yuzyil\w*|yy\b)",
    re.IGNORECASE,
)

_THOUSANDS_RE = re.compile(
    r"^(?P<body>\d{1,3}(?:[.\u00a0\u202f ]\d{3})+)(?:,(?P<dec>\d+))?$"
)
_DECIMAL_COMMA_RE = re.compile(r"^(?P<body>\d+),(?P<dec>\d+)$")
_DECIMAL_DOT_SHORT_RE = re.compile(r"^(?P<body>\d+)\.(?P<dec>\d{1,2})$")


def integer_to_turkish(n: int) -> str:
    if n == 0:
        return "sıfır"
    if n < 0:
        return f"eksi {integer_to_turkish(-n)}"
    parts: list[str] = []
    rest = n
    for scale, name in _SCALES:
        if rest >= scale:
            q, rest = divmod(rest, scale)
            if scale == 1000 and q == 1:
                parts.append("bin")
            else:
                parts.append(f"{integer_to_turkish(q)} {name}")
    if rest:
        parts.append(_under_1000(rest))
    return " ".join(p for p in parts if p)


def _under_1000(n: int) -> str:
    if n <= 0:
        return ""
    parts: list[str] = []
    h, rem = divmod(n, 100)
    if h:
        if h == 1:
            parts.append("yüz")
        else:
            parts.append(f"{_ONES[h]} yüz")
    t, o = divmod(rem, 10)
    if t:
        parts.append(_TENS[t])
    if o:
        parts.append(_ONES[o])
    return " ".join(parts)


def ordinal_to_turkish(n: int) -> str:
    if n in _ORDINAL_1_20:
        return _ORDINAL_1_20[n]
    if n <= 0:
        return integer_to_turkish(n)
    base = integer_to_turkish(n)
    last = base.split()[-1]
    if last.endswith(("ı", "i", "u", "ü", "a", "e", "o", "ö")):
        return f"{base}nci"
    return f"{base}inci"


def _clean_num_token(s: str) -> str:
    return (
        (s or "")
        .strip()
        .replace("\u00a0", "")
        .replace("\u202f", "")
        .replace(" ", "")
    )


def _speak_fraction_digits(frac: str) -> str:
    """Ondalik basamaklari tek tek oku (3,05 → virgül sıfır beş)."""
    return " ".join(integer_to_turkish(int(d)) for d in frac if d.isdigit())


def _expand_plain_number(s: str) -> str:
    s = _clean_num_token(s)
    if not s:
        return s

    # Tarih: 9.11.1989 / 9/11/1989
    if re.fullmatch(r"\d{1,2}[./]\d{1,2}[./]\d{2,4}", s):
        a, b, c = re.split(r"[./]", s)
        return (
            f"{integer_to_turkish(int(a))} "
            f"{integer_to_turkish(int(b))} "
            f"{integer_to_turkish(int(c))}"
        )

    # Turkce binlik: 40.000 / 1.250.000 / 1.250.000,75
    m = _THOUSANDS_RE.fullmatch(s)
    if m:
        n = int(re.sub(r"[.\u00a0\u202f ]", "", m.group("body")))
        spoken = integer_to_turkish(n)
        if m.group("dec"):
            spoken = f"{spoken} virgül {_speak_fraction_digits(m.group('dec'))}"
        return spoken

    # Turkce ondalik virgul: 3,5 / 12,05
    m = _DECIMAL_COMMA_RE.fullmatch(s)
    if m:
        return (
            f"{integer_to_turkish(int(m.group('body')))} virgül "
            f"{_speak_fraction_digits(m.group('dec'))}"
        )

    # Kisa nokta ondalik (surum / nadir): 3.14 — binlik degil
    m = _DECIMAL_DOT_SHORT_RE.fullmatch(s)
    if m:
        return (
            f"{integer_to_turkish(int(m.group('body')))} nokta "
            f"{_speak_fraction_digits(m.group('dec'))}"
        )

    if re.fullmatch(r"\d+", s):
        return integer_to_turkish(int(s))
    return s


def _join_spoken_suffix(spoken: str, suffix: str) -> str:
    """iki bin alti yuz + de → 'iki bin alti yuz de' (TTS akici)."""
    suf = (suffix or "").lstrip("'\u2018\u2019´`ʼ").strip()
    if not suf:
        return spoken
    return f"{spoken} {suf}"


def expand_number_token(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return s
    m = re.fullmatch(r"%\s*(" + _NUM_CORE + r")", s)
    if m:
        return f"yüzde {_expand_plain_number(m.group(1))}"
    m = re.fullmatch(r"(" + _NUM_CORE + r")\s*%", s)
    if m:
        return f"yüzde {_expand_plain_number(m.group(1))}"
    m = re.fullmatch(
        rf"(?P<num>{_NUM_CORE})(?P<suf>{_TR_SUFFIX})",
        s,
    )
    if m:
        spoken = _expand_plain_number(m.group("num"))
        return _join_spoken_suffix(spoken, m.group("suf") or "")
    return _expand_plain_number(s)


def expand_ordinal_centuries(text: str) -> str:
    """1. yuzyil → birinci yuzyil (TTS)."""

    def _repl(m: re.Match[str]) -> str:
        n = int(m.group("n"))
        tail = m.group("tail")
        if tail.lower() in ("yy", "yy."):
            tail = "yüzyıl"
        return f"{ordinal_to_turkish(n)} {tail}"

    return _ORDINAL_DOT_RE.sub(_repl, text or "")


def expand_numbers_for_turkish_tts(text: str) -> str:
    """Altyazi icin DEGIL — yalnizca seslendirme metni."""
    out = (text or "").strip()
    if not out:
        return out
    out = expand_ordinal_centuries(out)

    def _repl(m: re.Match[str]) -> str:
        num = m.group("num")
        suf = m.group("suf") or ""
        whole = m.group(0)
        if whole.lstrip().startswith("%") or whole.rstrip().endswith("%"):
            return f"yüzde {_expand_plain_number(num)}"
        spoken = _expand_plain_number(num)
        return _join_spoken_suffix(spoken, suf)

    out = _NUM_WITH_SUFFIX_RE.sub(_repl, out)
    return re.sub(r"\s+", " ", out).strip()
