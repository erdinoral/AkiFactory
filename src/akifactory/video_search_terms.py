"""Stok video arama terimleri — konu odaklı anchor + ayni sahne yedekleri."""

from __future__ import annotations

import json
import re
from typing import Callable

from loguru import logger

_MAX_RETRIES = 5
_SCRIPT_EXCERPT = 900

_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "about",
        "video",
        "story",
        "hikaye",
        "ve",
        "bir",
        "icin",
        "ile",
        "uzerine",
        "nedir",
        "nasıl",
        "nasil",
        "what",
        "how",
        "why",
        "lost",
        "city",
        "of",
    }
)

# Tek basina / tamamen doga B-roll — konu izin vermedikce engelle
_NATURE_BLOCK = frozenset(
    {
        "mountain",
        "mountains",
        "hill",
        "hills",
        "landscape",
        "desert",
        "sand",
        "dunes",
        "sky",
        "clouds",
        "ocean",
        "sea",
        "forest",
        "jungle",
        "nature",
        "drone",
        "timelapse",
        "sunset",
        "sunrise",
        "travel",
        "adventure",
        "background",
        "cinematic",
        "abstract",
        "texture",
        "ice",
        "glacier",
        "snow",
        "lake",
        "river",
        "waterfall",
        "dağ",
        "dag",
        "tepe",
        "manzara",
        "col",
        "colde",
    }
)

# Konu disi flora/fauna — kum col konusuna cicek/bocek sokma
_BIOTA_BLOCK = frozenset(
    {
        "flower",
        "flowers",
        "bloom",
        "blooms",
        "petal",
        "petals",
        "garden",
        "gardens",
        "butterfly",
        "butterflies",
        "insect",
        "insects",
        "bee",
        "bees",
        "bird",
        "birds",
        "wildlife",
        "animal",
        "animals",
        "puppy",
        "cat",
        "dog",
        "rose",
        "roses",
        "meadow",
        "floral",
        "orchid",
        "tulip",
    }
)

# "ancient/ruins" tek basina eslesme sayilmasin
_GENERIC_FILLER = frozenset(
    {
        "ancient",
        "historical",
        "history",
        "old",
        "mystery",
        "mysterious",
        "ruins",
        "archaeology",
        "archaeological",
        "artifact",
        "museum",
        "document",
        "antique",
        "medieval",
        "archive",
        "relic",
        "shadow",
        "fog",
        "mist",
        "torch",
        "chamber",
        "close",
        "up",
        "aerial",
        "site",
        "walk",
        "detail",
        "civilization",
        "civilisation",
        "temple",
        "stone",
        "brick",
        "excavation",
        "urban",
        "city",
        "lost",
    }
)

# Ayirt edici yer/kultur isimleri — ortak kelime (pyramid/temple) YOK
_CIV_MARKERS: dict[str, frozenset[str]] = {
    "americas": frozenset(
        {
            "maya",
            "mayan",
            "inca",
            "aztec",
            "aztek",
            "machu",
            "picchu",
            "chichen",
            "itza",
            "mesoamerican",
            "yucatan",
        }
    ),
    "mesopotamia": frozenset(
        {
            "sumer",
            "sumerian",
            "babylon",
            "babylonian",
            "mesopotamia",
            "mesopotamian",
            "ziggurat",
            "cuneiform",
            "uruk",
            "assyrian",
        }
    ),
    "egypt": frozenset(
        {
            "egypt",
            "egyptian",
            "giza",
            "sphinx",
            "pharaoh",
            "nile",
        }
    ),
    "indus": frozenset({"mohenjo", "harappa", "harappan", "indus"}),
    "anatolia": frozenset(
        {
            "hittite",
            "hattusa",
            "gobekli",
            "catalhoyuk",
            "ephesus",
            "cappadocia",
            "derinkuyu",
            "anatolia",
            "anatolian",
        }
    ),
    "amazon": frozenset({"amazon", "amazonian", "fawcett"}),
    "polar": frozenset({"antarctica", "antarctic", "arctic"}),
    "geothermal": frozenset({"darvaza", "turkmenistan", "karakum"}),
    "pink_lake": frozenset({"hillier"}),
    "neolithic": frozenset({"skara", "brae", "orkney"}),
    "baltic": frozenset({"baltic"}),
}

# Domain → izin verilen doga kelimeleri (NATURE_BLOCK istisnasi)
_DOMAIN_NATURE_ALLOW: dict[str, frozenset[str]] = {
    "maritime": frozenset({"ocean", "sea", "wave", "waves", "storm", "underwater"}),
    "baltic": frozenset({"ocean", "sea", "wave", "waves", "underwater", "storm"}),
    "polar": frozenset({"ice", "glacier", "snow", "waterfall", "mountain"}),
    "geothermal": frozenset({"desert", "sand", "dunes"}),
    "pink_lake": frozenset({"lake", "sand", "dunes"}),
    "amazon": frozenset({"jungle", "forest", "river"}),
    "americas": frozenset({"jungle", "forest"}),
    "cave": frozenset(),
    "neolithic": frozenset({"ocean", "sea"}),
}

_DOMAIN_VOCAB: dict[str, frozenset[str]] = {
    "map": frozenset(
        {
            "map",
            "maps",
            "chart",
            "charts",
            "cartography",
            "atlas",
            "parchment",
            "navigation",
            "geography",
            "globe",
            "harita",
        }
    ),
    "manuscript": frozenset(
        {
            "manuscript",
            "manuscripts",
            "book",
            "books",
            "codex",
            "parchment",
            "scroll",
            "library",
            "writing",
            "text",
            "voynich",
            "voynik",
            "kitap",
        }
    ),
    "egypt": frozenset(
        {
            "pyramid",
            "pyramids",
            "piramit",
            "sphinx",
            "temple",
            "ruins",
            "monument",
            "statue",
            "archaeology",
            "egypt",
            "egyptian",
            "giza",
            "pharaoh",
            "nile",
        }
    ),
    "maritime": frozenset(
        {
            "ship",
            "ships",
            "ocean",
            "sea",
            "triangle",
            "storm",
            "wave",
            "waves",
            "underwater",
            "wreck",
            "sonar",
            "submarine",
            "aviation",
            "airplane",
            "bermuda",
        }
    ),
    "baltic": frozenset(
        {
            "baltic",
            "sonar",
            "anomaly",
            "underwater",
            "wreck",
            "shipwreck",
            "ocean",
            "sea",
            "scan",
            "seafloor",
            "submarine",
            "radar",
        }
    ),
    "geothermal": frozenset(
        {
            "darvaza",
            "crater",
            "gas",
            "fire",
            "flame",
            "flames",
            "burning",
            "desert",
            "sand",
            "dunes",
            "turkmenistan",
            "karakum",
            "doorway",
            "hell",
        }
    ),
    "polar": frozenset(
        {
            "antarctica",
            "antarctic",
            "glacier",
            "ice",
            "snow",
            "blood",
            "falls",
            "waterfall",
            "frozen",
            "taylor",
            "mcmurdo",
        }
    ),
    "pink_lake": frozenset(
        {
            "hillier",
            "pink",
            "lake",
            "salt",
            "saline",
            "australia",
            "australian",
            "lagoon",
            "algae",
            "shore",
        }
    ),
    "amazon": frozenset(
        {
            "amazon",
            "amazonian",
            "jungle",
            "rainforest",
            "river",
            "expedition",
            "canopy",
            "fawcett",
            "brazil",
            "explorer",
            "trail",
        }
    ),
    "neolithic": frozenset(
        {
            "skara",
            "brae",
            "orkney",
            "neolithic",
            "stone",
            "village",
            "prehistoric",
            "scotland",
            "settlement",
            "coastal",
        }
    ),
    "historical": frozenset(
        {
            "ancient",
            "historical",
            "history",
            "medieval",
            "antique",
            "old",
            "archive",
            "museum",
            "document",
            "ruins",
            "archaeology",
            "artifact",
            "mystery",
        }
    ),
    "mesopotamia": frozenset(
        {
            "sumer",
            "sumerian",
            "mesopotamia",
            "mesopotamian",
            "babylon",
            "babylonian",
            "ziggurat",
            "uruk",
            "assyrian",
            "cuneiform",
            "tablet",
            "clay",
            "iraq",
            "tigris",
            "euphrates",
        }
    ),
    "indus": frozenset(
        {
            "indus",
            "mohenjo",
            "daro",
            "harappa",
            "harappan",
            "pakistan",
            "sindh",
            "brick",
            "drainage",
            "urban",
            "civilization",
            "archaeology",
            "ruins",
        }
    ),
    "cave": frozenset(
        {
            "cave",
            "caves",
            "cavern",
            "underground",
            "tunnel",
            "tunnels",
            "catacomb",
            "catacombs",
            "derinkuyu",
            "cappadocia",
            "torch",
            "chamber",
            "subterranean",
            "grotto",
        }
    ),
    "anatolia": frozenset(
        {
            "anatolia",
            "anatolian",
            "hittite",
            "hittites",
            "hattusa",
            "catalhoyuk",
            "gobekli",
            "tepe",
            "ephesus",
            "troy",
            "ruins",
            "temple",
            "archaeology",
        }
    ),
    "americas": frozenset(
        {
            "maya",
            "mayan",
            "inca",
            "aztec",
            "pyramid",
            "temple",
            "machu",
            "picchu",
            "chichen",
            "itza",
            "andes",
            "jungle",
            "ruins",
            "stone",
            "mesoamerican",
        }
    ),
    "mystery": frozenset(
        {
            "mystery",
            "mysterious",
            "ruins",
            "artifact",
            "torch",
            "fog",
            "mist",
            "chamber",
            "ancient",
            "archaeology",
            "museum",
            "relic",
            "shadow",
        }
    ),
}

_DOMAIN_HINTS: list[tuple[str, tuple[str, ...]]] = [
    (
        "baltic",
        (
            "baltık",
            "baltik",
            "baltic",
            "baltic sea",
            "baltic anomaly",
            "deniz anomal",
        ),
    ),
    (
        "geothermal",
        (
            "darvaza",
            "cehennem kapı",
            "cehennem kapi",
            "door to hell",
            "gas crater",
            "karakum",
            "türkmenistan",
            "turkmenistan",
            "derveze",
        ),
    ),
    (
        "polar",
        (
            "blood falls",
            "kan şelale",
            "kan selale",
            "antarktika",
            "antarctica",
            "antarctic",
            "taylor glacier",
            "mcmurdo",
        ),
    ),
    (
        "pink_lake",
        (
            "hillier",
            "pembe göl",
            "pembe gol",
            "pink lake",
            "pink lagoon",
            "lake hillier",
        ),
    ),
    (
        "amazon",
        (
            "lost city of z",
            "z şehri",
            "z sehri",
            "fawcett",
            "amazon",
            "amazon orman",
            "rainforest expedition",
        ),
    ),
    (
        "neolithic",
        (
            "skara brae",
            "skara",
            "orkney",
            "neolitik",
            "neolithic",
            "stone age village",
        ),
    ),
    ("map", ("map", "harita", "chart", "cartograph", "piri reis", "atlas", "navigation")),
    (
        "manuscript",
        (
            "manuscript",
            "voynich",
            "voynik",
            "codex",
            "kitap",
            "book",
            "el yaz",
            "çivi",
            "civi",
            "tablet",
        ),
    ),
    (
        "egypt",
        (
            "pyramid",
            "piramit",
            "giza",
            "sphinx",
            "mısır",
            "misir",
            "egypt",
            "firavun",
            "pharaoh",
            "nile",
        ),
    ),
    ("maritime", ("bermuda", "triangle", "shipwreck", "deniz", "okyanus", "gemi", "batık", "batik")),
    (
        "indus",
        (
            "mohenjo",
            "harappa",
            "harappan",
            "indus",
            "hindu nehir",
            "indus valley",
            "sindh",
            "mohenjodaro",
        ),
    ),
    (
        "cave",
        (
            "derinkuyu",
            "yeraltı",
            "yeralti",
            "mağara",
            "magara",
            "cave city",
            "underground city",
            "cappadocia",
            "kapadokya",
            "catacomb",
            "katakomb",
        ),
    ),
    (
        "anatolia",
        (
            "hitit",
            "hittite",
            "hattusa",
            "hattuşa",
            "çatalhöyük",
            "catalhoyuk",
            "göbekli",
            "gobekli",
            "efes",
            "ephesus",
            "troya",
            "troy",
            "anadolu",
            "anatolia",
        ),
    ),
    (
        "americas",
        (
            "maya",
            "inca",
            "aztec",
            "aztek",
            "machu",
            "picchu",
            "chichen",
            "itza",
            "mesoamerican",
            "yucatan",
        ),
    ),
    (
        "mesopotamia",
        (
            "sümer",
            "sumer",
            "sumere",
            "mezopotam",
            "mesopotam",
            "babil",
            "babylon",
            "uruk",
            "enlil",
            "marduk",
            "enki",
            "assur",
            "asur",
            "fırat",
            "firat",
            "dicle",
            "tigris",
            "euphrates",
        ),
    ),
    (
        "mystery",
        (
            "gizem",
            "mystery",
            "kayip",
            "kayıp",
            "esrar",
            "bilinmeyen",
            "unsolved",
        ),
    ),
]

_ANCHOR_OVERRIDES: list[tuple[tuple[str, ...], str]] = [
    (("baltık", "baltik", "baltic sea", "baltic anomaly", "deniz anomal"), "Baltic Sea underwater anomaly"),
    (("darvaza", "cehennem kapı", "cehennem kapi", "door to hell", "derveze"), "Darvaza gas crater fire"),
    (("blood falls", "kan şelale", "kan selale", "taylor glacier"), "Blood Falls Antarctica glacier"),
    (("hillier", "pembe göl", "pembe gol", "pink lake", "lake hillier"), "Lake Hillier pink lake Australia"),
    (("lost city of z", "z şehri", "z sehri", "fawcett"), "Amazon rainforest lost city expedition"),
    (("skara brae", "skara", "orkney"), "Skara Brae Neolithic village Orkney"),
    (("sümer", "sumer", "sumere", "uruk", "enlil", "enki"), "ancient Sumerian civilization"),
    (("mezopotam", "mesopotam", "fırat", "firat", "dicle", "euphrates", "tigris"), "ancient Mesopotamia"),
    (("babil", "babylon", "marduk", "nebuchadnezzar"), "ancient Babylon"),
    (("mısır", "misir", "giza", "firavun", "pharaoh", "egypt"), "ancient Egypt pyramids"),
    (("mohenjo", "harappa", "harappan", "indus valley", "hindu nehir"), "Indus Valley civilization Mohenjo-Daro"),
    (("derinkuyu", "yeraltı şehir", "yeralti sehir", "underground city", "kapadokya", "cappadocia"), "Derinkuyu underground city Cappadocia"),
    (("hitit", "hittite", "hattusa", "hattuşa"), "ancient Hittite Anatolia ruins"),
    (("göbekli", "gobekli", "çatalhöyük", "catalhoyuk"), "Gobekli Tepe ancient temple"),
    (("maya", "chichen", "itza"), "ancient Maya temple ruins"),
    (("inca", "machu", "picchu"), "Machu Picchu Inca ruins"),
    (("piri reis",), "Piri Reis map"),
    (("voynich", "voynik"), "Voynich manuscript"),
    (("bermuda",), "Bermuda Triangle ocean storm"),
]

_DOMAIN_FALLBACK: dict[str, tuple[str, ...]] = {
    "baltic": (
        "Baltic Sea underwater wreck",
        "sonar seafloor scan animation",
        "underwater shipwreck dark water",
        "submarine ocean depths",
        "stormy northern sea aerial",
    ),
    "geothermal": (
        "burning gas crater desert night",
        "desert fire pit aerial",
        "Turkmenistan desert sand dunes",
        "flames rising from crater",
        "gas flare desert night",
    ),
    "polar": (
        "Antarctica glacier ice wall",
        "red mineral waterfall ice",
        "frozen waterfall glacier close up",
        "Antarctic ice cave blue",
        "glacier meltwater stream",
    ),
    "pink_lake": (
        "pink salt lake aerial Australia",
        "bright pink lagoon shoreline",
        "salt flat pink water drone",
        "saline pink lake close up",
        "Australian coastal salt lake",
    ),
    "amazon": (
        "Amazon rainforest river boat",
        "dense jungle canopy aerial",
        "Amazon expedition trail mist",
        "tropical river through rainforest",
        "jungle ruins overgrown stone",
    ),
    "neolithic": (
        "Skara Brae stone houses",
        "Neolithic coastal village ruins",
        "Orkney prehistoric stone settlement",
        "ancient stone dwelling interior",
        "windswept coastal archaeological site",
    ),
    "map": ("old antique map", "ancient world map", "historical map parchment"),
    "manuscript": ("ancient cuneiform clay tablet", "old book manuscript", "medieval codex"),
    "egypt": ("ancient Egypt pyramids", "Giza pyramid complex aerial", "Sphinx desert ruins"),
    "maritime": ("ocean storm aerial", "ship at sea", "underwater shipwreck"),
    "mesopotamia": (
        "ancient Mesopotamia ruins",
        "Sumerian ziggurat",
        "cuneiform clay tablet",
        "ancient Babylon archaeological site",
    ),
    "indus": (
        "Mohenjo-Daro archaeological ruins",
        "Indus Valley brick city aerial",
        "Harappa ancient urban ruins",
    ),
    "cave": (
        "underground cave city tunnels",
        "Derinkuyu underground city",
        "torch lit cave chamber",
    ),
    "anatolia": (
        "ancient Anatolian ruins temple",
        "Hittite archaeological site",
        "Gobekli Tepe stone pillars",
    ),
    "americas": (
        "Maya temple pyramid jungle",
        "Machu Picchu stone ruins",
        "ancient Mesoamerican pyramid",
    ),
    "mystery": (
        "mysterious foggy ruins walk",
        "torch lit stone chamber",
        "museum mystery artifact close up",
    ),
    "historical": (
        "archaeological excavation site",
        "museum historical artifact close up",
        "old parchment archive shelves",
    ),
}

# Ozel domain once — mystery/historical en sonda
_DOMAIN_PRIORITY: tuple[str, ...] = (
    "baltic",
    "geothermal",
    "polar",
    "pink_lake",
    "amazon",
    "neolithic",
    "mesopotamia",
    "indus",
    "cave",
    "anatolia",
    "americas",
    "egypt",
    "map",
    "manuscript",
    "maritime",
    "mystery",
    "historical",
)

_TURKEY_MODERN_MARKERS = (
    "turkish house",
    "turkey house",
    "istanbul",
    "ankara",
    "turkish home",
    "modern house turkey",
    "turk ev",
    "turkiye",
)

_VARIATION_SUFFIXES = (
    "aerial",
    "close up",
    "historical",
    "documentary",
    "wide shot",
)

_GENERIC_ANCHORS = frozenset(
    {
        "ancient archaeological ruins",
        "archaeological excavation site",
        "ancient ruins",
        "historical ruins",
        "mysterious ancient ruins",
    }
)


def _primary_domain(domains: set[str]) -> str:
    for d in _DOMAIN_PRIORITY:
        if d in domains:
            return d
    return "historical"


def build_terms_prompt(video_subject: str, video_script: str, amount: int) -> str:
    excerpt = (video_script or "").strip()[:_SCRIPT_EXCERPT]
    return f"""
# Role: Stock Footage Search Query Generator (Pexels / Pixabay)

## Goal
English-only queries for stock video/photo. Match the topic's **exact place, biome, and era**.
If exact footage may be rare, fall back to the **same visual family** — never a different civilization or random nature.

## Hard rules
1. **Stay on subject** — Baltic anomaly → underwater/sonar/northern sea. Darvaza → burning crater/desert fire. Pink lake → pink salt lake. Lost City of Z → Amazon jungle/river expedition. Blood Falls → Antarctic ice/glacier red water.
2. **Similar fallback only** — same geography/biome (desert→sand dunes+fire; polar→ice/glacier; jungle→rainforest river). NOT "close enough history".
3. **NEVER cross-contaminate civilizations** — do not add Maya/Inca/Egypt/Sumer/Machu Picchu unless the subject is about that place.
4. **NEVER inject unrelated biota** — no flowers, butterflies, insects, gardens, wildlife unless the subject is about them.
5. **NEVER** modern Turkey homes/Istanbul unless subject is modern Turkey.
6. English only. JSON only. No Turkish query words.

## Strategy
1. **anchor** — precise English subject (place + distinctive feature).
2. **primary_terms** — must keep anchor place/feature words.
3. **related_terms** — same biome/scene angles (aerial, close-up, walk-through) — still same topic family.

## Examples
Baltic Sea Anomaly:
{{"anchor":"Baltic Sea underwater anomaly","primary_terms":["Baltic Sea seafloor sonar","Baltic underwater wreck","northern sea underwater scan"],"related_terms":["underwater shipwreck dark water","submarine ocean depths","stormy northern sea aerial"]}}

Darvaza / Door to Hell:
{{"anchor":"Darvaza gas crater fire","primary_terms":["Darvaza burning crater","desert gas crater flames","Turkmenistan fire pit night"],"related_terms":["burning crater desert aerial","gas flare desert night","sand dunes around fire crater"]}}

Lost City of Z:
{{"anchor":"Amazon rainforest lost city expedition","primary_terms":["Amazon jungle expedition trail","Amazon river boat rainforest","overgrown jungle ruins stone"],"related_terms":["dense rainforest canopy aerial","misty jungle path explorer","tropical river through trees"]}}

Lake Hillier:
{{"anchor":"Lake Hillier pink lake Australia","primary_terms":["Lake Hillier pink water aerial","pink salt lake Australia","bright pink lagoon shore"],"related_terms":["saline pink lake drone","pink water close up shoreline","Australian coastal salt lake"]}}

## Forbidden examples
- Subject "Baltic Sea Anomaly" → "Maya temple", "Machu Picchu", "flower garden"  ❌
- Subject "Darvaza crater" → "butterfly meadow", "Egyptian pyramid"  ❌
- Subject "Amazon Lost City of Z" → "Maya Chichen Itza" (different culture)  ❌

## Output (JSON only)
{{
  "anchor": "...",
  "primary_terms": ["...", "...", "..."],
  "related_terms": ["...", "...", "..."]
}}

## Video subject
{video_subject.strip()}

## Script excerpt
{excerpt or "(no script yet)"}

Provide ~{amount} unique English queries total. Return only JSON.
""".strip()


def _has_turkish_chars(text: str) -> bool:
    return bool(re.search(r"[ğüşıöçĞÜŞİÖÇ]", text or ""))


def _topic_about_turkey(text: str) -> bool:
    blob = (text or "").lower()
    return any(
        m in blob
        for m in (
            "türkiye",
            "turkiye",
            "turkey ",
            "istanbul",
            "ankara",
            "osmanlı",
            "osmanli",
            "atatürk",
            "ataturk",
        )
    )


def _english_anchor_from_subject(video_subject: str, video_script: str = "") -> str:
    blob = f"{video_subject} {video_script}".lower()
    for hints, anchor in _ANCHOR_OVERRIDES:
        if any(h in blob for h in hints):
            return anchor
    subj = (video_subject or "").strip()
    if subj and not _has_turkish_chars(subj):
        return subj
    domains = _infer_domains(blob)
    domain = _primary_domain(domains)
    fb = _DOMAIN_FALLBACK.get(domain) or _DOMAIN_FALLBACK["historical"]
    if fb:
        return fb[0]
    return "archaeological excavation site"


def _is_english_stock_term(term: str) -> bool:
    t = (term or "").strip()
    if len(t) < 2:
        return False
    if _has_turkish_chars(t):
        return False
    return bool(re.search(r"[a-zA-Z]", t))


def _tokenize(text: str) -> list[str]:
    return [
        w
        for w in re.findall(r"[\w\u00c0-\u024f]+", (text or "").lower())
        if len(w) >= 2 and w not in _STOPWORDS
    ]


def _infer_domains(text: str) -> set[str]:
    blob = (text or "").lower()
    found: set[str] = set()
    for domain, hints in _DOMAIN_HINTS:
        if any(h in blob for h in hints):
            found.add(domain)
    # "deniz" tek basina maritime — ama baltic zaten yakalandiysa ekstra
    if not found:
        found.add("historical")
    # generic mystery+historical overlap: keep specific domains only when present
    if found - {"mystery", "historical"}:
        found.discard("mystery")
    return found


def _domain_vocab(domains: set[str]) -> set[str]:
    vocab: set[str] = set()
    for d in domains:
        vocab |= set(_DOMAIN_VOCAB.get(d, ()))
    return vocab


def _domain_specific_vocab(domains: set[str]) -> set[str]:
    """Generic filler cikarilmis, ayirt edici kelimeler."""
    return {w for w in _domain_vocab(domains) if w not in _GENERIC_FILLER}


def _allowed_nature_words(domains: set[str]) -> set[str]:
    allowed: set[str] = set()
    for d in domains:
        allowed |= set(_DOMAIN_NATURE_ALLOW.get(d, ()))
    return allowed


def _is_nature_only(term: str, domains: set[str] | None = None) -> bool:
    """Tum kelimeler genel doga B-roll ve konuya ozel isim yok."""
    words = set(_tokenize(term))
    if not words:
        return True
    domains = domains or set()
    allow = _allowed_nature_words(domains)
    specific = _domain_specific_vocab(domains)
    if words & specific:
        return False
    if words & allow:
        # orn. "desert sand dunes" geothermal icin OK — doga-only sayma
        return False
    return all(w in _NATURE_BLOCK for w in words)


def _has_blocked_biota(term: str) -> bool:
    words = set(_tokenize(term))
    return bool(words & _BIOTA_BLOCK)


def _has_foreign_civ(term: str, domains: set[str]) -> bool:
    words = set(_tokenize(term))
    for civ, markers in _CIV_MARKERS.items():
        if civ in domains:
            continue
        if words & markers:
            return True
    return False


def _is_blocked_term(term: str, subject: str, script: str, domains: set[str]) -> bool:
    tl = term.lower()
    if not _topic_about_turkey(f"{subject} {script}"):
        if any(m in tl for m in _TURKEY_MODERN_MARKERS):
            return True
        if "turkish" in tl or " turkey" in tl:
            return True
    if _has_blocked_biota(term):
        return True
    if _has_foreign_civ(term, domains):
        return True
    if _is_nature_only(term, domains):
        return True
    return False


def _term_matches_anchor(term: str, anchor: str) -> bool:
    anchor_l = (anchor or "").lower()
    term_l = (term or "").lower()
    if not anchor_l or not term_l:
        return False
    if term_l in anchor_l or anchor_l in term_l:
        return True
    for tok in _tokenize(anchor):
        if len(tok) >= 4 and tok not in _GENERIC_FILLER and tok in term_l:
            return True
    return False


def _is_valid_related(term: str, domains: set[str], anchor: str = "") -> bool:
    if _has_blocked_biota(term):
        return False
    if _has_foreign_civ(term, domains):
        return False
    if _is_nature_only(term, domains):
        words = set(_tokenize(term))
        allow = _allowed_nature_words(domains)
        specific = _domain_specific_vocab(domains)
        if not (words & (allow | specific)):
            return False
    words = set(_tokenize(term))
    specific = _domain_specific_vocab(domains)
    if words & specific:
        return True
    if anchor and _term_matches_anchor(term, anchor):
        return True
    # Genel "ancient ruins" tek basina yetmez
    return False


def _normalize_term(term: str) -> str:
    return re.sub(r"\s+", " ", (term or "").strip())


def refine_search_terms(
    video_subject: str,
    raw_primary: list[str],
    *,
    anchor: str | None = None,
    related: list[str] | None = None,
    amount: int = 5,
    video_script: str = "",
) -> list[str]:
    """Anchor + primary + ayni-sahne related; konu disi terimleri at."""
    subject = (video_subject or "").strip()
    blob = f"{subject} {video_script}"
    domains_probe = _infer_domains(blob)
    primary = _primary_domain(domains_probe)
    raw_anchor = _normalize_term(anchor or "")
    if not raw_anchor or _has_turkish_chars(raw_anchor) or not _is_english_stock_term(raw_anchor):
        anchor_en = _english_anchor_from_subject(subject, video_script)
    else:
        anchor_en = raw_anchor
        # LLM yanlis medeniyet / genel "ruins" anchori verdiyse konu anchoruna cevir
        if _has_foreign_civ(anchor_en, domains_probe):
            anchor_en = _english_anchor_from_subject(subject, video_script)
        elif (
            primary not in {"historical", "mystery"}
            and anchor_en.lower() in _GENERIC_ANCHORS
        ):
            anchor_en = _english_anchor_from_subject(subject, video_script)

    domains = _infer_domains(f"{subject} {anchor_en} {video_script}")
    # Anchor domainini de ekle
    domains |= _infer_domains(anchor_en)

    out: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> bool:
        t = _normalize_term(term)
        if len(t) < 2 or not _is_english_stock_term(t):
            return False
        if _is_blocked_term(t, subject, video_script, domains):
            return False
        key = t.lower()
        if key in seen:
            return False
        seen.add(key)
        out.append(t)
        return True

    if anchor_en:
        add(anchor_en)

    for raw in raw_primary:
        t = _normalize_term(str(raw or ""))
        if not t or t.lower() == anchor_en.lower():
            continue
        if not _is_english_stock_term(t):
            continue
        if _is_blocked_term(t, subject, video_script, domains):
            continue
        if anchor_en and _term_matches_anchor(t, anchor_en):
            add(t)
            continue
        if _is_valid_related(t, domains, anchor_en):
            add(t)
        # Eski davranis: "anchor + unrelated" birlestirme YOK — konu kirlenmesi

    for raw in related or []:
        t = _normalize_term(str(raw or ""))
        if not t or not _is_english_stock_term(t):
            continue
        if _is_blocked_term(t, subject, video_script, domains):
            continue
        if _is_valid_related(t, domains, anchor_en):
            add(t)

    domain_key = _primary_domain(domains)
    if len(out) < amount:
        for fb in _DOMAIN_FALLBACK.get(domain_key, _DOMAIN_FALLBACK["historical"]):
            add(fb)
            if len(out) >= amount:
                break

    vi = 0
    while len(out) < amount and anchor_en and vi < len(_VARIATION_SUFFIXES):
        add(f"{anchor_en} {_VARIATION_SUFFIXES[vi]}")
        vi += 1

    return out[:amount]


def parse_terms_response(response: str) -> tuple[str, list[str], list[str]]:
    """anchor, primary_terms, related_terms."""
    text = (response or "").strip()
    if not text or text.startswith("Error:"):
        return "", [], []

    data: object | None = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                pass
        if data is None:
            match = re.search(r"\[[\s\S]*\]", text)
            if match:
                try:
                    arr = json.loads(match.group())
                    if isinstance(arr, list):
                        terms = [str(x).strip() for x in arr if str(x).strip()]
                        return (terms[0] if terms else "", terms, [])
                except json.JSONDecodeError:
                    pass

    if isinstance(data, dict):
        anchor = str(data.get("anchor") or data.get("subject") or "").strip()

        def _as_list(key: str) -> list[str]:
            raw = data.get(key)
            if not isinstance(raw, list):
                return []
            return [str(x).strip() for x in raw if str(x).strip()]

        primary = _as_list("primary_terms")
        related = _as_list("related_terms")

        legacy = data.get("terms") or data.get("search_terms") or data.get("queries")
        if isinstance(legacy, list) and not primary:
            for item in legacy:
                if isinstance(item, dict):
                    q = str(item.get("q") or item.get("query") or "").strip()
                    tier = str(item.get("tier") or "primary").lower()
                    if not q:
                        continue
                    if tier.startswith("rel"):
                        related.append(q)
                    else:
                        primary.append(q)
                else:
                    primary.append(str(item).strip())

        if primary and not anchor:
            anchor = primary[0]
        return anchor, primary, related

    if isinstance(data, list):
        terms = [str(x).strip() for x in data if str(x).strip()]
        return (terms[0] if terms else "", terms, [])

    return "", [], []


def fallback_search_terms(
    video_subject: str,
    video_script: str = "",
    amount: int = 7,
) -> list[str]:
    """LLM yokken domain/anchor yedegi — Ingilizce stok sorgulari."""
    subject = (video_subject or "").strip()
    script = video_script or ""
    domains = _infer_domains(f"{subject} {script}")
    domain_key = _primary_domain(domains)
    fb_related = list(_DOMAIN_FALLBACK.get(domain_key, _DOMAIN_FALLBACK["historical"]))
    anchor_en = _english_anchor_from_subject(subject, script)
    return refine_search_terms(
        subject,
        [],
        anchor=anchor_en,
        related=fb_related,
        amount=amount,
        video_script=script,
    )


def generate_search_terms(
    video_subject: str,
    video_script: str,
    amount: int = 7,
    *,
    generate_response: Callable[[str], str],
) -> list[str]:
    subject = (video_subject or "").strip()
    prompt = build_terms_prompt(subject, video_script or "", amount)

    for attempt in range(_MAX_RETRIES):
        try:
            response = generate_response(prompt)
            if response and "Error:" in response:
                logger.error(f"search terms LLM error: {response}")
                break
            anchor, primary, related = parse_terms_response(response)
            refined = refine_search_terms(
                subject,
                primary,
                anchor=anchor or None,
                related=related,
                amount=amount,
                video_script=video_script or "",
            )
            if refined:
                logger.success(
                    f"stock search terms (anchor={anchor or subject!r}): {refined}"
                )
                return refined
        except Exception as exc:
            logger.warning(f"search terms attempt {attempt + 1} failed: {exc}")

    refined = fallback_search_terms(subject, video_script or "", amount=amount)
    logger.warning(f"search terms fallback: {refined}")
    return refined
