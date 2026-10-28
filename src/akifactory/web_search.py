"""Konu/senaryo icin web kaynak ozetleri — video oncesi arastirma + editor dogrulama."""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)

_USER_AGENT = "AkiFactory/1.0 (fact-check; +https://github.com/local/akifactory)"
_MAX_SNIPPET = 520
_MAX_RESEARCH_SNIPPET = 960
_MAX_TOTAL_CHARS = 3200
_DDG_REGION = "wt-wt"


@dataclass
class WebSnippet:
    title: str
    body: str
    url: str
    source: str


def _clip(text: str, limit: int = _MAX_SNIPPET) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= limit:
        return t
    return t[: limit - 1].rstrip() + "…"


async def _wikipedia_page_extract(client: httpx.AsyncClient, title: str, *, lang: str) -> str:
    """Sayfa giris paragrafi — REST ozetinden genelde daha uzun."""
    api = f"https://{lang}.wikipedia.org/w/api.php"
    try:
        ex = await client.get(
            api,
            params={
                "action": "query",
                "prop": "extracts",
                "exintro": 1,
                "explaintext": 1,
                "titles": title,
                "format": "json",
                "redirects": 1,
                "utf8": 1,
            },
        )
        if ex.status_code != 200:
            return ""
        pages = (ex.json().get("query") or {}).get("pages") or {}
        for page in pages.values():
            body = (page.get("extract") or "").strip()
            if body:
                return _clip(body, _MAX_RESEARCH_SNIPPET)
    except Exception:
        pass
    return ""


async def _wikipedia_snippets(query: str, *, lang: str = "tr", limit: int = 3) -> list[WebSnippet]:
    out: list[WebSnippet] = []
    api = f"https://{lang}.wikipedia.org/w/api.php"
    headers = {"User-Agent": _USER_AGENT}
    try:
        async with httpx.AsyncClient(timeout=14.0, follow_redirects=True, headers=headers) as client:
            sr = await client.get(
                api,
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "format": "json",
                    "srlimit": max(1, min(limit, 5)),
                    "utf8": 1,
                },
            )
            if sr.status_code != 200:
                return out
            data = sr.json()
            hits = (data.get("query") or {}).get("search") or []
            for row in hits[:limit]:
                title = (row.get("title") or "").strip()
                if not title:
                    continue
                snippet = _clip(re.sub(r"<[^>]+>", "", row.get("snippet") or ""))
                summary_url = (
                    f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title, safe='')}"
                )
                body = snippet
                page_url = f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'), safe='')}"
                try:
                    sm = await client.get(summary_url)
                    if sm.status_code == 200:
                        sj = sm.json()
                        body = _clip(sj.get("extract") or body, _MAX_RESEARCH_SNIPPET)
                        page_url = sj.get("content_urls", {}).get("desktop", {}).get("page") or page_url
                except Exception:
                    pass
                lead = await _wikipedia_page_extract(client, title, lang=lang)
                if lead and len(lead) > len(body):
                    body = lead
                elif body:
                    body = _clip(body, _MAX_RESEARCH_SNIPPET)
                if body:
                    out.append(WebSnippet(title=title, body=body, url=page_url, source=f"Wikipedia ({lang})"))
    except Exception as exc:
        log.debug("wikipedia search failed: %s", exc)
    return out


def _ddg_text_sync(query: str, *, max_results: int = 4, region: str = _DDG_REGION) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for mod_name in ("ddgs", "duckduckgo_search"):
        try:
            mod = __import__(mod_name, fromlist=["DDGS"])
            ddgs_cls = getattr(mod, "DDGS")
            with ddgs_cls() as ddgs:
                rows = list(ddgs.text(query, max_results=max_results, region=region))
            if rows:
                return rows
        except Exception:
            continue
    return rows


async def _duckduckgo_snippets(query: str, *, limit: int = 4) -> list[WebSnippet]:
    out: list[WebSnippet] = []
    try:
        raw = await asyncio.to_thread(_ddg_text_sync, query, max_results=limit)
        for row in raw[:limit]:
            title = _clip((row.get("title") or "").strip(), 120)
            body = _clip(row.get("body") or row.get("snippet") or "", _MAX_SNIPPET)
            url = (row.get("href") or row.get("url") or "").strip()
            if title and body:
                out.append(WebSnippet(title=title, body=body, url=url, source="DuckDuckGo"))
    except Exception as exc:
        log.debug("ddg search failed: %s", exc)
    return out


def _dedupe_snippets(items: list[WebSnippet]) -> list[WebSnippet]:
    seen: set[str] = set()
    out: list[WebSnippet] = []
    for it in items:
        key = re.sub(r"\W+", "", (it.title + it.body[:80]).lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


_TR_EN_WIKI_SUBS: list[tuple[str, str]] = [
    (r"eski\s+taş\s+devri", "Stone Age"),
    (r"eski\s+tas\s+devri", "Stone Age"),
    (r"taş\s+devri", "Stone Age"),
    (r"tas\s+devri", "Stone Age"),
    (r"paleolitik", "Paleolithic"),
    (r"neolitik", "Neolithic"),
    (r"el\s+yazmas[ıi]", "manuscript"),
    (r"borular[ıi]", "pipes"),
    (r"adas[ıi]", "island"),
    (r"üçgen[ıi]?|ucgen[ıi]?", "triangle"),
    (r"piramit(?:ler)?(?:i)?", "pyramid"),
    (r"şehri|sehir(?:i)?", "city"),
    (r"olay[ıi]", "incident"),
    (r"gizem(?:i)?", "mystery"),
    (r"antik\s+", "ancient "),
    (r"efsane(?:si)?", "legend"),
]


_EN_NICHE_SUFFIX: dict[str, str] = {
    "tarih_gizem": "history mystery",
    "teknoloji": "technology",
    "uzay": "space",
    "tarihi_insanlar": "biography history",
    "tarihi_olaylar": "historical event",
    "savaslar": "military history",
    "yeme_icme": "food recipe",
    "oyun": "video game",
    "muzik": "music",
    "sanat": "art history",
    "seyahat": "travel tourism",
    "genel": "",
}


def _ascii_latin_variants(text: str) -> list[str]:
    """Gobeklitepe gibi ASCII yazim varyantlari."""
    folded = unicodedata.normalize("NFKD", (text or "").strip())
    ascii_only = "".join(c for c in folded if not unicodedata.combining(c))
    ascii_only = re.sub(r"\s+", " ", ascii_only).strip()
    if not ascii_only or ascii_only.lower() == text.strip().lower():
        return []
    return [ascii_only]


def _english_wiki_queries(topic: str) -> list[str]:
    """Turkce basliklardan Ingilizce arama cumleleri (heuristik)."""
    raw = (topic or "").strip()
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def add(q: str) -> None:
        q = re.sub(r"\s+", " ", q.strip())
        if len(q) < 2:
            return
        key = q.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(q)

    en = raw
    for pat, repl in _TR_EN_WIKI_SUBS:
        en = re.sub(pat, repl, en, flags=re.IGNORECASE)
    add(en)
    stripped = re.sub(
        r"\b(?:el|yazmasi|yazmas[ıi]|borular[ıi]|gizem(?:i)?|olay[ıi]|efsane(?:si)?)\b",
        "",
        raw,
        flags=re.IGNORECASE,
    )
    add(re.sub(r"\s+", " ", stripped).strip())
    latin_chunks = re.findall(r"[A-Za-z][A-Za-z0-9\s\-'.]{1,48}", raw)
    for chunk in latin_chunks:
        add(chunk.strip())
    for variant in _ascii_latin_variants(raw):
        add(variant)
    return out[:5]


def _atlas_extra_queries(topic: str) -> list[str]:
    try:
        from akifactory import atlas_topics as atlas_mod

        en = atlas_mod.english_title_for_topic(topic)
        return [en] if en else []
    except Exception:
        return []


def _is_weak_search_query(query: str) -> bool:
    """TR nis ekleri veya genel kelimeler alakasiz sonuc uretir."""
    q = re.sub(r"\s+", " ", (query or "").strip().lower())
    if not q:
        return True
    generic = {
        "tarih gizem",
        "tarih mystery",
        "tarih olay",
        "tarih biyografi",
        "savaş tarihi",
        "savas tarihi",
        "tarih",
        "gizem",
        "mystery",
        "teknoloji",
        "uzay",
        "müzik",
        "muzik",
    }
    if q in generic:
        return True
    latin = re.findall(r"[a-z]{3,}", q)
    tr_markers = re.findall(
        r"\b(?:tarih|gizem|olay|efsane|antik|boru|yazma|adas|sehir|üçgen|ucgen|teknoloji|uzay|müzik|muzik)\b",
        q,
    )
    return bool(tr_markers) and len(latin) <= 1


_PROPER_CASE_SUFFIX_RE = re.compile(r"(?:nın|nin|nun|nün|dan|den|tan|ten|ya|ye|da|de|ta|te|a|e)$")


def _core_topic_query(topic: str) -> str:
    """Soru kalibindan cekirdek arama: "Neden Marsa Gitmek Zor ?" → "Mars"."""
    out: list[str] = []
    for word in re.findall(r"[\w']+", topic or ""):
        low = word.lower().replace("'", "")
        if low in _TOPIC_FILLER_WORDS or len(low) < 3:
            continue
        if "'" in word:
            word = word.split("'", 1)[0]
        elif word[:1].isupper():
            stripped = _PROPER_CASE_SUFFIX_RE.sub("", word)
            if len(stripped) >= 3:
                word = stripped
        out.append(word)
    return " ".join(out)


def _english_search_queries(
    topic: str,
    script: str,
    niche_id: str,
    extra_queries: list[str] | None = None,
) -> list[str]:
    """Wiki (TR+EN) ve DuckDuckGo icin oncelikli Ingilizce sorgular."""
    topic = (topic or "").strip()
    niche = (niche_id or "genel").strip().lower()
    out: list[str] = []
    seen: set[str] = set()

    def add(q: str) -> None:
        q = re.sub(r"\s+", " ", (q or "").strip())
        if len(q) < 2 or _is_weak_search_query(q):
            return
        key = q.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(q)

    for q in _atlas_extra_queries(topic):
        add(q)
    for q in extra_queries or []:
        add(q)
    from akifactory.script_topic import is_question_form_topic

    if is_question_form_topic(topic):
        core = _core_topic_query(topic)
        if core and core.lower() != topic.lower().rstrip(" ?"):
            add(core)
    en_forms = _english_wiki_queries(topic)
    for q in en_forms:
        add(q)

    base_en = en_forms[0] if en_forms else topic
    suffix = _EN_NICHE_SUFFIX.get(niche, "")
    if suffix and suffix.split()[0].lower() not in base_en.lower():
        add(f"{base_en} {suffix}".strip())

    first = (script or "").strip().split(".")[0].strip()
    if first and len(first) > 16:
        for q in _english_wiki_queries(f"{topic} {first[:80]}"):
            add(q)

    if topic and not _is_weak_search_query(topic):
        latin = re.findall(r"[A-Za-z]{3,}", topic)
        if len(latin) >= 1:
            add(topic)

    return out[:5]


_CHAPTER_FOCUS_PATTERNS: list[tuple[str, str]] = [
    (r"kesfi|keşfi|kesif|keşif|bulun|discovery|found", "discovery found"),
    (r"tarihcesi|tarihi|tarih|history|origin", "history origin"),
    (r"icerik|içerik|content|language|dil", "content language script"),
    (r"sifre|şifre|cipher|decrypt|coz", "decipherment cipher"),
    (r"resim|gorsel|illustration|diagram", "illustrations diagrams"),
    (r"kapanis|kapanış|closing|future|gelecek", "modern research status"),
]


def topic_research_extra_queries(topic: str, niche_id: str = "genel") -> list[str]:
    """Ana konu arastirmasi icin ek Ingilizce sorgular."""
    out: list[str] = []
    seen: set[str] = set()

    def add(q: str) -> None:
        q = re.sub(r"\s+", " ", (q or "").strip())
        if len(q) < 4:
            return
        key = q.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(q)

    for q in _english_wiki_queries(topic)[:3]:
        add(q)
        add(f"{q} history")
        add(f"{q} discovery")
    niche = (niche_id or "genel").strip().lower()
    if re.search(r"taş\s*devri|tas\s*devri|stone\s*age|paleolitik", topic, re.IGNORECASE):
        add("Stone Age mysteries archaeology")
        add("Paleolithic Neolithic archaeological discoveries")
    if niche in {"tarih_gizem", "tarihi_olaylar", "tarihi_insanlar", "savaslar"}:
        base = _english_wiki_queries(topic)
        if base:
            add(f"{base[0]} when discovered")
            add(f"{base[0]} who discovered")
    return out[:6]


def chapter_focus_queries(main: str, chapter_title: str, niche_id: str = "genel") -> list[str]:
    """Uzun video bolumu icin odakli Ingilizce arama cumleleri."""
    out: list[str] = []
    seen: set[str] = set()
    main = (main or "").strip()
    title = (chapter_title or "").strip()
    low = title.lower()

    def add(q: str) -> None:
        q = re.sub(r"\s+", " ", (q or "").strip())
        if len(q) < 4 or _is_weak_search_query(q):
            return
        key = q.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(q)

    for q in _english_wiki_queries(f"{main} {title}"):
        add(q)
    for q in _english_wiki_queries(main)[:2]:
        add(f"{q} {title}")
    for pat, suffix in _CHAPTER_FOCUS_PATTERNS:
        if re.search(pat, low):
            for q in _english_wiki_queries(main)[:2]:
                add(f"{q} {suffix}")
            if re.search(r"kesfi|keşfi|kesif|keşif|bulun|discovery|found", low):
                add("Wilfrid Voynich 1912 manuscript discovery")
                add("Voynich manuscript Jesuit collection 1912 Italy")
            break
    for q in topic_research_extra_queries(main, niche_id)[:2]:
        add(q)
    return out[:6]


def _snippet_blob(snippet: WebSnippet) -> str:
    return f"{snippet.title} {snippet.body}".lower()


# Soru/dolgu kelimeleri konuyu tanimlamaz: "Neden Marsa Gitmek Zor" → yalnizca "marsa"
# ayirt edici; yoksa "Neden gitmek zorundasın" adli Eurovision sarkisi eslesir
_TOPIC_FILLER_WORDS = frozenset(
    """
    neden niçin nicin niye nasıl nasil hangi kim kimdir nedir ne nerede nereden nereye
    zaman mı mi mu mü mıdır midir var yok için icin ile gibi kadar çok cok daha en bir bu şu
    olan olarak oldu olur olmak olması olmasi gitmek gidilir gidemiyoruz yapmak yapılır etmek
    zor zordur kolay mümkün mumkun gerçek gercek gerçekten gercekten aslında aslinda büyük buyuk
    neler hakkında hakkinda bilinmeyen gerçekler gercekler sırrı sirri sır sir hikayesi
    why how what who when where which the and for with hard difficult really
    """.split()
)


_TR_FOLD = str.maketrans("çğıöşüâîûÇĞİIÖŞÜÂÎÛ", "cgiosuaiucgiiosuaiu")


def _fold_words(text: str) -> list[str]:
    """Turkce harf/ASCII farkini yok say (deasciifier "Marsa"yi "Marşa" yapabiliyor)."""
    folded = unicodedata.normalize("NFKD", (text or "").translate(_TR_FOLD).lower())
    return re.findall(r"\w+", "".join(c for c in folded if not unicodedata.combining(c)))


_FOLDED_FILLER = frozenset(w for f in _TOPIC_FILLER_WORDS for w in _fold_words(f))


def _topic_content_stems(topic: str) -> list[str]:
    words = [w for w in _fold_words(topic) if len(w) > 2]
    content = [w for w in words if w not in _FOLDED_FILLER] or words
    # Turkce ek: "marsa" → "mars", "istanbulda" → "istanb"
    return [w[: max(4, len(w) - 3)] if len(w) > 4 else w for w in dict.fromkeys(content)]


def _filter_snippets_for_topic(snippets: list[WebSnippet], topic: str) -> list[WebSnippet]:
    """Konu disi kaynaklari (or. Tas Devri -> PKK, Ankara -> spor salonu) ele."""
    from akifactory.script_topic import (
        has_off_topic_conflict_drift,
        is_ancient_history_topic,
        normalize_text_for_match,
        topic_anchor_phrases,
    )

    if not snippets:
        return snippets

    anchors = topic_anchor_phrases(topic)
    stems = _topic_content_stems(topic)

    kept: list[WebSnippet] = []
    for sn in snippets:
        blob = normalize_text_for_match(_snippet_blob(sn))
        if not blob:
            continue
        if anchors:
            if not any(a in blob for a in anchors):
                continue
        elif stems:
            # Genel konu: ayirt edici kelimelerin koku gecmeli (ankara, savas, mars, ...)
            tokens = set(_fold_words(_snippet_blob(sn)))
            hits = sum(1 for st in stems if any(t.startswith(st) for t in tokens))
            need = 1 if len(stems) <= 2 else min(2, len(stems))
            if hits < need:
                continue
        if is_ancient_history_topic(topic) and has_off_topic_conflict_drift(blob, topic):
            continue
        kept.append(sn)

    if kept:
        return kept
    # Hic eslesme yoksa alakasiz ilk kaynagi vermek senaryoyu zehirliyor
    return []


def _is_wikipedia_snippet(sn: WebSnippet) -> bool:
    src = (sn.source or "").lower()
    url = (sn.url or "").lower()
    return "wikipedia" in src or "wikipedia.org" in url


def _prefer_wikipedia(snippets: list[WebSnippet]) -> list[WebSnippet]:
    wiki = [s for s in snippets if _is_wikipedia_snippet(s)]
    other = [s for s in snippets if not _is_wikipedia_snippet(s)]
    return wiki + other


async def gather_fact_context(
    topic: str,
    script: str = "",
    *,
    lang_id: str = "tr",
    niche_id: str = "genel",
    extra_queries: list[str] | None = None,
) -> list[WebSnippet]:
    """Konu icin Wikipedia (TR+EN) + DuckDuckGo (+ opsiyonel Crawl4AI derinlestirme)."""
    niche = (niche_id or "genel").strip().lower()
    all_hits: list[WebSnippet] = []
    queries = _english_search_queries(topic, script, niche, extra_queries)
    if not queries and (topic or "").strip():
        queries = [(topic or "").strip()]

    # 1) Once Wikipedia (asıl dogrulama kaynagi)
    def relevant_wiki() -> list[WebSnippet]:
        on_topic = _filter_snippets_for_topic(_dedupe_snippets(all_hits), topic)
        return [s for s in on_topic if _is_wikipedia_snippet(s)]

    for query in queries:
        all_hits.extend(await _wikipedia_snippets(query, lang="tr", limit=2))
        all_hits.extend(await _wikipedia_snippets(query, lang="en", limit=2))
        if len(relevant_wiki()) >= 3:
            break

    wiki_hits = relevant_wiki()
    # 2) Wiki zayifsa (konu disi sonuclar sayilmaz) DDG ile doldur
    if len(wiki_hits) < 2:
        for query in queries:
            if len(_filter_snippets_for_topic(_dedupe_snippets(all_hits), topic)) >= 6:
                break
            all_hits.extend(await _duckduckgo_snippets(query, limit=2))

    deduped = _dedupe_snippets(all_hits)
    filtered = _filter_snippets_for_topic(deduped, topic)
    filtered = _prefer_wikipedia(filtered)

    wiki_ok = sum(1 for s in filtered if _is_wikipedia_snippet(s))
    # 3) Crawl4AI sadece Wiki yetersizken ve yalnizca konuyla eslesen dis URL'lerde
    if wiki_ok < 2:
        try:
            from akifactory.crawl_enrich import enrich_snippets_with_crawl4ai

            enriched = await enrich_snippets_with_crawl4ai(filtered, topic=topic)
            enriched = _filter_snippets_for_topic(enriched, topic)
            filtered = _prefer_wikipedia(enriched)
        except Exception as exc:
            log.debug("crawl enrich skipped: %s", exc)
    else:
        # Wiki yeterli — dis site gurultusunu alma
        filtered = [s for s in filtered if _is_wikipedia_snippet(s)] or filtered[:3]

    return filtered[:6]


def format_research_for_writer(snippets: list[WebSnippet]) -> str:
    """Yazar LLM icin ham kaynak blogu (senaryo oncesi arastirma)."""
    if not snippets:
        return ""
    parts: list[str] = []
    total = 0
    for i, sn in enumerate(snippets, start=1):
        block = f"[{sn.source}] {sn.title}\n{sn.body}"
        if sn.url:
            block += f"\n({sn.url})"
        if total + len(block) > _MAX_TOTAL_CHARS:
            remain = _MAX_TOTAL_CHARS - total
            if remain > 120:
                parts.append(block[:remain] + "…")
            break
        parts.append(block)
        total += len(block)
    return "\n\n".join(parts)


def format_context_for_editor(snippets: list[WebSnippet]) -> str:
    if not snippets:
        return (
            "(Web kaynagi alinamadi. Yine de senaryodaki bariz tutarsizliklari duzelt; "
            "emin olmadigin bilgiyi ekleme veya abartma.)"
        )
    parts: list[str] = []
    total = 0
    for i, sn in enumerate(snippets, start=1):
        block = f"KAYNAK {i} [{sn.source}] {sn.title}\n{sn.body}"
        if sn.url:
            block += f"\nURL: {sn.url}"
        if total + len(block) > _MAX_TOTAL_CHARS:
            remain = _MAX_TOTAL_CHARS - total
            if remain > 120:
                parts.append(block[:remain] + "…")
            break
        parts.append(block)
        total += len(block)
    return "\n\n".join(parts)
