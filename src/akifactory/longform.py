"""Uzun video — montajsiz: tek ses + altyazi + stok gorseller."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from akifactory import batch as batch_mod
from akifactory import job_log
from akifactory import ollama_util
from akifactory import script_quality as script_q
from akifactory import script_prompts as script_pr
from akifactory import script_translate as script_tr_mod
from akifactory import text_utils
from akifactory import video_source as vid_src
from akifactory import longform_gallery as lf_gal_mod
from akifactory.gallery import task_montage_assets
from akifactory.paths import data_dir, engine_task_dir

_jobs: dict[str, "LongformJob"] = {}


@dataclass
class LongformJob:
    longform_id: str
    main_subject: str
    cancelled: bool = False
    phase: str = "tr"
    state: int = 0
    progress: int = 0
    step: str = ""
    error: str | None = None
    script: str = ""
    task_id: str | None = None
    en_task_id: str | None = None
    en_script: str = ""
    gallery_entry_id: str | None = None
    current_chapter: int = -1
    script_done: bool = False
    chapters: list[dict[str, Any]] = field(default_factory=list)
    common: dict[str, Any] = field(default_factory=dict)


def _normalize_chapter_title(title: str, main: str) -> str:
    return text_utils.normalize_chapter_title(title, main)


def full_chapter_heading(main: str, sub: str) -> str:
    return text_utils.full_chapter_heading(main, sub)


def _chapter_outline(job: LongformJob) -> str:
    main = job.main_subject.strip()
    lines: list[str] = []
    for ch in sorted(job.chapters, key=lambda c: int(c.get("index", 0))):
        t = full_chapter_heading(main, ch.get("title") or "")
        lines.append(f"{int(ch.get('index', 0)) + 1}. {t}")
    return "\n".join(lines)


def _last_sentences(text: str, *, n: int = 3) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    parts = re.findall(r"[^.!?…]+[.!?…]+", raw)
    if not parts:
        return raw[-280:]
    return " ".join(s.strip() for s in parts[-n:] if s.strip())


def _prior_chapters_context(job: LongformJob, current_index: int) -> str:
    """Onceki bolum ozetleri + hemen onceki bolumun bitisi (devam noktasi)."""
    parts: list[str] = []
    main = job.main_subject.strip()
    prev_ending = ""
    covered: list[str] = []
    for ch in sorted(job.chapters, key=lambda c: int(c.get("index", 0))):
        idx = int(ch.get("index", 0))
        if idx >= current_index:
            break
        script = (ch.get("script") or ch.get("video_script") or "").strip()
        title = full_chapter_heading(main, ch.get("title") or "")
        sub = (ch.get("title") or "").strip()
        if sub:
            covered.append(f"{idx + 1}. {sub}")
        if not script:
            continue
        # Ozet: her onceki bolumden kisa hatirlatma (yeniden anlatma icin degil)
        excerpt = script if len(script) <= 220 else script[:220].rsplit(" ", 1)[0] + "…"
        parts.append(f"Bolum {idx + 1} ozeti — {title}:\n{excerpt}")
        prev_ending = _last_sentences(script, n=3)

    if not parts and not prev_ending:
        return ""

    blocks = []
    if covered:
        blocks.append(
            "DAHA ONCE ISLENEN ODAKLAR (bunlari bastan anlatma):\n" + "\n".join(covered)
        )
    if parts:
        blocks.append("ONCEKI BOLUM OZETLERI:\n" + "\n\n".join(parts[-3:]))
    if prev_ending:
        blocks.append(
            "HEMEN ONCEKI BOLUMUN BITIS CUMLELERI — ANLATIMA BURADAN DEVAM ET "
            "(yeniden tanitma / tarih-yer-grup sunumu YASAK):\n"
            f"{prev_ending}"
        )
    return "\n\n".join(blocks)


def _longform_script_acceptable(
    script: str,
    topic: str,
    *,
    niche_id: str,
    is_first: bool,
) -> bool:
    issues = script_q.script_quality_issues(
        script, topic, niche_id=niche_id, longform=True
    )
    if not is_first:
        issues = [
            i
            for i in issues
            if i not in ("klise_hook", "jenerik_hook", "zayif_hook", "acilis_konu_disinda")
        ]
    return not issues


_RESTART_OPENERS = (
    "yılında",
    "yilinda",
    "tarihinde",
    "yılının",
    "yilinin",
    "bir grup",
    "bir ekip",
    "olay şöyle",
    "hikaye şöyle",
    "konumuz",
    "bugün anlatacağımız",
    "bugun anlatacagimiz",
)


def looks_like_longform_restart(
    script: str,
    *,
    first_script: str = "",
    is_first: bool,
) -> bool:
    """Orta/son bolumun olayi bastan tanittigini yakala (Dyatlov tipi tekrar)."""
    if is_first:
        return False
    opening = (script or "").strip()[:260].lower()
    if not opening:
        return False
    has_year = bool(re.search(r"\b(1[89]\d{2}|20\d{2})\b", opening))
    opener_hit = any(p in opening for p in _RESTART_OPENERS)
    # «1959'da / yılında … grup …» tipi belgesel yeniden acilis
    if has_year and opener_hit:
        return True
    if has_year and re.search(
        r"\b(rusya|sovyet|dağ|dag|pass|geçit|gecit|enstitü|enstitu)\b", opening
    ):
        return True
    first_open = (first_script or "").strip()[:220].lower()
    if first_open and len(opening) > 40:
        a = set(re.findall(r"[a-zçğıöşüâîû0-9]{4,}", opening))
        b = set(re.findall(r"[a-zçğıöşüâîû0-9]{4,}", first_open))
        if a and b:
            overlap = len(a & b) / max(1, min(len(a), len(b)))
            if overlap >= 0.45 and has_year:
                return True
    return False


async def rewrite_longform_chapter_continuity(
    script: str,
    *,
    main_subject: str,
    chapter_title: str,
    prior_ending: str,
    writer_model_name: str | None = None,
) -> str:
    """Bastan anlatan bolumu onceki bolumun bitisinden devam ettir."""
    from akifactory.llm_profiles import writer_model as resolve_writer_default
    from akifactory.ollama_util import chat as ollama_chat

    base = (script or "").strip()
    if len(base) < 40:
        return base
    ending = (prior_ending or "").strip()
    prompt = f"""Bu metin cok bolumlu TEK belgesel videonun ara bolumu.
Model yanlis olarak olayi BASTAN anlattı. Sen duzelt: anlatima DEVAM et.

ANA KONU: {main_subject.strip()}
BU BOLUMUN ODAĞI: {chapter_title.strip()}

ONCEKI BOLUMUN BITISI (buradan dogal devam):
{ending or "(onceki bitis yok — yine de bastan tanitma)"}

YANLIS / BASTAN ANLATAN TASLAK:
{base}

ZORUNLU KURALLAR:
1) Ilk cumle ASLA yil+yer+grup tanitimi olmasin (orn. «1959'da…», «Rusya'da bir grup…», «Dyatlov ve ekibi…» yeniden sunumu YASAK)
2) Onceki bolumun bitisinden kopmadan devam et; yeni sahne/detaya gec
3) Olayi, ekibi, tarihi, yeri yeniden tanitma — izleyici zaten biliyor
4) 6–10 cumle, ~45–55 sn; alt baslik okuma; soru yok
5) Yanitinda SADECE duzeltilmis senaryo metni

CIKTI:"""

    fixed = await ollama_chat(
        [{"role": "user", "content": prompt}],
        model=writer_model_name or resolve_writer_default(),
        think=False,
        timeout=150.0,
    )
    out = (fixed or "").strip()
    return out if len(out) >= 80 else base


async def _expand_longform_chapter_script(
    script: str,
    *,
    main_subject: str,
    chapter_title: str,
    chapter_index: int,
    total_chapters: int,
    research_context: str = "",
    writer_model_name: str | None = None,
) -> str:
    """Cok kisa bolum metnini yazar LLM ile genislet."""
    from akifactory.llm_profiles import writer_model as resolve_writer_default
    from akifactory.ollama_util import chat as ollama_chat

    base = (script or "").strip()
    if not base:
        return base
    research_block = ""
    if (research_context or "").strip():
        research_block = f"\nARASTIRMA NOTU:\n{research_context.strip()[:900]}\n"
    cont = ""
    if int(chapter_index) > 0:
        cont = (
            "\n- Bu ara bolum: olayi/ekibi/yeri BASTAN tanitma; anlatima devam et\n"
            "- Ilk cumle «yil + yer + bir grup…» ekspozisyonu olmasin\n"
        )
    prompt = f"""Asagidaki uzun video BOLUM senaryosu cok kisa. EN AZ 6 cumle olacak sekilde genislet.

ANA KONU: {main_subject.strip()}
BOLUM ODAĞI: {chapter_title.strip()}
BOLUM: {chapter_index + 1}/{total_chapters}
{research_block}
MEVCUT METIN:
{base}

KURALLAR:
- Mevcut dogru bilgileri koru; somut detay ekle (tarih, isim, yer, sebep, sonuc)
- Alt baslik veya bolum adi OKUMA; soru cumlesi yok
- 6-10 cumle; yaklasik 45-55 saniye konusma (~400-700 karakter)
- Turkce konusma dili; markdown yok{cont}
- Yanitinda SADECE genisletilmis senaryo metni olsun"""

    expanded = await ollama_chat(
        [{"role": "user", "content": prompt}],
        model=writer_model_name or resolve_writer_default(),
        think=False,
        timeout=150.0,
    )
    return (expanded or base).strip()


async def _ensure_job_research(job: LongformJob) -> None:
    """Ana konu icin Wiki+DDG arastirmasi (bir kez)."""
    common = job.common
    if common.get("_research_ready"):
        return
    common["_research_brief"] = ""
    common["_research_ready"] = True
    try:
        from akifactory import content_studio as studio_mod
        from akifactory import llm_profiles as llm_prof

        if not studio_mod.should_use_web_research(
            common.get("niche", "genel"),
            bool(common.get("editor_web_verify", True)),
        ):
            return
        job.step = "Web arastirmasi (Wikipedia + DuckDuckGo)..."
        installed = await ollama_util.list_installed_models()
        editor = llm_prof.resolve_editor_model(installed, common.get("editor_model"))
        brief, count = await studio_mod.fetch_topic_research(
            job.main_subject.strip(),
            lang_id=common.get("production_language", "tr"),
            niche_id=common.get("niche", "genel"),
            model=editor,
        )
        common["_research_brief"] = brief
        common["_research_sources"] = count
    except Exception:
        common["_research_brief"] = ""


async def _chapter_research_snippet(
    main_subject: str,
    chapter_title: str,
    common: dict[str, Any],
) -> str:
    """Bolum odagi icin Wiki+DDG arastirma notu."""
    from akifactory import content_studio as studio_mod
    from akifactory import llm_profiles as llm_prof

    main = (main_subject or "").strip()
    title = (chapter_title or "").strip()
    if not main or not title:
        return ""
    if not studio_mod.should_use_web_research(
        common.get("niche", "genel"),
        bool(common.get("editor_web_verify", True)),
    ):
        return ""
    try:
        installed = await ollama_util.list_installed_models()
        editor = llm_prof.resolve_editor_model(installed, common.get("editor_model"))
        brief, _ = await studio_mod.fetch_chapter_research(
            main,
            title,
            lang_id=common.get("production_language", "tr"),
            niche_id=common.get("niche", "genel"),
            model=editor,
        )
        return brief
    except Exception:
        return ""


async def generate_longform_chapter_script_with_retry(
    ch: dict[str, Any],
    job: LongformJob,
    common: dict[str, Any],
    *,
    attempts: int = 3,
) -> str:
    import asyncio

    main = job.main_subject.strip()
    title = _normalize_chapter_title(ch.get("title") or "", main)
    ch["title"] = title
    ch["display_title"] = full_chapter_heading(main, title)
    idx = int(ch.get("index", 0))
    prior = _prior_chapters_context(job, idx)
    outline = _chapter_outline(job)
    all_titles = [str(c.get("title") or "") for c in job.chapters]
    script_topic = ch["display_title"]
    niche_id = common.get("niche", "genel")
    is_first = idx <= 0
    last_err = ""

    def _polish(text: str) -> str:
        """MÖ/MS ac, TTS duzelt — kalite kontrolunden once."""
        raw = (text or "").strip()
        if not raw:
            return raw
        polished = text_utils.prepare_script_for_engine(raw, "tr", niche_id=niche_id) or raw
        return text_utils.scrub_longform_chapter_narration(
            polished,
            main_subject=main,
            chapter_title=title,
            all_chapter_titles=all_titles,
        )

    def _ok(text: str) -> bool:
        return len(text) >= 10 and _longform_script_acceptable(
            text, script_topic, niche_id=niche_id, is_first=is_first
        )

    def _soft_ok(text: str) -> bool:
        """Son care: yeterli anlatim varsa az_cumle uretimi tamamen durdurmasin."""
        if len(text) < 160:
            return False
        issues = script_q.script_quality_issues(
            text, script_topic, niche_id=niche_id, longform=True
        )
        if not is_first:
            issues = [
                i
                for i in issues
                if i
                not in (
                    "klise_hook",
                    "jenerik_hook",
                    "zayif_hook",
                    "acilis_konu_disinda",
                )
            ]
        soft = {
            "az_cumle",
            "cok_kisa",
            "klise_ifade",
            "zayif_hook",
            "acilis_konu_disinda",
            "jenerik_hook",
            "klise_hook",
            "cok_soru",
        }
        hard = [i for i in issues if i not in soft]
        if hard:
            return False
        import re as _re

        marks = len(_re.findall(r"[.!?…]+", text))
        words = len(text.split())
        # 4+ nokta veya yeterli kelime — montaj icin ses uretilebilsin
        if marks >= 3 and words >= 30:
            return True
        if len(text) >= 220 and words >= 40:
            return True
        return "az_cumle" not in issues and "cok_kisa" not in issues

    for attempt in range(max(1, attempts)):
        try:
            if attempt > 0:
                await asyncio.sleep(1.5 + attempt * 2.0)
            chapter_research = ""
            if not (ch.get("video_script") or "").strip():
                chapter_research = await _chapter_research_snippet(main, title, common)
                if chapter_research:
                    ch["_chapter_research"] = chapter_research
                    await ollama_util.release_vram_for_model_swap()
            script_text = (
                await script_pr.generate_longform_chapter_script(
                    main_subject=main,
                    chapter_title=title,
                    chapter_index=idx,
                    total_chapters=len(job.chapters),
                    prior_context=prior,
                    chapter_outline=outline,
                    lang_id=common.get("production_language", "tr"),
                    platform_id=common.get("platform", "youtube_shorts"),
                    niche_id=niche_id,
                    research_context=str(common.get("_research_brief") or ""),
                    chapter_research=chapter_research,
                    all_chapter_titles=all_titles,
                    think_guidance=str(common.get("think_guidance") or ""),
                )
            ).strip()
            script_text = _polish(script_text)
            if not is_first and looks_like_longform_restart(
                script_text,
                first_script=(
                    (job.chapters[0].get("script") or job.chapters[0].get("video_script") or "")
                    if job.chapters
                    else ""
                ),
                is_first=False,
            ):
                from akifactory import llm_profiles as llm_prof

                installed = await ollama_util.list_installed_models()
                writer = llm_prof.resolve_writer_model(
                    installed, common.get("writer_model")
                )
                ending = _last_sentences(
                    next(
                        (
                            (c.get("script") or c.get("video_script") or "")
                            for c in sorted(
                                job.chapters, key=lambda x: int(x.get("index", 0))
                            )
                            if int(c.get("index", 0)) == idx - 1
                        ),
                        "",
                    ),
                    n=3,
                )
                job_log.info(
                    job.longform_id,
                    f"Bolum {idx + 1}: bastan anlatim tespit — devam rewrite",
                )
                script_text = _polish(
                    await rewrite_longform_chapter_continuity(
                        script_text,
                        main_subject=main,
                        chapter_title=title,
                        prior_ending=ending,
                        writer_model_name=writer,
                    )
                )
            if _ok(script_text):
                return script_text
            issues = script_q.script_quality_issues(
                script_text,
                script_topic,
                niche_id=niche_id,
                longform=True,
            )
            last_err = "Senaryo kalite kontrolu: " + ", ".join(issues[:4])
            if attempt >= attempts - 1 and (
                "az_cumle" in issues or "cok_kisa" in issues or not script_text
            ):
                from akifactory import llm_profiles as llm_prof

                installed = await ollama_util.list_installed_models()
                writer = llm_prof.resolve_writer_model(
                    installed, common.get("writer_model")
                )
                expanded = await _expand_longform_chapter_script(
                    script_text,
                    main_subject=main,
                    chapter_title=title,
                    chapter_index=idx,
                    total_chapters=len(job.chapters),
                    research_context=str(common.get("_research_brief") or ""),
                    writer_model_name=writer,
                )
                expanded = _polish(expanded)
                if _ok(expanded):
                    return expanded
                if _soft_ok(expanded):
                    return expanded
                issues = script_q.script_quality_issues(
                    expanded,
                    script_topic,
                    niche_id=niche_id,
                    longform=True,
                )
                last_err = "Senaryo kalite kontrolu: " + ", ".join(issues[:4])
                script_text = expanded
            if attempt >= attempts - 1 and _soft_ok(script_text):
                return script_text
        except Exception as exc:
            last_err = str(exc) or "Senaryo hatasi"
    raise RuntimeError(
        f"Bolum senaryosu uretilemedi ({attempts} deneme)."
        + (f" ({last_err})" if last_err else "")
    )


async def review_longform_chapter_script(
    job: LongformJob,
    ch: dict[str, Any],
    script: str,
) -> str:
    """Tek bolum senaryosu — editor incelemesi (baslik uyumu, Turkce, akis)."""
    from akifactory import llm_profiles as llm_prof
    from akifactory.content_studio import EDITOR_CHAT_OPTIONS
    from akifactory.ollama_util import chat as ollama_chat

    base = (script or "").strip()
    if len(base) < 20:
        return base

    installed = await ollama_util.list_installed_models()
    editor = llm_prof.resolve_editor_model(installed, job.common.get("editor_model"))
    niche = job.common.get("niche", "genel")
    niche_label = script_pr.NICHE_LABELS.get(niche, niche)
    idx = int(ch.get("index", 0))
    total = len(job.chapters)
    title = ch.get("display_title") or full_chapter_heading(
        job.main_subject, ch.get("title") or ""
    )
    prior = _prior_chapters_context(job, idx)
    outline = _chapter_outline(job)
    all_titles = [str(c.get("title") or "") for c in job.chapters]
    is_first = idx <= 0
    is_last = idx >= total - 1

    hook_rule = (
        "Guclu hook / dikkat cekici giris"
        if is_first
        else (
            "Onceki bolumun bitisinden DEVAM et — olayi/ekibi/yeri/tarihi bastan tanitma; "
            "ilk cumle «1959'da / Rusya'da bir grup…» tipi ekspozisyon olmasin"
        )
    )
    close_rule = "Guclu kapanis / ozet" if is_last else "Sonraki bolume kopuk gecis birak"

    prompt = f"""Sen uzun belgesel video BOLUM editörüsün.
Bu TEK uzun videonun {idx + 1}. bolumu — her bolum ayri video DEGIL; anlatim surekli ilerler.

ANA KONU: {job.main_subject.strip()}
BOLUM {idx + 1}/{total}: {title}
ALT BASLIK: {ch.get("title") or ""}
NIS: {niche_label}

TUM BOLUM PLANI:
{outline}

ONCEKI BOLUMLER (baglam — TEKRARLAMA, BASTAN ANLATMA):
{prior or "(ilk bolum — hook onemli)"}

BU BOLUMUN SENARYOSU:
{base}

GOREV — yalnizca bu bolumu incele ve duzelt:
1) Alt baslik ve ana konuya uygun mu; baska konu/konu disi bilgi kaldir
2) Turkce: dogal konusma dili; Turkce karakterler zorunlu (ç ğ ı ö ş ü) — ASCII yasak
3) {hook_rule}
4) {close_rule}
5) Yaklasik 45-55 sn konusma uzunlugunda kalsin (cok uzatma veya agresif kesme yapma)
6) Bariz olumsuz hata/abartma duzelt; emin degilsen ekleme
7) Alt baslik, bolum adi veya plan maddesi OKUYAN cumleleri kaldir; dogrudan icerikle basla
8) Metin olayi sifirdan anlatıyorsa (yil+yer+grup sunumu) onceki bolum bitisinden devam edecek sekilde YENIDEN YAZ

CIKTI: Sadece duzeltilmis bu bolumun metni. Aciklama, madde, etiket yok."""

    reviewed = await ollama_chat(
        [{"role": "user", "content": prompt}],
        model=editor,
        think=False,
        clean_script=False,
        options={**EDITOR_CHAT_OPTIONS, "temperature": 0.35},
        timeout=120.0,
    )
    cleaned = text_utils.prepare_script_for_engine((reviewed or "").strip(), "tr") or (reviewed or "").strip()
    if len(cleaned) < len(base) * 0.35:
        cleaned = base
    first_script = ""
    if job.chapters:
        first_script = (
            job.chapters[0].get("script") or job.chapters[0].get("video_script") or ""
        )
    if not is_first and looks_like_longform_restart(
        cleaned, first_script=first_script, is_first=False
    ):
        ending = _last_sentences(
            next(
                (
                    (c.get("script") or c.get("video_script") or "")
                    for c in sorted(job.chapters, key=lambda x: int(x.get("index", 0)))
                    if int(c.get("index", 0)) == idx - 1
                ),
                "",
            ),
            n=3,
        )
        from akifactory import llm_profiles as llm_prof

        writer = llm_prof.resolve_writer_model(installed, job.common.get("writer_model"))
        cleaned = await rewrite_longform_chapter_continuity(
            cleaned,
            main_subject=job.main_subject,
            chapter_title=str(ch.get("title") or ""),
            prior_ending=ending,
            writer_model_name=writer,
        )
        cleaned = (
            text_utils.prepare_script_for_engine(cleaned, "tr") or cleaned
        ).strip()
    if not _longform_script_acceptable(
        cleaned, title, niche_id=niche, is_first=is_first
    ):
        return base
    out = text_utils.enforce_longform_chapter_limits(cleaned)
    return await _longform_apply_fact_check(job, ch, out)


async def _longform_apply_fact_check(
    job: LongformJob,
    ch: dict[str, Any],
    script: str,
) -> str:
    """Arastirma notuna gore bolum senaryosunu fact-check et."""
    from akifactory import content_studio as studio_mod
    from akifactory import llm_profiles as llm_prof

    out = (script or "").strip()
    if not out:
        return out
    niche = job.common.get("niche", "genel")
    if not studio_mod.should_use_web_research(
        niche, bool(job.common.get("editor_web_verify", True))
    ):
        return out
    research = (job.common.get("_research_brief") or "").strip()
    ch_notes = (ch.get("_chapter_research") or "").strip()
    combined = research
    if ch_notes and ch_notes not in research:
        combined = f"{research}\n\n{ch_notes}".strip() if research else ch_notes
    if not combined:
        return out
    try:
        installed = await ollama_util.list_installed_models()
        editor = llm_prof.resolve_editor_model(installed, job.common.get("editor_model"))
        out = await studio_mod.apply_research_fact_check(
            out,
            topic=job.main_subject.strip(),
            research_brief=combined,
            platform=job.common.get("platform", "youtube_shorts"),
            niche_id=niche,
            lang_id=job.common.get("production_language", "tr"),
            editor_model=editor,
            max_chars=text_utils.MAX_LONGFORM_CHAPTER_CHARS,
        )
        return text_utils.scrub_longform_chapter_narration(
            out,
            main_subject=job.main_subject.strip(),
            chapter_title=ch.get("title") or "",
            all_chapter_titles=[str(c.get("title") or "") for c in job.chapters],
        )
    except Exception:
        return out


async def generate_longform_full_script(job: LongformJob) -> str:
    """Tum alt basliklardan tek ~10 dk senaryo — bolum hatalari izole."""
    common = job.common
    lang_id = common.get("production_language", "tr")
    job.script_done = False
    await _ensure_job_research(job)
    await ollama_util.release_vram_for_model_swap()
    parts: list[str] = []
    for ch in sorted(job.chapters, key=lambda c: int(c.get("index", 0))):
        idx = int(ch.get("index", 0))
        job.current_chapter = idx
        main = job.main_subject.strip()
        title = _normalize_chapter_title(ch.get("title") or "", main)
        ch["title"] = title
        ch["display_title"] = full_chapter_heading(main, title)
        job.step = f"Bolum {idx + 1}/{len(job.chapters)} senaryosu"
        job_log.info(job.longform_id, f"Senaryo basliyor: bolum {idx + 1} — {title}")
        try:
            manual = (ch.get("video_script") or "").strip()
            existing = (ch.get("script") or manual).strip()
            if manual:
                cleaned = text_utils.prepare_script_for_engine(manual, lang_id) or manual
                ch["script"] = cleaned.strip()
                ch["video_script"] = ch["script"]
            elif existing:
                ch["script"] = existing
                ch["video_script"] = existing
            else:
                script = await generate_longform_chapter_script_with_retry(
                    ch, job, common, attempts=3
                )
                ch["video_script"] = script
                ch["script"] = script
            if common.get("dual_llm", True) and not ch.get("_reviewed"):
                job.step = f"Bolum {idx + 1}/{len(job.chapters)} editor incelemesi"
                job.progress = max(job.progress, int(8 * (idx + 1) / max(len(job.chapters), 1)))
                await ollama_util.release_vram_for_model_swap()
                ch["script"] = await review_longform_chapter_script(job, ch, ch["script"])
                ch["_reviewed"] = True
            else:
                job.step = f"Bolum {idx + 1}/{len(job.chapters)} fact-check"
                ch["script"] = await _longform_apply_fact_check(job, ch, ch["script"])
            ch["video_script"] = ch["script"]
            ch.pop("error", None)
            if ch.get("state") == -1:
                ch["state"] = 0
            parts.append(ch["script"])
        except Exception as exc:
            err = str(exc) or "Senaryo hatasi"
            ch["error"] = err
            ch["state"] = -1
            ch["script"] = ch.get("script") or ""
            ch["video_script"] = ch.get("video_script") or ch["script"]
            job_log.error(job.longform_id, f"Bolum {idx + 1} senaryo hatasi: {err}")
            continue
    # Eksik bolumler icin bir kez daha yumusak deneme (az_cumle yuzunden bos kalanlar)
    for ch in sorted(job.chapters, key=lambda c: int(c.get("index", 0))):
        if (ch.get("script") or ch.get("video_script") or "").strip():
            continue
        idx = int(ch.get("index", 0))
        try:
            job.step = f"Bolum {idx + 1} senaryo kurtarma"
            job_log.warn(job.longform_id, f"Bolum {idx + 1} senaryo kurtarma denemesi")
            script = await generate_longform_chapter_script_with_retry(
                ch, job, common, attempts=2
            )
            ch["video_script"] = script
            ch["script"] = script
            ch.pop("error", None)
            if ch.get("state") == -1:
                ch["state"] = 0
            parts.append(script)
        except Exception as exc:
            job_log.error(
                job.longform_id,
                f"Bolum {idx + 1} kurtarma basarisiz: {exc}",
            )
    job.current_chapter = len(job.chapters)
    job.script_done = True
    full = "\n\n".join(p for p in parts if p.strip())
    return text_utils.enforce_longform_full_script_limits(full)


def _split_script_to_chapters(job: LongformJob, script: str) -> bool:
    """Tam senaryoyu bolumlere bol. Paragraf sayisi uyusmazsa cumle gruplarina dus."""
    raw = (script or "").strip()
    chapters = sorted(job.chapters, key=lambda c: int(c.get("index", 0)))
    if not chapters or not raw:
        return False

    parts = [p.strip() for p in raw.split("\n\n") if p.strip()]
    if len(parts) == len(chapters):
        for ch, part in zip(chapters, parts):
            ch["script"] = part
            ch["video_script"] = part
            if ch.get("state") == -1:
                ch["state"] = 0
            ch.pop("error", None)
        return True

    # Cumle bazli esit bolme (model tek blok veya farkli paragraf sayisi verdiyse)
    from akifactory.script_quality import _split_sentences

    sents = _split_sentences(raw)
    if len(sents) < len(chapters):
        return False
    n = len(chapters)
    base = len(sents) // n
    rem = len(sents) % n
    idx = 0
    for i, ch in enumerate(chapters):
        take = base + (1 if i < rem else 0)
        chunk = " ".join(sents[idx : idx + take]).strip()
        idx += take
        if len(chunk) < 40:
            return False
        ch["script"] = chunk
        ch["video_script"] = chunk
        if ch.get("state") == -1:
            ch["state"] = 0
        ch.pop("error", None)
    return True


async def review_longform_full_script(job: LongformJob, script: str) -> str:
    """Tam senaryo — tutarlilik, Turkce kalite, son editor incelemesi."""
    from akifactory import llm_profiles as llm_prof
    from akifactory.content_studio import EDITOR_CHAT_OPTIONS
    from akifactory.ollama_util import chat as ollama_chat

    base = (script or "").strip()
    if len(base) < 80:
        return base

    await ollama_util.release_vram_for_model_swap()
    installed = await ollama_util.list_installed_models()
    editor = llm_prof.resolve_editor_model(installed, job.common.get("editor_model"))
    niche = job.common.get("niche", "genel")
    niche_label = script_pr.NICHE_LABELS.get(niche, niche)
    outline = _chapter_outline(job)

    prompt = f"""Sen uzun belgesel video SON KALE editörsün.

ANA KONU: {job.main_subject.strip()}
NIS: {niche_label}
BOLUM PLANI ({len(job.chapters)} bolum):
{outline}

ASAGIDA TUM BOLUMLERIN BIRLESTIRILMIS SENARYOSU VAR (bolumler bos satirla ayrilmis):

{base}

GOREV — son inceleme:
1) Bolumler arasi tutarlilik; ayni ekspozisyonu (yil+yer+grup tanitimi) her bolumde TEKRARLAMA — orta bolumler anlatima devam etsin
2) Turkce: dogal konusma dili; Turkce karakterler zorunlu (ç ğ ı ö ş ü) — ASCII yasak
3) Bariz olumsuz/tarihsel hatalari yumusat; emin degilsen ekleme
4) Her bolum ~45-55 sn konusma uzunlugunda kalsin
5) Bolum sayisi ve sira DEGISMEZ; ayni yapi korunur
6) Ilk bolum guclu hook, sonraki bolumler oncekinin bitisinden devam, son bolum kapanis
7) Alt basliklari veya plan maddelerini sesli okuyan cumleleri kaldir; icerik dogrudan anlatilsin
8) Her bolum «1959'da / Rusya'da bir grup…» diye sifirdan basliyorsa ortadaki acilislari devam sahnesine cevir

CIKTI: Sadece duzeltilmis TAM senaryo. Bolumler arasinda tek bos satir. Aciklama yok."""

    reviewed = await ollama_chat(
        [{"role": "user", "content": prompt}],
        model=editor,
        think=False,
        clean_script=False,
        options={**EDITOR_CHAT_OPTIONS, "temperature": 0.35},
        timeout=180.0,
    )
    cleaned = text_utils.prepare_script_for_engine((reviewed or "").strip(), "tr") or (reviewed or "").strip()
    if len(cleaned) < len(base) * 0.45:
        return base
    return text_utils.enforce_longform_full_script_limits(cleaned)


async def _produce_chapter_assets(
    client: httpx.AsyncClient,
    engine_base: str,
    job: LongformJob,
    ch: dict[str, Any],
    *,
    lang_id: str,
    chapter_no: int,
    chapter_total: int,
    reuse_materials: list[str] | None = None,
) -> str:
    idx = int(ch.get("index", 0))
    slug = ch.get("folder_slug") or lf_gal_mod.chapter_folder_slug(idx, ch.get("title") or "")
    ch["folder_slug"] = slug
    script_key = "en_script" if lang_id == "en" else "script"
    script = (ch.get(script_key) or ch.get("video_script") or "").strip()
    if not script:
        raise RuntimeError(f"Bolum {chapter_no} senaryosu bos")
    subject = (
        ch.get("display_title")
        or full_chapter_heading(job.main_subject, ch.get("title") or "")
    ).strip()
    job.step = f"Bolum {chapter_no}/{chapter_total}: ses + altyazi ({lang_id.upper()}) — {ch.get('title') or slug}"

    def _tick(td: dict[str, Any]) -> None:
        local = int(td.get("progress", 0) or 0)
        base = 15 + int(75 * (chapter_no - 1) / max(chapter_total, 1))
        span = max(75 // max(chapter_total, 1), 8)
        job.progress = min(95, base + int(local * span / 100))

    common = batch_mod._voice_common_for_lang(dict(job.common), lang_id)
    common["production_language"] = lang_id
    common["_video_subject"] = subject
    if reuse_materials:
        common["video_source"] = "local"
        common["_video_materials"] = reuse_materials
    else:
        resolved_source = await vid_src.resolve_video_source(
            common.get("video_source", "pexels"),
            subject,
        )
        common["video_source"] = resolved_source

    item = {"topic": subject, "video_script": script}
    payload = batch_mod._build_engine_payload(item, common)
    task_id = await batch_mod._start_engine_subtitle(
        client, engine_base, payload, common.get("outro_id")
    )

    await batch_mod._wait_engine_task(
        client,
        engine_base,
        task_id,
        cancelled=lambda: job.cancelled,
        on_tick=_tick,
    )
    _save_script_txt(task_id, script)

    from akifactory.gallery import task_montage_paths

    paths = task_montage_paths(task_id)
    if "audio" not in paths:
        raise RuntimeError(
            f"Bolum {chapter_no}/{chapter_total}: ses dosyasi olusmadi ({lang_id.upper()})"
        )
    if "subtitle" not in paths:
        raise RuntimeError(
            f"Bolum {chapter_no}/{chapter_total}: altyazi dosyasi olusmadi ({lang_id.upper()})"
        )

    if not reuse_materials:
        job.step = f"Bolum {chapter_no}/{chapter_total}: gorseller indiriliyor"
        exclude = {
            str(u).strip()
            for u in (job.common.get("_stock_exclude_urls") or [])
            if str(u).strip()
        }
        # Tum bolum gorselleri tek klasorde: data/longform/{id}/clips/
        clips_dir = _export_dir(job) / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)
        _download_materials_for_task(
            task_id, common, exclude_urls=exclude, dest_dir=clips_dir
        )
        # common mute set guncellendi — job'a yaz
        merged = set(job.common.get("_stock_exclude_urls") or [])
        merged |= set(common.get("_stock_exclude_urls") or [])
        merged |= exclude
        job.common["_stock_exclude_urls"] = sorted(merged)

    export = _export_dir(job)
    bundle = lf_gal_mod.export_chapter_bundle(
        export,
        slug=slug,
        task_id=task_id,
        lang=lang_id,
        script=script,
        title=subject,
        copy_task_clips=False,  # gorseller zaten ortak clips/ icinde
    )
    if not bundle.get("audio"):
        raise RuntimeError(f"Bolum {chapter_no}: ses pakete kopyalanamadi")
    if not bundle.get("subtitle"):
        raise RuntimeError(f"Bolum {chapter_no}: altyazi pakete kopyalanamadi")
    return task_id


async def _produce_all_chapters(
    client: httpx.AsyncClient,
    engine_base: str,
    job: LongformJob,
    *,
    lang_id: str,
    reuse_by_tr_task: dict[str, list[str]] | None = None,
    skip_completed: bool = False,
) -> None:
    chapters = sorted(job.chapters, key=lambda c: int(c.get("index", 0)))
    total = len(chapters)
    for i, ch in enumerate(chapters, start=1):
        if job.cancelled:
            raise RuntimeError("Iptal edildi")
        if skip_completed:
            if lang_id == "en" and (ch.get("en_task_id") or "").strip():
                continue
            if lang_id != "en" and (ch.get("task_id") or "").strip():
                continue
        # Senaryosu basarisiz bolumu atla — diger bolumlere devam
        if ch.get("state") == -1 and not (ch.get("script") or ch.get("video_script") or "").strip():
            job_log.warn(
                job.longform_id,
                f"Bolum {i} atlandi (senaryo yok): {ch.get('error') or ''}",
            )
            continue
        job.current_chapter = int(ch.get("index", 0))
        reuse = None
        if reuse_by_tr_task and lang_id == "en":
            tr_tid = (ch.get("task_id") or "").strip()
            reuse = reuse_by_tr_task.get(tr_tid)
        try:
            job_log.info(
                job.longform_id,
                f"Uretim basliyor: bolum {i}/{total} lang={lang_id}",
            )
            task_id = await _produce_chapter_assets(
                client,
                engine_base,
                job,
                ch,
                lang_id=lang_id,
                chapter_no=i,
                chapter_total=total,
                reuse_materials=reuse,
            )
            if lang_id == "en":
                ch["en_task_id"] = task_id
            else:
                ch["task_id"] = task_id
            ch["state"] = 1
            ch.pop("error", None)
        except Exception as exc:
            err = str(exc) or "Bolum uretim hatasi"
            ch["state"] = -1
            ch["error"] = err
            job_log.error(job.longform_id, f"Bolum {i} uretim hatasi: {err}")
            continue
    if chapters:
        job.task_id = next(
            (c.get("task_id") for c in chapters if c.get("task_id")),
            chapters[0].get("task_id"),
        )
        if lang_id == "en":
            job.en_task_id = next(
                (c.get("en_task_id") for c in chapters if c.get("en_task_id")),
                chapters[0].get("en_task_id"),
            )


def _mp3_duration(path: Path) -> float:
    try:
        from akifactory.engine.services import voice

        d = float(voice.get_audio_duration(str(path)))
        return d if d > 0 else 0.0
    except Exception:
        return 0.0


def _load_task_search_terms(task_id: str) -> list[str]:
    script_file = engine_task_dir(task_id) / "script.json"
    if not script_file.is_file():
        return []
    try:
        data = json.loads(script_file.read_text(encoding="utf-8"))
        terms = data.get("search_terms") or []
        if isinstance(terms, str):
            return [t.strip() for t in terms.split(",") if t.strip()]
        if isinstance(terms, list):
            return [str(t).strip() for t in terms if str(t).strip()]
    except Exception:
        pass
    return []


def _download_materials_for_task(
    task_id: str,
    common: dict[str, Any],
    *,
    exclude_urls: set[str] | None = None,
    dest_dir: Path | str | None = None,
) -> list[str]:
    from akifactory.engine.models.schema import VideoAspect, VideoConcatMode

    from akifactory import platforms as plat_mod
    from akifactory.stock_materials import download_mixed_stock_materials
    from akifactory.stock_registry import normalize_stock_url

    terms = _load_task_search_terms(task_id)
    if not terms:
        subj = (common.get("_video_subject") or "").strip()
        terms = [subj] if subj else ["documentary"]
    audio_path = engine_task_dir(task_id) / "audio.mp3"
    duration = _mp3_duration(audio_path)
    if duration <= 0:
        duration = 600.0
    platform_id = common.get("platform", "youtube")
    p = plat_mod.resolve(platform_id)
    aspect = common.get("video_aspect") or p.get("aspect_ratio") or "16:9"
    clip = int(
        common.get("video_clip_duration")
        or plat_mod.longform_clip_duration(aspect, platform_id)
    )
    source = common.get("video_source", "pexels")
    blocked: set[str] = set(exclude_urls or ())
    blocked |= {
        normalize_stock_url(u)
        for u in (common.get("_stock_exclude_urls") or [])
        if normalize_stock_url(u)
    }
    target = str(dest_dir).strip() if dest_dir else ""
    if target:
        Path(target).mkdir(parents=True, exist_ok=True)
    paths = download_mixed_stock_materials(
        task_id=task_id,
        search_terms=terms,
        source=source,
        video_aspect=VideoAspect(aspect),
        video_contact_mode=VideoConcatMode.sequential,
        audio_duration=duration,
        max_clip_duration=clip,
        exclude_urls=blocked,
        dest_dir=target or None,
    )
    # download_mixed mute set'i gunceller — sonraki bolumlere aktar
    common["_stock_exclude_urls"] = sorted(blocked)
    return paths


def _save_script_txt(task_id: str, script: str) -> None:
    if not script.strip():
        return
    path = engine_task_dir(task_id) / "script.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(script.strip(), encoding="utf-8")


def _persist_job_meta(job: LongformJob) -> None:
    export = _export_dir(job)
    meta = {
        "longform_id": job.longform_id,
        "main_subject": job.main_subject,
        "task_id": job.task_id,
        "en_task_id": job.en_task_id,
        "script": job.script,
        "en_script": job.en_script,
        "chapters": job.chapters,
        "common": job.common,
    }
    (export / "job-meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _export_dir(job: LongformJob) -> Path:
    out = data_dir() / "longform" / job.longform_id
    out.mkdir(parents=True, exist_ok=True)
    return out


async def _produce_assets_bundle(
    client: httpx.AsyncClient,
    engine_base: str,
    job: LongformJob,
    *,
    lang_id: str,
    script: str,
    video_subject: str,
    reuse_materials: list[str] | None = None,
) -> str:
    common = batch_mod._voice_common_for_lang(dict(job.common), lang_id)
    common["production_language"] = lang_id
    common["_video_subject"] = video_subject
    if reuse_materials:
        common["video_source"] = "local"
        common["_video_materials"] = reuse_materials
    else:
        resolved_source = await vid_src.resolve_video_source(
            common.get("video_source", "pexels"),
            video_subject,
        )
        common["video_source"] = resolved_source

    item = {"topic": video_subject, "video_script": script}
    payload = batch_mod._build_engine_payload(item, common)
    if not (payload.get("video_script") or "").strip():
        raise RuntimeError("Senaryo bos — uretim baslatilamadi.")

    def _tick(td: dict[str, Any]) -> None:
        job.progress = int(td.get("progress", 0) or 0)
        job.step = batch_mod.progress_step_label(job.progress)

    task_id = await batch_mod._start_engine_subtitle(
        client, engine_base, payload, common.get("outro_id")
    )

    def _cancelled() -> bool:
        return job.cancelled

    td = await batch_mod._wait_engine_task(
        client,
        engine_base,
        task_id,
        cancelled=_cancelled,
        on_tick=_tick,
    )
    final_script = (td.get("script") or script or "").strip()
    _save_script_txt(task_id, final_script)

    if not reuse_materials:
        job.progress = max(job.progress, 85)
        job.step = "Gorseller indiriliyor"
        exclude = {
            str(u).strip()
            for u in (job.common.get("_stock_exclude_urls") or [])
            if str(u).strip()
        }
        clips_dir = _export_dir(job) / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)
        _download_materials_for_task(
            task_id, common, exclude_urls=exclude, dest_dir=clips_dir
        )
        merged = set(job.common.get("_stock_exclude_urls") or [])
        merged |= set(common.get("_stock_exclude_urls") or [])
        merged |= exclude
        job.common["_stock_exclude_urls"] = sorted(merged)

    return task_id


async def plan_chapters(
    subject: str,
    niche_id: str = "genel",
    count: int = 11,
) -> list[str]:
    subj = subject.strip()
    if len(subj) < 2:
        return []
    niche = script_pr.resolve_niche(niche_id)
    label = script_pr.NICHE_LABELS.get(niche, niche)
    n = max(8, min(12, int(count or 11)))
    prompt = (
        f"Sen {label} nişinde YouTube belgesel / uzun video editörüsün.\n"
        f"ANA KONU (SABIT — degismez): {subj}\n"
        f"Gorev: Bu TEK ana konuyu {n} bolumluk seriye bol. Her satir yalnizca KISA ALT BASLIK olmali.\n"
        f"Her bolum ~45–55 sn konusma; montajda tek videoda birlestirilecek.\n\n"
        f"KURALLAR:\n"
        f"- Her satir «{subj}» ana konusunun bir alt basligi (tarihcesi, kesfi, icerigi gibi)\n"
        f"- Ana konu adini TEKRARLAMA; sadece kisa alt basligi yaz (ornek: tarihcesi, kesfi)\n"
        f"- Yeni ana konu, baska video konusu YASAK\n"
        f"- Bolumler tek hikaye: giris → gelisme → sonuc\n"
        f"- Ilk bolum hook/giris alt basligi, son bolum kapanis alt basligi\n"
        f"- Numara veya madde isareti kullanma\n\n"
        f"Ornek ana konu: Voynich el yazmasi\n"
        f"DOGRU alt basliklar:\n"
        f"tarihcesi\n"
        f"kesfi\n"
        f"icerigi ve dili\n"
        f"sifre cozme girisimleri\n"
        f"YANLIS (ayri konu — yazma):\n"
        f"Atlantis efsanesi\n"
        f"Rosetta tasi\n"
        f"Sadece Turkce karakterlerle {n} satir kisa alt baslik yaz."
    )
    text = await script_pr.ollama_chat(
        [{"role": "user", "content": prompt}],
        think=False,
        clean_script=False,
    )
    if not text:
        return []
    lines = [ln.strip().lstrip("0123456789.-) ").strip() for ln in text.splitlines()]
    out: list[str] = []
    seen: set[str] = set()
    for ln in lines:
        if len(ln) <= 2:
            continue
        key = ln.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(_normalize_chapter_title(ln, subj))
        if len(out) >= n:
            break
    return out


def _parse_brainstorm(text: str) -> dict[str, Any]:
    """LLM etiketli metnini bolumlere ayir (ODAK/ACILAR/HOOK/NOKTALAR/TON/BOLUMLER)."""
    sections: dict[str, list[str]] = {
        "odak": [],
        "acilar": [],
        "hook": [],
        "noktalar": [],
        "ton": [],
        "bolumler": [],
    }
    aliases = {
        "odak": "odak",
        "focus": "odak",
        "acilar": "acilar",
        "açilar": "acilar",
        "açılar": "acilar",
        "aci": "acilar",
        "hook": "hook",
        "giris": "hook",
        "giriş": "hook",
        "noktalar": "noktalar",
        "ana noktalar": "noktalar",
        "anahtar noktalar": "noktalar",
        "ton": "ton",
        "bolumler": "bolumler",
        "bölümler": "bolumler",
        "bolum": "bolumler",
    }
    current: str | None = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        head_match = None
        if ":" in line:
            head, _, rest = line.partition(":")
            key = head.strip().lower()
            if key in aliases:
                head_match = aliases[key]
                current = head_match
                rest = re.sub(r"^\s*(?:[-*•]|\d{1,2}[.)])\s*", "", rest).strip()
                if rest:
                    sections[current].append(rest)
                continue
        if current is None:
            continue
        item = re.sub(r"^\s*(?:[-*•]|\d{1,2}[.)])\s*", "", line).strip()
        if item:
            sections[current].append(item)

    def _one(key: str) -> str:
        return " ".join(sections[key]).strip()

    return {
        "summary": _one("odak"),
        "angles": [x for x in sections["acilar"] if x][:6],
        "hooks": [x for x in sections["hook"] if x][:4],
        "key_points": [x for x in sections["noktalar"] if x][:8],
        "tone": _one("ton"),
        "chapters": [x for x in sections["bolumler"] if len(x) > 2][:12],
    }


def _parse_plan_questions(text: str) -> list[dict[str, Any]]:
    """LLM etiketli metnini soru listesine ayir (SORU/COKLU/SECENEKLER)."""
    questions: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    mode = ""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("soru"):
            _, _, rest = line.partition(":")
            if cur and cur.get("options"):
                questions.append(cur)
            cur = {"question": rest.strip(), "options": [], "allow_multiple": False}
            mode = "q"
            continue
        if cur is None:
            continue
        if low.startswith("coklu") or low.startswith("çoklu"):
            _, _, rest = line.partition(":")
            cur["allow_multiple"] = rest.strip().lower().startswith(("evet", "e", "yes"))
            mode = "q"
            continue
        if low.startswith("secenekler") or low.startswith("seçenekler") or low.startswith("secenek"):
            mode = "opt"
            _, _, rest = line.partition(":")
            item = re.sub(r"^\s*(?:[-*•]|\d{1,2}[.)])\s*", "", rest).strip()
            if item:
                cur["options"].append(item)
            continue
        item = re.sub(r"^\s*(?:[-*•]|\d{1,2}[.)])\s*", "", line).strip()
        if mode == "opt" and item:
            cur["options"].append(item)
        elif mode == "q" and not cur.get("question"):
            cur["question"] = item
    if cur and cur.get("options"):
        questions.append(cur)

    out: list[dict[str, Any]] = []
    for i, q in enumerate(questions):
        opts = [o for o in q.get("options", []) if len(o) > 1][:4]
        text_q = (q.get("question") or "").strip()
        if not text_q or len(opts) < 2:
            continue
        out.append(
            {
                "id": f"q{i + 1}",
                "question": text_q,
                "options": opts,
                "allow_multiple": False,
            }
        )
        if len(out) >= 6:
            break
    return out


async def plan_questions(
    subject: str,
    niche_id: str = "genel",
    draft_chapters: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Uzun video icin planlama sorulari — her biri tek secimli."""
    subj = (subject or "").strip()
    if len(subj) < 2:
        return []
    niche = script_pr.resolve_niche(niche_id)
    label = script_pr.NICHE_LABELS.get(niche, niche)
    drafts = [str(c).strip() for c in (draft_chapters or []) if str(c).strip()][:12]
    draft_block = ""
    if drafts:
        draft_block = (
            "\nTASLAK BOLUM PLANI (bunlara gore soru sor):\n"
            + "\n".join(f"- {c}" for c in drafts)
            + "\n"
        )
    prompt = (
        f"Sen {label} nisinde YouTube belgesel yapimcisisin.\n"
        f"ANA KONU: {subj}\n"
        f"{draft_block}"
        "Gorev: Bu uzun video (~10 dk) icin kullaniciya SORACAGIN 4-5 planlama sorusu uret. "
        "Her soru bir yapim kararini netlestirsin (anlatim acisi, ton, hedef kitle, odak alt konu, hook tarzi gibi).\n"
        "KRITIK: Her soruda kullanici YALNIZCA BIR secenek secebilir — COKLU secim YOK.\n"
        "Her soru icin 3-4 SOMUT, birbirinden farkli hazir secenek ver.\n\n"
        "Yanitini SADECE su etiketli formatta, Turkce karakterlerle yaz (baska aciklama yok):\n\n"
        "SORU: (soru metni)\n"
        "COKLU: hayir\n"
        "SECENEKLER:\n"
        "- (secenek 1)\n"
        "- (secenek 2)\n"
        "- (secenek 3)\n"
        "SORU: (sonraki soru)\n"
        "COKLU: hayir\n"
        "SECENEKLER:\n"
        "- ...\n\n"
        "Tum sorularda COKLU: hayir yaz."
    )
    text = await ollama_util.chat(
        [{"role": "user", "content": prompt}],
        think=False,
        clean_script=False,
        timeout=150.0,
    )
    if not text:
        return []
    return _parse_plan_questions(text)


async def brainstorm_topic(
    subject: str,
    niche_id: str = "genel",
    *,
    note: str = "",
    prior: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Uzun video icin beyin firtinasi — konuyu birlikte planla."""
    subj = (subject or "").strip()
    if len(subj) < 2:
        return {}
    niche = script_pr.resolve_niche(niche_id)
    label = script_pr.NICHE_LABELS.get(niche, niche)
    user_note = (note or "").strip()

    prior_block = ""
    if prior:
        prior_ch = prior.get("chapters") or []
        if prior_ch:
            prior_block = (
                "\nONCEKI PLAN (kullanici geri bildirimine gore GELISTIR, sifirdan yazma):\n"
                + "\n".join(f"- {c}" for c in prior_ch[:12])
                + "\n"
            )

    note_block = ""
    if user_note:
        note_block = (
            f"\nKULLANICININ YONLENDIRMESI (buna oncelik ver): {user_note}\n"
            "Kullanicinin secimlerini plana entegre et; bolum basliklarini buna gore GUNCELLE.\n"
        )

    prompt = (
        f"Sen {label} nisinde deneyimli bir YouTube belgesel yapimcisisin.\n"
        f"ANA KONU: {subj}\n"
        f"Gorev: Bu konu icin bir uzun video (~10 dk) BEYIN FIRTINASI yap. "
        f"Izleyiciyi ekranda tutacak acilar, hook ve islenecek noktalari dusun.\n"
        f"{note_block}{prior_block}\n"
        "Yanitini SADECE su etiketli formatta, Turkce karakterlerle yaz (baska aciklama yok):\n\n"
        "ODAK: (tek cumle — bu videoyu ne benzersiz/merak uyandirici yapar)\n"
        "ACILAR:\n"
        "- (3-5 farkli anlatim acisi / yaklasim fikri)\n"
        "HOOK:\n"
        "- (2-3 carpici acilis cumlesi fikri)\n"
        "NOKTALAR:\n"
        "- (islenmesi gereken 4-7 somut alt konu/olgu)\n"
        "TON: (tek cumle — anlatim tonu onerisi)\n"
        "BOLUMLER:\n"
        "- (8-11 kisa bolum alt basligi; ana konu adini tekrarlama, sadece alt baslik)\n"
    )
    text = await ollama_util.chat(
        [{"role": "user", "content": prompt}],
        think=False,
        clean_script=False,
        timeout=180.0,
    )
    if not text:
        return {}
    parsed = _parse_brainstorm(text)
    parsed["chapters"] = [
        _normalize_chapter_title(c, subj) for c in parsed.get("chapters", [])
    ]
    parsed["subject"] = subj
    return parsed


def _common_without_bgm(common: dict[str, Any]) -> dict[str, Any]:
    out = dict(common)
    out["bgm_mode"] = "none"
    out["bgm_track"] = None
    out["bgm_volume"] = 0.0
    return out


def _task_assets(task_id: str | None) -> dict[str, Any]:
    assets = task_montage_assets(task_id)
    tid = (task_id or "").strip()
    if tid:
        script_path = engine_task_dir(tid) / "script.txt"
        if script_path.is_file() and script_path.stat().st_size > 0:
            assets["script_url"] = f"/api/tasks/{tid}/script"
    return assets


def create_longform(
    main_subject: str,
    chapter_titles: list[str],
    common: dict[str, Any],
    *,
    scripts: list[str] | None = None,
) -> str:
    longform_id = uuid.uuid4().hex[:12]
    main = main_subject.strip()
    titles = [_normalize_chapter_title(t.strip(), main) for t in chapter_titles if t.strip()]
    script_list = scripts or []
    chapters = []
    for i, title in enumerate(titles):
        display = full_chapter_heading(main, title)
        chapters.append(
            {
                "index": i,
                "title": title,
                "display_title": display,
                "topic": display,
            }
        )
        if i < len(script_list) and str(script_list[i] or "").strip():
            chapters[-1]["video_script"] = str(script_list[i] or "").strip()
    _jobs[longform_id] = LongformJob(
        longform_id=longform_id,
        main_subject=main,
        chapters=chapters,
        common=_common_without_bgm(common),
        phase="tr",
    )
    return longform_id


def prepare_retry(
    longform_id: str,
    *,
    auto_retry_failed: bool | None = None,
    auto_retry_rounds: int | None = None,
) -> LongformJob | None:
    job = _jobs.get(longform_id)
    if not job:
        return None
    if job.state == 4:
        return None
    if job.state != -1:
        return None

    fail_idx = max(0, int(job.current_chapter))
    has_any_script = any(
        (ch.get("script") or ch.get("video_script") or "").strip()
        for ch in job.chapters
    )
    all_scripts = all(
        (ch.get("script") or ch.get("video_script") or "").strip()
        for ch in job.chapters
    )
    scripts_ready = bool(job.script_done or all_scripts)
    resume_scripts = bool((job.script or "").strip() or has_any_script)

    job.error = None
    job.state = 0
    job.cancelled = False
    job.task_id = None
    job.en_task_id = None
    job.en_script = job.en_script if scripts_ready else ""

    for ch in job.chapters:
        idx = int(ch.get("index", 0))
        if scripts_ready and idx < fail_idx and (ch.get("task_id") or "").strip():
            continue
        if idx >= fail_idx:
            ch.pop("task_id", None)
            ch.pop("en_task_id", None)
            ch.pop("folder_slug", None)

    if scripts_ready:
        job.script_done = True
        if not (job.script or "").strip():
            job.script = "\n\n".join(
                (ch.get("script") or ch.get("video_script") or "").strip()
                for ch in sorted(job.chapters, key=lambda c: int(c.get("index", 0)))
                if (ch.get("script") or ch.get("video_script") or "").strip()
            )
    elif resume_scripts:
        job.script_done = False
    else:
        job.script_done = False
        job.script = ""
        for ch in job.chapters:
            if int(ch.get("index", 0)) >= fail_idx:
                ch.pop("script", None)
                ch.pop("video_script", None)
                ch.pop("_reviewed", None)

    job.common["resume_production"] = resume_scripts or scripts_ready
    job.progress = max(
        0,
        min(
            90,
            int(15 + 75 * fail_idx / max(len(job.chapters), 1))
            if (resume_scripts or scripts_ready)
            else 0,
        ),
    )
    job.step = (
        "Kaldigi yerden devam ediliyor"
        if (resume_scripts or scripts_ready)
        else "Senaryo yeniden hazirlaniyor"
    )
    dual = bool(job.common.get("dual_language"))
    tr_done = all((ch.get("task_id") or "").strip() for ch in job.chapters)
    if dual and scripts_ready and tr_done:
        job.phase = "en"
    elif dual:
        job.phase = "tr"
    else:
        job.phase = "single"

    if auto_retry_failed is not None:
        job.common["auto_retry_failed"] = bool(auto_retry_failed)
    if auto_retry_rounds is not None:
        job.common["auto_retry_rounds"] = max(0, min(5, int(auto_retry_rounds)))
    return job


async def _run_longform(longform_id: str, engine_base: str) -> None:
    job = _jobs.get(longform_id)
    if not job:
        return
    dual = bool(job.common.get("dual_language"))
    single_lang = job.common.get("production_language", "tr")
    auto_retry = bool(job.common.get("auto_retry_failed", True))
    auto_rounds = max(0, min(5, int(job.common.get("auto_retry_rounds") or 2)))
    passes = 1 + (auto_rounds if auto_retry else 0)

    async with httpx.AsyncClient(timeout=60.0) as client:
        for round_idx in range(passes):
            if job.cancelled:
                break
            if round_idx > 0 and job.state != -1:
                break
            if round_idx > 0:
                job.state = 0
                job.task_id = None
                job.en_task_id = None
                job.error = None
                job.progress = 0

            job.state = 4
            job.phase = "tr" if dual else "single"
            resume_assets = bool(job.common.pop("resume_production", False))
            try:
                if not resume_assets:
                    job.step = "Senaryo hazirlaniyor"
                    job.current_chapter = -1
                    job.script_done = False
                    script = await generate_longform_full_script(job)
                    if job.cancelled:
                        raise RuntimeError("Iptal edildi")
                    job.step = "Tum senaryo son inceleme (editor)"
                    job.progress = 12
                    script = await review_longform_full_script(job, script)
                    job.script = script
                    _split_script_to_chapters(job, script)
                    export = _export_dir(job)
                    (export / "script-tr.txt").write_text(script, encoding="utf-8")
                else:
                    all_scripts = all(
                        (ch.get("script") or ch.get("video_script") or "").strip()
                        for ch in job.chapters
                    )
                    if not all_scripts:
                        job.step = "Eksik bolum senaryolari tamamlanıyor"
                        job.current_chapter = -1
                        script = await generate_longform_full_script(job)
                        if job.cancelled:
                            raise RuntimeError("Iptal edildi")
                        if all(
                            (ch.get("script") or ch.get("video_script") or "").strip()
                            for ch in job.chapters
                        ):
                            job.step = "Tum senaryo son inceleme (editor)"
                            script = await review_longform_full_script(job, script)
                        job.script = script or job.script
                        _split_script_to_chapters(job, job.script)
                        export = _export_dir(job)
                        if job.script:
                            (export / "script-tr.txt").write_text(job.script, encoding="utf-8")
                    else:
                        job.script_done = True
                        if not (job.script or "").strip():
                            job.script = "\n\n".join(
                                (ch.get("script") or ch.get("video_script") or "").strip()
                                for ch in sorted(
                                    job.chapters, key=lambda c: int(c.get("index", 0))
                                )
                                if (ch.get("script") or ch.get("video_script") or "").strip()
                            )
                    job.step = "Senaryo hazir — bolum uretimine devam"
                    job.progress = max(job.progress, 12)

                lang_id = "tr" if dual else str(single_lang)
                tr_done = all((ch.get("task_id") or "").strip() for ch in job.chapters)
                if not tr_done:
                    job.step = "Bolum sesleri ve altyazilari uretiliyor"
                    await _produce_all_chapters(
                        client,
                        engine_base,
                        job,
                        lang_id=lang_id,
                        skip_completed=resume_assets,
                    )

                if dual and not job.cancelled:
                    en_done = all((ch.get("en_task_id") or "").strip() for ch in job.chapters)
                    if not en_done:
                        job.phase = "en"
                        if not job.en_script.strip():
                            job.step = "EN bolum senaryolari ceviriliyor"
                            en_parts: list[str] = []
                            for ch in sorted(job.chapters, key=lambda c: int(c.get("index", 0))):
                                if (ch.get("en_script") or "").strip():
                                    en_parts.append(ch["en_script"].strip())
                                    continue
                                if not (ch.get("script") or "").strip():
                                    ch.setdefault("error", ch.get("error") or "TR senaryo yok")
                                    continue
                                try:
                                    tr_script = (ch.get("script") or "").strip()
                                    en_script = (
                                        await script_tr_mod.translate_script(
                                            tr_script, from_lang="tr", to_lang="en"
                                        )
                                    ).strip()
                                    if not en_script:
                                        raise RuntimeError("EN senaryo cevirisi basarisiz")
                                    ch["en_script"] = en_script
                                    en_parts.append(en_script)
                                except Exception as exc:
                                    err = str(exc) or "EN ceviri hatasi"
                                    ch["error"] = err
                                    if ch.get("state") != 1:
                                        ch["state"] = -1
                                    job_log.error(
                                        job.longform_id,
                                        f"EN ceviri hatasi bolum {ch.get('index')}: {err}",
                                    )
                                    continue
                            job.en_script = "\n\n".join(en_parts)
                            export = _export_dir(job)
                            if job.en_script:
                                (export / "script-en.txt").write_text(
                                    job.en_script, encoding="utf-8"
                                )
                        else:
                            job.step = "EN ses ve altyazi (bolum bolum)"

                        reuse_map: dict[str, list[str]] = {}
                        reuse_tags: list[str] = []
                        try:
                            for ch in sorted(job.chapters, key=lambda c: int(c.get("index", 0))):
                                tr_tid = (ch.get("task_id") or "").strip()
                                if not tr_tid:
                                    continue
                                slug = ch.get("folder_slug") or lf_gal_mod.chapter_folder_slug(
                                    int(ch.get("index", 0)), ch.get("title") or ""
                                )
                                tag = f"lf{job.longform_id[:8]}-en-{slug}"
                                reuse_tags.append(tag)
                                extra = await batch_mod._fetch_engine_task_materials(
                                    client, engine_base, tr_tid
                                )
                                reuse_map[tr_tid] = vid_src.stage_task_clips_for_reuse(
                                    tr_tid, tag, extra_paths=extra or None
                                )
                            job.step = "EN ses ve altyazi (bolum bolum)"
                            await _produce_all_chapters(
                                client,
                                engine_base,
                                job,
                                lang_id="en",
                                reuse_by_tr_task=reuse_map,
                                skip_completed=resume_assets,
                            )
                        finally:
                            for tag in reuse_tags:
                                vid_src.cleanup_reuse_folder(tag)

                if job.cancelled:
                    job.state = -1
                    job.error = "Iptal edildi"
                else:
                    ok_count = sum(1 for ch in job.chapters if ch.get("task_id"))
                    fail_count = sum(
                        1
                        for ch in job.chapters
                        if ch.get("state") == -1 or (ch.get("error") and not ch.get("task_id"))
                    )
                    missing_scripts = sum(
                        1
                        for ch in job.chapters
                        if not (ch.get("script") or ch.get("video_script") or "").strip()
                    )
                    _persist_job_meta(job)
                    if ok_count == 0:
                        job.state = -1
                        job.error = job.error or "Hicbir bolum uretilemedi"
                        job_log.error(job.longform_id, job.error)
                    else:
                        entry = lf_gal_mod.archive_from_job(job)
                        if entry:
                            job.gallery_entry_id = entry.get("id")
                        job.state = 1
                        job.progress = 100
                        total_ch = max(len(job.chapters), 1)
                        if fail_count or missing_scripts or ok_count < total_ch:
                            job.step = (
                                f"Kismi tamamlandi: {ok_count}/{total_ch} bolumde ses+altyazi var. "
                                f"Eksik basliklar icin Tekrar dene."
                            )
                            job.error = (
                                f"{total_ch - ok_count} bolumde ses/altyazi yok "
                                f"(senaryo veya TTS). Galeri klasorunde sadece uretilen basliklar var."
                            )
                            job_log.warn(job.longform_id, job.step)
                        else:
                            job.step = "Tamamlandi"
                            job.error = None
                        job.phase = "done"
            except Exception as exc:
                job.state = -1
                job.error = str(exc) or "Uretim hatasi"
                job_log.error(job.longform_id, job.error)

        await ollama_util.unload_all_models()


async def run_longform(longform_id: str, engine_base: str) -> None:
    await _run_longform(longform_id, engine_base)


async def retry_longform(longform_id: str, engine_base: str) -> None:
    job = prepare_retry(longform_id)
    if not job:
        return
    job.cancelled = False
    await _run_longform(longform_id, engine_base)


def get_longform(longform_id: str) -> dict[str, Any] | None:
    job = _jobs.get(longform_id)
    if not job:
        return None
    if job.state == 1 and not job.gallery_entry_id:
        if job.task_id or any(ch.get("task_id") for ch in job.chapters):
            entry = lf_gal_mod.archive_from_job(job)
            if entry:
                job.gallery_entry_id = entry.get("id")
    dual = bool(job.common.get("dual_language"))
    chapter_count = len(job.chapters)
    chapter_errors = [
        f"Bolum {int(ch.get('index', 0)) + 1}: {ch.get('error')}"
        for ch in job.chapters
        if ch.get("error")
    ]
    errors = list(chapter_errors)
    if job.state == -1 and job.error and job.error not in errors:
        errors.insert(0, job.error)
    chapters_out = []
    for ch in job.chapters:
        idx = int(ch.get("index", 0))
        if ch.get("state") == -1:
            ch_state = -1
        elif job.state == 1 and ch.get("task_id"):
            ch_state = 1
        elif ch.get("task_id"):
            ch_state = 1
        elif job.script_done or job.state == 1:
            ch_state = 1 if (ch.get("script") or ch.get("video_script")) else 0
        elif job.state == -1:
            ch_state = 1 if idx < job.current_chapter else -1 if idx == job.current_chapter else 0
        elif idx < job.current_chapter:
            ch_state = 1
        elif idx == job.current_chapter:
            ch_state = 4
        else:
            ch_state = 0
        ch_task = ch.get("task_id")
        ch_en_task = ch.get("en_task_id")
        chapters_out.append(
            {
                "index": idx,
                "title": ch.get("title", ""),
                "display_title": ch.get("display_title")
                or full_chapter_heading(job.main_subject, ch.get("title") or ""),
                "topic": ch.get("topic")
                or ch.get("display_title")
                or full_chapter_heading(job.main_subject, ch.get("title") or ""),
                "script": ch.get("script") or ch.get("video_script") or "",
                "folder_slug": ch.get("folder_slug") or "",
                "task_id": ch_task,
                "en_task_id": ch_en_task,
                "state": ch_state,
                "error": ch.get("error") or "",
                "assets": _task_assets(ch_task),
                "assets_en": _task_assets(ch_en_task) if dual and ch_en_task else {},
            }
        )
    done_chapters = sum(1 for ch in job.chapters if ch.get("task_id"))
    failed_chapters = sum(
        1 for ch in job.chapters if ch.get("state") == -1 or (ch.get("error") and not ch.get("task_id"))
    )
    return {
        "longform_id": longform_id,
        "mode": "assets",
        "main_subject": job.main_subject,
        "cancelled": job.cancelled,
        "dual_language": dual,
        "phase": job.phase,
        "state": job.state,
        "running": 1 if job.state == 4 else 0,
        "progress": job.progress,
        "step": job.step,
        "error": job.error,
        "script": job.script,
        "en_script": job.en_script,
        "task_id": job.task_id,
        "en_task_id": job.en_task_id,
        "assets": _task_assets(job.task_id),
        "assets_en": _task_assets(job.en_task_id) if dual else {},
        "gallery_entry_id": job.gallery_entry_id,
        "gallery_assets": lf_gal_mod.assets_for_entry(job.gallery_entry_id)
        if job.gallery_entry_id
        else {},
        "export_dir": (
            str(lf_gal_mod.entry_dir(job.gallery_entry_id))
            if job.gallery_entry_id
            else (str(_export_dir(job)) if job.state == 1 else None)
        ),
        "total": chapter_count,
        "total_videos": chapter_count * (2 if dual else 1),
        "done": chapter_count if job.state == 1 and failed_chapters == 0 else done_chapters,
        "failed": failed_chapters if failed_chapters else (1 if job.state == -1 else 0),
        "errors": errors,
        "chapters": chapters_out,
    }


def cancel_longform(longform_id: str) -> bool:
    job = _jobs.get(longform_id)
    if not job:
        return False
    job.cancelled = True
    return True
