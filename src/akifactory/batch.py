"""Seri (batch) video uretim kuyrugu."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

from akifactory import bgm as bgm_mod
from akifactory import content_studio as studio_mod
from akifactory import fonts_util
from akifactory import job_log
from akifactory import lang_presets as lang_pres_mod
from akifactory import languages as lang
from akifactory import llm_profiles as llm_prof
from akifactory import ollama_util
from akifactory import outros as outro_mod
from akifactory import platforms as plat
from akifactory import script_hooks as script_hk
from akifactory import script_prompts as script_pr
from akifactory import script_quality as script_q
from akifactory import script_translate as script_tr_mod
from akifactory import subtitle_styles as sub_st
from akifactory import text_utils
from akifactory import topic_memory as topic_mem
from akifactory import video_source as vid_src

logger = logging.getLogger(__name__)

_batches: dict[str, "BatchJob"] = {}


@dataclass
class BatchJob:
    batch_id: str
    cancelled: bool = False
    tasks: list[dict[str, Any]] = field(default_factory=list)
    common: dict[str, Any] = field(default_factory=dict)
    # AI gorsel pause/resume (task index -> Event / payload)
    ai_waiters: dict[int, asyncio.Event] = field(default_factory=dict)
    ai_resume_data: dict[int, dict[str, Any]] = field(default_factory=dict)


PROGRESS_STEPS = (
    (10, "Senaryo"),
    (20, "Anahtar kelime"),
    (30, "TTS"),
    (35, "AI gorsel"),
    (40, "Goruntu"),
    (50, "Altyazi"),
    (100, "Montaj"),
)

# Chatterbox + RVC tek thread'de uzun surebilir — kisa timeout yanlis "motor olmedi" uyarisi verir
_ENGINE_HTTP_TIMEOUT = httpx.Timeout(30.0, read=900.0)
# motor progress 0'da uzun sure kalirsa (zombi task / kuyruk) — yeniden dene
_ENGINE_STUCK_PROGRESS0_SEC = 480


def progress_step_label(
    progress: int,
    *,
    has_script: bool = False,
    has_task: bool = False,
) -> str:
    """motor progress=0 iken 'Senaryo' yaniltici — motor aslinda TTS/stok/montajda olabilir."""
    p = int(progress or 0)
    if p <= 0:
        if has_task:
            return "Motor (ses/gorsel)"
        if has_script:
            return "Motor baslatiliyor"
        return "Senaryo"
    label = "Baslatiliyor"
    for threshold, name in PROGRESS_STEPS:
        if p < threshold:
            return name
        label = name
    return label


def _video_urls(engine_base: str, videos: list[Any]) -> list[str]:
    urls: list[str] = []
    for v in videos or []:
        if isinstance(v, str):
            urls.append(v if v.startswith("http") else f"{engine_base}/{v.lstrip('/')}")
    return urls


def _apply_lang_preset(common: dict[str, Any], lang_id: str) -> dict[str, Any]:
    out = dict(common)
    preset = lang_pres_mod.get(lang_id)
    if preset.get("tts_engine"):
        out["tts_engine"] = str(preset["tts_engine"])
    if preset.get("edge_voice"):
        out["edge_voice"] = preset["edge_voice"]
    if preset.get("rvc_voice"):
        out["rvc_voice"] = preset["rvc_voice"]
    if "rvc_pitch" in preset:
        out["rvc_pitch"] = int(preset["rvc_pitch"])
    if "rvc_index_rate" in preset:
        out["rvc_index_rate"] = float(preset["rvc_index_rate"])
    if preset.get("voice_rate"):
        out["voice_rate"] = float(preset["voice_rate"])
    if preset.get("subtitle_style_id"):
        out["subtitle_style_id"] = preset["subtitle_style_id"]
    return out


def dual_languages(common: dict[str, Any]) -> tuple[str, str]:
    """Cift dil: (1. video dili, 2. video dili) — ikisi ayni olamaz."""
    primary = str(common.get("production_language") or "tr").strip().lower()[:2] or "tr"
    if primary not in lang.LANGUAGES:
        primary = "tr"
    second = str(common.get("second_language") or "").strip().lower()[:2]
    if second not in lang.LANGUAGES or second == primary:
        second = "en" if primary != "en" else "tr"
    return primary, second


def _edge_voice_for_lang(lid: str, like: str) -> str:
    """Hedef dilin Edge sesi — TR/EN'de dil ayari, digerlerinde ayni cinsiyet."""
    if lid in lang_pres_mod.SUPPORTED:
        preset_voice = lang_pres_mod.get(lid).get("edge_voice")
        if preset_voice:
            return str(preset_voice)
    gender = "-Female" if like.endswith("-Female") else "-Male"
    for v in lang.EDGE_VOICES.get(lid, []):
        if v["id"].endswith(gender):
            return v["id"]
    return lang.resolve(lid).voice_name


def _voice_common_for_lang(base: dict[str, Any], lang_id: str) -> dict[str, Any]:
    """Formdaki ses ayarlarini uretim diline uygular.

    RVC karakteri TR/EN'de korunur; Edge sesi baska dile aitse hedef dilin sesine
    cevrilir. RVC desteklemeyen dilde (DE/FR) Edge'e gecilir.
    """
    if base.get("use_lang_preset"):
        out = _apply_lang_preset(base, lang_id)
        out["production_language"] = lang_id
        return out
    out = dict(base)
    out["production_language"] = lang_id
    lid = (lang_id or "tr").strip().lower()[:2]
    tts = (out.get("tts_engine") or "edge").strip().lower()
    if lid == "en" and base.get("en_tts_engine"):
        out["tts_engine"] = str(base["en_tts_engine"]).strip().lower()
        tts = out["tts_engine"]
    if tts == "rvc" and lid not in ("tr", "en"):
        out["tts_engine"] = tts = "edge"
    ev = (out.get("edge_voice") or "").strip()
    mismatch = bool(ev) and not ev.lower().startswith(f"{lid}-")
    if tts in ("edge", "rvc") and (mismatch or (not ev and lid == "en")):
        out["edge_voice"] = _edge_voice_for_lang(lid, ev)
    return out


def _build_engine_payload(item: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
    platform_id = common.get("platform", "tiktok")
    p = plat.resolve(platform_id)
    prod = lang.resolve(common.get("production_language", "tr"))
    tts_in = (common.get("tts_engine") or "edge").lower()
    tts, _tts_note = lang.resolve_effective_tts_engine(
        tts_in,
        rvc_voice=common.get("rvc_voice"),
        production_language=prod.id,
    )
    common = {**common, "tts_engine": tts}
    voice = lang.resolve_voice(
        prod.id,
        tts,
        common.get("edge_voice"),
        common.get("rvc_voice"),
    )
    if tts == "rvc":
        from akifactory.rvc_util import configure_tts_rvc_chain

        rvc_voice = common.get("rvc_voice")
        configure_tts_rvc_chain(
            tts,
            rvc_voice=rvc_voice,
            rvc_pitch=int(common.get("rvc_pitch", 0)),
            rvc_index_rate=float(common.get("rvc_index_rate", 1.0)),
            production_language=prod.id,
            edge_voice=common.get("edge_voice"),
        )
    elif tts == "chatterbox":
        from akifactory.rvc_util import configure_tts_rvc_chain

        configure_tts_rvc_chain(
            tts,
            rvc_voice=common.get("rvc_voice"),
            rvc_pitch=int(common.get("rvc_pitch", 0)),
            rvc_index_rate=float(common.get("rvc_index_rate", 1.0)),
            production_language=prod.id,
            edge_voice=common.get("edge_voice"),
        )
    else:
        from akifactory.rvc_util import configure_tts_rvc_chain

        configure_tts_rvc_chain(tts)
    lang.sync_subtitle_provider_for_tts(tts)
    style = sub_st.resolve(
        common.get("subtitle_style_id"),
        common.get("subtitle_overrides"),
    )
    aspect = common.get("video_aspect") or p["aspect_ratio"]
    clip = int(common.get("video_clip_duration") or p["max_clip_duration"])
    resolved_source = common.get("video_source", "pexels")
    sub_pos = p.get("subtitle_position", "bottom")
    payload: dict[str, Any] = {
        "video_subject": item["topic"].strip(),
        "video_language": prod.video_language,
        "video_aspect": aspect,
        "video_source": resolved_source,
        "voice_name": voice,
        "voice_rate": float(common.get("voice_rate") or 1.08),
        "voice_volume": 1.0,
        "video_count": 1,
        "video_clip_duration": clip,
        "paragraph_number": 1,
        "subtitle_enabled": True,
        "bgm_volume": common.get("bgm_volume", 0.2),
        "font_size": 56,
        "stroke_width": 1.5,
        "subtitle_position": sub_pos,
    }
    if sub_pos == "center":
        payload["subtitle_position"] = "center"
    bgm_type, bgm_file = bgm_mod.resolve_bgm_payload(
        mode=common.get("bgm_mode", "niche"),
        track=common.get("bgm_track"),
        niche_id=common.get("niche"),
    )
    payload["bgm_type"] = bgm_type
    payload["bgm_file"] = bgm_file
    item["bgm_file"] = bgm_file
    sub_st.apply_to_payload(payload, style)
    # Platform konumu stil uzerinde kazanir (TikTok/Shorts alt, Reels orta)
    # Ozel stil override'i varsa onu koru
    ov = common.get("subtitle_overrides") or {}
    if ov.get("subtitle_position"):
        payload["subtitle_position"] = ov["subtitle_position"]
    else:
        payload["subtitle_position"] = sub_pos
    if payload.get("subtitle_enabled", True):
        payload["font_name"] = fonts_util.ensure_subtitle_font(prod.id)
    script_pr.apply_to_payload(
        payload,
        lang_id=prod.id,
        platform_id=platform_id,
        niche_id=common.get("niche", "genel"),
        subject=item.get("topic", ""),
    )
    if len(payload.get("custom_system_prompt") or "") > 8000:
        payload["custom_system_prompt"] = (payload["custom_system_prompt"] or "")[:8000]
    if len(payload.get("video_script_prompt") or "") > 2000:
        payload["video_script_prompt"] = (payload["video_script_prompt"] or "")[:2000]
    raw_script = (item.get("video_script") or "").strip()
    if raw_script:
        cleaned = (
            text_utils.prepare_script_for_engine(
                raw_script,
                prod.id,
                niche_id=common.get("niche", "genel"),
            )
            or raw_script
        )
        payload["video_script"] = cleaned.strip() or raw_script
        payload["custom_system_prompt"] = ""
        payload["video_script_prompt"] = ""
    if resolved_source == "local":
        materials = vid_src.list_local_materials()
        if materials:
            payload["video_materials"] = materials
            payload["video_concat_mode"] = "sequential"
    elif resolved_source != "local":
        payload["video_concat_mode"] = "sequential"
    staged = common.get("_video_materials")
    if staged:
        payload["video_source"] = "local"
        payload["video_materials"] = staged
        payload["video_concat_mode"] = "sequential"
    return payload


async def _finalize_batch_script(
    script_text: str,
    topic: str,
    common: dict[str, Any],
    *,
    research_brief: str = "",
) -> str:
    ollama = await ollama_util.fetch_status(probe=False)
    installed = ollama.get("models") or []
    writer, editor = llm_prof.resolve_script_models(
        installed, common.get("writer_model"), common.get("editor_model")
    )
    return await studio_mod.finalize_script(
        script_text,
        topic=topic,
        platform=common.get("platform", "tiktok"),
        niche_id=common.get("niche", "genel"),
        editor_model=editor,
        dual_llm=bool(common.get("dual_llm")),
        strengthen=bool(common.get("strengthen_hook", True)),
        web_verify=bool(common.get("editor_web_verify", True)),
        research_brief=research_brief,
        lang_id=common.get("production_language", "tr"),
    )


async def _generate_batch_script(topic: str, common: dict[str, Any]) -> str:
    lang_id = common.get("production_language", "tr")
    platform_id = common.get("platform", "tiktok")
    niche_id = common.get("niche", "genel")
    script_text = ""
    use_web = studio_mod.should_use_web_research(
        niche_id, bool(common.get("editor_web_verify", True))
    )
    research_brief = ""

    if use_web and not common.get("dual_llm"):
        ollama = await ollama_util.fetch_status(probe=False)
        installed = ollama.get("models") or []
        _w, editor = llm_prof.resolve_script_models(
            installed, common.get("writer_model"), common.get("editor_model")
        )
        research_brief, _ = await studio_mod.fetch_topic_research(
            topic,
            lang_id=lang_id,
            niche_id=niche_id,
            model=editor,
        )
        await ollama_util.release_vram_for_model_swap()

    if common.get("dual_llm"):
        ollama = await ollama_util.fetch_status(probe=False)
        installed = ollama.get("models") or []
        writer, editor = llm_prof.resolve_script_models(
            installed, common.get("writer_model"), common.get("editor_model")
        )
        pack = await studio_mod.two_pass_script(
            subject=topic,
            lang_id=lang_id,
            platform_id=platform_id,
            niche_id=niche_id,
            paragraph_number=1,
            writer_model_name=writer,
            editor_model=editor,
            web_verify=bool(common.get("editor_web_verify", True)),
            experimental_template=bool(common.get("niche_experimental")),
        )
        script_text = (pack.get("script") or "").strip()
        research_brief = (pack.get("research_brief") or "").strip()
        # Dual zaten fact-check yapti — finalize'da tekrar web dogrulama yok
        return await _finalize_batch_script(
            script_text,
            topic,
            {**common, "editor_web_verify": False},
            research_brief="",
        )

    if not script_text:
        ollama = await ollama_util.fetch_status(probe=False)
        installed = ollama.get("models") or []
        writer = llm_prof.resolve_writer_model(installed, common.get("writer_model"))
        script_text = (
            await script_pr.generate_script_text(
                subject=topic,
                lang_id=lang_id,
                platform_id=platform_id,
                niche_id=niche_id,
                experimental_template=bool(common.get("niche_experimental")),
                research_context=research_brief,
                writer_model=writer,
            )
        ).strip()

    return await _finalize_batch_script(
        script_text, topic, common, research_brief=research_brief
    )


async def generate_batch_script_with_retry(
    topic: str,
    common: dict[str, Any],
    *,
    attempts: int = 3,
) -> str:
    """Ollama gecici hatalarinda bolum senaryosunu yeniden dener."""
    import asyncio

    niche_id = common.get("niche", "genel")
    last_err = ""
    for attempt in range(max(1, attempts)):
        try:
            if attempt > 0:
                await asyncio.sleep(1.5 + attempt * 2.0)
                try:
                    await ollama_util.probe_model(ollama_util.get_config_model(), force=True)
                except Exception:
                    pass
            script_text = (await _generate_batch_script(topic, common)).strip()
            if len(script_text) >= 10:
                if script_q.is_script_acceptable(
                    script_text, topic, niche_id=niche_id
                ):
                    return script_text
                issues = script_q.script_quality_issues(
                    script_text, topic, niche_id=niche_id
                )
                last_err = "Senaryo kalite kontrolu: " + ", ".join(issues[:4])
                # Kisa metni genislet — az_cumle dongusunu kir (tam yeniden uretimden once)
                if "az_cumle" in issues or "cok_kisa" in issues:
                    ollama = await ollama_util.fetch_status(probe=False)
                    installed = ollama.get("models") or []
                    writer = llm_prof.resolve_writer_model(
                        installed, common.get("writer_model")
                    )
                    expanded = (
                        await studio_mod.expand_short_script(
                            script_text,
                            topic=topic,
                            niche_id=niche_id,
                            writer_model=writer,
                        )
                    ).strip()
                    if expanded and script_q.is_script_acceptable(
                        expanded, topic, niche_id=niche_id
                    ):
                        return expanded
                    if expanded:
                        issues2 = script_q.script_quality_issues(
                            expanded, topic, niche_id=niche_id
                        )
                        last_err = "Senaryo kalite kontrolu: " + ", ".join(issues2[:4])
            else:
                last_err = "Senaryo bos veya cok kisa"
        except Exception as exc:
            last_err = str(exc) or "Senaryo hatasi"
    raise RuntimeError(
        f"Senaryo uretilemedi (Ollama, {attempts} deneme). "
        f"ollama serve ve model kontrol edin."
        + (f" ({last_err})" if last_err else "")
    )


async def _fetch_engine_task_materials(
    client: httpx.AsyncClient, engine_base: str, task_id: str
) -> list[str]:
    try:
        r = await client.get(f"{engine_base}/api/v1/tasks/{task_id}")
        if r.status_code != 200:
            return []
        raw = (r.json().get("data") or {}).get("materials") or []
        out: list[str] = []
        for m in raw:
            if isinstance(m, str) and m.strip():
                from pathlib import Path

                p = Path(m)
                if p.is_file():
                    out.append(str(p))
        return out
    except Exception:
        return []


def _engine_error_detail(data: dict[str, Any], fallback: str) -> str:
    """motor tum dogrulama hatalarini 'field required' olarak maskeler; gercek
    alan(lar)i data icindeki hata listesinden cikarip anlamli mesaj uretir."""
    errors = data.get("data")
    if isinstance(errors, list) and errors:
        parts: list[str] = []
        for err in errors:
            if not isinstance(err, dict):
                continue
            loc = err.get("loc") or []
            field_name = ".".join(str(x) for x in loc if x != "body")
            msg = err.get("msg") or ""
            parts.append(f"{field_name}: {msg}" if field_name else msg)
        detail = " · ".join(p for p in parts if p)
        if detail:
            return f"{fallback} ({detail})"
    return data.get("message") or fallback


def _subtitle_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """motor SubtitleRequest semasina uygun hale getir.

    - subtitle_enabled: SubtitleRequest'te str; bool pydantic v2'de reddedilir
      (motor bunu 'field required' olarak gosterir).
    - video_source: 'local' olmali; aksi halde motor video_terms arar ama
      SubtitleRequest'te yok — uzun videoda gorseller zaten ayri indirilir.
    """
    body = dict(payload)
    if "subtitle_enabled" in body and isinstance(body["subtitle_enabled"], bool):
        body["subtitle_enabled"] = "true" if body["subtitle_enabled"] else "false"
    body["video_source"] = "local"
    return body


async def _start_engine_subtitle(
    client: httpx.AsyncClient,
    engine_base: str,
    payload: dict[str, Any],
    outro_id: str | None,
) -> str:
    """Ses + altyazi (montaj yok)."""
    r = await client.post(
        f"{engine_base}/api/v1/subtitle", json=_subtitle_payload(payload)
    )
    data = r.json()
    if r.status_code >= 400:
        raise RuntimeError(_engine_error_detail(data, "Ses/altyazi baslatilamadi"))
    task_id = (data.get("data") or {}).get("task_id")
    if not task_id:
        raise RuntimeError("task_id alinamadi")
    if outro_id:
        outro_mod.register_task_outro(task_id, outro_id)
    from akifactory import task_timing as tt_mod

    tt_mod.record_start(task_id)
    return task_id


async def _start_engine_video(
    client: httpx.AsyncClient,
    engine_base: str,
    payload: dict[str, Any],
    outro_id: str | None,
) -> str:
    from akifactory import minimax_h3_bridge as h3

    if h3.load_settings().get("enabled"):
        # Montaj/encode GPU'yu kullanir — Studio render ederken ust uste binme
        await h3.wait_studio_idle()
    r = await client.post(f"{engine_base}/api/v1/videos", json=payload)
    data = r.json()
    if r.status_code >= 400:
        raise RuntimeError(_engine_error_detail(data, "Baslatilamadi"))
    task_id = (data.get("data") or {}).get("task_id")
    if not task_id:
        raise RuntimeError("task_id alinamadi")
    if outro_id:
        outro_mod.register_task_outro(task_id, outro_id)
    from akifactory import task_timing as tt_mod

    tt_mod.record_start(task_id)
    return task_id


async def _wait_engine_task(
    client: httpx.AsyncClient,
    engine_base: str,
    task_id: str,
    *,
    cancelled: Callable[[], bool],
    on_tick: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    import time

    stuck_since = time.monotonic()
    last_progress = -1
    while not cancelled():
        await asyncio.sleep(2)
        tr = await client.get(f"{engine_base}/api/v1/tasks/{task_id}")
        if tr.status_code >= 400:
            raise RuntimeError(f"motor gorev sorgusu basarisiz (HTTP {tr.status_code})")
        td = tr.json().get("data") or {}
        if on_tick:
            on_tick(td)
        state = td.get("state", 4)
        if state == 1:
            return td
        if state == -1:
            raise RuntimeError(td.get("error") or "Hata")
        prog = int(td.get("progress") or 0)
        if prog != last_progress:
            stuck_since = time.monotonic()
            last_progress = prog
        # progress=0 zombi: baglanti koptu, retry yeni task_id aldı ama motor eski istegi bitiriyor
        elif prog <= 0 and (time.monotonic() - stuck_since) >= _ENGINE_STUCK_PROGRESS0_SEC:
            raise RuntimeError(
                "motor gorevi ilerlemiyor (progress=0). "
                "Onceki deneme hala motoru mesgul ediyor olabilir — iptal edip yeniden dene."
            )
    raise RuntimeError("Iptal edildi")


async def _run_en_variant(
    client: httpx.AsyncClient,
    engine_base: str,
    t: dict[str, Any],
    common: dict[str, Any],
    tr_task_id: str,
    tr_script: str,
    *,
    cancelled: Callable[[], bool],
) -> None:
    tag = tr_task_id[:12]
    extra = await _fetch_engine_task_materials(client, engine_base, tr_task_id)
    materials = vid_src.stage_task_clips_for_reuse(tr_task_id, tag, extra_paths=extra or None)
    if not materials:
        raise RuntimeError("Kaynak gorevde stok klip bulunamadi")

    primary, second = dual_languages(common)
    en_script = (
        await script_tr_mod.translate_script(tr_script, from_lang=primary, to_lang=second)
    ).strip()
    if not en_script:
        vid_src.cleanup_reuse_folder(tag)
        raise RuntimeError("Senaryo cevirisi basarisiz")

    en_common = _voice_common_for_lang(common, second)
    en_common["video_source"] = "local"
    en_common["_video_materials"] = materials
    en_topic = f"{t.get('topic', 'Video')} ({second.upper()})"
    en_item = {"topic": en_topic, "video_script": en_script}

    t["phase"] = "en"
    t["progress"] = 0
    t["step"] = f"{second.upper()} baslatiliyor"

    def _tick(td: dict[str, Any]) -> None:
        t["progress"] = int(td.get("progress", 0) or 0)
        t["step"] = progress_step_label(t["progress"])
        from akifactory import task_timing as tt_mod

        tid = t.get("en_task_id")
        if tid:
            el = tt_mod.elapsed(tid)
            if el is not None:
                t["en_production_elapsed_sec"] = el

    try:
        payload = _build_engine_payload(en_item, en_common)
        en_task_id = await _start_engine_video(
            client, engine_base, payload, common.get("outro_id")
        )
        t["en_task_id"] = en_task_id
        td = await _wait_engine_task(
            client, engine_base, en_task_id, cancelled=cancelled, on_tick=_tick
        )
        t["progress"] = 100
        t["step"] = progress_step_label(100)
        t["en_videos"] = _video_urls(engine_base, td.get("videos") or [])
        t["en_script"] = en_script
        t["reuse_tag"] = tag
        from akifactory import task_timing as tt_mod

        en_prod = tt_mod.finish(en_task_id)
        if en_prod is not None:
            t["en_production_sec"] = en_prod
    except Exception:
        vid_src.cleanup_reuse_folder(tag)
        raise
    else:
        vid_src.cleanup_reuse_folder(tag)


async def _archive_now(t: dict[str, Any], common: dict[str, Any], engine_base: str) -> None:
    """Video biter bitmez galeriye yaz — uygulama kapanirsa kayit kaybolmasin."""
    try:
        await asyncio.to_thread(archive_task_to_gallery, t, common, engine_base)
        from akifactory import ai_cover
        await ai_cover.finish_task(t)
    except Exception as exc:
        logger.warning("Galeri arsivi basarisiz (%s): %s", t.get("task_id"), exc)


def _remember_topic_done(t: dict[str, Any], common: dict[str, Any]) -> None:
    niche = str(common.get("niche") or "genel")
    topic = str(t.get("topic") or "")
    topic_mem.remember_produced(niche, topic)
    if common.get("atlas_source"):
        try:
            from akifactory import atlas_topics as atlas_mod

            atlas_mod.remember_atlas_completion(topic, niche_id=niche)
        except Exception:
            pass


async def _prefill_batch_scripts(job: BatchJob, *, limit: int = 1) -> None:
    """Bir sonraki senaryoyu onceden uret — paralel Ollama yok (VRAM/RAM)."""

    async def _one(t: dict[str, Any]) -> None:
        if job.cancelled or t.get("state") not in (None, 0):
            return
        if (t.get("video_script") or "").strip():
            return
        common = dict(job.common)
        lang_id = str(common.get("production_language", "tr"))
        common = _voice_common_for_lang(common, lang_id)
        try:
            if job.cancelled:
                return
            script = await generate_batch_script_with_retry(t.get("topic", ""), common, attempts=3)
            if script and not job.cancelled:
                t["video_script"] = script
        except Exception:
            pass

    if job.cancelled:
        return
    pending = [
        t
        for t in job.tasks
        if t.get("state") in (None, 0) and not (t.get("video_script") or "").strip()
    ]
    for t in pending[: max(1, int(limit or 1))]:
        if job.cancelled:
            return
        await _one(t)


async def _release_batch_memory(batch_id: str, *, reason: str = "") -> None:
    """Videolar arasi Ollama unload — yeni sunucu acmaz, VRAM bosaltir."""
    try:
        await asyncio.wait_for(ollama_util.unload_all_models(), timeout=20.0)
        if reason:
            job_log.info(batch_id, f"Bellek temizligi: {reason}")
    except Exception:
        pass
    try:
        import gc

        gc.collect()
    except Exception:
        pass


def _record_batch_history(t: dict[str, Any], common: dict[str, Any], *, lang_id: str) -> None:
    try:
        from akifactory import history as hist_mod
        from akifactory import languages as lang_mod
        from akifactory import last_voice as last_voice_mod

        tts = str(common.get("tts_engine") or "edge").lower()
        voice = lang_mod.resolve_voice(
            lang_id,
            tts,
            common.get("edge_voice"),
            common.get("rvc_voice"),
        )
        hist_mod.add_entry(
            topic=str(t.get("topic") or ""),
            platform=str(common.get("platform") or "tiktok"),
            language=lang_id,
            voice=voice,
            tts_engine=tts,
            niche=str(common.get("niche") or "genel"),
        )
        last_voice_mod.save(
            {
                "tts_engine": tts,
                "edge_voice": common.get("edge_voice"),
                "rvc_voice": common.get("rvc_voice"),
                "rvc_pitch": common.get("rvc_pitch", 0),
                "rvc_index_rate": common.get("rvc_index_rate", 1.0),
            }
        )
    except Exception:
        pass


async def _wait_for_ai_visuals(
    job: BatchJob,
    task_index: int,
    t: dict[str, Any],
    common: dict[str, Any],
) -> None:
    """Senaryo hazir — H3 Studio/Fooocus promptlari; otomatik veya elle dosya bekle."""
    from akifactory import ai_visuals as ai_vis
    from akifactory import minimax_h3_bridge as h3

    script = (t.get("video_script") or "").strip()
    topic = (t.get("topic") or "").strip()
    # MiniMax otomatiğe: her zaman continue zinciri (1=yeni, 2+=devam)
    h3_cfg = h3.load_settings()
    if "ai_visual_auto_minimax" in common:
        auto_h3 = bool(common.get("ai_visual_auto_minimax"))
    else:
        auto_h3 = bool(h3_cfg.get("enabled"))

    continue_mode = True if auto_h3 else bool(common.get("ai_visual_continue"))
    # Studio'da o an secili ayarlar; klip suresi sahne sayisini ve prompt zamanlamasini belirler
    h3_eff = await h3.effective_settings() if auto_h3 else None
    clip_s = int(h3_eff["duration"]) if h3_eff else ai_vis.SEGMENT_SECONDS
    if h3_eff:
        t["minimax_settings"] = h3.describe_settings(h3_eff)
        job_log.info(job.batch_id, f"H3 Studio ayarlari: {t['minimax_settings']}")
    segs = common.get("ai_visual_segments")
    if segs is None:
        segs = ai_vis.estimate_segment_count(script, segment_seconds=clip_s)
    segs = ai_vis.clamp_segment_count(segs, segment_seconds=clip_s)

    t["progress"] = 35
    t["step"] = "AI gorsel"
    t["phase"] = "awaiting_ai_visuals"
    t["ai_prompts_status"] = "generating"
    t["ai_task_index"] = task_index
    job_log.info(job.batch_id, f"AI gorsel promptlari uretiliyor (task {task_index})")

    try:
        pack = await ai_vis.build_prompt_pack(
            topic=topic or "video",
            niche_id=str(common.get("niche") or "genel"),
            segment_count=int(segs),
            continue_mode=continue_mode,
            script=script,
            segment_seconds=clip_s,
        )
        t["ai_prompts"] = pack
        t["ai_prompts_status"] = "ready"
    except Exception as exc:
        t["ai_prompts"] = None
        t["ai_prompts_status"] = "error"
        t["ai_prompts_error"] = str(exc)
        job_log.error(job.batch_id, f"AI prompt hatasi: {exc}")

    if job.cancelled:
        t["state"] = -1
        t["error"] = "Iptal edildi"
        return

    if auto_h3 and t.get("ai_prompts_status") == "ready" and t.get("ai_prompts"):
        t["step"] = "H3 Studio"
        t["ai_prompts_status"] = "minimax_running"
        t["minimax_status"] = "running"

        def _prog(msg: str, extra: dict[str, Any]) -> None:
            t["minimax_status_text"] = msg
            if extra.get("done") is not None and extra.get("total"):
                t["minimax_progress"] = {
                    "done": extra.get("done"),
                    "total": extra.get("total"),
                }
            job_log.info(job.batch_id, f"H3 Studio: {msg}")

        try:
            await _release_batch_memory(job.batch_id, reason="H3 Studio oncesi Ollama bosaltildi")
            prompts = h3.extract_scene_prompts(t["ai_prompts"])
            aspect = str(common.get("video_aspect") or h3_cfg.get("aspect") or "9:16")
            # Paket sahne basina mod verdiyse (yeni/continue) o; yoksa 1. t2v, sonrasi continue
            asset_ids, materials, tag = await h3.produce_and_stage(
                prompts=prompts,
                continue_chain=True,
                aspect=aspect,
                on_progress=_prog,
                modes=h3.extract_scene_modes(t["ai_prompts"], len(prompts)),
                settings=h3_eff,
            )
            job.ai_resume_data[task_index] = {
                "materials": materials,
                "tag": tag,
                "asset_ids": asset_ids,
                "source": "minimax_auto",
                "clip_seconds": clip_s,
            }
            t["ai_prompts_status"] = "resumed"
            t["minimax_status"] = "done"
            t["ai_visual_tag"] = tag
            job_log.info(
                job.batch_id,
                f"H3 Studio otomatik tamam — {len(materials)} klip (task {task_index})",
            )
            return
        except Exception as exc:
            t["minimax_status"] = "error"
            t["minimax_error"] = str(exc)
            t["ai_prompts_status"] = "ready"
            job_log.error(job.batch_id, f"H3 Studio otomatik hata: {exc}")
            # Elle moda dus — kullanici dosya secene kadar bekle
            if not bool(common.get("ai_visual_auto_minimax_strict")):
                job_log.info(
                    job.batch_id,
                    "H3 Studio basarisiz — elle surukle-birak bekleniyor",
                )
            else:
                t["state"] = -1
                t["error"] = f"H3 Studio: {exc}"
                return

    ev = asyncio.Event()
    job.ai_waiters[task_index] = ev
    job_log.info(
        job.batch_id,
        f"AI gorsel bekleniyor — Pinokio uretimi + dosya secimi (task {task_index})",
    )

    while not ev.is_set():
        if job.cancelled:
            break
        try:
            await asyncio.wait_for(ev.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass

    job.ai_waiters.pop(task_index, None)

    if job.cancelled:
        t["state"] = -1
        t["error"] = "Iptal edildi"
        t["phase"] = "cancelled"
        return

    resume = job.ai_resume_data.get(task_index) or {}
    if not resume.get("materials"):
        t["state"] = -1
        t["error"] = "AI gorsel/video secilmedi"
        return


def resume_ai_visuals(
    batch_id: str,
    *,
    asset_ids: list[str],
    task_index: int | None = None,
) -> dict[str, Any]:
    """Kullanici dosyalari secti — stage et ve batch'i montaja devam ettir."""
    from akifactory import ai_visuals as ai_vis

    job = _batches.get(batch_id)
    if not job:
        raise ValueError("Batch bulunamadi")

    awaiting = [
        i
        for i, t in enumerate(job.tasks)
        if t.get("state") == 4 and t.get("phase") == "awaiting_ai_visuals"
    ]
    if task_index is None:
        if len(awaiting) != 1:
            raise ValueError("Hangi gorev icin devam edilecegi belirsiz — task_index ver")
        task_index = awaiting[0]
    if task_index < 0 or task_index >= len(job.tasks):
        raise ValueError("Gecersiz task_index")
    t = job.tasks[task_index]
    if t.get("phase") != "awaiting_ai_visuals":
        raise ValueError("Bu gorev AI gorsel beklemiyor")

    materials, tag = ai_vis.stage_selected(list(asset_ids or []))
    job.ai_resume_data[task_index] = {"materials": materials, "tag": tag, "asset_ids": list(asset_ids)}
    t["ai_prompts_status"] = "resumed"
    ev = job.ai_waiters.get(task_index)
    if ev:
        ev.set()
    job_log.info(batch_id, f"AI gorsel devam — {len(materials)} dosya (task {task_index})")
    return {"ok": True, "task_index": task_index, "count": len(materials), "tag": tag}


async def _run_batch(batch_id: str, engine_base: str) -> None:
    job = _batches.get(batch_id)
    if not job:
        return
    dual = bool(job.common.get("dual_language"))
    primary, second = dual_languages(job.common)
    second_up = second.upper()
    job_log.info(
        batch_id,
        f"Batch basladi — {len(job.tasks)} konu, dual={dual}"
        + (f" ({primary}+{second})" if dual else ""),
    )
    # Sadece ilk konu senaryosu — 3 paralel Ollama yuklenmesini engelle
    await _prefill_batch_scripts(job, limit=1)
    async with httpx.AsyncClient(timeout=_ENGINE_HTTP_TIMEOUT) as client:
        for task_index, t in enumerate(job.tasks):
            if job.cancelled:
                t["state"] = -1
                t["error"] = "Iptal edildi"
                continue
            if t.get("state") not in (None, 0):
                continue
            topic = t.get("topic", "")
            # 2. dil retry: 1. dil videolari hazirsa tekrar uretme
            if (
                dual
                and t.get("tr_done")
                and t.get("videos")
                and (t.get("script") or t.get("video_script") or "").strip()
            ):
                t["state"] = 4
                t["phase"] = "en"
                t["error"] = None
                t["en_error"] = None
                job_log.info(batch_id, f"{second_up} yeniden deneme: {topic}")
                try:
                    common = dict(job.common)
                    await _run_en_variant(
                        client,
                        engine_base,
                        t,
                        common,
                        t["task_id"],
                        (t.get("script") or t.get("video_script") or "").strip(),
                        cancelled=lambda: job.cancelled,
                    )
                    t["state"] = 1
                    t["phase"] = "done"
                    _record_batch_history(t, job.common, lang_id=primary)
                    _remember_topic_done(t, job.common)
                    await _archive_now(t, job.common, engine_base)
                except Exception as en_exc:
                    t["state"] = -1
                    t["phase"] = "en"
                    t["en_error"] = str(en_exc)
                    t["error"] = f"{second_up} uretim basarisiz: {en_exc}"
                finally:
                    await _release_batch_memory(batch_id, reason=f"{second_up} retry: {topic}")
                continue
            t["state"] = 4
            t["phase"] = "tr" if dual else "single"
            job_log.info(batch_id, f"Konu basliyor: {topic}")
            try:
                common = _voice_common_for_lang(dict(job.common), primary)
                if job.cancelled:
                    t["state"] = -1
                    t["error"] = "Iptal edildi"
                    continue
                if common.get("_video_materials"):
                    common["video_source"] = "local"
                elif common.get("ai_manual_visuals") or vid_src.is_pinokio_source(
                    common.get("video_source")
                ):
                    # Stok indirme yok — senaryo sonrasi AI gorsel / MiniMax
                    common["ai_manual_visuals"] = True
                    if vid_src.is_pinokio_source(common.get("video_source")):
                        common["ai_visual_auto_minimax"] = True
                        common["ai_visual_continue"] = True
                    common["video_source"] = "local"
                else:
                    resolved_source = await vid_src.resolve_video_source(
                        common.get("video_source", "pexels"),
                        t.get("topic", ""),
                    )
                    common["video_source"] = resolved_source
                if job.cancelled:
                    t["state"] = -1
                    t["error"] = "Iptal edildi"
                    continue
                t["progress"] = 10
                t["step"] = "Senaryo"
                if not (t.get("video_script") or "").strip():
                    script = await generate_batch_script_with_retry(t.get("topic", ""), common, attempts=3)
                    if job.cancelled:
                        t["state"] = -1
                        t["error"] = "Iptal edildi"
                        continue
                    if script:
                        t["video_script"] = script
                if not (t.get("video_script") or "").strip():
                    t["state"] = -1
                    t["error"] = (
                        "Senaryo uretilemedi (Ollama). ollama serve ve ollama pull qwen3.5:9b"
                    )
                    continue

                # AI gorsel modu: senaryo hazir → prompt uret → kullanici dosya yukleyene kadar bekle
                if common.get("ai_manual_visuals") and not common.get("_video_materials"):
                    await _wait_for_ai_visuals(job, task_index, t, common)
                    if t.get("state") == -1:
                        continue
                    resume = job.ai_resume_data.get(task_index) or {}
                    materials = resume.get("materials")
                    if materials:
                        common["_video_materials"] = materials
                        common["video_source"] = "local"
                        common["video_clip_duration"] = int(
                            resume.get("clip_seconds")
                            or common.get("video_clip_duration")
                            or 5
                        )
                        t["ai_visual_tag"] = resume.get("tag")
                    else:
                        t["state"] = -1
                        t["error"] = "AI gorsel/video secilmedi"
                        continue
                    t["phase"] = "tr" if dual else "single"
                    t["step"] = "Goruntu"
                    t["progress"] = 40

                payload = _build_engine_payload(t, common)
                if not (payload.get("video_script") or "").strip():
                    t["state"] = -1
                    t["error"] = (
                        "Senaryo uretilemedi (Ollama). ollama serve ve ollama pull qwen3.5:9b"
                    )
                    continue
                if job.cancelled:
                    t["state"] = -1
                    t["error"] = "Iptal edildi"
                    continue

                def _tr_tick(td: dict[str, Any]) -> None:
                    t["progress"] = int(td.get("progress", 0) or 0)
                    t["step"] = progress_step_label(
                        t["progress"],
                        has_script=True,
                        has_task=True,
                    )
                    from akifactory import task_timing as tt_mod

                    el = tt_mod.elapsed(task_id)
                    if el is not None:
                        t["production_elapsed_sec"] = el

                from akifactory import minimax_h3_bridge as h3

                if h3.load_settings().get("enabled"):

                    def _studio_wait(msg: str) -> None:
                        t["step"] = msg
                        job_log.info(batch_id, msg)

                    await h3.wait_studio_idle(on_wait=_studio_wait)
                t["step"] = "Motor baslatiliyor"
                task_id = await _start_engine_video(
                    client, engine_base, payload, common.get("outro_id")
                )
                t["task_id"] = task_id
                t["step"] = progress_step_label(0, has_script=True, has_task=True)
                td = await _wait_engine_task(
                    client,
                    engine_base,
                    task_id,
                    cancelled=lambda: job.cancelled,
                    on_tick=_tr_tick,
                )
                t["progress"] = 100
                t["step"] = progress_step_label(100)
                t["videos"] = _video_urls(engine_base, td.get("videos") or [])
                t["script"] = (td.get("script") or t.get("video_script") or "").strip()
                t["tr_done"] = True
                from akifactory import task_timing as tt_mod

                prod = tt_mod.finish(task_id)
                if prod is not None:
                    t["production_sec"] = prod

                if dual:
                    tr_script = t["script"]
                    if len(tr_script) < 10:
                        t["state"] = -1
                        t["error"] = f"{primary.upper()} senaryo alinamadi — {second_up} uretilemedi"
                        continue
                    try:
                        await _run_en_variant(
                            client,
                            engine_base,
                            t,
                            common,
                            task_id,
                            tr_script,
                            cancelled=lambda: job.cancelled,
                        )
                    except Exception as en_exc:
                        if t.get("videos"):
                            # 1. dil hazir ama 2. dil dustu — yalnizca 2. dil retry icin state=-1
                            t["state"] = -1
                            t["phase"] = "en"
                            t["tr_done"] = True
                            t["en_error"] = str(en_exc)
                            t["error"] = f"{second_up} uretim basarisiz: {en_exc}"
                            _record_batch_history(t, job.common, lang_id=primary)
                            await _archive_now(t, job.common, engine_base)
                            continue
                        raise

                t["state"] = 1
                t["phase"] = "done"
                _record_batch_history(t, job.common, lang_id=primary)
                _remember_topic_done(t, job.common)
                await _archive_now(t, job.common, engine_base)
            except Exception as e:
                t["state"] = -1
                t["error"] = str(e)
                job_log.error(batch_id, f"Konu hatasi ({topic}): {e}")
                if t.get("reuse_tag"):
                    vid_src.cleanup_reuse_folder(t["reuse_tag"])
            finally:
                # Her video sonrasi Ollama bosalt — yeni motor/server acmaz
                await _release_batch_memory(batch_id, reason=f"konu bitti: {topic}")
                # Siradaki tek senaryoyu onceden hazirla (paralel degil)
                if not job.cancelled and task_index + 1 < len(job.tasks):
                    await _prefill_batch_scripts(job, limit=1)
        job_log.info(batch_id, "Batch bitti")
        await _release_batch_memory(batch_id, reason="batch sonu")


def _reset_failed_task(t: dict[str, Any], *, dual: bool) -> None:
    err = (t.get("error") or "").lower()
    tr_done = bool(t.get("tr_done"))
    en_failed = dual and tr_done and t.get("state") == -1
    t["error"] = None
    t["progress"] = 0
    t["step"] = ""
    if en_failed:
        t["state"] = 0
        t["phase"] = None
        t["en_task_id"] = None
        t["en_videos"] = []
        t["en_script"] = ""
        return
    t["state"] = 0
    t["phase"] = None
    t["task_id"] = None
    t["videos"] = []
    t["script"] = ""
    t["tr_done"] = False
    t["en_task_id"] = None
    t["en_videos"] = []
    t["en_script"] = ""
    if "senaryo" in err:
        t["video_script"] = ""


def prepare_failed_retry(batch_id: str) -> int:
    job = _batches.get(batch_id)
    if not job:
        return 0
    dual = bool(job.common.get("dual_language"))
    n = 0
    for t in job.tasks:
        if t.get("state") == -1:
            _reset_failed_task(t, dual=dual)
            n += 1
    return n


async def run_batch_with_retries(
    batch_id: str,
    engine_base: str,
    *,
    auto_retry: bool = True,
    rounds: int = 2,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    job = _batches.get(batch_id)
    if not job:
        return
    pass_count = 1 + (max(0, rounds) if auto_retry else 0)
    for round_idx in range(pass_count):
        if cancelled and cancelled():
            job.cancelled = True
        if job.cancelled:
            break
        if round_idx > 0:
            if not prepare_failed_retry(batch_id):
                break
        await _run_batch(batch_id, engine_base)
        data = get_batch(batch_id)
        if not data or not data.get("failed"):
            break


def create_batch(
    topics: list[str],
    common: dict[str, Any],
    *,
    scripts: list[str] | None = None,
    batch_id: str | None = None,
) -> str:
    bid = batch_id or uuid.uuid4().hex[:12]
    dual = bool(common.get("dual_language"))
    primary, second = dual_languages(common)
    script_list = scripts or []
    tasks = []
    idx = 0
    for t in topics:
        topic = t.strip()
        if not topic:
            continue
        pre_script = ""
        if idx < len(script_list) and script_list[idx]:
            pre_script = str(script_list[idx]).strip()
        idx += 1
        tasks.append(
            {
                "topic": topic,
                "state": 0,
                "progress": 0,
                "task_id": None,
                "videos": [],
                "dual_language": dual,
                "primary_language": primary,
                "second_language": second if dual else None,
                "phase": None,
                "tr_done": False,
                "en_task_id": None,
                "en_videos": [],
                "en_script": "",
                "video_script": pre_script,
            }
        )
    _batches[bid] = BatchJob(batch_id=bid, tasks=tasks, common=common)
    return bid


def create_batch_with_id(
    batch_id: str,
    topics: list[str],
    common: dict[str, Any],
    *,
    scripts: list[str] | None = None,
) -> str:
    return create_batch(topics, common, scripts=scripts, batch_id=batch_id)


async def run_batch(batch_id: str, engine_base: str) -> None:
    await run_batch_with_retries(batch_id, engine_base)


def get_batch(batch_id: str) -> dict[str, Any] | None:
    job = _batches.get(batch_id)
    if not job:
        return None
    done = sum(1 for t in job.tasks if t.get("state") == 1)
    failed = sum(1 for t in job.tasks if t.get("state") == -1)
    errors = [t.get("error") for t in job.tasks if t.get("state") == -1 and t.get("error")]
    dual = bool(job.common.get("dual_language"))
    primary, second = dual_languages(job.common)
    return {
        "batch_id": batch_id,
        "cancelled": job.cancelled,
        "dual_language": dual,
        "primary_language": primary,
        "second_language": second if dual else None,
        "total": len(job.tasks),
        "done": done,
        "failed": failed,
        "errors": errors,
        "tasks": job.tasks,
    }


def collect_running_task_ids(batch_id: str) -> list[str]:
    job = _batches.get(batch_id)
    if not job:
        return []
    ids: list[str] = []
    for t in job.tasks:
        if t.get("state") != 4:
            continue
        for key in ("task_id", "en_task_id"):
            tid = str(t.get(key) or "").strip()
            if tid and tid not in ids:
                ids.append(tid)
    return ids


def cancel_batch(batch_id: str) -> bool:
    job = _batches.get(batch_id)
    if not job:
        return False
    job.cancelled = True
    for ev in list(job.ai_waiters.values()):
        ev.set()
    return True


def _resolve_task_voice(common: dict[str, Any]) -> tuple[str, str]:
    """Arsiv icin (voice, tts_provider) — RVC ise model adi, degilse edge sesi."""
    tts = (common.get("tts_engine") or common.get("tts_provider") or "edge").strip()
    if tts == "rvc":
        return (common.get("rvc_voice") or "").strip(), "rvc"
    return (common.get("edge_voice") or "").strip(), tts


def archive_completed_tasks_to_gallery(batch_id: str, engine_base: str) -> int:
    """Tamamlanan gorevleri backend'de galeriye arsivler (uygulama kapali olsa bile
    video kaybolmaz). task_id'ye gore tekrar-onleme oldugu icin frontend arsivi ile
    cakismaz. Caption/publish paketi galeri acilinca frontend'de doldurulur."""
    job = _batches.get(batch_id)
    if not job:
        return 0
    archived = 0
    for t in job.tasks:
        if t.get("state") == 1:
            archived += archive_task_to_gallery(t, job.common or {}, engine_base)
    return archived


def archive_task_to_gallery(t: dict[str, Any], common: dict[str, Any], engine_base: str) -> int:
    """Tek gorevin 1. dil (ve cift dilde 2. dil) videosunu galeriye yazar; task_id varsa dokunmaz."""
    from akifactory import gallery as gal_mod

    dual = bool(common.get("dual_language"))
    primary, second = dual_languages(common)
    voice, tts_provider = _resolve_task_voice(common)
    shared = {
        "engine_base": engine_base,
        "aspect": common.get("video_aspect") or "",
        "platform": common.get("platform", ""),
        "niche": common.get("niche", ""),
        "voice": voice,
        "tts_provider": tts_provider,
        "bgm_file": str(t.get("bgm_file") or ""),
    }
    topic = (t.get("topic") or "").strip()
    archived = 0
    tr_task_id = t.get("task_id")
    if tr_task_id and (t.get("tr_done") or t.get("state") == 1):
        tr_script = (t.get("script") or t.get("video_script") or "").strip()
        try:
            archived += len(
                gal_mod.archive_from_task(
                    task_id=str(tr_task_id),
                    subject=topic,
                    video_urls=t.get("videos") or [],
                    language=primary,
                    duration_sec=script_hk.estimate_duration_sec(tr_script),
                    production_sec=int(t.get("production_sec") or 0),
                    title=topic,
                    script=tr_script,
                    **shared,
                )
            )
        except Exception as exc:
            logger.warning("Galeri arsivi basarisiz (%s): %s", tr_task_id, exc)
    en_task_id = t.get("en_task_id")
    if dual and en_task_id and t.get("state") == 1:
        en_script = (t.get("en_script") or "").strip()
        try:
            archived += len(
                gal_mod.archive_from_task(
                    task_id=str(en_task_id),
                    subject=f"{topic} ({second.upper()})",
                    video_urls=t.get("en_videos") or [],
                    language=second,
                    duration_sec=script_hk.estimate_duration_sec(en_script),
                    production_sec=int(t.get("en_production_sec") or 0),
                    # 1. dil konusu baslik olarak yazilmasin — yayin paketi 2. dilde uretilir
                    title="",
                    script=en_script,
                    **shared,
                )
            )
        except Exception as exc:
            logger.warning("Galeri arsivi basarisiz (%s): %s", en_task_id, exc)
    return archived
