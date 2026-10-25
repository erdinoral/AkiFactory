"""Arayuz Ingilizce sozlugunu gunceller: web/assets/i18n/en.json

index.html + app.js icindeki gorunen Turkce metinleri toplar, sozlukte olmayanlari
Ayarlar'da secili LLM ile (Ollama veya bulut) cevirir. Var olan ceviriler korunur.

    python scripts/build_ui_i18n.py            # eksikleri cevir
    python scripts/build_ui_i18n.py --check    # yalnizca eksik sayisini goster
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

WEB = ROOT / "web"
OUT = WEB / "assets" / "i18n" / "en.json"
ATTRS = ("placeholder", "title", "aria-label", "data-help", "alt")
SKIP_TAGS = {"script", "style", "code", "pre", "textarea"}
SEP_RE = re.compile(r" · | — | – | \| |: ")
BATCH = 60


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def wanted(s: str, *, strict: bool = False) -> bool:
    if len(s) < 2 or not re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]{2}", s):
        return False
    words = s.split()
    if all(re.fullmatch(r"[a-z0-9_-]+", w) for w in words) and any("-" in w for w in words):
        return False  # CSS sinif adlari
    if re.search(r"\b[a-z_]+\.[a-z_]+\b", s) and " " not in s.strip(" ?:"):
        return False  # o.file gibi kod parcasi
    if not strict and re.fullmatch(r"[A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü'’]{2,}[.…!?]*", s):
        return True  # gorunen tek kelime (Uretim, Galeri, hazir)
    if re.fullmatch(r"[\w.\-/:\\]+", s) and not re.search(r"[çğıöşüÇĞİÖŞÜ]", s) and " " not in s:
        # tek kelime: yalnizca bilinen Turkce kaliplari al
        return bool(re.search(r"(ler|lar|niz|siz|yor|ma|me|et|al|ac|sec|ekle|sil|kaydet|yukle|uret)$", s.lower()))
    return not re.fullmatch(r"[\w.\-/:]+\.(mp4|mp3|json|py|toml|png|txt|wav|pth|index)", s)


class _Html(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.out: set[str] = set()

    def handle_starttag(self, tag, attrs):
        if tag not in ("br", "input", "img", "meta", "link", "hr", "source", "wbr"):
            self.stack.append(tag)
        for k, v in attrs:
            if k in ATTRS and v:
                self.add(v)

    def handle_endtag(self, tag):
        while self.stack and self.stack.pop() != tag:
            pass

    def handle_data(self, data):
        if not any(t in SKIP_TAGS for t in self.stack):
            self.add(data)

    def add(self, raw: str, *, strict: bool = False) -> None:
        s = norm(raw)
        if wanted(s, strict=strict):
            self.out.add(s)
            parts = SEP_RE.split(s)
            if len(parts) > 1:
                self.out.update(p.strip() for p in parts if wanted(p.strip(), strict=strict))


def _placeholder_key(s: str) -> str | None:
    """`Bu niste ${n} konu` -> "Bu niste {0} konu" (i18n.js sablon eslestirmesi)."""
    s = re.sub(r"\$\{[^{}]*$", "", s)  # kapanmamis ic ice sablon kuyrugu
    slots = re.findall(r"\$\{[^}]*\}", s)
    if not slots or len(slots) > 9:
        return None
    counter = iter(range(len(slots)))
    out = norm(re.sub(r"\$\{[^}]*\}", lambda _m: "{%d}" % next(counter), s)).strip(" ,(")
    literal = re.sub(r"\{\d\}", "", out)
    if re.search(r"[{};=]|=>|\|\||&&", literal):
        return None
    if len(re.sub(r"[^A-Za-zÇĞİÖŞÜçğıöşü]", "", literal)) < 4:
        return None
    return out


def _unescape_js(s: str) -> str:
    return s.replace("\\'", "'").replace('\\"', '"').replace("\\n", " ").replace("\\`", "`")


def collect() -> list[str]:
    parser = _Html()
    parser.feed((WEB / "index.html").read_text(encoding="utf-8"))
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    for m in re.finditer(r'(["\'`])((?:\\.|(?!\1).){2,400}?)\1', js):
        s = _unescape_js(m.group(2))
        if re.match(r"^(/api|/assets|\.|#|\w+:/)", s):
            continue
        if "<" in s and ">" in s:
            parser.feed(re.sub(r"\$\{[^}]*\}", " ", s))
            continue
        segs = re.split(r"\$\{[^}]*\}", s)
        if len(segs) > 1:
            key = _placeholder_key(s)
            if key:
                parser.add(key)
        for seg in segs:
            seg = norm(seg)
            if re.search(r"[{};=]|=>|\|\||&&", seg):
                continue
            if len(segs) > 1:
                parser.add(seg.strip(" ,(—·:"))  # sablon metni: ${x} hazir
            elif " " in seg or re.search(r"[çğıöşüÇĞİÖŞÜ]", seg):
                parser.add(seg.strip(" ,(—·:"), strict=True)
    # `${p} hazir${...}` gibi ic ice sablonlar regex'e takilir: ${...} arasi kelimeler
    for m in re.finditer(r"\}([^`${}<>\"'=;]{3,80})\$\{", js):
        parser.add(m.group(1).strip(" ,(—·:"))
    for label in _api_labels():
        parser.add(label)
    for text in _settings_asset_texts():
        parser.add(text)
    for text in _backend_labels():
        parser.add(text)
    return sorted(parser.out)


def _backend_labels() -> list[str]:
    """API yanitlarinda gelen sabit Turkce basliklar (yayin paketi tavsiye konulari)."""
    try:
        from akifactory.content_studio import SHARE_TIP_CATEGORIES

        return list(SHARE_TIP_CATEGORIES)
    except Exception:
        return []


def _settings_asset_texts() -> list[str]:
    """Ayarlar > Dosyalar aciklamalari (backend metni, sunucu gerekmez)."""
    try:
        from akifactory import settings_assets

        data = settings_assets.scan_all()
    except Exception:
        return []
    out: list[str] = []
    for block in data.values():
        out.append(block.get("instructions") or "")
        out.extend(i.get("note") or "" for i in block.get("items") or [])
    return [t for t in out if t]


def _api_labels() -> list[str]:
    """Uygulama aciksa /api/config etiketleri (ses motoru, nis, platform...) — backend'den gelir."""
    import httpx

    for port in range(7860, 7866):
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/api/config", timeout=20.0)
            if r.status_code == 200 and isinstance(r.json(), dict):
                break
        except Exception:
            continue
    else:
        print("  (uygulama kapali — backend etiketleri atlandi)")
        return []
    out: list[str] = []

    def walk(v, key=""):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, k)
        elif isinstance(v, list):
            for x in v:
                walk(x, key)
        elif isinstance(v, str) and key in ("label", "name", "description", "hint", "note", "title") and len(v) < 200:
            out.append(v)

    walk(r.json())
    return out


def _prompt(batch: list[str]) -> str:
    return (
        "Translate these user interface strings of a desktop short-video studio app from Turkish to "
        "natural, concise English. The Turkish is often typed without diacritics (Uretim = Üretim).\n"
        "Rules: keep it short like UI text; keep product and model names unchanged (AkiFactory, Akiyom, "
        "Pexels, Pixabay, Ollama, Gemini, MiniMax, H3, Qwen, RVC, Edge TTS, Chatterbox, Whisper, WanGP, "
        "Fooocus, Telegram, NVIDIA, Pinokio, ffmpeg); keep emojis, arrows (→), symbols, "
        "numbers, file paths, punctuation and leading/trailing characters; keep placeholders like {0} "
        "and {1} exactly (they are filled in at runtime); 'nis' means content niche; 'dk' = min, 'sn' = s; "
        "'seslendirme' means voiceover; 'altyazi' means subtitles. If a string is already English or "
        "untranslatable, return it unchanged.\n"
        "Return ONLY a JSON object that maps every input string exactly to its English translation.\n\n"
        + json.dumps(batch, ensure_ascii=False, indent=0)
    )


async def _translate(batch: list[str]) -> dict[str, str]:
    from akifactory import ollama_util

    for _ in range(3):
        text = await ollama_util.chat(
            [{"role": "user", "content": _prompt(batch)}],
            think=False,
            options={"temperature": 0.1, "num_predict": 8192},
            timeout=240.0,
            clean_script=False,
            format_json=True,
        )
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
        try:
            data = json.loads(t[t.find("{") : t.rfind("}") + 1])
        except Exception:
            continue
        if isinstance(data, dict):
            return {
                k: str(v).strip()
                for k, v in data.items()
                if k in batch
                and isinstance(v, str)
                and v.strip()
                and sorted(re.findall(r"\{\d\}", k)) == sorted(re.findall(r"\{\d\}", v))
            }
    return {}


def main() -> int:
    strings = collect()
    current: dict[str, str] = {}
    if OUT.is_file():
        current = json.loads(OUT.read_text(encoding="utf-8"))
    missing = [s for s in strings if s not in current]
    print(f"metin: {len(strings)} · sozlukte: {len(strings) - len(missing)} · eksik: {len(missing)}")
    if "--check" in sys.argv or not missing:
        return 0
    for i in range(0, len(missing), BATCH):
        batch = missing[i : i + BATCH]
        got = asyncio.run(_translate(batch))
        current.update({k: v for k, v in got.items() if v != k})
        print(f"  {min(i + BATCH, len(missing))}/{len(missing)} · cevrildi: {len(got)}")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(dict(sorted(current.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
