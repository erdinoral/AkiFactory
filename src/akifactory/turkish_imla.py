"""Turkce yazim/imla kurallari — LLM prompt + otomatik duzeltme.

Kullanici kurallari: data/turkish_imla_rules.json
  - replacements: yanlis -> dogru (tam kelime eslesmesi)
  - prompt_hints: yalnizca LLM'e gosterilen ek imla notlari
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from akifactory.paths import data_dir, resource_dir

RULES_FILE = data_dir() / "turkish_imla_rules.json"
WORD_FREQ_FILE = resource_dir() / "lang" / "tr_wordfreq.txt"

_WB_L = r"(?<![\wçğıöşüÇĞİÖŞÜ])"
_WB_R = r"(?![\wçğıöşüÇĞİÖŞÜ])"

# Sik gorulen LLM / ASCII hatalari (tam kelime)
_BUILTIN_REPLACEMENTS: dict[str, str] = {
    "birsey": "bir şey",
    "birşey": "bir şey",
    "hersey": "her şey",
    "herşey": "her şey",
    "hicbirsey": "hiçbir şey",
    "hiçbirsey": "hiçbir şey",
    "hicbirşey": "hiçbir şey",
    "hiçbirşey": "hiçbir şey",
    "yalnış": "yanlış",
    "yalnis": "yanlış",
    "herzaman": "her zaman",
    "dahada": "daha da",
    "birkere": "bir kere",
    "herhangibir": "herhangi bir",
    "yada": "ya da",
    "orjinal": "orijinal",
    "şöför": "şoför",
    "sofor": "şoför",
    "bilmiyodum": "bilmiyordum",
    # Homograf / ozel isim — deasciify + LLM hatalari (tam kelime; ekli formlar asagida regex)
    "Aşma Bahçe": "Asma Bahçe",
    "Aşma Bahçeler": "Asma Bahçeler",
    "Aşma bahçe": "Asma bahçe",
    "Babel": "Babil",
    "Babel'in": "Babil'in",
    "Babel'de": "Babil'de",
    "Babıl": "Babil",
    "Babıl'de": "Babil'de",
    "Babılın": "Babilin",
    "Babıllerin": "Babillilerin",
    "yanlız": "yalnız",
    "yanliz": "yalnız",
    "yalnızca": "yalnızca",
    "herkez": "herkes",
    "herkezin": "herkesin",
    "bircok": "birçok",
    "ogrenci": "öğrenci",
    "ogretmen": "öğretmen",
    "ülke": "ülke",
    "ulke": "ülke",
    "Turkiye": "Türkiye",
    "turkiye": "Türkiye",
    "TURKIYE": "TÜRKİYE",
    "guzel": "güzel",
    "sehir": "şehir",
    "sehrin": "şehrin",
    "sehirde": "şehirde",
    "tarihçe": "tarihçe",
    "tarihce": "tarihçe",
    "imparatorlugu": "imparatorluğu",
    "imparatorluk": "imparatorluk",
    "Impatorluk": "İmparatorluk",
    "Imparatorlugu": "İmparatorluğu",
    "Imparatorluk": "İmparatorluk",
    "Sumer": "Sümer",
    "Sumerler": "Sümerler",
    "Sumer'in": "Sümer'in",
    "Sumerlerin": "Sümerlerin",
    "Babil Imparatorlugu": "Babil İmparatorluğu",
    "Mezopotamya": "Mezopotamya",
    "mezopotamya": "Mezopotamya",
    "antik cag": "antik çağ",
    "antik çag": "antik çağ",
    "yuzyil": "yüzyıl",
    "yuzyilda": "yüzyılda",
    "yuzyilin": "yüzyılın",
    "yüzyil": "yüzyıl",
    "arkeoloji": "arkeoloji",
    "arkeolog": "arkeolog",
    "gizemli": "gizemli",
    "cozulemeyen": "çözülemeyen",
    "cozuldu": "çözüldü",
    "oldugunu": "olduğunu",
    "oldugu": "olduğu",
    "degil": "değil",
    "degildi": "değildi",
    "icin": "için",
    "uzerinde": "üzerinde",
    "uzerine": "üzerine",
    "goruldu": "görüldü",
    "gorunuyor": "görünüyor",
    "konusu": "konusu",
    "konusunda": "konusunda",
}

# Prompt'ta LLM'e gosterilen sabit imla/dilbilgisi kurallari (referans checklist)
_STATIC_PROMPT_RULES: tuple[str, ...] = (
    "Türkçe karakterleri doğru ve eksiksiz kullan: ç, ğ, ı, i, ö, ş, ü, İ, I — ASCII yasak",
    "Küçük i'nin büyüğü İ; küçük ı'nın büyüğü I — Turkiye/Istanbul değil Türkiye/İstanbul",
    "bir şey, her şey, hiçbir şey, her biri, hiç kimse, her zaman, bir kere, ya da → AYRI yazılır",
    "birçok, birkaç, herhangi, herkes → BİTİŞİK yazılır (bir çok değil)",
    "yalnız (yanlız değil), herkes (herkez değil), yanlış (yalnış değil)",
    "Bağlaç de/da (bile anlamı) AYRI; bulunma eki -de/-da BİTİŞİK (Evde vs Ben de)",
    "Özel isim + ek kesme ile: Türkiye'de, Hammurabi'nin, Mezopotamya'nın; cins isimde kesme yok: şehirde, kralın",
    "TAMLAMA: «…krallıklarından/öğrencilerinden biri» öncesinde -de/-da DEĞİL -in/-ın/-ün/-un kullan",
    "  Doğru: Mezopotamya'nın en etkili krallıklarından biri | Yanlış: Mezopotamya'da en etkili krallıklarından biri",
    "Ek seçiminde ünlü uyumu: Sümerler (Sümerlar değil), krallıklar (krallıkler değil)",
    "Tarih/coğrafya: Sümer, Babil (Babel/Babıl değil), Mezopotamya, Hammurabi, Tutankamon — yerleşik Türkçe yazım",
    "Asma bahçeleri (asma = asılı bahçe; aşma YAZMA — TTS «aşma» okur)",
    "Su kanalı / su kemeri (şu kanalı değil — «şu» işaret zamiri, su = water)",
    "Tarih: Milattan Önce / Milattan Sonra (MÖ, MS yazma — TTS)",
    "Sayı ekleri TTS için kesmesiz: 1922de, 8i (8'i, 1922'de yazma)",
    "Roma rakamı YAZMA (I., II., III.) — ikinci Nebukadnezar, birinci yüzyıl gibi Türkçe söyle",
)

# Deasciifier bu kokleri/kelimeleri yanlis "duzeltir" (asma→aşma, Babil→Babıl, su→şu).
_DEASCII_BLOCK_EXACT = frozenset(
    {
        "su",
        "sular",
        "suyun",
        "suya",
        "suyu",
        "sudan",
        "sularin",
        "suların",
        "asma",
        "asmalar",
        "asmalari",
        "asmaları",
        "asmalarin",
        "asmaların",
        "asmayi",
        "asmayı",
        "asmaya",
        "asmada",
        "asmadan",
        "babil",
        "babilin",
        "babilde",
        "babilden",
        "babile",
        "babili",
        "babel",
        "babelin",
        "ise",  # baglac (ise→işe yazilmasin)
        "sakin",
    }
)
_DEASCII_BLOCK_PREFIXES = (
    "asma",  # asma bahçe… — asmak fiili ASCII'de nadiren; asma* koru
    "babil",
    "babel",
)
_HAS_TR_LETTER = re.compile(r"[çğıöşüÇĞİÖŞÜ]")
_DEASCII_TOKEN_RE = re.compile(
    r"[A-Za-zÇçĞğİıÖöŞşÜüÂâÊêÎîÔôÛû]+(?:['\u2018\u2019´`ʼ][A-Za-zÇçĞğİıÖöŞşÜü]+)?"
)

# Baglamli yazim onarimi (ekli formlar dahil) — deasciify/LLM sonrasi
_ASMA_BAHCE_RE = re.compile(
    r"(?i)\b(aşma)(\s+)(bahçe\w*)",
)
_BABEL_RE = re.compile(r"(?i)\bbabel\b")
_BABIL_CORRUPT_RE = re.compile(r"(?i)\b(babıl)(\w*)")
_BABIL_YANLIS_EK_RE = re.compile(
    r"(?i)\bbabil(['\u2018\u2019´`ʼ])ın\b",
)
# «şu» isaret zamiri vs «su» (water) — yalnizca su baglami
_SU_CONTEXT_RE = re.compile(
    r"(?i)\b(şu)(\s+)(kanal\w*|kemer\w*|tepel\w*|yönet\w*|yonet\w*|"
    r"depo\w*|tank\w*|kuyu\w*|nehir\w*|ırmak\w*|irmak\w*|çeşme\w*|cesme\w*|"
    r"bent\w*|baraj\w*|sulama\w*|havuz\w*|boru\w*|akarsu\w*)",
)

# «X'de en …larından biri» → «X'nın en …larından biri» (baglama bagli tamlama hatasi)
_TAMLAMA_BIRI_RE = re.compile(
    r"\b([\wçğıöşüÇĞİÖŞÜ]+)'d([ae])\s+((?:en\s+)?[\wçğıöşüÇĞİÖŞÜâîû\s]+?(?:larından|lerinden|larindan|lerinden))\s+biri\b",
    re.IGNORECASE,
)


def _last_vowel_harmony(word: str) -> str:
    for ch in reversed(word):
        c = ch.lower()
        if c in "aıou":
            return "ın" if c in "aı" else "un"
        if c in "eiöü":
            return "in" if c in "ei" else "ün"
    return "ın"


def _proper_tamlayan_form(word: str) -> str:
    """Ozel isim + tamlayan eki: Mezopotamya'nın, Hammurabi'nin."""
    p = word.strip()
    if not p:
        return p
    suf = _last_vowel_harmony(p)
    if p[-1].lower() in "aeiouöüı":
        return f"{p}'n{suf}"
    return f"{p}'{suf}"


def _match_case(sample: str, replacement: str) -> str:
    """Ilk harf buyuklugunu ornek kelimeye yaklastir."""
    if not replacement:
        return replacement
    if sample.isupper():
        return replacement.upper()
    if sample[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def apply_context_spelling_repairs(text: str) -> str:
    """Deasciify/LLM homograf ve ozel isim bozulmalarini baglama gore duzelt.

    Tek kelime sozlugu yetmez (aşma bahçeleri, şu kanalları); ekli formlari da kapsar.
    """
    out = text or ""
    if not out.strip():
        return out

    def _asma(m: re.Match[str]) -> str:
        return f"{_match_case(m.group(1), 'asma')}{m.group(2)}{m.group(3)}"

    out = _ASMA_BAHCE_RE.sub(_asma, out)

    def _babel(m: re.Match[str]) -> str:
        return _match_case(m.group(0), "Babil")

    out = _BABEL_RE.sub(_babel, out)

    def _babil_corrupt(m: re.Match[str]) -> str:
        rest = m.group(2) or ""
        rest_fix = rest.replace("ı", "i").replace("I", "İ") if rest else ""
        if rest_fix.lower().startswith("ler"):
            return _match_case(m.group(1), "Babilli") + rest_fix
        return _match_case(m.group(1), "Babil") + rest_fix

    out = _BABIL_CORRUPT_RE.sub(_babil_corrupt, out)
    out = _BABIL_YANLIS_EK_RE.sub(r"Babil\1in", out)

    def _su_ctx(m: re.Match[str]) -> str:
        return f"{_match_case(m.group(1), 'su')}{m.group(2)}{m.group(3)}"

    out = _SU_CONTEXT_RE.sub(_su_ctx, out)
    return out


def apply_grammar_fixes(text: str) -> str:
    """Baglama bagli dilbilgisi duzeltmeleri (regex — sinirli ama yuksek deger)."""
    out = text or ""

    def _tamlama_sub(m: re.Match[str]) -> str:
        noun = m.group(1)
        middle = m.group(3)
        return f"{_proper_tamlayan_form(noun)} {middle} biri"

    out = _TAMLAMA_BIRI_RE.sub(_tamlama_sub, out)
    out = apply_context_spelling_repairs(out)
    out = re.sub(
        r"\bŞu,\s+tepelere\b",
        "Su, tepelere",
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(
        r"\bŞu\s+tepelere\b",
        "Su tepelere",
        out,
        flags=re.IGNORECASE,
    )
    return out


def _compile_word_fixes(mapping: dict[str, str]) -> tuple[tuple[re.Pattern[str], str], ...]:
    rules: list[tuple[re.Pattern[str], str]] = []
    for wrong, right in sorted(mapping.items(), key=lambda x: -len(x[0])):
        w = wrong.strip()
        if not w or w == right:
            continue
        pat = re.compile(rf"{_WB_L}{re.escape(w)}{_WB_R}", re.IGNORECASE)
        rules.append((pat, right))
    return tuple(rules)


@lru_cache(maxsize=4)
def _all_word_fixes() -> tuple[tuple[re.Pattern[str], str], ...]:
    merged = dict(_BUILTIN_REPLACEMENTS)
    merged.update(_load_user_replacements_raw())
    return _compile_word_fixes(merged)


def _load_rules_file() -> dict:
    path = RULES_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_user_replacements_raw() -> dict[str, str]:
    data = _load_rules_file()
    raw = data.get("replacements") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        key = str(k).strip()
        val = str(v).strip()
        if key and val:
            out[key] = val
    return out


def load_user_prompt_hints() -> list[str]:
    data = _load_rules_file()
    hints = data.get("prompt_hints") or []
    if not isinstance(hints, list):
        return []
    return [str(h).strip() for h in hints if str(h).strip()]


def rules_file_path() -> Path:
    return RULES_FILE


def ensure_rules_file() -> Path:
    """Ornek kurallar dosyasini olustur (yoksa)."""
    if RULES_FILE.is_file():
        return RULES_FILE
    sample = {
        "_schema_version": 1,
        "_aciklama": (
            "replacements: LLM'nin sik yazdigi yanlis -> dogru (tam kelime). "
            "prompt_hints: sadece LLM prompt'una eklenir, otomatik degismez."
        ),
        "replacements": {
            "Sumerler": "Sümerler",
            "Babil Imparatorlugu": "Babil İmparatorluğu",
            "yanlız": "yalnız",
            "birşey": "bir şey",
        },
        "prompt_hints": [
            "Tarih nişinde yer adları: Mezopotamya, Babil, Ur, Uruk — Türkçe karakterli yaz",
            "Kişi adlarında Türkçeleştirme yapma; bilinen Türkçe yazımı kullan (Tutankamon, Kleopatra)",
        ],
    }
    RULES_FILE.write_text(
        json.dumps(sample, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _all_word_fixes.cache_clear()
    return RULES_FILE


def reload_rules() -> None:
    _all_word_fixes.cache_clear()


def _should_skip_deascii_token(token: str) -> bool:
    """Zaten TR harfli veya bilinen yanlis-pozitif kokler — dokunma."""
    if _HAS_TR_LETTER.search(token):
        return True
    base = re.split(r"['\u2018\u2019´`ʼ]", token, maxsplit=1)[0]
    low = base.casefold()
    if low in _DEASCII_BLOCK_EXACT or token.casefold() in _DEASCII_BLOCK_EXACT:
        return True
    return any(low.startswith(p) for p in _DEASCII_BLOCK_PREFIXES)


# Kelime listesi yoksa: gercek Turkce senaryolarda kelimelerin ~%35-60'i TR harfi
# icerir; ASCII yazilmis metinde ~0.
_ALREADY_TURKISH_TOKEN_RATIO = 0.15
# ASCII hali de gecerli kelimeyse (ise/işe, sakin/sakın) yalnizca TR hali bu kat
# daha yayginsa cevir (olmus/olmuş ~120x, guzel/güzel ~450x).
_ASCII_FORM_FREQ_RATIO = 20
_APOSTROPHE_RE = re.compile(r"['\u2018\u2019´`ʼ]")


@lru_cache(maxsize=1)
def _word_freq() -> dict[str, int]:
    table: dict[str, int] = {}
    try:
        with WORD_FREQ_FILE.open(encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) == 2 and parts[1].isdigit():
                    table[parts[0]] = int(parts[1])
    except OSError:
        return {}
    return table


def _word_count(word: str, table: dict[str, int]) -> int:
    base = _APOSTROPHE_RE.split(word, maxsplit=1)[0]
    if not base:
        return 0
    # ASCII "I" hem İ hem I olabilir (Istanbul / Isik)
    forms = {
        base.replace("İ", "i").replace("I", "ı").lower(),
        base.replace("İ", "i").replace("I", "i").lower(),
    }
    return max(table.get(f, 0) for f in forms)


def _is_sentence_start(text: str, pos: int) -> bool:
    before = text[:pos].rstrip(" \t\"'«“‘(-—–")
    return not before or before[-1] in ".!?:\n…"


def _pick_turkish_form(token: str, candidates: list[str], table: dict[str, int]) -> str:
    """ASCII kelime yerine TR karakterli adayi yalnizca kelime listesi destekliyorsa sec."""
    best, best_n = token, 0
    for cand in candidates:
        if not cand or cand == token or len(cand) != len(token):
            continue
        n = _word_count(cand, table)
        if n > best_n:
            best, best_n = cand, n
    if best_n == 0:
        return token
    ascii_n = _word_count(token, table)
    if ascii_n and best_n < ascii_n * _ASCII_FORM_FREQ_RATIO:
        return token
    return best


def apply_deasciify(text: str) -> str:
    """ASCII yazilmis Turkce kelimeleri dogru karakterlere cevirir (homograf korumali).

    Kelime listesiyle (resource/lang/tr_wordfreq.txt) karisik metinlerde de calisir:
    "Sinirlari"→"Sınırları" duzelir; ASCII hali de gecerli olan "ise", "sakin", "Mali"
    korunur. Tek kelimelik Deasciifier baglamsiz tahmin eder (ise→işe, olmus→ölmüş);
    once tam metin (baglamli) sonucu denenir.
    """
    raw = text or ""
    if not raw.strip():
        return raw
    tokens = list(_DEASCII_TOKEN_RE.finditer(raw))
    if not tokens:
        return raw
    table = _word_freq()
    if not table:
        tr_tokens = sum(1 for m in tokens if _HAS_TR_LETTER.search(m.group(0)))
        if tr_tokens / len(tokens) >= _ALREADY_TURKISH_TOKEN_RATIO:
            return raw
    try:
        from turkish.deasciifier import Deasciifier

        fixed = Deasciifier(raw).convert_to_turkish()
    except Exception:
        return raw
    if not fixed or len(fixed) != len(raw):
        if not table:
            return raw
        fixed = raw
    # Baslik (Title Case) degilse cumle ortasi kisa buyuk harfli kelime ozel isimdir (Utu, Enki)
    title_case = sum(1 for m in tokens if m.group(0)[:1].isupper()) >= len(tokens) * 0.6
    proper = (
        set()
        if title_case
        else {
            m.group(0)
            for m in tokens
            if m.group(0)[:1].isupper() and len(m.group(0)) <= 4 and not _is_sentence_start(raw, m.start())
        }
    )
    chars = list(raw)
    for m in tokens:
        tok = m.group(0)
        if _should_skip_deascii_token(tok):
            continue
        start, end = m.span()
        if not table:
            chars[start:end] = fixed[start:end]
            continue
        if tok in proper:
            continue
        context_form = fixed[start:end]
        new = _pick_turkish_form(tok, [context_form], table)
        if new == tok and _word_count(tok, table) == 0:
            try:
                new = _pick_turkish_form(tok, [Deasciifier(tok).convert_to_turkish()], table)
            except Exception:
                new = tok
        chars[start:end] = new
    return "".join(chars)


def apply_spelling_rules(text: str) -> str:
    """Sozluk tabanli yazim duzeltmeleri (yerlesik + data/turkish_imla_rules.json)."""
    out = text or ""
    if not out.strip():
        return out
    ensure_rules_file()
    for pattern, replacement in _all_word_fixes():
        out = pattern.sub(replacement, out)
    return out


def apply_turkish_imla(text: str, *, deasciify: bool = True) -> str:
    """Tam imla hatti: deasciify + sozluk + dilbilgisi duzeltmeleri."""
    out = (text or "").strip()
    if not out:
        return out
    if deasciify:
        out = apply_deasciify(out)
    out = apply_spelling_rules(out)
    out = apply_grammar_fixes(out)
    return out


def imla_prompt_block(*, max_hints: int = 20) -> str:
    """LLM system/editor prompt'una eklenecek imla blogu."""
    ensure_rules_file()
    lines = ["YAZIM VE İMLA (zorunlu):"]
    lines.extend(f"- {rule}" for rule in _STATIC_PROMPT_RULES)
    user_hints = load_user_prompt_hints()[:max_hints]
    if user_hints:
        lines.append("- Kullanici / proje kurallari:")
        lines.extend(f"  · {h}" for h in user_hints)
    user_rep = _load_user_replacements_raw()
    if user_rep:
        examples = list(user_rep.items())[:12]
        lines.append("- Sik duzeltilen kelimeler (ornek):")
        for wrong, right in examples:
            lines.append(f"  · «{wrong}» değil «{right}»")
    return "\n".join(lines)
