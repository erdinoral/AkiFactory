"""Crawl4AI ile DDG URL'lerini LLM-hazir Markdown'a derinlestir (opsiyonel).

Kurulum: python scripts/bootstrap.py --crawl4ai
Kapat: AKI_CRAWL4AI=0
Yoksa / hata olursa sessizce atlanir — Wiki+DDG akisi bozulmaz.
"""

from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from akifactory.web_search import WebSnippet

log = logging.getLogger(__name__)

_MAX_PAGES = 2
_PAGE_TIMEOUT_MS = 18_000
_BODY_LIMIT = 1400
_SKIP_HOSTS = (
    "wikipedia.org",
    "wikimedia.org",
    "duckduckgo.com",
    "google.",
    "bing.com",
    "youtube.com",
    "youtu.be",
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "tiktok.com",
)


def crawl4ai_enabled() -> bool:
    flag = (os.environ.get("AKI_CRAWL4AI") or "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    try:
        import crawl4ai  # noqa: F401

        return True
    except Exception:
        return False


def _host_ok(url: str) -> bool:
    u = (url or "").strip().lower()
    if not u.startswith(("http://", "https://")):
        return False
    return not any(h in u for h in _SKIP_HOSTS)


def _md_text(result: object) -> str:
    md = getattr(result, "markdown", None)
    if md is None:
        return ""
    if isinstance(md, str):
        return md.strip()
    for attr in ("fit_markdown", "raw_markdown", "markdown_with_citations"):
        val = getattr(md, attr, None)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return str(md).strip()


def _clean_body(text: str, limit: int = _BODY_LIMIT) -> str:
    """Nav/menu link satirlarini at; LLM icin duz metin birak."""
    raw = (text or "").replace("\r\n", "\n").strip()
    kept: list[str] = []
    for line in raw.split("\n"):
        s = line.strip()
        if not s:
            kept.append("")
            continue
        # Salt markdown link / menu satiri
        link_only = re.fullmatch(r"(?:\[[^\]]+\]\([^)]+\)\s*)+", s)
        if link_only:
            continue
        if s.startswith(("# ", "## ", "### ")) and len(s) < 80:
            # kisa basliklari tut
            kept.append(s)
            continue
        # Cok link yogun satir
        if s.count("](") >= 3 and len(re.sub(r"\[.*?\]\(.*?\)", "", s).strip()) < 40:
            continue
        low = s.lower()
        if any(
            x in low
            for x in (
                "cookie",
                "subscribe",
                "newsletter",
                "sign in",
                "log in",
                "privacy policy",
                "terms of use",
                "ask the chatbot",
                "games & quizzes",
            )
        ):
            continue
        kept.append(s)
    t = "\n".join(kept)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"[^\S\n]{2,}", " ", t).strip()
    # Inline markdown linkleri duz metne indir
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    if len(t) <= limit:
        return t
    return t[: limit - 1].rstrip() + "…"


def _url_key(url: str) -> str:
    return (url or "").split("#", 1)[0].rstrip("/").lower()


def _pick_urls(snippets: list[WebSnippet], *, limit: int = _MAX_PAGES) -> list[tuple[str, str]]:
    """(url, title) — once DDG / dis kaynaklar."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    ordered = sorted(
        snippets,
        key=lambda s: (0 if (s.source or "").lower().startswith("duck") else 1),
    )
    for sn in ordered:
        url = (sn.url or "").strip()
        if not _host_ok(url):
            continue
        key = _url_key(url)
        if key in seen:
            continue
        seen.add(key)
        out.append((url, sn.title or url))
        if len(out) >= limit:
            break
    return out


def _build_run_config(topic: str) -> Any:
    from crawl4ai import CacheMode, CrawlerRunConfig

    query = (topic or "").strip()
    md_gen = None
    try:
        from crawl4ai.content_filter_strategy import BM25ContentFilter, PruningContentFilter
        from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

        content_filter = (
            BM25ContentFilter(user_query=query, bm25_threshold=1.2)
            if query
            else PruningContentFilter(threshold=0.48, threshold_type="fixed", min_word_threshold=25)
        )
        md_gen = DefaultMarkdownGenerator(
            content_filter=content_filter,
            options={"ignore_links": True, "ignore_images": True},
        )
    except Exception:
        md_gen = None

    # Surum farklarina dayanikli — gereksiz kwargs dusur
    attempts: list[dict[str, Any]] = [
        {
            "cache_mode": CacheMode.BYPASS,
            "page_timeout": _PAGE_TIMEOUT_MS,
            "wait_until": "domcontentloaded",
            "remove_overlay_elements": True,
            "word_count_threshold": 40,
        },
        {
            "cache_mode": CacheMode.BYPASS,
            "page_timeout": _PAGE_TIMEOUT_MS,
        },
        {},
    ]
    last_err: Exception | None = None
    for kwargs in attempts:
        cfg = dict(kwargs)
        if md_gen is not None:
            cfg["markdown_generator"] = md_gen
        try:
            return CrawlerRunConfig(**cfg)
        except Exception as exc:
            last_err = exc
            continue
    if last_err:
        log.debug("CrawlerRunConfig fallback: %s", last_err)
    return CrawlerRunConfig()


async def enrich_snippets_with_crawl4ai(
    snippets: list[WebSnippet],
    *,
    topic: str = "",
) -> list[WebSnippet]:
    """Secili URL'leri Crawl4AI ile derinlestir; basarisizsa orijinal listeyi dondur."""
    from akifactory.web_search import WebSnippet

    if not snippets or not crawl4ai_enabled():
        return snippets

    targets = _pick_urls(snippets)
    if not targets:
        return snippets

    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig
    except Exception as exc:
        log.debug("crawl4ai import fail: %s", exc)
        return snippets

    try:
        browser_cfg = BrowserConfig(headless=True, verbose=False)
    except Exception:
        browser_cfg = None

    run_cfg = _build_run_config(topic)
    enriched: list[WebSnippet] = []
    by_url = {_url_key(s.url): s for s in snippets if s.url}

    try:
        crawler_cm = (
            AsyncWebCrawler(config=browser_cfg)
            if browser_cfg is not None
            else AsyncWebCrawler()
        )
        async with crawler_cm as crawler:
            for url, title in targets:
                try:
                    result = await crawler.arun(url=url, config=run_cfg)
                except TypeError:
                    try:
                        result = await crawler.arun(url)
                    except Exception as exc:
                        log.debug("crawl4ai arun fail %s: %s", url, exc)
                        continue
                except Exception as exc:
                    log.debug("crawl4ai arun fail %s: %s", url, exc)
                    continue
                if result is None or not getattr(result, "success", True):
                    continue
                body = _clean_body(_md_text(result))
                if len(body) < 120:
                    continue
                key = _url_key(url)
                base = by_url.get(key)
                enriched.append(
                    WebSnippet(
                        title=(base.title if base and base.title else title)[:160],
                        body=body,
                        url=url,
                        source="Crawl4AI",
                    )
                )
    except Exception as exc:
        log.debug("crawl4ai session fail: %s", exc)
        return snippets

    if not enriched:
        return snippets

    crawl_keys = {_url_key(e.url) for e in enriched}
    kept = [s for s in snippets if _url_key(s.url) not in crawl_keys]
    return enriched + kept
