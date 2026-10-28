"""
AkiFactory — web arayuzu (FastAPI).
Uretim + Galeri sekmeleri.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from akifactory.__version__ import __version__
from akifactory import batch as batch_mod
from akifactory import topic_memory as topic_mem
from akifactory import atlas_topics as atlas_mod
from akifactory import longform as longform_mod
from akifactory import production_queue as prod_q
from akifactory import bgm as bgm_mod
from akifactory import caption as caption_mod
from akifactory import content_studio as studio_mod
from akifactory import fooocus_prompt as fooocus_mod
from akifactory import wangp_prompt as wangp_mod
from akifactory import drafts as drafts_mod
from akifactory import features_util
from akifactory import gallery as gal
from akifactory import ai_visuals as ai_vis
from akifactory import longform_gallery as lf_gal
from akifactory import thumbnail as thumb_mod
from akifactory import history as hist
from akifactory import last_voice as last_voice_mod
from akifactory import lang_presets as lang_pres_mod
from akifactory import script_translate as script_tr_mod
from akifactory import fonts_util
from akifactory import languages as lang
from akifactory import llm_profiles as llm_prof
from akifactory import ollama_util
from akifactory import outros as outro_mod
from akifactory import platforms as plat
from akifactory import script_hooks as script_hk
from akifactory import script_prompts as script_pr
from akifactory import settings_assets as settings_mod
from akifactory import telegram_notify as tg_mod
from akifactory import first_run as setup_mod
from akifactory import backup as backup_mod
from akifactory import system_live as syslive_mod
from akifactory import stock_api_keys as api_keys_mod
from akifactory import llm_api as llm_api_mod
from akifactory import minimax_h3_bridge as h3_bridge_mod
from akifactory import hook_examples as hook_ex_mod
from akifactory import hook_generator as hook_gen_mod
from akifactory import hook_memory as hook_mem_mod
from akifactory import subtitle_styles as sub_st
from akifactory import video_source as vid_src
from akifactory import video_analysis as va_mod
from akifactory import voice_convert as vc_mod
from contextlib import asynccontextmanager

from akifactory.paths import app_root, engine_task_dir
from akifactory.text_utils import prepare_script_for_engine, prepare_video_script

WEB_DIR = app_root() / "web"


def engine_base() -> str:
    return os.environ.get("AKI_ENGINE_API", "http://127.0.0.1:8080").rstrip("/")


def _engine_pid_alive() -> bool:
    """``.aki_engine_pid`` dosyasindaki surec hala ayakta mi?"""
    try:
        pid_file = app_root() / ".aki_engine_pid"
        if not pid_file.is_file():
            return False
        pid = int((pid_file.read_text(encoding="utf-8") or "0").strip().split()[0])
        if pid <= 0:
            return False
        if sys.platform == "win32":
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout or ""
            return str(pid) in out
        os.kill(pid, 0)
        return True
    except Exception:
        return False


_NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
}


def _httpx_json(r: httpx.Response) -> dict[str, Any]:
    """Motor bazen duz metin (Internal Server Error) dondurur."""
    try:
        data = r.json()
        return data if isinstance(data, dict) else {"data": data}
    except Exception:
        text = (r.text or "").strip()
        return {"message": text[:500] or f"Motor HTTP {r.status_code}"}


STATE_LABELS = {
    -1: "Hata",
    1: "Tamam",
    4: "Uretiliyor",
}


def _read_engine_task_disk_meta(task_id: str) -> dict[str, Any]:
    """Motor progress=0 ile basarisiz olunca gercek asamayi script.json'dan cikar."""
    import json

    from akifactory.paths import engine_task_dir

    path = engine_task_dir(task_id) / "script.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    params = data.get("params") if isinstance(data.get("params"), dict) else {}
    script = (data.get("script") or params.get("video_script") or "").strip()
    voice = str(params.get("voice_name") or "")
    task_dir = path.parent
    return {
        "script_saved": bool(script),
        "had_script": bool(script),
        "voice_name": voice,
        "has_audio": (task_dir / "audio.mp3").is_file()
        and (task_dir / "audio.mp3").stat().st_size > 0,
    }


def _short_voice_err(msg: str, *, limit: int = 220) -> str:
    """UI'ya uzun torchcodec/FFmpeg traceback'i basma."""
    text = (msg or "").strip() or "Ses uretilemedi"
    low = text.lower()
    if "torchcodec" in low or "libtorchcodec" in low:
        return (
            "Ses motoru torchcodec/FFmpeg hatasi verdi. "
            "Uygulamayi yeniden baslatip tekrar dene; "
            "olmazsa gecici olarak Edge TTS sec."
        )
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def _failure_hint(
    progress: int,
    *,
    production_language: str = "",
    had_script: bool = False,
    script_saved: bool = False,
    voice_name: str = "",
    has_audio: bool = False,
) -> str:
    p = int(progress or 0)
    rvc = (voice_name or "").strip().lower().startswith("rvc:")

    # Senaryo dosyasi var ama progress sifir — genelde ses (RVC/Edge) asamasinda patlar
    if script_saved and not has_audio and p < 30:
        if rvc:
            return (
                "Senaryo tamam; RVC ses (Tamer Karadagli) uretilemedi. ffmpeg eksik olabilir "
                "(winget install Gyan.FFmpeg) veya gecici cozum: Ses motoru = Edge TTS. "
                "AkiFactory.bat ile yeniden acin. Detay: .aki_engine.log"
            )
        return (
            "Senaryo tamam ama ses uretilemedi. Ses motorunu Edge TTS yapmayi deneyin "
            "veya .aki_engine.log dosyasina bakin."
        )

    if p < 10:
        lang = (production_language or "").strip().lower()
        if had_script:
            return (
                "Video motoru hazir senaryoyu kullanamadi. AkiFactory.bat penceresini "
                "tamamen kapatip yeniden acin (eski motor sureci kalabilir)."
            )
        if lang == "en":
            return (
                "Video motoru senaryo adiminda durdu (EN). Ingilizce metin genelde "
                "Turkce videodan cevrilir; once tek TR video deneyin."
            )
        return (
            "Video motoru senaryo uretemedi. Once «Senaryo uret» ile metin yazin veya "
            "Ollama modellerini kontrol edin (ollama serve, ollama pull qwen3.5:9b)."
        )
    if p < 20:
        return "Video anahtar kelimeleri uretilemedi."
    if p < 30:
        if rvc:
            return (
                "RVC ses uretilemedi. ffmpeg kurulu mu (winget install Gyan.FFmpeg) "
                "veya Edge TTS deneyin."
            )
        return "Ses uretimi basarisiz. Edge TTS veya RVC deneyin."
    if p < 40:
        return "Pexels/Pixabay gorsel indirilemedi. API anahtarini kontrol edin."
    if p < 50:
        return "Altyazi olusturulamadi."
    if has_audio and script_saved:
        return (
            "Video montaji basarisiz (stok klipler birlestirilemedi). "
            "Cift dil EN adiminda olabilir — AkiFactory.bat ile yeniden acip tekrar deneyin. "
            "Detay: .aki_engine.log"
        )
    return "Video birlestirme basarisiz."


class SubtitleStyleBody(BaseModel):
    style_id: str = "tiktok_classic"
    font_size_key: str | None = None
    text_fore_color: str | None = None
    subtitle_position: str | None = None
    text_background_color: bool | None = None


class GenerateRequest(BaseModel):
    video_subject: str = Field(..., min_length=2, max_length=500)
    platform: str = plat.DEFAULT_PLATFORM
    video_aspect: str | None = None
    video_source: str = "pexels"
    production_language: str = lang.DEFAULT_LANGUAGE
    tts_engine: str = lang.DEFAULT_TTS_ENGINE
    tts_provider: str | None = None
    edge_voice: str | None = None
    niche: str = "genel"
    strengthen_hook: bool = True
    dual_llm: bool = True
    editor_web_verify: bool = True
    writer_model: str | None = None
    editor_model: str | None = None
    video_script: str | None = None
    video_count: int = Field(1, ge=1, le=5)
    video_clip_duration: int | None = None
    paragraph_number: int = Field(1, ge=1, le=5)
    subtitle_enabled: bool = True
    subtitle_style: SubtitleStyleBody | None = None
    bgm_volume: float = Field(0.2, ge=0.0, le=1.0)
    bgm_mode: str = "niche"
    bgm_track: str | None = None
    voice_rate: float = Field(1.08, ge=0.5, le=2.0)
    rvc_voice: str | None = None
    rvc_pitch: int = Field(0, ge=-12, le=12)
    rvc_index_rate: float = Field(1.0, ge=0.0, le=1.0)
    outro_id: str | None = None
    use_lang_preset: bool = False
    ai_manual_visuals: bool = False
    ai_visual_asset_ids: list[str] = Field(default_factory=list)
    production_mode: str = "automatic"


class LanguageVariantRequest(BaseModel):
    source_task_id: str = Field(..., min_length=8)
    target_language: str = "en"
    subject: str = ""
    source_script: str = Field(..., min_length=10, max_length=4000)
    platform: str = plat.DEFAULT_PLATFORM
    video_aspect: str | None = None
    video_clip_duration: int | None = None
    niche: str = "genel"
    subtitle_style: SubtitleStyleBody | None = None
    bgm_volume: float = Field(0.2, ge=0.0, le=1.0)
    bgm_mode: str = "niche"
    bgm_track: str | None = None
    outro_id: str | None = None
    use_lang_preset: bool = False
    tts_engine: str | None = None
    tts_provider: str | None = None
    edge_voice: str | None = None
    rvc_voice: str | None = None
    rvc_pitch: int | None = Field(None, ge=-12, le=12)
    rvc_index_rate: float | None = Field(None, ge=0.0, le=1.0)


class LangPresetBody(BaseModel):
    tts_engine: str | None = None
    edge_voice: str | None = None
    rvc_voice: str | None = None
    rvc_pitch: int | None = Field(None, ge=-12, le=12)
    rvc_index_rate: float | None = Field(None, ge=0.0, le=1.0)
    voice_rate: float | None = Field(None, ge=0.5, le=2.0)
    subtitle_style_id: str | None = None


class LongformPlanRequest(BaseModel):
    subject: str = Field(..., min_length=2, max_length=500)
    niche: str = "genel"
    chapter_count: int = Field(11, ge=8, le=12)


class LongformBrainstormRequest(BaseModel):
    subject: str = Field(..., min_length=2, max_length=500)
    niche: str = "genel"
    note: str = Field("", max_length=2000)
    prior: dict[str, Any] | None = None


class LongformQuestionsRequest(BaseModel):
    subject: str = Field(..., min_length=2, max_length=500)
    niche: str = "genel"
    draft_chapters: list[str] = Field(default_factory=list, max_length=12)


class LongformGenerateRequest(BaseModel):
    main_subject: str = Field(..., min_length=2, max_length=500)
    chapters: list[str] = Field(..., min_length=1, max_length=12)
    scripts: list[str | None] | None = None
    platform: str = plat.DEFAULT_PLATFORM
    video_aspect: str | None = None
    video_source: str = "pexels"
    production_language: str = lang.DEFAULT_LANGUAGE
    tts_engine: str = lang.DEFAULT_TTS_ENGINE
    tts_provider: str | None = None
    edge_voice: str | None = None
    niche: str = "genel"
    video_clip_duration: int | None = None
    subtitle_style: SubtitleStyleBody | None = None
    bgm_volume: float = 0.0
    bgm_mode: str = "none"
    bgm_track: str | None = None
    voice_rate: float = 1.08
    rvc_voice: str | None = None
    rvc_pitch: int = Field(0, ge=-12, le=12)
    rvc_index_rate: float = Field(1.0, ge=0.0, le=1.0)
    outro_id: str | None = None
    dual_llm: bool = True
    strengthen_hook: bool = True
    writer_model: str | None = None
    editor_model: str | None = None
    dual_language: bool = False
    editor_web_verify: bool = True
    auto_retry_failed: bool = True
    auto_retry_rounds: int = Field(2, ge=0, le=5)
    think_guidance: str = Field("", max_length=4000)
    auto_retry_failed: bool = True
    auto_retry_rounds: int = Field(2, ge=0, le=5)


class BatchGenerateRequest(BaseModel):
    topics: list[str] = Field(..., min_length=1, max_length=10)
    platform: str = plat.DEFAULT_PLATFORM
    video_aspect: str | None = None
    video_source: str = "pexels"
    production_language: str = lang.DEFAULT_LANGUAGE
    tts_engine: str = lang.DEFAULT_TTS_ENGINE
    tts_provider: str | None = None
    edge_voice: str | None = None
    niche: str = "genel"
    video_clip_duration: int | None = None
    subtitle_style: SubtitleStyleBody | None = None
    bgm_volume: float = 0.2
    bgm_mode: str = "niche"
    bgm_track: str | None = None
    voice_rate: float = 1.08
    rvc_voice: str | None = None
    rvc_pitch: int = Field(0, ge=-12, le=12)
    rvc_index_rate: float = Field(1.0, ge=0.0, le=1.0)
    outro_id: str | None = None
    dual_llm: bool = True
    strengthen_hook: bool = True
    editor_web_verify: bool = True
    writer_model: str | None = None
    editor_model: str | None = None
    dual_language: bool = False
    second_language: str | None = None
    use_lang_preset: bool = False
    en_tts_engine: str | None = None
    en_edge_voice: str | None = None
    en_rvc_voice: str | None = None
    en_rvc_pitch: int | None = Field(None, ge=-12, le=12)
    en_rvc_index_rate: float | None = Field(None, ge=0.0, le=1.0)
    scripts: list[str] | None = None
    auto_retry_failed: bool = True
    auto_retry_rounds: int = Field(2, ge=0, le=5)
    niche_experimental: bool = False
    ai_manual_visuals: bool = False
    ai_visual_asset_ids: list[str] = Field(default_factory=list)
    ai_visual_continue: bool = False
    ai_visual_segments: int | None = Field(None, ge=9, le=12)
    ai_visual_auto_minimax: bool = False
    production_mode: str = "automatic"


class ScriptPreviewRequest(BaseModel):
    video_subject: str = Field(..., min_length=2, max_length=500)
    platform: str = plat.DEFAULT_PLATFORM
    production_language: str = lang.DEFAULT_LANGUAGE
    niche: str = "genel"
    strengthen_hook: bool = True
    dual_llm: bool = True
    editor_web_verify: bool = True
    writer_model: str | None = None
    editor_model: str | None = None
    paragraph_number: int = Field(1, ge=1, le=5)


class PublishReviewRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=500)
    script: str = Field(..., min_length=10, max_length=4000)
    platform: str = plat.DEFAULT_PLATFORM
    production_language: str = lang.DEFAULT_LANGUAGE
    niche: str = "genel"
    editor_model: str | None = None
    video_aspect: str = "9:16"
    include_wangp: bool = False  # WanGP yalnizca uzun video
    include_share_tips: bool = True
    include_fooocus: bool = False
    scene_count: int = Field(5, ge=3, le=8)
    wangp_style: str = "dark_mystery"
    wangp_line_mode: str = "sliding_window"


class SuggestTopicsRequest(BaseModel):
    niche: str = "tarih_gizem"
    count: int = Field(5, ge=1, le=10)


class WangpPromptRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=500)
    niche: str = "tarih_gizem"
    scene_count: int = Field(5, ge=3, le=8)
    batch_count: int = Field(1, ge=1, le=4)
    style: str = "dark_mystery"
    line_mode: str = "sliding_window"
    aspect: str = "9:16"


class FooocusPromptRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=500)
    niche: str = "tarih_gizem"
    style: str = "photorealistic"
    aspect: str = "9:16"
    purpose: str = "thumbnail"
    variant_count: int = Field(1, ge=1, le=3)


class AiVisualPromptBody(BaseModel):
    topic: str = Field("", max_length=500)
    niche: str = "tarih_gizem"
    segment_count: int | None = Field(None, ge=9, le=12)
    continue_mode: bool = False
    script: str | None = None


class AiVisualResumeBody(BaseModel):
    asset_ids: list[str] = Field(default_factory=list)
    task_index: int | None = None


class GalleryFooocusBody(BaseModel):
    style: str = "photorealistic"
    purpose: str = "thumbnail"
    variant_count: int = Field(1, ge=1, le=3)


class GalleryWangpBody(BaseModel):
    style: str = "dark_mystery"
    line_mode: str = "sliding_window"
    scene_count: int = Field(5, ge=3, le=8)
    batch_count: int = Field(1, ge=1, le=2)


class GalleryPublishFieldBody(BaseModel):
    """Detay paneli Degistir — sadece ilgili alan LLM ile yenilenir."""

    field: str = "title"  # title | description | tags | share_tips


class ArchiveRequest(BaseModel):
    task_id: str
    subject: str = ""
    aspect: str = "9:16"
    platform: str = ""
    language: str = ""
    voice: str = ""
    niche: str = ""
    tts_provider: str = ""
    videos: list[str] = Field(default_factory=list)
    script: str = ""
    generate_caption: bool = True
    caption: str = ""
    hashtags: str = ""
    title: str = ""
    publish_pack: dict[str, Any] = Field(default_factory=dict)
    notify: bool = False
    notify_subject: str = ""
    production_sec: int = 0


class HistoryLabelBody(BaseModel):
    label: str = ""


class LastVoiceBody(BaseModel):
    tts_engine: str = "edge"
    edge_voice: str | None = None
    rvc_voice: str | None = None
    rvc_pitch: int = Field(0, ge=-12, le=12)
    rvc_index_rate: float = Field(1.0, ge=0.0, le=1.0)
    platform: str | None = None


class EstimateRequest(BaseModel):
    topic: str = Field("", max_length=500)
    script: str = Field("", max_length=20000)
    video_count: int = Field(1, ge=1, le=10)
    platform: str = plat.DEFAULT_PLATFORM
    niche: str = "genel"
    dual_language: bool = False
    production_language: str = lang.DEFAULT_LANGUAGE


class VoiceTestBody(BaseModel):
    """Ses testi — secili motor + ~30 sn hikaye; yalnizca audio."""

    text: str | None = None
    tts_engine: str = lang.DEFAULT_TTS_ENGINE
    production_language: str = lang.DEFAULT_LANGUAGE
    edge_voice: str | None = None
    rvc_voice: str | None = None
    rvc_pitch: int = Field(0, ge=-12, le=12)
    rvc_index_rate: float = Field(0.65, ge=0.0, le=1.0)
    voice_rate: float = Field(1.0, ge=0.5, le=2.0)


class ChatterboxTestBody(BaseModel):
    text: str | None = None
    production_language: str = lang.DEFAULT_LANGUAGE
    rvc_voice: str | None = None
    rvc_pitch: int = Field(0, ge=-12, le=12)
    rvc_index_rate: float = Field(0.78, ge=0.0, le=1.0)


class DraftSaveBody(BaseModel):
    id: str | None = None
    label: str = ""
    settings: dict[str, Any] = Field(default_factory=dict)


class SettingsSectionBody(BaseModel):
    section: str = "all"


class AssetDeleteBody(BaseModel):
    section: str
    id: str


class TelegramSettingsBody(BaseModel):
    enabled: bool | None = None
    bot_token: str | None = None
    chat_id: str | None = None
    notify_video: bool | None = None
    notify_queue: bool | None = None


class StockApiKeysBody(BaseModel):
    pexels_key: str | None = None
    pixabay_key: str | None = None


class LlmApiSettingsBody(BaseModel):
    provider: str | None = None
    openai_api_key: str | None = None
    nvidia_api_key: str | None = None
    gemini_api_key: str | None = None
    grok_api_key: str | None = None
    claude_api_key: str | None = None
    openai_model: str | None = None
    nvidia_model: str | None = None
    gemini_model: str | None = None
    grok_model: str | None = None
    claude_model: str | None = None


class LlmModelsBody(BaseModel):
    provider: str | None = None
    api_key: str | None = None


class MinimaxH3SettingsBody(BaseModel):
    enabled: bool | None = None
    auto_start: bool | None = None
    base_url: str | None = None
    aspect: str | None = None
    quality: str | None = None
    duration: int | None = None
    steps: int | None = None
    silent_audio: bool | None = None
    timeout_sec: int | None = None


class SetupRunBody(BaseModel):
    start_ollama: bool = True
    pull_model: bool = True
    install_ffmpeg: bool = True


class HookExampleBody(BaseModel):
    niche: str = "tarih_gizem"
    text: str = Field(..., min_length=8, max_length=500)


class HookMemoryBody(BaseModel):
    niche: str = "tarih_gizem"
    text: str = Field(..., min_length=8, max_length=500)
    rating: str = Field(..., pattern="^(good|bad)$")
    topic: str = ""
    note: str = ""


class HookRateBody(BaseModel):
    niche: str = "tarih_gizem"
    example_id: str = ""
    text: str = ""
    rating: str = Field(..., pattern="^(good|bad)$")

class GalleryThumbnailBody(BaseModel):
    frame_index: int | None = Field(None, ge=0)


class DesktopResolveBody(BaseModel):
    url: str = ""
    default_name: str = ""


def _safe_filename(name: str) -> str:
    s = re.sub(r'[<>:"/\\|?*]+', "", name).strip() or "video"
    return s[:80] + ".mp4"


def _safe_audio_filename(name: str) -> str:
    s = re.sub(r'[<>:"/\\|?*]+', "", name).strip() or "ses"
    if not s.lower().endswith(".wav"):
        s = s[:80] + ".wav"
    return s[:96]


def _media_type_for_path(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    if ext == ".mov":
        return "video/quicktime"
    if ext == ".webm":
        return "video/webm"
    return "video/mp4"


async def _archive_publish_meta(
    body: ArchiveRequest,
) -> tuple[dict[str, Any], str, str, str]:
    """Yayin paketi + caption/hashtag/baslik — seri uretim galeri kaydi icin."""
    publish_pack = dict(body.publish_pack or {})
    caption = (body.caption or "").strip()
    hashtags = (body.hashtags or "").strip()
    title = (body.title or "").strip()

    if publish_pack.get("titles") or publish_pack.get("descriptions"):
        if not caption:
            caption = (publish_pack.get("best_caption") or "").strip()
        if not hashtags:
            hashtags = (publish_pack.get("best_hashtags") or "").strip()
        if not title:
            title = (publish_pack.get("best_title") or "").strip()
        return publish_pack, caption, hashtags, title

    if not body.generate_caption:
        return publish_pack, caption, hashtags, title

    script = (body.script or "").strip()
    if len(script) >= 10:
        ollama = await ollama_util.fetch_status(probe=False)
        installed = ollama.get("models") or []
        editor = llm_prof.resolve_editor_model(installed, None)
        lang = (body.language or "tr").lower()
        topic = studio_mod.normalize_topic_for_language(
            body.subject or "", lang
        ) or (body.subject or "")
        try:
            # Kisa video: yayin paketi + Fooocus (son adim). WanGP yalnizca uzun videoda.
            publish_pack = await studio_mod.full_post_production(
                topic=topic,
                script=script,
                platform=body.platform or "tiktok",
                language=body.language or "tr",
                niche_id=body.niche or "genel",
                editor_model=editor,
                aspect=body.aspect or "9:16",
                include_wangp=False,
                include_fooocus=True,
                include_share_tips=lang.startswith("tr"),
                scene_count=5,
            )
            caption = (publish_pack.get("best_caption") or caption).strip()
            hashtags = (publish_pack.get("best_hashtags") or hashtags).strip()
            title = (publish_pack.get("best_title") or title).strip()
            if lang.startswith("en") and (
                not title
                or studio_mod.text_looks_turkish(title)
                or not caption
                or studio_mod.text_looks_turkish(caption)
            ):
                fb_t, fb_c = studio_mod.english_publish_fallback(
                    topic,
                    script,
                    body.niche or "genel",
                )
                if not title or studio_mod.text_looks_turkish(title):
                    title = fb_t
                    publish_pack["best_title"] = title
                if not caption or studio_mod.text_looks_turkish(caption):
                    caption = fb_c
                    publish_pack["best_caption"] = caption
            return publish_pack, caption, hashtags, title
        except Exception:
            pass

    if not caption:
        social = await caption_mod.generate_caption(
            body.subject,
            body.platform or "custom",
            body.language or "tr",
            script,
            niche_id=getattr(body, "niche", None) or getattr(body, "niche_id", None) or "genel",
        )
        caption = social.get("caption", "")
        hashtags = social.get("hashtags", "") or hashtags
        if not title:
            title = (social.get("title") or "").strip()
    lang_final = (body.language or "tr").lower()
    if lang_final.startswith("en") and (
        not title
        or studio_mod.text_looks_turkish(title)
        or not caption
        or studio_mod.text_looks_turkish(caption)
    ):
        fb_t, fb_c = studio_mod.english_publish_fallback(
            studio_mod.normalize_topic_for_language(body.subject or "", "en"),
            script,
            getattr(body, "niche", None) or "genel",
        )
        if not title or studio_mod.text_looks_turkish(title):
            title = fb_t
        if not caption or studio_mod.text_looks_turkish(caption):
            caption = fb_c
    return publish_pack, caption, hashtags, title


def _gpu_ui() -> dict:
    try:
        from akifactory.gpu import gpu_profile_for_ui

        return gpu_profile_for_ui()
    except Exception:
        return {"gpu_available": False}


def _subtitle_overrides(body: SubtitleStyleBody | None) -> dict[str, Any] | None:
    if not body:
        return None
    ov: dict[str, Any] = {}
    if body.font_size_key:
        ov["font_size_key"] = body.font_size_key
    if body.text_fore_color:
        ov["text_fore_color"] = body.text_fore_color
    if body.subtitle_position:
        ov["subtitle_position"] = body.subtitle_position
    if body.text_background_color is not None:
        ov["text_background_color"] = body.text_background_color
    return ov or None


def _apply_lang_preset_to_generate(body: GenerateRequest) -> None:
    if not body.use_lang_preset:
        return
    preset = lang_pres_mod.get(body.production_language)
    if preset.get("tts_engine"):
        body.tts_engine = str(preset["tts_engine"])
        body.tts_provider = body.tts_engine
    if preset.get("edge_voice"):
        body.edge_voice = preset["edge_voice"]
    if preset.get("rvc_voice"):
        body.rvc_voice = preset["rvc_voice"]
    if "rvc_pitch" in preset:
        body.rvc_pitch = int(preset["rvc_pitch"])
    if "rvc_index_rate" in preset:
        body.rvc_index_rate = float(preset["rvc_index_rate"])
    if preset.get("voice_rate"):
        body.voice_rate = float(preset["voice_rate"])
    sid = preset.get("subtitle_style_id")
    if sid:
        if body.subtitle_style is None:
            body.subtitle_style = SubtitleStyleBody(style_id=sid)
        else:
            body.subtitle_style.style_id = sid


async def _require_llm(*, probe: bool = True) -> dict[str, Any]:
    """Ollama veya bulut LLM hazir mi? Degilse 503."""
    ok, err, st = await llm_api_mod.ensure_ready(probe_ollama=probe)
    if not ok:
        raise HTTPException(503, err or "LLM hazir degil")
    return st


def _subtitle_body_from_preset(lang_id: str, style: SubtitleStyleBody | None) -> SubtitleStyleBody | None:
    preset = lang_pres_mod.get(lang_id)
    sid = preset.get("subtitle_style_id")
    if not sid:
        return style
    if style is None:
        return SubtitleStyleBody(style_id=sid)
    return SubtitleStyleBody(
        style_id=sid,
        font_size_key=style.font_size_key,
        text_fore_color=style.text_fore_color,
        subtitle_position=style.subtitle_position,
        text_background_color=style.text_background_color,
    )


async def _fetch_engine_task_materials(task_id: str) -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(f"{engine_base()}/api/v1/tasks/{task_id}")
        if r.status_code != 200:
            return []
        task = _httpx_json(r).get("data") or {}
        raw = task.get("materials") or []
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


async def _start_engine_video_task(payload: dict[str, Any], outro_id: str | None) -> str:
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{engine_base()}/api/v1/videos", json=payload)
        data = _httpx_json(r)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Motor API baglantisi: {e}") from e
    if r.status_code >= 400:
        msg = data.get("message") or data.get("detail") or str(data)
        raise HTTPException(r.status_code, msg or "Motor video gorevi baslatilamadi")
    task_id = (data.get("data") or {}).get("task_id")
    if not task_id:
        raise HTTPException(500, "task_id alinamadi")
    if outro_id:
        outro_mod.register_task_outro(task_id, outro_id)
    from akifactory import task_timing as tt_mod

    tt_mod.record_start(task_id)
    return task_id


async def _build_engine_payload(
    *,
    subject: str,
    platform_id: str,
    production_language: str,
    tts_engine: str,
    edge_voice: str | None = None,
    video_aspect: str | None = None,
    video_source: str,
    video_clip_duration: int | None,
    video_count: int,
    subtitle_style: SubtitleStyleBody | None,
    subtitle_enabled: bool = True,
    bgm_volume: float = 0.2,
    bgm_mode: str = "niche",
    bgm_track: str | None = None,
    voice_rate: float = 1.08,
    paragraph_number: int = 1,
    niche_id: str = "genel",
    video_script: str | None = None,
    rvc_voice: str | None = None,
    rvc_pitch: int = 0,
    rvc_index_rate: float = 1.0,
    video_materials: list[dict[str, str]] | None = None,
) -> tuple[dict[str, Any], str | None]:
    p = plat.resolve(platform_id)
    prod = lang.resolve(production_language)
    tts_in = (tts_engine or "edge").lower()
    tts, tts_note = lang.resolve_effective_tts_engine(
        tts_in,
        rvc_voice=rvc_voice,
        production_language=production_language,
    )
    tts_err = lang.tts_validation_error(production_language, tts)
    if tts_err:
        raise HTTPException(400, tts_err)
    if tts == "rvc" and (rvc_voice or "").strip():
        rvc_err = lang.tts_validation_error(production_language, "rvc")
        if rvc_err:
            raise HTTPException(400, f"RVC: {rvc_err}")
    voice_name = lang.resolve_voice(
        production_language, tts, edge_voice, rvc_voice
    )
    if tts == "rvc":
        from akifactory.rvc_util import configure_tts_rvc_chain

        configure_tts_rvc_chain(
            tts,
            rvc_voice=rvc_voice,
            rvc_pitch=rvc_pitch,
            rvc_index_rate=rvc_index_rate,
            production_language=production_language,
            edge_voice=edge_voice,
        )
    elif tts == "chatterbox":
        from akifactory.rvc_util import configure_tts_rvc_chain

        configure_tts_rvc_chain(
            tts,
            rvc_voice=rvc_voice,
            rvc_pitch=rvc_pitch,
            rvc_index_rate=rvc_index_rate,
            production_language=production_language,
            edge_voice=edge_voice,
        )
    else:
        from akifactory.rvc_util import configure_tts_rvc_chain

        configure_tts_rvc_chain(tts)
    lang.sync_subtitle_provider_for_tts(tts)
    style = sub_st.resolve(
        subtitle_style.style_id if subtitle_style else "tiktok_classic",
        _subtitle_overrides(subtitle_style),
    )
    aspect = video_aspect or p["aspect_ratio"]
    clip = int(video_clip_duration or p["max_clip_duration"])
    sub_pos = p.get("subtitle_position", "bottom")
    resolved_source = await vid_src.resolve_video_source(video_source, subject)
    payload: dict[str, Any] = {
        "video_subject": subject.strip(),
        "video_language": prod.video_language,
        "video_aspect": aspect,
        "video_source": resolved_source,
        "voice_name": voice_name,
        "voice_rate": voice_rate,
        "voice_volume": 1.0,
        "video_count": video_count,
        "video_clip_duration": clip,
        "paragraph_number": paragraph_number,
        "subtitle_enabled": subtitle_enabled,
        "bgm_volume": bgm_volume,
        "font_size": 56,
        "stroke_width": 1.5,
        "subtitle_position": sub_pos,
    }
    if sub_pos == "center":
        payload["subtitle_position"] = "center"
    bgm_type, bgm_file = bgm_mod.resolve_bgm_payload(
        mode=bgm_mode, track=bgm_track, niche_id=niche_id
    )
    payload["bgm_type"] = bgm_type
    payload["bgm_file"] = bgm_file
    sub_st.apply_to_payload(payload, style)
    # Platform konumu stil uzerinde kazanir; kullanici override varsa onu koru
    ov_pos = (_subtitle_overrides(subtitle_style) or {}).get("subtitle_position")
    if ov_pos:
        payload["subtitle_position"] = ov_pos
    else:
        payload["subtitle_position"] = sub_pos
    if payload.get("subtitle_enabled", True):
        payload["font_name"] = fonts_util.ensure_subtitle_font(production_language)
    script_pr.apply_to_payload(
        payload,
        lang_id=production_language,
        platform_id=platform_id,
        niche_id=niche_id,
        subject=subject,
    )
    # motor VideoParams: custom_system_prompt max 8000, video_script_prompt max 2000
    if len(payload.get("custom_system_prompt") or "") > 8000:
        payload["custom_system_prompt"] = (payload["custom_system_prompt"] or "")[:8000]
    if len(payload.get("video_script_prompt") or "") > 2000:
        payload["video_script_prompt"] = (payload["video_script_prompt"] or "")[:2000]
    raw_script = (video_script or "").strip()
    if raw_script:
        cleaned = (
            prepare_script_for_engine(
                raw_script,
                production_language,
                niche_id=niche_id,
            )
            or raw_script
        )
        payload["video_script"] = cleaned.strip() or raw_script
        # Hazir senaryo varken motor ic LLM cagirmasin — promptlari bosalt
        payload["custom_system_prompt"] = ""
        payload["video_script_prompt"] = ""
    if video_materials:
        payload["video_source"] = "local"
        payload["video_materials"] = video_materials
        payload["video_concat_mode"] = "sequential"
    elif resolved_source == "local":
        materials = vid_src.list_local_materials()
        if not materials:
            folder = vid_src.local_videos_dir()
            raise HTTPException(
                400,
                f"Yerel klasorde video/resim yok. Dosyalari buraya koyun:\n{folder}",
            )
        payload["video_materials"] = materials
        payload["video_concat_mode"] = "sequential"
    elif resolved_source != "local":
        # Stok klipler + araya fotograf: sirali montaj (V V I V V)
        payload["video_concat_mode"] = "sequential"
    return payload, tts_note


def create_app() -> FastAPI:
    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        await prod_q.ensure_worker(engine_base())
        yield
        # Pencere/uygulama kapaninca bekleyen sira kalmasin
        try:
            prod_q.clear_queue_on_exit()
        except Exception:
            pass
        prod_q.shutdown_worker()
        await ollama_util.unload_all_models()

    app = FastAPI(title="AkiFactory", docs_url=None, redoc_url=None, lifespan=_lifespan)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_request: Request, exc: Exception):
        if isinstance(exc, HTTPException):
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": jsonable_encoder(exc.detail)},
            )
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc) or "Internal Server Error"},
        )

    @app.middleware("http")
    async def api_json_error_middleware(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            if isinstance(exc, HTTPException):
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": jsonable_encoder(exc.detail)},
                )
            return JSONResponse(
                status_code=500,
                content={"detail": str(exc) or "Internal Server Error"},
            )

    @app.get("/api/health")
    async def health():
        ollama = await ollama_util.fetch_status(probe=False)
        queue_snap = prod_q.get_snapshot()
        queue_busy = bool(queue_snap.get("processing"))
        engine_timeout = 18.0 if queue_busy else 5.0
        try:
            async with httpx.AsyncClient(timeout=engine_timeout) as client:
                r = await client.get(f"{engine_base()}/docs")
            engine_ok = r.status_code == 200
        except Exception:
            # Chatterbox/RVC sirasinda motor meşgul olabilir — yalnizca PID canliyken ölü sayma
            engine_ok = bool(queue_busy and _engine_pid_alive())
        return {
            "ok": engine_ok,
            "engine_busy": queue_busy,
            "engine_api": engine_base(),
            "queue": {
                "active_count": queue_snap.get("active_count", 0),
                "pending_count": queue_snap.get("pending_count", 0),
                "processing": queue_snap.get("processing", False),
                "worker_alive": queue_snap.get("worker_alive", False),
            },
            "ollama": {
                "running": bool(ollama.get("running")),
                "model_ok": ollama.get("model_ok") is not False,
                "model_name": ollama.get("model_name") or ollama_util.get_config_model(),
                "model_error": ollama.get("model_error") or "",
            },
            "llm_api": llm_api_mod.public_settings(),
        }

    @app.get("/api/version")
    async def api_version():
        return {"version": __version__, "api_json_safe": True}

    @app.get("/api/ollama/status")
    async def ollama_status(probe: bool = False):
        status = await ollama_util.fetch_status(probe=probe)
        status["configured_model"] = ollama_util.get_config_model()
        return status

    @app.post("/api/ollama/unload")
    async def ollama_unload():
        await ollama_util.unload_all_models()
        return {"ok": True}

    @app.get("/api/config")
    async def ui_config():
        from akifactory.rvc_registry import list_for_ui as rvc_list_for_ui
        from akifactory.rvc_tts import is_rvc_available

        from akifactory.chatterbox_util import status_dict as chatterbox_status_dict

        # probe=False — sayfa acilisinda model yukleme testi (90 sn) UI'yi kilitlemesin
        ollama = await ollama_util.fetch_status(probe=False)
        outro_mod.ensure_channel_folders()
        installed = ollama.get("models") or []
        llm_pub = llm_api_mod.public_settings()
        cloud = llm_api_mod.is_cloud() and llm_api_mod.provider_key_set()
        if cloud:
            writer_models = llm_api_mod.writer_models_for_ui()
            default_writer = llm_api_mod.resolve_model()
            editor_models = list(writer_models)
            default_editor = default_writer
        else:
            editor_models = llm_prof.list_editor_models_for_ui(installed)
            writer_models = llm_prof.list_writer_models_for_ui(installed)
            default_editor = llm_prof.resolve_editor_model(installed)
            default_writer = llm_prof.resolve_writer_model(installed)
        vision_models = llm_prof.list_vision_models_for_ui(installed)
        default_vision = llm_prof.resolve_vision_model(installed)
        rvc_ok = is_rvc_available()
        return {
            "engine_api": engine_base(),
            "app_version": __version__,
            "production_languages": lang.list_for_ui(),
            "tts_engines": lang.tts_engines_for_ui(rvc_ok=rvc_ok),
            "rvc_available": rvc_ok,
            "rvc_voices": rvc_list_for_ui(lang.DEFAULT_LANGUAGE),
            "rvc_folder": str(app_root() / "models" / "rvc"),
            "edge_voices": lang.EDGE_VOICES,
            "chatterbox_status": chatterbox_status_dict(),
            "platforms": plat.list_for_ui(),
            "video_sources": vid_src.list_for_ui(),
            "niches": script_pr.list_niches_for_ui(),
            "features": features_util.all_flags(),
            "subtitle_styles": sub_st.list_for_ui(),
            "bgm_tracks": bgm_mod.list_tracks_for_ui(),
            "bgm_categories": bgm_mod.list_categories_for_ui(),
            "bgm_folder": str(bgm_mod.user_bgm_dir()),
            "outros": outro_mod.list_for_ui(),
            "outros_folder": str(outro_mod.outros_dir()),
            "llm_writer_model": default_writer,
            "llm_writer_models": writer_models,
            "llm_default_writer": default_writer,
            "llm_editor_models": editor_models,
            "llm_default_editor": default_writer if llm_prof.EDITOR_FOLLOWS_WRITER or cloud else default_editor,
            "llm_editor_follows_writer": bool(llm_prof.EDITOR_FOLLOWS_WRITER) or cloud,
            "llm_pipeline": {
                "writer": default_writer,
                "editor": default_writer if llm_prof.EDITOR_FOLLOWS_WRITER or cloud else default_editor,
                "writer_think": False,
                "editor_follows_writer": bool(llm_prof.EDITOR_FOLLOWS_WRITER) or cloud,
                "editor_think_on": [],
                "provider": llm_pub.get("provider") or "ollama",
                "cloud": cloud,
            },
            "llm_vision_models": vision_models,
            "llm_default_vision": default_vision,
            "defaults": {
                "platform": plat.DEFAULT_PLATFORM,
                "video_aspect": "9:16",
                "video_source": "pexels",
                "production_language": lang.DEFAULT_LANGUAGE,
                "tts_engine": lang.DEFAULT_TTS_ENGINE,
                "niche": "tarih_gizem",
                "subtitle_style_id": "tiktok_classic",
                "bgm_mode": "niche",
                "bgm_volume": 0.2,
                "dual_llm": True,
            },
            "gpu": _gpu_ui(),
            "ollama_status": ollama,
            "llm_api": llm_pub,
            "minimax_h3": h3_bridge_mod.public_settings(),
            "wangp_styles": [
                {"id": k, "label": v} for k, v in wangp_mod.STYLE_LABELS.items()
            ],
            "wangp_line_modes": [
                {"id": k, "label": v} for k, v in wangp_mod.LINE_MODE_LABELS.items()
            ],
            "fooocus_styles": [
                {"id": k, "label": v} for k, v in fooocus_mod.STYLE_LABELS.items()
            ],
            "fooocus_purposes": [
                {"id": k, "label": v} for k, v in fooocus_mod.PURPOSE_LABELS.items()
            ],
            "lang_presets": lang_pres_mod.list_for_ui(),
        }

    @app.get("/api/lang-presets")
    async def lang_presets_get():
        return {"presets": lang_pres_mod.list_for_ui()}

    @app.put("/api/lang-presets/{lang_id}")
    async def lang_presets_put(lang_id: str, body: LangPresetBody):
        try:
            saved = lang_pres_mod.save(lang_id, body.model_dump(exclude_none=True))
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"ok": True, "lang": lang_id, "preset": saved}

    @app.get("/api/settings/assets")
    async def settings_assets_get():
        return settings_mod.scan_all()

    @app.post("/api/settings/refresh")
    async def settings_refresh(body: SettingsSectionBody):
        data = settings_mod.refresh_section(body.section)
        if not data.get("ok"):
            raise HTTPException(400, data.get("error", "Yenileme basarisiz"))
        if body.section.strip().lower() in ("rvc", "all") and "rvc_available" in data:
            data["tts_engines"] = lang.tts_engines_for_ui(rvc_ok=data["rvc_available"])
        return data

    @app.post("/api/settings/files/upload")
    async def settings_files_upload(
        section: str = Form(...),
        target: str = Form(""),
        kind: str = Form(""),
        pitch: int = Form(0),
        files: list[UploadFile] = File(...),
    ):
        import shutil
        import tempfile

        from akifactory import asset_upload as upload_mod

        key = section.strip().lower()
        if key not in upload_mod.MAX_BYTES:
            raise HTTPException(400, "Bolum: bgm, outros veya rvc")
        limit = upload_mod.MAX_BYTES[key]
        tmp_dir = Path(tempfile.mkdtemp(prefix="aki_upload_"))
        try:
            saved: list[tuple[Path, str]] = []
            for i, uf in enumerate(files[:20]):
                name = Path(uf.filename or f"dosya{i}").name
                tmp = tmp_dir / f"{i}_{upload_mod.slug(name)}"
                size = 0
                with tmp.open("wb") as out:
                    while chunk := await uf.read(1024 * 1024):
                        size += len(chunk)
                        if size > limit:
                            raise HTTPException(413, f"{name} cok buyuk (siniri {limit // 1024**2} MB)")
                        out.write(chunk)
                saved.append((tmp, name))
            if not saved:
                raise HTTPException(400, "Dosya secilmedi")

            def _store() -> list[str]:
                if key == "bgm":
                    return [upload_mod.save_bgm(t, n, target).name for t, n in saved]
                if key == "outros":
                    t, n = saved[0]
                    return [upload_mod.save_channel_clip(t, n, target, kind.strip().lower()).name]
                return [upload_mod.save_rvc(saved, target, pitch).name]

            try:
                names = await asyncio.to_thread(_store)
            except (ValueError, RuntimeError) as e:
                raise HTTPException(400, str(e)) from e
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        data = settings_mod.refresh_section(key)
        if key == "rvc" and "rvc_available" in data:
            data["tts_engines"] = lang.tts_engines_for_ui(rvc_ok=data["rvc_available"])
        return {**data, "saved": names}

    @app.post("/api/settings/files/delete")
    async def settings_files_delete(body: AssetDeleteBody):
        from akifactory import asset_upload as upload_mod

        key = body.section.strip().lower()
        try:
            upload_mod.delete_asset(key, body.id)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        data = settings_mod.refresh_section(key)
        if key == "rvc" and "rvc_available" in data:
            data["tts_engines"] = lang.tts_engines_for_ui(rvc_ok=data["rvc_available"])
        return data

    @app.post("/api/settings/open-folder")
    async def settings_open_folder(body: SettingsSectionBody):
        section = body.section.strip().lower()
        if section not in ("rvc", "bgm", "outros"):
            raise HTTPException(400, "Bolum: rvc, bgm veya outros")
        if not settings_mod.open_section_folder(section):
            raise HTTPException(500, "Klasor acilamadi")
        return {"ok": True, "section": section}

    @app.get("/api/telegram/settings")
    async def telegram_settings_get():
        return tg_mod.get_settings_public()

    @app.get("/api/telegram/guide")
    async def telegram_guide():
        return tg_mod.get_telegram_guide()

    @app.put("/api/telegram/settings")
    async def telegram_settings_put(body: TelegramSettingsBody):
        out = tg_mod.update_settings(
            enabled=body.enabled,
            bot_token=body.bot_token,
            chat_id=body.chat_id,
            notify_video=body.notify_video,
            notify_queue=body.notify_queue,
        )
        if body.bot_token and body.bot_token.strip():
            out = await tg_mod.refresh_bot_username_from_token()
        return out

    @app.get("/api/settings/ai-cover")
    async def ai_cover_settings_get():
        from akifactory import ai_cover
        return {**ai_cover.settings(), "installation": ai_cover.installation_status()}

    @app.post("/api/settings/ai-cover/install")
    async def ai_cover_install():
        from akifactory import ai_cover
        return ai_cover.start_install()

    @app.put("/api/settings/ai-cover")
    async def ai_cover_settings_put(body: dict):
        from akifactory import ai_cover
        if not isinstance(body.get("enabled"), bool):
            raise HTTPException(400, "enabled boolean olmali")
        return ai_cover.set_enabled(body["enabled"])

    @app.post("/api/telegram/discover-chat")
    async def telegram_discover_chat():
        detail = await tg_mod.discover_chat_id_detail()
        if not detail.get("ok"):
            raise HTTPException(404, detail.get("error") or "Chat bulunamadi.")
        cid = str(detail.get("chat_id") or "")
        out = tg_mod.update_settings(chat_id=cid)
        if detail.get("bot_username"):
            out = tg_mod.remember_bot_username(detail["bot_username"])
        return out

    @app.post("/api/telegram/test")
    async def telegram_test():
        result = await tg_mod.send_test()
        if not result.get("ok"):
            raise HTTPException(400, result.get("error") or "Telegram gonderilemedi")
        return result

    @app.get("/api/settings/stock-api")
    async def stock_api_settings_get():
        return api_keys_mod.get_settings_public()

    @app.get("/api/settings/stock-api/guide")
    async def stock_api_guide():
        return api_keys_mod.get_api_guide()

    @app.put("/api/settings/stock-api")
    async def stock_api_settings_put(body: StockApiKeysBody):
        return api_keys_mod.update_settings(
            pexels_key=body.pexels_key,
            pixabay_key=body.pixabay_key,
        )

    @app.post("/api/settings/stock-api/test")
    async def stock_api_test(body: StockApiKeysBody | None = None):
        p = body.pexels_key if body and body.pexels_key else None
        x = body.pixabay_key if body and body.pixabay_key else None
        pex = await api_keys_mod.test_pexels(p)
        pix = await api_keys_mod.test_pixabay(x)
        return {"pexels": pex, "pixabay": pix}

    @app.get("/api/settings/stock-api/quota")
    async def stock_api_quota():
        return await api_keys_mod.fetch_quota()

    @app.get("/api/settings/llm")
    async def llm_api_settings_get():
        return llm_api_mod.public_settings()

    @app.put("/api/settings/llm")
    async def llm_api_settings_put(body: LlmApiSettingsBody):
        patch = {k: v for k, v in body.model_dump().items() if v is not None}
        llm_api_mod.save_settings(patch)
        pub = llm_api_mod.public_settings()
        cloud = llm_api_mod.is_cloud() and llm_api_mod.provider_key_set()
        writers = llm_api_mod.writer_models_for_ui() if cloud else []
        default_writer = llm_api_mod.resolve_model() if cloud else ""
        return {
            **pub,
            "llm_writer_models": writers,
            "llm_default_writer": default_writer,
            "llm_writer_model": default_writer,
            "cloud": cloud,
        }

    @app.post("/api/settings/llm/models")
    async def llm_api_models(body: LlmModelsBody):
        res = await llm_api_mod.fetch_models(body.provider, body.api_key)
        if res["provider"] == llm_api_mod.active_provider() and llm_api_mod.provider_key_set():
            res["writer_models"] = llm_api_mod.writer_models_for_ui()
        return res

    @app.post("/api/settings/llm/test")
    async def llm_api_test():
        return await llm_api_mod.test_provider()

    @app.get("/api/settings/minimax-h3")
    async def minimax_h3_settings_get():
        pub = h3_bridge_mod.public_settings()
        from akifactory import minimax_studio_launch as launch

        health = await launch.discover_studio_health(pub.get("base_url"))
        if health.get("ok") and health.get("base_url") and health["base_url"] != pub.get("base_url"):
            h3_bridge_mod.save_settings({"base_url": health["base_url"]})
            pub = h3_bridge_mod.public_settings()
        return {**pub, "health": health}

    @app.put("/api/settings/minimax-h3")
    async def minimax_h3_settings_put(body: MinimaxH3SettingsBody):
        patch = {k: v for k, v in body.model_dump().items() if v is not None}
        cfg = h3_bridge_mod.save_settings(patch)
        from akifactory import minimax_studio_launch as launch

        health = await launch.discover_studio_health(cfg.get("base_url"))
        return {**h3_bridge_mod.public_settings(), "health": health}

    @app.post("/api/settings/minimax-h3/test")
    async def minimax_h3_test():
        from akifactory import minimax_studio_launch as launch

        return await launch.discover_studio_health(h3_bridge_mod.load_settings().get("base_url"))

    @app.post("/api/settings/minimax-h3/start")
    async def minimax_h3_start():
        from akifactory import minimax_studio_launch as launch

        cfg = h3_bridge_mod.load_settings()
        result = await launch.ensure_studio(
            preferred_url=cfg.get("base_url"),
            auto_start=True,
            force_start=True,
        )
        if result.get("ok") and result.get("base_url"):
            h3_bridge_mod.save_settings({"base_url": result["base_url"]})
        return {**h3_bridge_mod.public_settings(), "health": result, **result}

    @app.get("/api/settings/hooks")
    async def hooks_settings_get(niche: str | None = None):
        from akifactory import script_prompts as script_pr

        if niche:
            key = script_pr.resolve_niche(niche)
            return {
                "niche": key,
                "examples": hook_ex_mod.list_for_niche(key),
                "memory": hook_mem_mod.list_for_niche(key),
            }
        return {
            "niches": script_pr.list_niches_for_ui(),
            "examples": hook_ex_mod.public_snapshot(),
            "memory": hook_mem_mod.public_snapshot(),
        }

    @app.post("/api/settings/hooks/examples")
    async def hooks_example_add(body: HookExampleBody):
        from akifactory import script_prompts as script_pr

        key = script_pr.resolve_niche(body.niche)
        try:
            entry = hook_ex_mod.add_example(key, body.text)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"ok": True, "entry": entry, "examples": hook_ex_mod.list_for_niche(key)}

    @app.delete("/api/settings/hooks/examples/{example_id}")
    async def hooks_example_delete(example_id: str, niche: str = "tarih_gizem"):
        from akifactory import script_prompts as script_pr

        key = script_pr.resolve_niche(niche)
        if not hook_ex_mod.remove_example(key, example_id):
            raise HTTPException(404, "Hook ornegi bulunamadi")
        return {"ok": True, "examples": hook_ex_mod.list_for_niche(key)}

    @app.post("/api/settings/hooks/memory")
    async def hooks_memory_add(body: HookMemoryBody):
        from akifactory import script_prompts as script_pr

        key = script_pr.resolve_niche(body.niche)
        rating = "good" if body.rating == "good" else "bad"
        try:
            entry = hook_mem_mod.add_entry(
                key,
                body.text,
                rating=rating,
                topic=body.topic,
                note=body.note,
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"ok": True, "entry": entry, "memory": hook_mem_mod.list_for_niche(key)}

    @app.post("/api/settings/hooks/rate")
    async def hooks_rate_example(body: HookRateBody):
        from akifactory import script_prompts as script_pr

        key = script_pr.resolve_niche(body.niche)
        rating: str = "good" if body.rating == "good" else "bad"
        hook_text = (body.text or "").strip()
        if not hook_text and body.example_id:
            for it in hook_ex_mod.list_for_niche(key):
                if it.get("id") == body.example_id:
                    hook_text = (it.get("text") or "").strip()
                    break
        if len(hook_text) < 8:
            raise HTTPException(400, "Gecersiz hook metni")
        removed = hook_ex_mod.remove_from_pool(key, body.example_id)
        rated_text = removed or hook_text
        try:
            hook_mem_mod.add_entry(key, rated_text, rating=rating, source="manual")
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

        exclude: list[str] = [rated_text]
        exclude.extend(hook_ex_mod.all_texts_for_niche(key))
        mem = hook_mem_mod.list_for_niche(key)
        exclude.extend((it.get("text") or "") for it in (mem.get("good") or []) + (mem.get("bad") or []))

        generated_entry = None
        warning = ""
        for _ in range(3):
            try:
                new_hook = await hook_gen_mod.generate_hook_example(key, exclude=exclude)
                generated_entry = hook_ex_mod.add_example(key, new_hook)
                break
            except ValueError:
                exclude.append(new_hook)
            except Exception as exc:
                warning = str(exc)
                break

        return {
            "ok": True,
            "rated": rated_text,
            "rating": rating,
            "generated": generated_entry,
            "warning": warning or None,
            "examples": hook_ex_mod.list_for_niche(key),
            "memory": hook_mem_mod.list_for_niche(key),
        }

    @app.delete("/api/settings/hooks/memory/{entry_id}")
    async def hooks_memory_delete(entry_id: str, niche: str = "tarih_gizem", rating: str = "good"):
        from akifactory import script_prompts as script_pr

        key = script_pr.resolve_niche(niche)
        r = "good" if rating == "good" else "bad"
        if not hook_mem_mod.remove_entry(key, entry_id, rating=r):
            raise HTTPException(404, "Hafiza kaydi bulunamadi")
        return {"ok": True, "memory": hook_mem_mod.list_for_niche(key)}

    @app.get("/api/setup/status")
    async def setup_status():
        return await setup_mod.fetch_setup_status()

    @app.post("/api/setup/run")
    async def setup_run(body: SetupRunBody | None = None):
        opts = body or SetupRunBody()
        return await setup_mod.run_setup(
            start_ollama=opts.start_ollama,
            pull_model_flag=opts.pull_model,
            install_ffmpeg=opts.install_ffmpeg,
        )

    @app.post("/api/setup/ollama-pull")
    async def setup_ollama_pull():
        if setup_mod._pull_running:
            return {"ok": False, "error": "Model indirme zaten calisiyor"}
        ok, msg = await asyncio.to_thread(setup_mod.pull_model)
        return {"ok": ok, "message": msg}

    @app.get("/api/system/live")
    async def system_live(include_quota: bool = True):
        return await syslive_mod.fetch_live_status(
            engine_base=engine_base(),
            include_quota=include_quota,
            probe_ollama=False,
        )

    @app.post("/api/backup/create")
    async def backup_create():
        try:
            return await asyncio.to_thread(backup_mod.create_backup)
        except Exception as exc:
            raise HTTPException(500, str(exc) or "Yedekleme basarisiz") from exc

    @app.get("/api/backup/list")
    async def backup_list():
        return {"items": backup_mod.list_backups()}

    @app.post("/api/backup/open-folder")
    async def backup_open_folder():
        folder = backup_mod.backups_dir()
        folder.mkdir(parents=True, exist_ok=True)
        import subprocess

        subprocess.run(["explorer", str(folder)], check=False)
        return {"ok": True, "path": str(folder)}

    @app.post("/api/desktop/resolve-video")
    async def desktop_resolve_video(body: DesktopResolveBody):
        from akifactory.video_save import resolve_video_path, safe_video_filename

        src = resolve_video_path(body.url)
        if not src or not src.is_file():
            raise HTTPException(404, "Video dosyasi bulunamadi")
        suggested = safe_video_filename(body.default_name or src.name)
        return {"ok": True, "path": str(src.resolve()), "suggested_name": suggested}

    @app.get("/api/bgm/preview/{filename:path}")
    async def bgm_preview(filename: str):
        path = bgm_mod.resolve_track_path(filename)
        if not path or not path.is_file():
            raise HTTPException(404, "Parca bulunamadi")
        return FileResponse(path, media_type="audio/mpeg", filename=path.name)

    @app.get("/api/history")
    async def api_history():
        return {"items": hist.list_entries()}

    @app.patch("/api/history/{entry_id}/favorite")
    async def api_history_favorite(entry_id: str):
        entry = hist.toggle_favorite(entry_id)
        if not entry:
            raise HTTPException(404, "Kayit bulunamadi")
        return entry

    @app.patch("/api/history/{entry_id}/label")
    async def api_history_label(entry_id: str, body: HistoryLabelBody):
        entry = hist.set_label(entry_id, body.label)
        if not entry:
            raise HTTPException(404, "Kayit bulunamadi")
        return entry

    @app.delete("/api/history/{entry_id}")
    async def api_history_delete(entry_id: str):
        if not hist.delete_entry(entry_id):
            raise HTTPException(404, "Kayit bulunamadi")
        return {"ok": True}

    @app.get("/api/voice/last")
    async def api_voice_last(platform: str | None = None):
        return {"voice": last_voice_mod.get(platform=platform)}

    @app.put("/api/voice/last")
    async def api_voice_last_save(body: LastVoiceBody):
        data = body.model_dump()
        platform = data.pop("platform", None)
        saved = last_voice_mod.save(data, platform=platform)
        return {"voice": saved}

    @app.post("/api/estimate")
    async def api_estimate(body: EstimateRequest):
        """Kuru calistirma — sure/API tahmini (feature: estimate_api)."""
        if not features_util.is_enabled("estimate_api"):
            raise HTTPException(
                404,
                "estimate_api kapali — config.toml [features] estimate_api = true",
            )
        script = (body.script or "").strip()
        per_sec = script_hk.estimate_duration_sec(script) if script else 45
        count = int(body.video_count or 1)
        if body.dual_language:
            count *= 2
        # Kabaca: senaryo + TTS + stok + montaj
        overhead = 90
        total_sec = count * (per_sec + overhead)
        warn = None
        if features_util.is_enabled("topic_similarity_warn") and (body.topic or "").strip():
            warn = topic_mem.similarity_warning(body.topic, body.niche)
        return {
            "ok": True,
            "video_count": count,
            "duration_est_sec_per_video": per_sec,
            "duration_est_sec_total": total_sec,
            "duration_est_min": round(total_sec / 60, 1),
            "api_calls_est": {
                "ollama_script": count if not script else 0,
                "stock_search": count,
                "tts": count,
            },
            "platform": body.platform,
            "niche": body.niche,
            "warning": warn,
            "notes": [
                "Tahmini degerler — gercek sure GPU/ag durumuna gore degisir.",
                "Stok API kotasi Ayarlar → API'ler panelinden kontrol edilir.",
            ],
        }

    @app.get("/api/topic/check")
    async def api_topic_check(topic: str = "", niche: str = "genel"):
        """Benzer konu uyarisi — engellemez (feature: topic_similarity_warn)."""
        if not features_util.is_enabled("topic_similarity_warn"):
            return {"enabled": False, "warning": None, "similar": []}
        similar = topic_mem.find_similar(topic, niche)
        return {
            "enabled": True,
            "warning": topic_mem.similarity_warning(topic, niche),
            "similar": similar,
        }

    @app.get("/api/voice/test/story")
    async def voice_test_story(lang_id: str = "tr"):
        from akifactory import voice_test as vt

        text = vt.default_story(lang_id)
        return {"ok": True, "text": text, "approx_sec": 30}

    @app.post("/api/voice/test")
    async def voice_test(body: VoiceTestBody):
        from akifactory import voice_test as vt

        try:
            result = await asyncio.to_thread(
                vt.synthesize_voice_test,
                tts_engine=body.tts_engine,
                production_language=body.production_language,
                edge_voice=body.edge_voice,
                rvc_voice=body.rvc_voice,
                rvc_pitch=int(body.rvc_pitch),
                rvc_index_rate=float(body.rvc_index_rate),
                voice_rate=float(body.voice_rate),
                text=body.text,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, _short_voice_err(str(exc))) from exc
        except Exception as exc:
            raise HTTPException(500, _short_voice_err(str(exc))) from exc
        return result

    @app.get("/api/voice/test/sample/{filename}")
    async def voice_test_sample(filename: str):
        from akifactory import voice_test as vt

        safe = Path(filename).name
        if safe != filename or ".." in filename:
            raise HTTPException(400, "Gecersiz dosya adi")
        path = vt.samples_dir() / safe
        if not path.is_file():
            raise HTTPException(404, "Test sesi bulunamadi")
        media = "audio/wav" if path.suffix.lower() == ".wav" else "audio/mpeg"
        return FileResponse(path, media_type=media, filename=safe)

    @app.get("/api/voicestudio/status")
    async def voicestudio_status():
        from akifactory import voicestudio_bridge as vs

        return await asyncio.to_thread(vs.status_dict)

    @app.post("/api/voicestudio/select")
    async def voicestudio_select(body: dict[str, Any]):
        from akifactory import voicestudio_bridge as vs

        pid = str(body.get("profile_id") or "").strip()
        if not pid:
            raise HTTPException(400, "profile_id gerekli")
        vs.write_settings(profile_id=pid)
        if body.get("tempo") is not None:
            vs.set_profile_tempo(pid, body.get("tempo"))
        return {"ok": True, "profile_id": pid, "tempo": vs.profile_tempo(pid)}

    @app.post("/api/voicestudio/start")
    async def voicestudio_start():
        from akifactory import voicestudio_bridge as vs

        if not vs.is_installed():
            raise HTTPException(404, "VoiceStudio kurulu degil")
        url = await asyncio.to_thread(vs.ensure_url)
        if not url:
            raise HTTPException(503, "VoiceStudio baslatilamadi — Pinokio'dan Start deneyin")
        return await asyncio.to_thread(vs.status_dict)

    @app.get("/api/chatterbox/status")
    async def chatterbox_status():
        from akifactory.chatterbox_util import status_dict

        return status_dict()

    @app.post("/api/chatterbox/test")
    async def chatterbox_test(body: ChatterboxTestBody):
        from akifactory.chatterbox_util import (
            normalize_turkish_tts_text,
            status_dict,
            synthesize_chatterbox_wav,
        )
        from akifactory.rvc_registry import get_voice as get_rvc_voice
        from akifactory.rvc_util import apply_post_rvc_to_file, configure_tts_rvc_chain

        st = status_dict()
        if not st.get("package_ready"):
            raise HTTPException(
                503, "Chatterbox paketi yok — python scripts/bootstrap.py --chatterbox"
            )
        lang_id = (body.production_language or lang.DEFAULT_LANGUAGE).strip().lower()
        tts_err = lang.tts_validation_error(lang_id, "chatterbox")
        if tts_err:
            raise HTTPException(400, tts_err)
        rvc_id = (body.rvc_voice or "").strip()
        if not rvc_id:
            raise HTTPException(400, "Chatterbox → RVC icin RVC sesi secin")
        sample_text = (body.text or "").strip() or (
            "Merhaba. Bu AkiFactory Chatterbox Multilingual testidir. "
            "Yil 1940 ve yuzde 50 ornekleri rakam normalizasyonu ile okunur."
        )
        spoken = (
            normalize_turkish_tts_text(sample_text)
            if lang_id.startswith("tr")
            else sample_text
        )
        out_dir = app_root() / "data" / "chatterbox_samples"
        out_dir.mkdir(parents=True, exist_ok=True)
        base_wav = out_dir / f"cb-test-{uuid.uuid4().hex[:10]}.wav"
        try:
            synthesize_chatterbox_wav(
                spoken[:500],
                base_wav,
                voice_key="tr-male",
                lang="tr" if lang_id.startswith("tr") else "en",
                normalize=False,
            )
            from akifactory.rvc_tts import is_rvc_available

            if not is_rvc_available():
                raise HTTPException(503, "RVC modeli yok — models/rvc/ klasorunu kontrol edin")
            configure_tts_rvc_chain(
                "chatterbox",
                rvc_voice=rvc_id,
                rvc_pitch=int(body.rvc_pitch),
                rvc_index_rate=float(body.rvc_index_rate),
                production_language=lang_id,
            )
            rvc_wav = base_wav.with_name(base_wav.stem + ".rvc.wav")
            if not apply_post_rvc_to_file(
                str(base_wav), str(rvc_wav), expected_chain="chatterbox"
            ):
                raise HTTPException(500, "RVC donusumu basarisiz")
            meta = get_rvc_voice(rvc_id)
            rvc_label = meta.label if meta else rvc_id
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, str(exc)) from exc
        return {
            "ok": True,
            "url": f"/api/chatterbox/sample/{rvc_wav.name}",
            "filename": rvc_wav.name,
            "chain": f"chatterbox→rvc:{rvc_id}",
            "normalized_text": spoken,
            "rvc_voice": rvc_id,
            "rvc_label": rvc_label,
        }

    @app.get("/api/chatterbox/sample/{filename}")
    async def chatterbox_sample_file(filename: str):
        safe = Path(filename).name
        if safe != filename or ".." in filename:
            raise HTTPException(400, "Gecersiz dosya adi")
        path = app_root() / "data" / "chatterbox_samples" / safe
        if not path.is_file():
            raise HTTPException(404, "Ornek ses bulunamadi")
        return FileResponse(path, media_type="audio/wav", filename=safe)

    @app.get("/api/voice/convert")
    async def voice_convert_list(limit: int = 50):
        return {"items": vc_mod.list_items(limit=limit)}

    @app.post("/api/voice/convert")
    async def voice_convert_upload(
        file: UploadFile = File(...),
        rvc_voice: str = Form(...),
        rvc_pitch: int = Form(0),
        rvc_index_rate: float = Form(1.0),
    ):
        from akifactory.rvc_tts import is_rvc_available

        if not is_rvc_available():
            raise HTTPException(
                503,
                "RVC kullanilamiyor. models/rvc/ klasorune model ekleyin.",
            )
        if not (rvc_voice or "").strip():
            raise HTTPException(400, "RVC sesi secin")
        try:
            data = await file.read()
            import asyncio

            loop = asyncio.get_event_loop()
            entry = await loop.run_in_executor(
                None,
                lambda: vc_mod.convert_upload(
                    data=data,
                    original_name=file.filename or "kayit.wav",
                    rvc_voice=rvc_voice.strip(),
                    rvc_pitch=int(rvc_pitch),
                    rvc_index_rate=float(rvc_index_rate),
                ),
            )
            return {"ok": True, "item": entry}
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except Exception as e:
            raise HTTPException(500, f"Ses donusumu basarisiz: {e}") from e

    @app.get("/api/voice/convert/{entry_id}/stream")
    async def voice_convert_stream(entry_id: str):
        item = vc_mod.get_item(entry_id)
        if not item:
            raise HTTPException(404, "Kayit bulunamadi")
        return FileResponse(item["path"], media_type="audio/wav")

    @app.get("/api/voice/convert/{entry_id}/download")
    async def voice_convert_download(entry_id: str):
        item = vc_mod.get_item(entry_id)
        if not item:
            raise HTTPException(404, "Kayit bulunamadi")
        base = Path(item.get("original_name") or "kayit").stem
        label = (item.get("rvc_voice_label") or "rvc").replace(" ", "_")
        fname = _safe_audio_filename(f"{base}_{label}")
        return FileResponse(
            item["path"],
            media_type="audio/wav",
            filename=fname,
        )

    @app.delete("/api/voice/convert/{entry_id}")
    async def voice_convert_delete(entry_id: str):
        if not vc_mod.delete_item(entry_id):
            raise HTTPException(404, "Kayit bulunamadi")
        return {"ok": True}

    @app.get("/api/drafts")
    async def api_drafts_list():
        return {"items": drafts_mod.list_drafts()}

    @app.get("/api/drafts/{draft_id}")
    async def api_drafts_get(draft_id: str):
        entry = drafts_mod.get_draft(draft_id)
        if not entry:
            raise HTTPException(404, "Taslak bulunamadi")
        return entry

    @app.post("/api/drafts")
    async def api_drafts_save(body: DraftSaveBody):
        if not body.settings:
            raise HTTPException(400, "Taslak ayarlari bos")
        mode = (body.settings.get("mode") or "short").strip().lower()
        if mode == "longform":
            subject = (
                body.settings.get("longform_subject") or body.settings.get("subject") or ""
            ).strip()
            if len(subject) < 2:
                raise HTTPException(400, "Ana konu en az 2 karakter olmali")
        else:
            subject = (body.settings.get("subject") or "").strip()
            batch = body.settings.get("batch_topics") or []
            if not subject and not batch:
                raise HTTPException(400, "Konu veya seri listesi gerekli")
        entry = drafts_mod.save_draft(
            settings=body.settings,
            draft_id=body.id,
            label=body.label,
        )
        return entry

    @app.delete("/api/drafts/{draft_id}")
    async def api_drafts_delete(draft_id: str):
        if not drafts_mod.delete_draft(draft_id):
            raise HTTPException(404, "Taslak bulunamadi")
        return {"ok": True}

    @app.get("/api/gallery/stats")
    async def gallery_stats():
        return await asyncio.to_thread(gal.compute_stats)

    @app.get("/api/gallery")
    async def gallery_list(
        platform: str | None = None,
        niche: str | None = None,
        include_stats: bool = False,
    ):
        def _load():
            items = gal.list_items(
                platform=platform, niche=niche, include_assets=False
            )
            out: dict[str, Any] = {"items": items}
            if include_stats:
                out["stats"] = gal.compute_stats()
            return out

        return await asyncio.to_thread(_load)

    @app.post("/api/gallery/bulk-delete")
    async def gallery_bulk_delete(body: dict[str, Any]):
        ids = body.get("ids") if isinstance(body, dict) else None
        if not isinstance(ids, list) or not ids:
            raise HTTPException(400, "ids gerekli")
        if len(ids) > 100:
            raise HTTPException(400, "En fazla 100 kayit")
        id_list = [str(i) for i in ids]
        pending = []
        for eid in id_list:
            item = gal.get_item(eid)
            if item:
                pending.append(item)
        result = await asyncio.to_thread(gal.delete_items, id_list)
        deleted_set = {str(x) for x in (result.get("deleted") or [])}
        forgotten = atlas_mod.forget_after_gallery_delete(
            [it for it in pending if str(it.get("id") or "") in deleted_set]
        )
        return {"ok": True, **result, "atlas": forgotten}

    @app.get("/api/gallery/longform")
    async def longform_gallery_list(platform: str | None = None, niche: str | None = None):
        return {"items": lf_gal.list_items(platform=platform, niche=niche)}

    @app.post("/api/gallery/longform/bulk-delete")
    async def longform_gallery_bulk_delete(body: dict[str, Any]):
        ids = body.get("ids") if isinstance(body, dict) else None
        if not isinstance(ids, list) or not ids:
            raise HTTPException(400, "ids gerekli")
        if len(ids) > 100:
            raise HTTPException(400, "En fazla 100 kayit")
        result = await asyncio.to_thread(lf_gal.delete_items, [str(i) for i in ids])
        return {"ok": True, **result}

    @app.get("/api/gallery/longform/{entry_id}")
    async def longform_gallery_get(entry_id: str):
        item = lf_gal.get_item(entry_id)
        if not item:
            raise HTTPException(404, "Uzun video bulunamadi")
        return item

    @app.get("/api/gallery/longform/{entry_id}/file/{filename:path}")
    async def longform_gallery_file(entry_id: str, filename: str):
        path = lf_gal.resolve_entry_file(entry_id, filename)
        if not path:
            raise HTTPException(404, "Dosya bulunamadi")
        media = _media_type_for_path(path)
        return FileResponse(path, media_type=media, filename=path.name)

    @app.post("/api/gallery/longform/{entry_id}/open-folder")
    async def longform_gallery_open_folder(entry_id: str):
        result = lf_gal.open_entry_folder(entry_id)
        if not result:
            raise HTTPException(404, "Klasor acilamadi")
        return result

    @app.delete("/api/gallery/longform/{entry_id}")
    async def longform_gallery_delete(entry_id: str):
        if not lf_gal.delete_item(entry_id):
            raise HTTPException(404, "Uzun video bulunamadi")
        return {"ok": True}

    @app.post("/api/gallery/longform/{entry_id}/publish-pack")
    async def longform_gallery_publish_pack(entry_id: str):
        """Uzun video icin baslik / aciklama / etiket uret (kisa video ile ayni yayin paketi)."""
        item = lf_gal.get_item(entry_id)
        if not item:
            raise HTTPException(404, "Uzun video bulunamadi")
        script = (item.get("script") or "").strip() or lf_gal.read_entry_script(entry_id)
        if len(script) < 10:
            raise HTTPException(400, "Senaryo metni yok — yayin paketi uretilemez")
        ollama = await _require_llm(probe=True)
        installed = ollama.get("models") or []
        editor = llm_prof.resolve_editor_model(installed, None)
        lang = (item.get("language") or "tr").lower()
        topic = (
            item.get("main_subject")
            or item.get("title")
            or item.get("subject")
            or "Uzun video"
        )
        # Uzun video: YouTube aciklama/etiket odakli; platform shorts olsa bile uzun format gibi isle
        platform = item.get("platform") or "youtube_shorts"
        try:
            # Uzun video: yayin paketi + WanGP (Fooocus kisa videoda).
            pack = await studio_mod.full_post_production(
                topic=topic,
                script=script,
                platform=platform,
                language=item.get("language") or "tr",
                niche_id=item.get("niche") or "genel",
                editor_model=editor,
                aspect="16:9",
                include_wangp=True,
                include_fooocus=False,
                include_share_tips=lang == "tr",
                scene_count=5,
            )
        except Exception as e:
            raise HTTPException(500, f"Yayin paketi uretilemedi: {e}") from e
        if not pack.get("titles") and not pack.get("descriptions"):
            raise HTTPException(500, "Yayin paketi bos dondu")
        caption = (pack.get("best_caption") or item.get("caption") or "").strip()
        hashtags = (pack.get("best_hashtags") or item.get("hashtags") or "").strip()
        title = (pack.get("best_title") or item.get("title") or topic).strip()
        updated = lf_gal.update_entry(
            entry_id,
            {
                "publish_pack": gal._slim_publish_pack(pack),
                "caption": caption,
                "hashtags": hashtags,
                "title": title,
            },
        )
        if not updated:
            raise HTTPException(500, "Galeri kaydi guncellenemedi")
        if script and not updated.get("script"):
            updated["script"] = script
        return {"ok": True, "publish_pack": pack, "item": updated}

    @app.post("/api/gallery/longform/{entry_id}/wangp")
    async def longform_gallery_wangp(entry_id: str, body: GalleryWangpBody | None = None):
        """Uzun video galerisi — WanGP promptu (Fooocus gibi yeniden uret)."""
        item = lf_gal.get_item(entry_id)
        if not item:
            raise HTTPException(404, "Uzun video bulunamadi")
        ollama = await _require_llm(probe=True)
        script = (item.get("script") or "").strip() or lf_gal.read_entry_script(entry_id)
        topic = (
            item.get("main_subject")
            or item.get("title")
            or item.get("subject")
            or "Uzun video"
        )
        req = body or GalleryWangpBody()
        if req.style not in wangp_mod.STYLE_LABELS:
            raise HTTPException(400, "Gecersiz stil")
        if req.line_mode not in wangp_mod.LINE_MODE_LABELS:
            raise HTTPException(400, "Gecersiz satir modu")
        niche = item.get("niche") or "genel"
        try:
            wangp = await wangp_mod.generate_wangp_prompt(
                topic=topic,
                niche_id=niche,
                scene_count=req.scene_count,
                style=req.style,
                line_mode=req.line_mode,
                aspect="16:9",
                batch_count=max(1, min(2, int(req.batch_count or 1))),
                script=script,
            )
            wangp = studio_mod._normalize_wangp_pack(wangp)
        except Exception as e:
            raise HTTPException(500, f"H3 Studio promptu uretilemedi: {e}") from e
        if not (wangp or {}).get("prompt"):
            raise HTTPException(500, "H3 Studio promptu bos dondu")
        pack = dict(item.get("publish_pack") or {})
        pack["wangp"] = wangp
        updated = lf_gal.update_entry(
            entry_id, {"publish_pack": gal._slim_publish_pack(pack)}
        )
        if not updated:
            raise HTTPException(500, "Galeri kaydi guncellenemedi")
        if script and not updated.get("script"):
            updated["script"] = script
        return {"ok": True, "wangp": wangp, "item": updated}

    @app.get("/api/gallery/{entry_id}")
    async def gallery_get(entry_id: str):
        item = await asyncio.to_thread(gal.get_list_item, entry_id, include_assets=True)
        if not item:
            raise HTTPException(404, "Galeri kaydi bulunamadi")
        return item

    @app.get("/api/gallery/{entry_id}/stream")
    async def gallery_stream(entry_id: str):
        item = gal.get_item(entry_id)
        if not item:
            raise HTTPException(404, "Video bulunamadi")
        return FileResponse(item["path"], media_type="video/mp4")

    @app.get("/api/gallery/{entry_id}/download")
    async def gallery_download(entry_id: str):
        item = gal.get_item(entry_id)
        if not item:
            raise HTTPException(404, "Video bulunamadi")
        fname = _safe_filename(item.get("subject", "akifactory"))
        return FileResponse(
            item["path"],
            media_type="video/mp4",
            filename=fname,
        )

    @app.get("/api/gallery/{entry_id}/audio")
    async def gallery_audio(entry_id: str):
        item = gal.get_item(entry_id)
        if not item:
            raise HTTPException(404, "Video bulunamadi")
        paths = gal.task_montage_paths(item.get("task_id"))
        audio = paths.get("audio")
        if not audio:
            raise HTTPException(404, "Ses dosyasi yok — gorev klasoru silinmis olabilir")
        safe = _safe_filename(item.get("subject", "akifactory")).replace(".mp4", "")
        return FileResponse(
            audio,
            media_type="audio/mpeg",
            filename=f"{safe}-ses.mp3",
        )

    @app.get("/api/gallery/{entry_id}/subtitle")
    async def gallery_subtitle(entry_id: str):
        item = gal.get_item(entry_id)
        if not item:
            raise HTTPException(404, "Video bulunamadi")
        paths = gal.task_montage_paths(item.get("task_id"))
        sub = paths.get("subtitle")
        if not sub:
            raise HTTPException(404, "Altyazi dosyasi yok — gorev klasoru silinmis olabilir")
        safe = _safe_filename(item.get("subject", "akifactory")).replace(".mp4", "")
        return FileResponse(
            sub,
            media_type="application/x-subrip",
            filename=f"{safe}-altyazi.srt",
        )

    @app.get("/api/gallery/{entry_id}/music")
    async def gallery_music(entry_id: str):
        item = gal.get_item(entry_id)
        if not item:
            raise HTTPException(404, "Video bulunamadi")
        path = bgm_mod.resolve_track_path(item.get("bgm_file") or "")
        if not path:
            raise HTTPException(404, "Muzik dosyasi bulunamadi")
        safe = _safe_filename(item.get("subject", "akifactory")).replace(".mp4", "")
        return FileResponse(path, media_type="audio/mpeg", filename=f"{safe}-muzik.mp3")

    @app.get("/api/gallery/{entry_id}/clip/{filename:path}")
    async def gallery_clip(entry_id: str, filename: str):
        item = gal.get_item(entry_id)
        if not item:
            raise HTTPException(404, "Video bulunamadi")
        path = gal.resolve_task_media_path(item.get("task_id"), filename)
        if not path:
            raise HTTPException(404, "Gorsel/klip bulunamadi")
        media = _media_type_for_path(path)
        return FileResponse(path, media_type=media, filename=path.name)

    @app.get("/api/gallery/{entry_id}/thumbnail/download")
    async def gallery_thumbnail_download(entry_id: str):
        from akifactory.paths import gallery_dir as gdir

        item = gal.get_item(entry_id)
        if not item:
            raise HTTPException(404, "Video bulunamadi")
        thumb_fn = item.get("thumbnail") or thumb_mod.thumbnail_filename(entry_id)
        path = gdir() / thumb_fn
        if not path.is_file():
            raise HTTPException(404, "Kapak gorseli yok — once Kapak cek")
        safe = _safe_filename(item.get("subject", "akifactory")).replace(".mp4", ".jpg")
        return FileResponse(path, media_type="image/jpeg", filename=safe)

    @app.get("/api/gallery/{entry_id}/thumbnail/{frame_index}")
    async def gallery_thumbnail_candidate(entry_id: str, frame_index: int):
        from akifactory.paths import gallery_dir as gdir

        fname = thumb_mod._candidate_filename(entry_id, frame_index)
        path = gdir() / fname
        if not path.is_file():
            path = gal.resolve_thumbnail_file(entry_id)
        if not path or not path.is_file():
            raise HTTPException(404, "Kapak adayi bulunamadi")
        return FileResponse(path, media_type="image/jpeg")

    @app.get("/api/gallery/{entry_id}/thumbnail")
    async def gallery_thumbnail_get(entry_id: str):
        path = gal.resolve_thumbnail_file(entry_id)
        if not path or not path.is_file():
            raise HTTPException(404, "Kapak gorseli yok — once Kapak cek")
        return FileResponse(path, media_type="image/jpeg")

    @app.post("/api/gallery/{entry_id}/thumbnail")
    async def gallery_thumbnail_generate(entry_id: str, body: GalleryThumbnailBody | None = None):
        item = gal.get_item(entry_id)
        if not item:
            raise HTTPException(404, "Video bulunamadi")
        from akifactory.paths import gallery_dir as gdir

        frame_index = body.frame_index if body else None
        existing_candidates = item.get("thumbnail_candidates") or []
        chosen = next((c for c in existing_candidates if c.get("index") == frame_index), None)
        if chosen and str(chosen.get("label", "")).startswith("AI kapak"):
            candidate_path = gdir() / thumb_mod._candidate_filename(entry_id, frame_index)
            if not candidate_path.is_file():
                raise HTTPException(404, "AI kapak dosyasi bulunamadi")
            gal.update_entry(entry_id, {"thumbnail": candidate_path.name, "thumbnail_index": frame_index})
            return {"ok": True, "item": gal.get_list_item(entry_id, include_assets=True)}
        try:
            meta = thumb_mod.generate_for_entry(
                Path(item["path"]),
                entry_id,
                gallery_root=gdir(),
                frame_index=frame_index,
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        meta["candidates"].extend(
            c for c in existing_candidates
            if str(c.get("label", "")).startswith("AI kapak")
        )
        updated = gal.update_entry(
            entry_id,
            {
                "thumbnail": meta["thumbnail"],
                "thumbnail_index": meta["thumbnail_index"],
                "thumbnail_candidates": meta["candidates"],
            },
        )
        row = gal.list_items()
        full = next((r for r in row if r.get("id") == entry_id), updated)
        return {
            "ok": True,
            "thumbnail_url": f"/api/gallery/{entry_id}/thumbnail",
            "thumbnail_download": f"/api/gallery/{entry_id}/thumbnail/download",
            "item": full,
            **meta,
        }

    @app.post("/api/gallery/{entry_id}/share-tips")
    async def gallery_share_tips(entry_id: str):
        item = gal.get_item(entry_id)
        if not item:
            raise HTTPException(404, "Video bulunamadi")
        lang = (item.get("language") or "tr").lower()
        if lang != "tr":
            raise HTTPException(400, "Yayin tavsiyeleri yalnizca Turkce videolar icin uretilir")
        script = (item.get("script") or "").strip()
        if len(script) < 10:
            raise HTTPException(400, "Senaryo metni yok — tavsiye uretilemez")
        ollama = await _require_llm(probe=True)
        installed = ollama.get("models") or []
        editor = llm_prof.resolve_editor_model(installed, None)
        try:
            tips = await studio_mod.generate_share_tips_tr(
                topic=item.get("subject") or item.get("title") or "Video",
                script=script,
                platform=item.get("platform") or "tiktok",
                niche_id=item.get("niche") or "genel",
                editor_model=editor,
                aspect=item.get("aspect") or "9:16",
            )
        except Exception as e:
            raise HTTPException(500, f"Yayin tavsiyeleri uretilemedi: {e}") from e
        if not tips:
            raise HTTPException(500, "Yayin tavsiyeleri bos dondu")
        if studio_mod.share_tips_are_placeholders(tips):
            raise HTTPException(
                500,
                "Yayin tavsiyeleri uretilemedi (model yalnizca baslik tekrar etti). Tekrar deneyin.",
            )
        pack = dict(item.get("publish_pack") or {})
        pack["share_tips"] = tips
        updated = gal.update_entry(entry_id, {"publish_pack": gal._slim_publish_pack(pack)})
        if not updated:
            raise HTTPException(500, "Galeri kaydi guncellenemedi")
        row = gal.list_items()
        full = next((r for r in row if r.get("id") == entry_id), updated)
        return {"ok": True, "share_tips": tips, "item": full}

    @app.post("/api/gallery/{entry_id}/fooocus")
    async def gallery_fooocus(entry_id: str, body: GalleryFooocusBody | None = None):
        item = gal.get_item(entry_id)
        if not item:
            raise HTTPException(404, "Video bulunamadi")
        ollama = await _require_llm(probe=True)
        req = body or GalleryFooocusBody()
        if req.style not in fooocus_mod.STYLE_LABELS:
            raise HTTPException(400, "Gecersiz stil")
        if req.purpose not in fooocus_mod.PURPOSE_LABELS:
            raise HTTPException(400, "Gecersiz amac")
        pack = dict(item.get("publish_pack") or {})
        try:
            fooocus = await fooocus_mod.generate_fooocus_prompt_for_gallery(
                subject=item.get("subject") or "",
                title=item.get("title") or "",
                script=item.get("script") or "",
                publish_pack=pack,
                niche_id=item.get("niche") or "genel",
                style=req.style,
                aspect=item.get("aspect") or "9:16",
                purpose=req.purpose,
                variant_count=req.variant_count,
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except Exception as e:
            raise HTTPException(500, f"Fooocus promptu uretilemedi: {e}") from e
        if not fooocus.get("prompt"):
            raise HTTPException(500, "Fooocus promptu bos dondu")
        pack["fooocus"] = fooocus
        updated = gal.update_entry(entry_id, {"publish_pack": gal._slim_publish_pack(pack)})
        if not updated:
            raise HTTPException(500, "Galeri kaydi guncellenemedi")
        row = gal.list_items()
        full = next((r for r in row if r.get("id") == entry_id), updated)
        return {"ok": True, "fooocus": fooocus, "item": full}

    @app.post("/api/gallery/{entry_id}/minimax")
    async def gallery_minimax(entry_id: str, body: GalleryWangpBody | None = None):
        """Kisa video detayinda H3 Studio sahne promptlarini olustur ve sakla."""
        item = gal.get_item(entry_id)
        if not item:
            raise HTTPException(404, "Video bulunamadi")
        await _require_llm(probe=True)
        req = body or GalleryWangpBody(scene_count=8)
        if req.style not in wangp_mod.STYLE_LABELS:
            raise HTTPException(400, "Gecersiz stil")
        if req.line_mode not in wangp_mod.LINE_MODE_LABELS:
            raise HTTPException(400, "Gecersiz satir modu")
        try:
            wangp = await wangp_mod.generate_wangp_prompt(
                topic=item.get("subject") or item.get("title") or "Kisa video",
                niche_id=item.get("niche") or "genel",
                scene_count=req.scene_count,
                style=req.style,
                line_mode=req.line_mode,
                aspect=item.get("aspect") or "9:16",
                batch_count=max(1, min(2, int(req.batch_count or 1))),
                script=(item.get("script") or "").strip(),
            )
            wangp = studio_mod._normalize_wangp_pack(wangp)
        except Exception as e:
            raise HTTPException(500, f"H3 Studio promptu uretilemedi: {e}") from e
        if not (wangp or {}).get("prompt"):
            raise HTTPException(500, "H3 Studio promptu bos dondu")
        pack = dict(item.get("publish_pack") or {})
        pack["wangp"] = wangp
        updated = gal.update_entry(entry_id, {"publish_pack": gal._slim_publish_pack(pack)})
        if not updated:
            raise HTTPException(500, "Galeri kaydi guncellenemedi")
        full = next((r for r in gal.list_items() if r.get("id") == entry_id), updated)
        return {"ok": True, "wangp": wangp, "item": full}

    @app.get("/api/analyze/history")
    async def analyze_history(gallery_id: str | None = None, limit: int = 30):
        return {"items": va_mod.list_history(gallery_id=gallery_id, limit=limit)}

    @app.post("/api/analyze/csv-import")
    async def analyze_csv_import(
        file: UploadFile = File(...),
        gallery_id: str = Form(""),
        topic: str = Form(""),
        platform: str = Form("youtube_shorts"),
        niche: str = Form("tarih_gizem"),
        note: str = Form(""),
        save_history: bool = Form(True),
    ):
        """YouTube Studio CSV ice aktarma — mevcut gorsel analize paralel."""
        raw = await file.read()
        if not raw:
            raise HTTPException(400, "CSV dosyasi bos")
        ollama = await _require_llm(probe=False)
        entry = None
        gid = (gallery_id or "").strip()
        if gid:
            entry = gal.get_item(gid)
            if not entry:
                raise HTTPException(404, "Galeri videosu bulunamadi")
        try:
            report = await va_mod.analyze_youtube_csv(
                csv_text=raw.decode("utf-8-sig", errors="replace"),
                topic=(topic or (entry or {}).get("subject") or "Video").strip(),
                platform=platform or (entry or {}).get("platform") or "youtube_shorts",
                niche_id=niche or (entry or {}).get("niche") or "tarih_gizem",
                note=note,
                gallery_entry=entry,
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except Exception as e:
            raise HTTPException(500, f"CSV analiz hatasi: {e}") from e
        saved = None
        if save_history:
            saved = va_mod.save_analysis(
                gallery_id=gid,
                gallery_subject=(entry or {}).get("subject") or topic or "CSV",
                youtube_stats=str((report.get("csv_meta") or {}).get("row_count") or ""),
                report=report,
                source_type="csv",
                image_mode="youtube_studio_csv",
            )
        return {"ok": True, "report": report, "history": saved}
    @app.post("/api/analyze/stats")
    async def analyze_stats(
        gallery_id: str = Form(...),
        files: list[UploadFile] = File(...),
        note: str = Form(""),
        extra_stats: str = Form(""),
        vision_model: str | None = Form(None),
        save_history: bool = Form(True),
    ):
        """Galeri videosu + YouTube Studio istatistik goruntusu (video karesi analiz edilmez)."""
        item = gal.get_item(gallery_id)
        if not item:
            raise HTTPException(404, "Galeri videosu bulunamadi")
        if not files:
            raise HTTPException(400, "YouTube Studio ekran goruntusu secin")
        ollama = await _require_llm(probe=False)
        installed = ollama.get("models") or []
        vision = llm_prof.resolve_vision_model(installed, vision_model)
        if not vision:
            raise HTTPException(
                503,
                "Vision model yuklu degil. Proje klasorunde: AkiFactory.bat vision",
            )
        uploads: list[tuple[str, bytes]] = []
        for uf in files[: va_mod.MAX_UPLOAD_IMAGES]:
            data = await uf.read()
            uploads.append((uf.filename or "studio.png", data))
        try:
            report = await va_mod.analyze_gallery_stats(
                item,
                uploads,
                note=note,
                extra_stats=extra_stats,
                vision_model=vision,
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except RuntimeError as e:
            raise HTTPException(503, str(e)) from e
        except Exception as e:
            raise HTTPException(500, f"Analiz basarisiz: {e}") from e

        subject = item.get("subject") or item.get("title") or "Video"
        record = None
        if save_history:
            record = va_mod.save_analysis(
                gallery_id=gallery_id,
                gallery_subject=subject,
                youtube_stats=extra_stats,
                report=report,
                source_type="stats",
                image_mode="youtube_studio",
            )
        return {
            "ok": True,
            "vision_model": vision,
            "gallery_id": gallery_id,
            "subject": subject,
            "report": report,
            "saved": record,
        }

    @app.delete("/api/gallery/{entry_id}")
    async def gallery_delete(entry_id: str):
        item = gal.get_item(entry_id)
        if not item:
            raise HTTPException(404, "Video bulunamadi")
        if not gal.delete_item(entry_id):
            raise HTTPException(
                409,
                "Dosya kullanimda — oynatmayı durdurup tekrar deneyin",
            )
        forgotten = atlas_mod.forget_after_gallery_delete([item])
        return {"ok": True, "atlas": forgotten}

    async def _regenerate_gallery_publish_pack(item: dict[str, Any]) -> dict[str, Any]:
        script = (item.get("script") or "").strip()
        if len(script) < 10:
            raise HTTPException(400, "Senaryo metni yok — yayin paketi uretilemez")
        ollama = await _require_llm(probe=True)
        installed = ollama.get("models") or []
        editor = llm_prof.resolve_editor_model(installed, None)
        lang = (item.get("language") or "tr").lower()
        topic = studio_mod.normalize_topic_for_language(
            item.get("subject") or item.get("title") or "Video", lang
        )
        pack = await studio_mod.full_post_production(
            topic=topic or "Video",
            script=script,
            platform=item.get("platform") or "tiktok",
            language=item.get("language") or "tr",
            niche_id=item.get("niche") or "genel",
            editor_model=editor,
            aspect=item.get("aspect") or "9:16",
            include_wangp=False,
            include_fooocus=True,
            include_share_tips=lang.startswith("tr"),
            scene_count=5,
        )
        if not pack.get("titles") and not pack.get("descriptions"):
            raise HTTPException(500, "Yayin paketi bos dondu")
        caption = (pack.get("best_caption") or item.get("caption") or "").strip()
        hashtags = (pack.get("best_hashtags") or item.get("hashtags") or "").strip()
        title = (pack.get("best_title") or "").strip()
        # EN'de Turkce baslik/aciklama kalmasin
        if lang.startswith("en"):
            if (
                not title
                or studio_mod.text_looks_turkish(title)
                or not caption
                or studio_mod.text_looks_turkish(caption)
            ):
                fb_t, fb_c = studio_mod.english_publish_fallback(
                    topic, script, item.get("niche") or "genel"
                )
                if not title or studio_mod.text_looks_turkish(title):
                    title = fb_t
                if not caption or studio_mod.text_looks_turkish(caption):
                    caption = fb_c
        elif not title:
            title = topic or item.get("subject") or "Video"
        updated = gal.update_entry(
            item["id"],
            {
                "publish_pack": gal._slim_publish_pack(pack),
                "caption": caption,
                "hashtags": hashtags,
                "title": title,
            },
        )
        if not updated:
            raise HTTPException(500, "Galeri kaydi guncellenemedi")
        row = gal.list_items()
        return next((r for r in row if r.get("id") == item["id"]), updated)

    async def _regen_publish_field_for_item(
        item: dict[str, Any],
        field: str,
        *,
        longform: bool = False,
    ) -> dict[str, Any]:
        """Sadece title|description|tags|share_tips alanini LLM ile yenile, digeri koru."""
        field_key = (field or "title").strip().lower()
        if field_key in ("baslik", "titles"):
            field_key = "title"
        if field_key in ("aciklama", "caption", "descriptions"):
            field_key = "description"
        if field_key in ("etiket", "hashtags", "hashtag"):
            field_key = "tags"
        if field_key in ("tavsiye", "tips"):
            field_key = "share_tips"
        if field_key not in ("title", "description", "tags", "share_tips"):
            raise HTTPException(
                400,
                "field: title | description | tags | share_tips",
            )

        script = (item.get("script") or "").strip()
        if longform and len(script) < 10:
            from akifactory import longform_gallery as lf_gal

            script = lf_gal.read_entry_script(item.get("id") or "", max_chars=20000)
        if len(script) < 10:
            raise HTTPException(400, "Senaryo metni yok — alan yenilenemez")

        ollama = await _require_llm(probe=True)
        installed = ollama.get("models") or []
        editor = llm_prof.resolve_editor_model(installed, None)
        lang = (item.get("language") or "tr").lower()
        topic = studio_mod.normalize_topic_for_language(
            item.get("main_subject")
            or item.get("subject")
            or item.get("title")
            or "Video",
            lang,
        )
        fresh = await studio_mod.publish_review(
            topic=topic or "Video",
            script=script,
            platform=item.get("platform") or ("youtube" if longform else "tiktok"),
            language=item.get("language") or "tr",
            niche_id=item.get("niche") or "genel",
            editor_model=editor,
            aspect=item.get("aspect") or ("16:9" if longform else "9:16"),
            include_share_tips=field_key == "share_tips" and lang.startswith("tr"),
        )
        if not fresh.get("titles") and not fresh.get("descriptions"):
            raise HTTPException(500, "Yenileme bos dondu")

        pack = dict(item.get("publish_pack") or {})
        updates: dict[str, Any] = {}
        if field_key == "title":
            for k in ("titles", "title_alternatives", "best_title"):
                if k in fresh:
                    pack[k] = fresh[k]
            title = (fresh.get("best_title") or "").strip()
            if lang.startswith("en") and (
                not title or studio_mod.text_looks_turkish(title)
            ):
                fb_t, _ = studio_mod.english_publish_fallback(
                    topic, script, item.get("niche") or "genel"
                )
                title = fb_t
                pack["best_title"] = title
                pack["titles"] = [{"rank": 1, "text": title, "why": "fallback"}]
            if title:
                updates["title"] = title
        elif field_key == "description":
            for k in ("descriptions", "caption_alternatives", "best_caption"):
                if k in fresh:
                    pack[k] = fresh[k]
            caption = (fresh.get("best_caption") or "").strip()
            if lang.startswith("en") and (
                not caption or studio_mod.text_looks_turkish(caption)
            ):
                _, fb_c = studio_mod.english_publish_fallback(
                    topic, script, item.get("niche") or "genel"
                )
                caption = fb_c
                pack["best_caption"] = caption
                pack["descriptions"] = [{"rank": 1, "text": caption, "why": "fallback"}]
            updates["caption"] = caption
        elif field_key == "tags":
            for k in ("hashtag_sets", "youtube_tags", "best_hashtags"):
                if k in fresh:
                    pack[k] = fresh[k]
            updates["hashtags"] = (fresh.get("best_hashtags") or "").strip()
        elif field_key == "share_tips":
            pack["share_tips"] = fresh.get("share_tips") or []

        if longform:
            from akifactory import longform_gallery as lf_gal

            updates["publish_pack"] = gal._slim_publish_pack(pack)
            updated = lf_gal.update_entry(item["id"], updates)
            if not updated:
                raise HTTPException(500, "Uzun video kaydi guncellenemedi")
            return lf_gal.get_item(item["id"]) or updated

        updates["publish_pack"] = gal._slim_publish_pack(pack)
        updated = gal.update_entry(item["id"], updates)
        if not updated:
            raise HTTPException(500, "Galeri kaydi guncellenemedi")
        row = gal.list_items()
        return next((r for r in row if r.get("id") == item["id"]), updated)

    @app.post("/api/gallery/{entry_id}/publish-field")
    async def gallery_publish_field(entry_id: str, body: GalleryPublishFieldBody):
        item = gal.get_item(entry_id)
        if not item:
            raise HTTPException(404, "Video bulunamadi")
        try:
            full = await _regen_publish_field_for_item(
                item, body.field, longform=False
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"Alan yenilenemedi: {e}") from e
        return {
            "ok": True,
            "field": body.field,
            "publish_pack": full.get("publish_pack") or {},
            "item": full,
        }

    @app.post("/api/gallery/longform/{entry_id}/publish-field")
    async def longform_gallery_publish_field(
        entry_id: str, body: GalleryPublishFieldBody
    ):
        from akifactory import longform_gallery as lf_gal

        item = lf_gal.get_item(entry_id)
        if not item:
            raise HTTPException(404, "Uzun video bulunamadi")
        try:
            full = await _regen_publish_field_for_item(
                item, body.field, longform=True
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"Alan yenilenemedi: {e}") from e
        return {
            "ok": True,
            "field": body.field,
            "publish_pack": full.get("publish_pack") or {},
            "item": full,
        }

    @app.post("/api/gallery/{entry_id}/publish-pack")
    async def gallery_publish_pack(entry_id: str):
        item = gal.get_item(entry_id)
        if not item:
            raise HTTPException(404, "Video bulunamadi")
        try:
            full = await _regenerate_gallery_publish_pack(item)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"Yayin paketi uretilemedi: {e}") from e
        return {"ok": True, "publish_pack": full.get("publish_pack") or {}, "item": full}

    @app.post("/api/gallery/fix-en-titles")
    async def gallery_fix_en_titles(limit: int = 30):
        """EN kayitlardaki Turkce baslik/aciklamalari yeniden uret."""
        items = gal.list_items()
        todo = [e for e in items if gal.en_title_needs_fix(e)]
        todo = todo[: max(1, min(80, int(limit or 30)))]
        fixed: list[str] = []
        errors: list[dict[str, str]] = []
        for entry in todo:
            try:
                updated = await _regenerate_gallery_publish_pack(entry)
                fixed.append(updated.get("id") or entry.get("id") or "")
            except HTTPException as e:
                errors.append(
                    {"id": entry.get("id") or "", "error": str(e.detail)}
                )
            except Exception as e:
                errors.append({"id": entry.get("id") or "", "error": str(e)[:200]})
        return {
            "ok": True,
            "checked": len(todo),
            "fixed": len(fixed),
            "ids": [i for i in fixed if i],
            "errors": errors,
            "remaining": max(0, len([e for e in gal.list_items() if gal.en_title_needs_fix(e)])),
        }

    @app.post("/api/gallery/archive")
    async def gallery_archive(body: ArchiveRequest):
        publish_pack, caption, hashtags, title = await _archive_publish_meta(body)
        duration = script_hk.estimate_duration_sec(body.script)
        created = gal.archive_from_task(
            task_id=body.task_id,
            subject=body.subject,
            video_urls=body.videos,
            engine_base=engine_base(),
            aspect=body.aspect,
            platform=body.platform,
            language=body.language,
            voice=body.voice,
            caption=caption,
            hashtags=hashtags,
            niche=body.niche,
            tts_provider=body.tts_provider,
            duration_sec=duration,
            production_sec=int(body.production_sec or 0),
            title=title or body.title,
            script=body.script,
            publish_pack=publish_pack or None,
        )
        if created and body.notify:
            try:
                subj = (body.notify_subject or body.subject or "").strip()
                if subj:
                    await tg_mod.notify_video_ready(subj, task_id=body.task_id)
            except Exception as exc:
                import logging

                logging.getLogger(__name__).warning("Telegram bildirim hatasi: %s", exc)
        return {"archived": len(created), "items": created, "caption": caption, "hashtags": hashtags}

    @app.post("/api/preview/script")
    async def preview_script(body: ScriptPreviewRequest):
        ollama = await _require_llm(probe=True)
        installed = ollama.get("models") or []
        writer, editor = llm_prof.resolve_script_models(
            installed, body.writer_model, body.editor_model
        )
        draft = ""
        pack: dict[str, Any] = {}
        research_brief = ""
        if body.dual_llm:
            pack = await studio_mod.two_pass_script(
                subject=body.video_subject,
                lang_id=body.production_language,
                platform_id=body.platform,
                niche_id=body.niche,
                paragraph_number=body.paragraph_number,
                writer_model_name=writer,
                editor_model=editor,
                web_verify=body.editor_web_verify,
            )
            script = pack.get("script") or ""
            draft = pack.get("draft") or ""
            research_brief = (pack.get("research_brief") or "").strip()
        else:
            if studio_mod.should_use_web_research(body.niche, body.editor_web_verify):
                research_brief, _ = await studio_mod.fetch_topic_research(
                    body.video_subject,
                    lang_id=body.production_language,
                    niche_id=body.niche,
                    model=editor,
                )
            script = await script_pr.generate_script_text(
                subject=body.video_subject,
                lang_id=body.production_language,
                platform_id=body.platform,
                niche_id=body.niche,
                paragraph_number=body.paragraph_number,
                research_context=research_brief,
                writer_model=writer,
            )
        if not script:
            raise HTTPException(500, "Senaryo uretilemedi")
        topic = body.video_subject
        niche = body.niche
        # Dual path zaten fact-check yapti; brief varsa finalize tekrar uygulamasin
        finalize_brief = "" if body.dual_llm else research_brief
        script = await studio_mod.finalize_script(
            script,
            topic=topic,
            platform=body.platform,
            niche_id=niche,
            editor_model=editor,
            dual_llm=bool(body.dual_llm),
            strengthen=bool(body.strengthen_hook),
            web_verify=bool(body.editor_web_verify) and not body.dual_llm,
            research_brief=finalize_brief,
            lang_id=body.production_language,
        )
        hook_ok = script_hk.validate_hook(script, topic, niche_id=niche)
        cliché = script_hk.is_cliche_hook(script, niche_id=niche) or (
            script_hk.is_generic_hook(script) and not script_hk.is_kids_niche(niche)
        )
        script = prepare_video_script(script, niche_id=niche)
        out = {
            "script": script,
            "draft_script": draft,
            "dual_llm": body.dual_llm,
            "writer_model": writer,
            "editor_model": editor if body.dual_llm else "",
            "hook": script_hk.first_sentence(script),
            "hook_strong": hook_ok and not cliché,
            "hook_cliche": cliché,
            "char_count": len(script),
            "duration_est_sec": script_hk.estimate_duration_sec(script),
        }
        if body.dual_llm:
            out["web_verified"] = pack.get("web_verified")
            out["web_sources"] = pack.get("web_sources", 0)
        if features_util.is_enabled("topic_similarity_warn"):
            out["topic_warning"] = topic_mem.similarity_warning(topic, niche)
        return out

    @app.post("/api/publish/review")
    async def publish_review(body: PublishReviewRequest):
        ollama = await _require_llm(probe=True)
        installed = ollama.get("models") or []
        editor = llm_prof.resolve_editor_model(installed, body.editor_model)
        try:
            result = await studio_mod.full_post_production(
                topic=body.topic.strip(),
                script=body.script.strip(),
                platform=body.platform,
                language=body.production_language,
                niche_id=body.niche,
                editor_model=editor,
                aspect=body.video_aspect,
                include_wangp=body.include_wangp,
                include_fooocus=bool(getattr(body, "include_fooocus", False)),
                include_share_tips=body.include_share_tips,
                wangp_style=body.wangp_style,
                wangp_line_mode=body.wangp_line_mode,
                scene_count=body.scene_count,
            )
        except Exception as e:
            raise HTTPException(500, f"Yayin paketi uretilemedi: {e}") from e
        if not result.get("titles") and not result.get("descriptions"):
            raise HTTPException(500, "Yayin paketi bos dondu")
        result["writer_model"] = llm_prof.writer_model()
        return result

    @app.post("/api/suggest/topics")
    async def suggest_topics(body: SuggestTopicsRequest):
        niche = (body.niche or "tarih_gizem").strip() or "tarih_gizem"
        want = 1 if niche == "seyahat" else int(body.count)
        blocked = topic_mem.get_blocked(niche)
        for entry in hist.list_entries():
            if (entry.get("niche") or "genel") == niche:
                topic = (entry.get("topic") or "").strip()
                if topic and not any(topic_mem.topics_match(topic, b) for b in blocked):
                    blocked.append(topic)

        recent = topic_mem.get_recent_suggested(niche)
        avoid = blocked + [t for t in recent if not any(topic_mem.topics_match(t, b) for b in blocked)]

        raw = await script_pr.suggest_topics(niche, want, exclude=avoid)
        topics = topic_mem.filter_new(raw, avoid, loose=True)[:want]

        if len(topics) < want:
            more = await script_pr.suggest_topics(niche, want * 2, exclude=avoid + topics)
            topics = topic_mem.filter_new(topics + more, avoid, loose=True)[:want]

        if not topics:
            # Son oneriler hepsini eledi — yalnizca uretilmisleri dislayarak dene
            topics = topic_mem.filter_new(raw, blocked, loose=True)[:want]

        import random

        random.shuffle(topics)
        topic_mem.remember_suggested(niche, topics)

        return {
            "topics": topics,
            "memory": topic_mem.stats(niche),
        }

    @app.post("/api/wangp/prompt")
    async def wangp_prompt(body: WangpPromptRequest):
        ollama = await _require_llm(probe=True)
        if body.line_mode not in wangp_mod.LINE_MODE_LABELS:
            raise HTTPException(400, "Gecersiz satir modu")
        if body.style not in wangp_mod.STYLE_LABELS:
            raise HTTPException(400, "Gecersiz stil")
        result = await wangp_mod.generate_wangp_prompt(
            topic=body.topic,
            niche_id=body.niche,
            scene_count=body.scene_count,
            batch_count=body.batch_count,
            style=body.style,
            line_mode=body.line_mode,
            aspect=body.aspect,
        )
        if not result.get("scenes"):
            raise HTTPException(500, "H3 Studio promptu uretilemedi")
        return result

    @app.post("/api/fooocus/prompt")
    async def fooocus_prompt(body: FooocusPromptRequest):
        ollama = await _require_llm(probe=True)
        if body.style not in fooocus_mod.STYLE_LABELS:
            raise HTTPException(400, "Gecersiz stil")
        if body.purpose not in fooocus_mod.PURPOSE_LABELS:
            raise HTTPException(400, "Gecersiz amac")
        if body.aspect not in ("9:16", "16:9", "1:1"):
            raise HTTPException(400, "Gecersiz en-boy orani")
        result = await fooocus_mod.generate_fooocus_prompt(
            topic=body.topic,
            niche_id=body.niche,
            style=body.style,
            aspect=body.aspect,
            purpose=body.purpose,
            variant_count=body.variant_count,
        )
        if not result.get("prompt"):
            raise HTTPException(500, "Fooocus promptu uretilemedi")
        return result

    @app.post("/api/ai-visuals/prompts")
    async def ai_visuals_prompts(body: AiVisualPromptBody):
        ollama = await _require_llm(probe=True)
        topic = (body.topic or "").strip()
        script = (body.script or "").strip() or None
        if len(topic) < 2 and not (script and len(script) >= 20):
            raise HTTPException(400, "Konu veya senaryo gerekli")
        try:
            return await ai_vis.build_prompt_pack(
                topic=topic or "video",
                niche_id=body.niche,
                segment_count=body.segment_count,
                continue_mode=body.continue_mode,
                script=script,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/ai-visuals/assets")
    async def ai_visuals_list():
        return {"ok": True, "assets": ai_vis.list_assets()}

    @app.post("/api/ai-visuals/upload")
    async def ai_visuals_upload(files: list[UploadFile] = File(...)):
        saved: list[dict[str, Any]] = []
        for f in files:
            raw = await f.read()
            try:
                saved.append(ai_vis.save_upload(f.filename or "asset.bin", raw))
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "assets": saved, "all": ai_vis.list_assets()}

    @app.delete("/api/ai-visuals/assets/{asset_id}")
    async def ai_visuals_delete(asset_id: str):
        if not ai_vis.delete_asset(asset_id):
            raise HTTPException(404, "Dosya yok")
        return {"ok": True, "assets": ai_vis.list_assets()}

    @app.get("/api/ai-visuals/file/{filename}")
    async def ai_visuals_file(filename: str):
        path = ai_vis.resolve_asset_path(filename)
        if path is None:
            raise HTTPException(404, "Dosya yok")
        return FileResponse(path)

    @app.post("/api/batch/{batch_id}/ai-visuals/resume")
    async def batch_ai_visuals_resume(batch_id: str, body: AiVisualResumeBody):
        try:
            return batch_mod.resume_ai_visuals(
                batch_id,
                asset_ids=list(body.asset_ids or []),
                task_index=body.task_index,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/generate")
    async def generate(body: GenerateRequest):
        try:
            return await _generate_impl(body)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, str(exc) or "Video uretimi baslatilamadi") from exc

    async def _generate_impl(body: GenerateRequest):
        ollama = await _require_llm(probe=False)
        _apply_lang_preset_to_generate(body)
        model = ollama_util.get_config_model()
        installed = ollama.get("models") or []
        if (not llm_api_mod.is_cloud()) and model and not ollama_util.model_installed(model, installed):
            raise HTTPException(400, f"Model yuklu degil. ollama pull {model}")

        tts_in = body.tts_provider or body.tts_engine
        had_client_script = bool((body.video_script or "").strip())
        script_text = (body.video_script or "").strip() or None
        writer, editor = llm_prof.resolve_script_models(
            installed, body.writer_model, body.editor_model
        )
        research_brief = ""

        dual_ok = False
        if body.dual_llm and not had_client_script:
            pack = await studio_mod.two_pass_script(
                subject=body.video_subject,
                lang_id=body.production_language,
                platform_id=body.platform,
                niche_id=body.niche,
                paragraph_number=body.paragraph_number,
                writer_model_name=writer,
                editor_model=editor,
                web_verify=body.editor_web_verify,
            )
            script_text = pack.get("script") or None
            research_brief = (pack.get("research_brief") or "").strip()
            dual_ok = bool((script_text or "").strip())

        if not (script_text or "").strip() and not had_client_script:
            if studio_mod.should_use_web_research(body.niche, body.editor_web_verify):
                research_brief, _ = await studio_mod.fetch_topic_research(
                    body.video_subject,
                    lang_id=body.production_language,
                    niche_id=body.niche,
                    model=editor,
                )
            script_text = await script_pr.generate_script_text(
                subject=body.video_subject,
                lang_id=body.production_language,
                platform_id=body.platform,
                niche_id=body.niche,
                paragraph_number=body.paragraph_number,
                research_context=research_brief,
                writer_model=writer,
            )

        if (script_text or "").strip() and not had_client_script:
            # Dual basariliysa finalize tekrar fact-check yapmasin; fallback'te brief kalsin
            script_text = await studio_mod.finalize_script(
                script_text or "",
                topic=body.video_subject,
                platform=body.platform,
                niche_id=body.niche,
                editor_model=editor,
                dual_llm=dual_ok,
                strengthen=bool(body.strengthen_hook),
                web_verify=bool(body.editor_web_verify) and not dual_ok,
                research_brief="" if dual_ok else research_brief,
                lang_id=body.production_language,
            )

        if not (script_text or "").strip():
            model = ollama_util.get_config_model() or "qwen3.5:9b"
            raise HTTPException(
                503,
                f"Senaryo uretilemedi. Ollama acik mi? (ollama serve) "
                f"Model yuklu mu? (ollama pull {model})",
            )

        video_materials = None
        video_source = body.video_source
        if body.ai_manual_visuals:
            # AI gorsel akisi batch kuyrugu uzerinden (senaryo sonrasi pause).
            # /api/generate dogrudan motor baslatir — burada desteklenmez.
            raise HTTPException(
                400,
                "AI gorsel/video icin 'Videoyu uret' kullan (kuyruk). "
                "Senaryo sonrasi promptlar gosterilir.",
            )

        payload, tts_note = await _build_engine_payload(
            subject=body.video_subject,
            platform_id=body.platform,
            production_language=body.production_language,
            tts_engine=tts_in,
            edge_voice=body.edge_voice,
            video_aspect=body.video_aspect,
            video_source=video_source,
            video_clip_duration=body.video_clip_duration,
            video_count=body.video_count,
            subtitle_style=body.subtitle_style,
            subtitle_enabled=body.subtitle_enabled,
            bgm_volume=body.bgm_volume,
            bgm_mode=body.bgm_mode,
            bgm_track=body.bgm_track,
            voice_rate=body.voice_rate,
            paragraph_number=body.paragraph_number,
            niche_id=body.niche,
            video_script=script_text,
            rvc_voice=body.rvc_voice,
            rvc_pitch=body.rvc_pitch,
            rvc_index_rate=body.rvc_index_rate,
            video_materials=video_materials,
        )
        prod = lang.resolve(body.production_language)
        tts, _ = lang.resolve_tts_with_fallback(body.production_language, tts_in)
        voice_name = lang.resolve_voice(
            body.production_language,
            tts,
            body.edge_voice,
            body.rvc_voice,
        )
        if not (payload.get("video_script") or "").strip():
            raise HTTPException(
                500,
                "Senaryo motora iletilemedi (video_script bos). Onizlemedeki metni "
                "kaydedip tekrar deneyin.",
            )
        try:
            task_id = await _start_engine_video_task(payload, body.outro_id)
        except HTTPException:
            raise
        hist.add_entry(
            topic=body.video_subject.strip(),
            platform=body.platform,
            language=prod.id,
            voice=voice_name,
            tts_engine=tts,
            niche=body.niche,
        )
        topic_mem.remember_produced(body.niche, body.video_subject.strip())
        out: dict[str, Any] = {"task_id": task_id, "script": script_text or ""}
        if tts_note:
            out["tts_fallback"] = tts_note
        if body.dual_llm and not had_client_script:
            out["dual_llm"] = True
            out["writer_model"] = writer
            out["editor_model"] = editor
        if features_util.is_enabled("topic_similarity_warn"):
            out["topic_warning"] = topic_mem.similarity_warning(
                body.video_subject.strip(), body.niche
            )
        return out

    @app.post("/api/video/reuse-cleanup/{tag}")
    async def video_reuse_cleanup(tag: str):
        vid_src.cleanup_reuse_folder(tag.strip())
        return {"ok": True}

    @app.post("/api/generate/language-variant")
    async def generate_language_variant(body: LanguageVariantRequest):
        """Ayni stok kliplerle farkli dilde ses + altyazi uretir."""
        ollama = await _require_llm(probe=False)

        target = (body.target_language or "en").strip().lower()
        if target not in lang_pres_mod.SUPPORTED:
            raise HTTPException(400, "Hedef dil: tr veya en")

        tag = body.source_task_id[:12]
        extra = await _fetch_engine_task_materials(body.source_task_id)
        materials = vid_src.stage_task_clips_for_reuse(
            body.source_task_id,
            tag,
            extra_paths=extra or None,
        )
        if not materials:
            raise HTTPException(
                400,
                "Kaynak gorevde stok klip bulunamadi. Once Turkce videoyu tamamlayin.",
            )

        script_text = body.source_script.strip()
        if target == "en":
            script_text = await script_tr_mod.translate_script(
                script_text,
                from_lang="tr",
                to_lang="en",
            )
        if not script_text.strip():
            vid_src.cleanup_reuse_folder(tag)
            raise HTTPException(500, "Senaryo cevirisi basarisiz")

        gen_like = GenerateRequest(
            video_subject=(body.subject or "Video").strip() or "Video",
            platform=body.platform,
            video_aspect=body.video_aspect,
            video_source="local",
            production_language=target,
            niche=body.niche,
            video_script=script_text,
            video_count=1,
            video_clip_duration=body.video_clip_duration,
            subtitle_style=body.subtitle_style,
            bgm_volume=body.bgm_volume,
            bgm_mode=body.bgm_mode,
            bgm_track=body.bgm_track,
            outro_id=body.outro_id,
            use_lang_preset=body.use_lang_preset,
            dual_llm=False,
            strengthen_hook=False,
        )
        if body.use_lang_preset:
            _apply_lang_preset_to_generate(gen_like)
        else:
            tts_manual = body.tts_provider or body.tts_engine
            if tts_manual:
                gen_like.tts_engine = tts_manual
                gen_like.tts_provider = tts_manual
            if body.edge_voice:
                gen_like.edge_voice = body.edge_voice
            if body.rvc_voice:
                gen_like.rvc_voice = body.rvc_voice
            if body.rvc_pitch is not None:
                gen_like.rvc_pitch = int(body.rvc_pitch)
            if body.rvc_index_rate is not None:
                gen_like.rvc_index_rate = float(body.rvc_index_rate)
        gen_like.subtitle_style = _subtitle_body_from_preset(target, gen_like.subtitle_style)

        tts_in = gen_like.tts_provider or gen_like.tts_engine
        try:
            payload, tts_note = await _build_engine_payload(
                subject=gen_like.video_subject,
                platform_id=gen_like.platform,
                production_language=target,
                tts_engine=tts_in,
                edge_voice=gen_like.edge_voice,
                video_aspect=gen_like.video_aspect,
                video_source="local",
                video_clip_duration=gen_like.video_clip_duration,
                video_count=1,
                subtitle_style=gen_like.subtitle_style,
                subtitle_enabled=True,
                bgm_volume=gen_like.bgm_volume,
                bgm_mode=gen_like.bgm_mode,
                bgm_track=gen_like.bgm_track,
                voice_rate=gen_like.voice_rate,
                paragraph_number=1,
                niche_id=gen_like.niche,
                video_script=script_text,
                rvc_voice=gen_like.rvc_voice,
                rvc_pitch=gen_like.rvc_pitch,
                rvc_index_rate=gen_like.rvc_index_rate,
                video_materials=materials,
            )
            if not (payload.get("video_script") or "").strip():
                vid_src.cleanup_reuse_folder(tag)
                raise HTTPException(
                    500,
                    "Ingilizce senaryo motora iletilemedi. TR senaryo bos olabilir.",
                )
            task_id = await _start_engine_video_task(payload, gen_like.outro_id)
        except HTTPException:
            vid_src.cleanup_reuse_folder(tag)
            raise
        except Exception as e:
            vid_src.cleanup_reuse_folder(tag)
            raise HTTPException(500, str(e)) from e

        prod = lang.resolve(target)
        tts, _ = lang.resolve_tts_with_fallback(target, tts_in)
        voice_name = lang.resolve_voice(
            target,
            tts,
            gen_like.edge_voice,
            gen_like.rvc_voice,
        )
        hist.add_entry(
            topic=gen_like.video_subject.strip(),
            platform=gen_like.platform,
            language=prod.id,
            voice=voice_name,
            tts_engine=tts,
            niche=gen_like.niche,
        )
        out: dict[str, Any] = {
            "task_id": task_id,
            "production_language": target,
            "script": script_text,
            "reuse_tag": tag,
        }
        if tts_note:
            out["tts_fallback"] = tts_note
        return out

    @app.post("/api/batch/generate")
    async def batch_generate(body: BatchGenerateRequest, background_tasks: BackgroundTasks):
        topics = [t.strip() for t in body.topics if t.strip()]
        if not topics:
            raise HTTPException(400, "En az bir konu gerekli")
        if len(topics) > 10:
            raise HTTPException(400, "En fazla 10 konu")
        # Tek konu: ayni baslik zaten uretiliyorsa ikinci kuyruk satiri acma.
        if len(topics) == 1:
            await prod_q.ensure_worker(engine_base())
            collision = prod_q.active_topic_collision(
                topics,
                kinds={prod_q.KIND_SINGLE, prod_q.KIND_BATCH},
            )
            if collision and collision.status == prod_q.STATUS_RUNNING:
                return {
                    "batch_id": collision.ref_id,
                    "queue_id": collision.queue_id,
                    "position": prod_q.queue_position(collision.queue_id),
                    "total": len(topics),
                    "queued": False,
                    "already_running": True,
                    "message": "Bu konu zaten uretiliyor — yeni sira eklenmedi.",
                }
            if collision and collision.status == prod_q.STATUS_PENDING:
                prod_q.cancel_item(collision.queue_id, remove=True)
        prod_lang = body.production_language
        second_lang = None
        if body.dual_language:
            prod_lang, second_lang = batch_mod.dual_languages(
                {"production_language": prod_lang, "second_language": body.second_language}
            )
        video_source = body.video_source
        video_clip = body.video_clip_duration
        pinokio = vid_src.is_pinokio_source(video_source)
        ai_manual = bool(body.ai_manual_visuals) or pinokio
        auto_h3 = bool(body.ai_visual_auto_minimax) or pinokio
        if ai_manual:
            # Stok yok — senaryo sonrasi AI gorsel / MiniMax adimi
            video_clip = video_clip or ai_vis.SEGMENT_SECONDS
        common = {
            "platform": body.platform,
            "video_aspect": body.video_aspect,
            "video_source": video_source,
            "production_language": prod_lang,
            "tts_engine": body.tts_provider or body.tts_engine,
            "edge_voice": body.edge_voice,
            "niche": body.niche,
            "video_clip_duration": video_clip,
            "subtitle_style_id": (body.subtitle_style.style_id if body.subtitle_style else "tiktok_classic"),
            "subtitle_overrides": _subtitle_overrides(body.subtitle_style),
            "bgm_volume": body.bgm_volume,
            "bgm_mode": body.bgm_mode,
            "bgm_track": body.bgm_track,
            "voice_rate": body.voice_rate,
            "rvc_voice": body.rvc_voice,
            "rvc_pitch": body.rvc_pitch,
            "rvc_index_rate": body.rvc_index_rate,
            "outro_id": body.outro_id,
            "dual_llm": body.dual_llm,
            "strengthen_hook": body.strengthen_hook,
            "editor_web_verify": body.editor_web_verify,
            "writer_model": body.writer_model,
            "editor_model": body.editor_model,
            "dual_language": body.dual_language,
            "second_language": second_lang,
            "use_lang_preset": body.use_lang_preset,
            "en_tts_engine": body.en_tts_engine,
            "en_edge_voice": body.en_edge_voice,
            "en_rvc_voice": body.en_rvc_voice,
            "en_rvc_pitch": body.en_rvc_pitch,
            "en_rvc_index_rate": body.en_rvc_index_rate,
            "niche_experimental": body.niche_experimental,
            "ai_manual_visuals": ai_manual,
            "ai_visual_continue": body.ai_visual_continue if not pinokio else True,
            "ai_visual_segments": body.ai_visual_segments,
            "ai_visual_auto_minimax": auto_h3,
            "production_mode": "manual" if body.production_mode == "manual" else "automatic",
        }
        batch_id = batch_mod.create_batch(topics, common, scripts=body.scripts)
        if len(topics) == 1:
            kind = prod_q.KIND_SINGLE
            label = f"Kisa video: {topics[0][:60]}"
        else:
            kind = prod_q.KIND_BATCH
            label = f"Seri uretim ({len(topics)} video)"
        item = prod_q.enqueue(
            kind,
            batch_id,
            label,
            meta={
                "count": len(topics),
                "auto_retry_failed": body.auto_retry_failed,
                "auto_retry_rounds": body.auto_retry_rounds,
                "recover": {
                    "topics": topics,
                    "common": common,
                    "scripts": body.scripts,
                },
            },
        )
        await prod_q.ensure_worker(engine_base())
        return {
            "batch_id": batch_id,
            "queue_id": item.queue_id,
            "position": prod_q.queue_position(item.queue_id),
            "total": len(topics),
            "queued": True,
        }

    @app.get("/api/topic-memory")
    async def topic_memory_get(niche: str = "tarih_gizem"):
        niche_id = (niche or "tarih_gizem").strip() or "tarih_gizem"
        # Uretim sirasi (hafiza) + mystery ID eslesmesi
        ordered_items = atlas_mod.list_produced_ordered(niche_id)
        if ordered_items:
            return {
                "niche": niche_id,
                "produced": [it["title"] for it in ordered_items],
                "produced_items": ordered_items,
                "ordered_by": "production",
                "stats": {
                    "produced": len(ordered_items),
                    "blocked": len(ordered_items),
                },
            }
        blocked = topic_mem.get_blocked(niche_id)
        # Hafiza en yeni basta — liste sirasi icin eskiden yeniye cevir
        chronological = list(reversed(blocked))
        return {
            "niche": niche_id,
            "produced": chronological,
            "produced_items": [
                {"id": None, "title": t, "category": ""} for t in chronological
            ],
            "ordered_by": "memory",
            "stats": topic_mem.stats(niche_id),
        }

    @app.delete("/api/topic-memory")
    async def topic_memory_delete(niche: str = "tarih_gizem", topic: str = ""):
        niche_id = (niche or "tarih_gizem").strip() or "tarih_gizem"
        if not topic.strip():
            raise HTTPException(400, "Konu gerekli")
        ok = atlas_mod.forget_atlas_topic(topic, niche_id=niche_id)
        if not ok and not topic_mem.forget_produced(niche_id, topic):
            raise HTTPException(404, "Konu bulunamadi")
        return {"ok": True}

    @app.post("/api/gallery/{entry_id}/open-folder")
    async def gallery_open_folder(entry_id: str):
        if not gal.open_entry_folder(entry_id):
            raise HTTPException(404, "Galeri kaydi veya dosya bulunamadi")
        return {"ok": True}

    @app.get("/api/queue")
    async def queue_status():
        await prod_q.ensure_worker(engine_base())
        prod_q.drop_completed()
        return prod_q.get_snapshot()

    async def _delete_engine_tasks_bg(task_ids: list[str]) -> None:
        """motor silme Windows'ta kilitli dosyada takilabilir — UI'yi bloklama."""
        if not task_ids:
            return
        base = engine_base()

        async def _one(tid: str) -> None:
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    await client.delete(f"{base}/api/v1/tasks/{tid}")
            except Exception:
                pass

        await asyncio.gather(*[_one(tid) for tid in task_ids], return_exceptions=True)

    @app.delete("/api/queue")
    async def queue_cancel_all():
        cancelled, task_ids = prod_q.cancel_all(remove=True)
        if task_ids:
            asyncio.create_task(_delete_engine_tasks_bg(task_ids))
        return {"cancelled": cancelled, "removed": True}

    @app.delete("/api/queue/{queue_id}")
    async def queue_cancel_one(queue_id: str):
        ok, task_ids = prod_q.cancel_item(queue_id, remove=True)
        if not ok:
            raise HTTPException(404, "Kuyruk kaydi bulunamadi")
        if task_ids:
            asyncio.create_task(_delete_engine_tasks_bg(task_ids))
        return {"ok": True}

    @app.get("/api/batch/{batch_id}")
    async def batch_status(batch_id: str):
        data = batch_mod.get_batch(batch_id)
        if not data:
            raise HTTPException(404, "Batch bulunamadi")
        return data

    @app.delete("/api/batch/{batch_id}")
    async def batch_cancel(batch_id: str):
        if not batch_mod.cancel_batch(batch_id):
            raise HTTPException(404, "Batch bulunamadi")
        return {"ok": True}

    @app.post("/api/longform/plan")
    async def longform_plan(body: LongformPlanRequest):
        chapters = await longform_mod.plan_chapters(
            body.subject,
            niche_id=body.niche,
            count=body.chapter_count,
        )
        if not chapters:
            raise HTTPException(
                502,
                "Bolum plani uretilemedi. Ollama calisiyor mu? ollama serve",
            )
        return {"chapters": chapters, "count": len(chapters)}

    @app.post("/api/longform/plan-questions")
    async def longform_plan_questions(body: LongformQuestionsRequest):
        questions = await longform_mod.plan_questions(
            body.subject,
            niche_id=body.niche,
            draft_chapters=body.draft_chapters or [],
        )
        if not questions:
            raise HTTPException(
                502,
                "Planlama sorulari uretilemedi. Ollama calisiyor mu? ollama serve",
            )
        return {"questions": questions, "count": len(questions)}

    @app.post("/api/longform/brainstorm")
    async def longform_brainstorm(body: LongformBrainstormRequest):
        plan = await longform_mod.brainstorm_topic(
            body.subject,
            niche_id=body.niche,
            note=body.note,
            prior=body.prior,
        )
        if not plan:
            raise HTTPException(
                502,
                "Dusunme plani uretilemedi. Ollama calisiyor mu? ollama serve",
            )
        return plan

    @app.post("/api/longform/generate")
    async def longform_generate(body: LongformGenerateRequest, background_tasks: BackgroundTasks):
        chapters = [c.strip() for c in body.chapters if c.strip()]
        if not chapters:
            raise HTTPException(400, "En az bir bolum gerekli")
        if len(chapters) > 12:
            raise HTTPException(400, "En fazla 12 bolum")
        prod_lang = body.production_language
        if body.dual_language:
            prod_lang = "tr"
        aspect = plat.normalize_aspect(
            body.video_aspect, default=plat.DEFAULT_LONGFORM_ASPECT
        )
        platform_id = (body.platform or plat.DEFAULT_LONGFORM_PLATFORM).strip() or plat.DEFAULT_LONGFORM_PLATFORM
        clip = body.video_clip_duration
        if not clip:
            clip = plat.longform_clip_duration(aspect, platform_id)
        common = {
            "platform": platform_id,
            "video_aspect": aspect,
            "video_source": body.video_source,
            "production_language": prod_lang,
            "tts_engine": body.tts_provider or body.tts_engine,
            "edge_voice": body.edge_voice,
            "niche": body.niche,
            "video_clip_duration": clip,
            "subtitle_style_id": (
                body.subtitle_style.style_id
                if body.subtitle_style
                else ("youtube" if aspect == "16:9" else "tiktok_classic")
            ),
            "subtitle_overrides": _subtitle_overrides(body.subtitle_style),
            "bgm_volume": 0.0,
            "bgm_mode": "none",
            "bgm_track": None,
            "voice_rate": body.voice_rate,
            "rvc_voice": body.rvc_voice,
            "rvc_pitch": body.rvc_pitch,
            "rvc_index_rate": body.rvc_index_rate,
            "outro_id": body.outro_id,
            "dual_llm": body.dual_llm,
            "strengthen_hook": body.strengthen_hook,
            "editor_web_verify": body.editor_web_verify,
            "writer_model": body.writer_model,
            "editor_model": body.editor_model,
            "dual_language": body.dual_language,
            "use_lang_preset": False,
            "auto_retry_failed": body.auto_retry_failed,
            "auto_retry_rounds": body.auto_retry_rounds,
            "think_guidance": (body.think_guidance or "").strip()[:4000],
        }
        longform_id = longform_mod.create_longform(
            body.main_subject.strip(),
            chapters,
            common,
            scripts=body.scripts,
        )
        main = body.main_subject.strip()
        item = prod_q.enqueue(
            prod_q.KIND_LONGFORM,
            longform_id,
            f"Uzun video: {main[:60]}",
            meta={
                "chapters": len(chapters),
                "auto_retry_failed": body.auto_retry_failed,
                "auto_retry_rounds": body.auto_retry_rounds,
            },
        )
        await prod_q.ensure_worker(engine_base())
        dual = body.dual_language
        return {
            "longform_id": longform_id,
            "queue_id": item.queue_id,
            "position": prod_q.queue_position(item.queue_id),
            "total": 1,
            "total_videos": 2 if dual else 1,
            "mode": "assets",
            "queued": True,
        }

    @app.get("/api/longform/{longform_id}")
    async def longform_status(longform_id: str):
        data = longform_mod.get_longform(longform_id)
        if not data:
            raise HTTPException(404, "Uzun video gorevi bulunamadi")
        return data

    @app.delete("/api/longform/{longform_id}")
    async def longform_cancel(longform_id: str):
        if not longform_mod.cancel_longform(longform_id):
            raise HTTPException(404, "Uzun video gorevi bulunamadi")
        return {"ok": True}

    @app.post("/api/longform/{longform_id}/retry")
    async def longform_retry(
        longform_id: str,
        body: LongformRetryRequest,
        background_tasks: BackgroundTasks,
    ):
        job = longform_mod.prepare_retry(
            longform_id,
            auto_retry_failed=body.auto_retry_failed,
            auto_retry_rounds=body.auto_retry_rounds,
        )
        if not job:
            data = longform_mod.get_longform(longform_id)
            if not data:
                raise HTTPException(404, "Uzun video gorevi bulunamadi")
            if data.get("running"):
                raise HTTPException(409, "Uretim devam ediyor")
            raise HTTPException(400, "Tekrar uretilecek basarisiz bolum yok")
        item = prod_q.enqueue(
            prod_q.KIND_LONGFORM,
            longform_id,
            f"Uzun video (tekrar): {job.main_subject[:50]}",
            meta={
                "retry": True,
                "auto_retry_failed": body.auto_retry_failed,
                "auto_retry_rounds": body.auto_retry_rounds,
            },
        )
        await prod_q.ensure_worker(engine_base())
        retrying = sum(
            1
            for c in job.chapters
            if not (c.get("task_id") or "").strip()
            or (
                bool(job.common.get("dual_language"))
                and (c.get("task_id") or "").strip()
                and not (c.get("en_task_id") or "").strip()
            )
        )
        return {
            "ok": True,
            "longform_id": longform_id,
            "queue_id": item.queue_id,
            "position": prod_q.queue_position(item.queue_id),
            "retrying": retrying,
        }

    @app.delete("/api/tasks/{task_id}")
    async def task_cancel(task_id: str):
        tid = (task_id or "").strip()
        if not tid:
            raise HTTPException(400, "Gorev ID gerekli")
        # Arka planda sil — kilitli dosya UI'yi "Durduruluyor"da birakmasin
        asyncio.create_task(_delete_engine_tasks_bg([tid]))
        return {"ok": True}

    @app.get("/api/tasks/{task_id}/script")
    async def task_script(task_id: str):
        tid = (task_id or "").strip()
        if not tid:
            raise HTTPException(400, "Gorev ID gerekli")
        path = engine_task_dir(tid) / "script.txt"
        if not path.is_file() or path.stat().st_size <= 0:
            raise HTTPException(404, "Senaryo dosyasi yok")
        return FileResponse(
            path,
            media_type="text/plain; charset=utf-8",
            filename=f"{tid}-script.txt",
        )

    @app.get("/api/tasks/{task_id}/audio")
    async def task_audio(task_id: str):
        tid = (task_id or "").strip()
        if not tid:
            raise HTTPException(400, "Gorev ID gerekli")
        path = engine_task_dir(tid) / "audio.mp3"
        if not path.is_file() or path.stat().st_size <= 0:
            raise HTTPException(404, "Ses dosyasi yok")
        return FileResponse(
            path,
            media_type="audio/mpeg",
            filename=f"{tid}-audio.mp3",
        )

    @app.get("/api/tasks/{task_id}/subtitle")
    async def task_subtitle(task_id: str):
        tid = (task_id or "").strip()
        if not tid:
            raise HTTPException(400, "Gorev ID gerekli")
        path = engine_task_dir(tid) / "subtitle.srt"
        if not path.is_file() or path.stat().st_size <= 0:
            raise HTTPException(404, "Altyazi dosyasi yok")
        return FileResponse(
            path,
            media_type="application/x-subrip",
            filename=f"{tid}-subtitle.srt",
        )

    @app.get("/api/tasks/{task_id}/clip/{filename:path}")
    async def task_clip(task_id: str, filename: str):
        tid = (task_id or "").strip()
        if not tid:
            raise HTTPException(400, "Gorev ID gerekli")
        path = gal.resolve_task_media_path(tid, filename)
        if not path:
            raise HTTPException(404, "Gorsel/klip bulunamadi")
        media = _media_type_for_path(path)
        return FileResponse(path, media_type=media, filename=path.name)

    @app.get("/api/tasks/{task_id}")
    async def task_status(task_id: str):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get(f"{engine_base()}/api/v1/tasks/{task_id}")
        except httpx.HTTPError as e:
            raise HTTPException(502, f"Motor API baglantisi: {e}") from e
        data = _httpx_json(r)
        if r.status_code == 404:
            raise HTTPException(404, "Gorev bulunamadi")
        if r.status_code >= 400:
            msg = data.get("message") or data.get("detail") or str(data)
            raise HTTPException(r.status_code, msg or "Motor gorev hatasi")
        task = data.get("data") or {}
        state = task.get("state", 4)
        videos = task.get("videos") or []
        urls = []
        for v in videos:
            if isinstance(v, str):
                if v.startswith("http"):
                    urls.append(v)
                else:
                    urls.append(f"{engine_base()}/{v.lstrip('/')}")
        progress = int(task.get("progress", 0) or 0)
        err = task.get("error", "") or ""
        script = task.get("script", "") or ""
        params = task.get("params") or {}
        prod_lang = ""
        had_script = False
        voice_name = ""
        if isinstance(params, dict):
            vl = str(params.get("video_language") or "")
            prod_lang = vl.split("-")[0].lower() if vl else ""
            had_script = bool(str(params.get("video_script") or "").strip())
            voice_name = str(params.get("voice_name") or "")
        disk = _read_engine_task_disk_meta(task_id) if state == -1 else {}
        if disk.get("had_script"):
            had_script = True
        if disk.get("voice_name"):
            voice_name = str(disk["voice_name"])
        failure_hint = (
            _failure_hint(
                progress,
                production_language=prod_lang,
                had_script=had_script,
                script_saved=bool(disk.get("script_saved")),
                voice_name=voice_name,
                has_audio=bool(disk.get("has_audio")),
            )
            if state == -1
            else ""
        )
        from akifactory import task_timing as tt_mod

        production_sec = None
        production_elapsed_sec = None
        if state == 1:
            production_sec = tt_mod.finish(task_id)
        elif state == 4:
            production_elapsed_sec = tt_mod.elapsed(task_id)
        return {
            "task_id": task_id,
            "state": state,
            "state_label": STATE_LABELS.get(state, "Bekleniyor"),
            "progress": progress,
            "step": batch_mod.progress_step_label(progress),
            "videos": urls,
            "script": script,
            "hook": script_hk.first_sentence(script) if script else "",
            "hook_strong": script_hk.validate_hook(script, task.get("video_subject", ""))
            if script
            else False,
            "error": err,
            "failure_hint": failure_hint,
            "production_sec": production_sec,
            "production_elapsed_sec": production_elapsed_sec,
        }

    @app.get("/assets/app.js")
    async def serve_app_js():
        path = WEB_DIR / "assets" / "app.js"
        if not path.is_file():
            raise HTTPException(404, "app.js yok")
        return FileResponse(
            path,
            media_type="application/javascript",
            headers=_NO_CACHE_HEADERS,
        )

    @app.get("/assets/app.css")
    async def serve_app_css():
        path = WEB_DIR / "assets" / "app.css"
        if not path.is_file():
            raise HTTPException(404, "app.css yok")
        return FileResponse(
            path,
            media_type="text/css",
            headers=_NO_CACHE_HEADERS,
        )

    @app.get("/splash")
    async def splash_page():
        path = WEB_DIR / "splash.html"
        if not path.is_file():
            raise HTTPException(404, "splash.html yok")
        return FileResponse(path, headers=_NO_CACHE_HEADERS)

    @app.get("/")
    async def index():
        index_path = WEB_DIR / "index.html"
        if not index_path.is_file():
            raise HTTPException(404, "web/index.html yok")
        return FileResponse(index_path, headers=_NO_CACHE_HEADERS)

    if (WEB_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")

    return app
