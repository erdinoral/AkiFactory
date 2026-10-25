"""AI gorsel/video — elle Fooocus + WanGP (5 sn segment) + surukle-birak montaj."""

from __future__ import annotations

import math
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from akifactory import fooocus_prompt as fooocus_mod
from akifactory import wangp_prompt as wangp_mod
from akifactory.paths import data_dir
from akifactory.video_source import local_videos_dir

SEGMENT_SECONDS = 5
# MiniMax zinciri: en kisa ~45 sn, en uzun ~60 sn (9–12 × 5 sn)
MIN_SEGMENTS = 9
MAX_SEGMENTS = 12
TARGET_SEGMENTS = 10  # ~50 sn
_ALLOWED_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".png", ".jpg", ".jpeg", ".webp"}
# Turkce TTS ~12–14 kelime / 5 sn → 45–60 sn ≈ 110–160 kelime
_WORDS_PER_SEGMENT = 13


def assets_dir() -> Path:
    d = data_dir() / "ai_visuals"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_name(name: str) -> str:
    base = Path(name).name
    base = re.sub(r"[^\w.\-]+", "_", base, flags=re.UNICODE)
    return base[:120] or f"asset_{uuid.uuid4().hex[:8]}"


def list_assets() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for p in sorted(assets_dir().iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if not p.is_file():
            continue
        if p.suffix.lower() not in _ALLOWED_EXT:
            continue
        kind = "image" if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} else "video"
        items.append(
            {
                "id": p.name,
                "name": p.name,
                "kind": kind,
                "size": p.stat().st_size,
                "url": f"/api/ai-visuals/file/{p.name}",
                "mtime": p.stat().st_mtime,
            }
        )
    return items


def save_upload(filename: str, data: bytes) -> dict[str, Any]:
    if not data:
        raise ValueError("Bos dosya")
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_EXT:
        raise ValueError(f"Desteklenmeyen uzanti: {ext}")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    safe = _safe_name(filename)
    out_name = f"{stamp}_{uuid.uuid4().hex[:6]}_{safe}"
    path = assets_dir() / out_name
    path.write_bytes(data)
    kind = "image" if ext in {".png", ".jpg", ".jpeg", ".webp"} else "video"
    return {
        "id": out_name,
        "name": out_name,
        "kind": kind,
        "size": len(data),
        "url": f"/api/ai-visuals/file/{out_name}",
    }


def delete_asset(asset_id: str) -> bool:
    safe = Path(asset_id).name
    path = assets_dir() / safe
    if not path.is_file():
        return False
    path.unlink(missing_ok=True)
    return True


def resolve_asset_path(asset_id: str) -> Path | None:
    safe = Path(asset_id).name
    path = (assets_dir() / safe).resolve()
    if not str(path).startswith(str(assets_dir().resolve())):
        return None
    return path if path.is_file() else None


def stage_selected(asset_ids: list[str]) -> tuple[list[dict[str, str]], str]:
    """Secilen dosyalari local_videos altina kopyala — motor video_materials."""
    if not asset_ids:
        raise ValueError("En az bir gorsel/video secilmeli")
    tag = f"ai_manual_{uuid.uuid4().hex[:10]}"
    dest_dir = local_videos_dir() / f"_ai_{tag}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    materials: list[dict[str, str]] = []
    for i, aid in enumerate(asset_ids):
        src = resolve_asset_path(aid)
        if src is None:
            raise ValueError(f"Dosya bulunamadi: {aid}")
        dest_name = f"{i:03d}_{src.name}"
        dest = dest_dir / dest_name
        shutil.copy2(src, dest)
        # motor mutlak yol kabul ediyor (local_videos icinde)
        materials.append({"provider": "local", "url": str(dest.resolve())})
    return materials, tag


def _format_wan_segments(
    scenes: list[str],
    *,
    continue_mode: bool,
    segment_seconds: int = SEGMENT_SECONDS,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, scene in enumerate(scenes):
        start = i * segment_seconds
        end = start + segment_seconds
        text = (scene or "").strip()
        if continue_mode and i > 0 and text:
            text = (
                f"CONTINUATION of previous {segment_seconds}s clip — same characters, "
                f"lighting, camera language, seamless motion continuity. Next action: {text}"
            )
        out.append(
            {
                "index": i + 1,
                "start_s": start,
                "end_s": end,
                "label": f"{start}–{end}s",
                "prompt": text,
            }
        )
    return out


def segments_to_block(segments: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for seg in segments:
        lines.append(f"[{seg['label']}] {seg['prompt']}")
    return "\n\n".join(lines)


def segment_bounds(segment_seconds: int = SEGMENT_SECONDS) -> tuple[int, int, int]:
    """(min, max, hedef) segment sayisi — toplam 45–60 sn (5 sn → 9, 12, 10)."""
    cs = max(1, int(segment_seconds or SEGMENT_SECONDS))
    lo = max(1, math.ceil(45 / cs))
    hi = max(lo, 60 // cs)
    return lo, hi, max(lo, min(hi, round(50 / cs)))


def clamp_segment_count(
    n: int | None, *, default: int | None = None, segment_seconds: int = SEGMENT_SECONDS
) -> int:
    """Segment sayisini 45–60 sn araligina kilitle (5 sn icin 9–12)."""
    lo, hi, target = segment_bounds(segment_seconds)
    try:
        v = int(n) if n is not None else int(default if default is not None else target)
    except (TypeError, ValueError):
        v = target
    return max(lo, min(hi, v))


def estimate_segment_count(
    script: str, *, default: int | None = None, segment_seconds: int = SEGMENT_SECONDS
) -> int:
    """Senaryo uzunlugundan H3 Studio segment sayisi — hedef 45–60 sn."""
    words = len((script or "").split())
    base = clamp_segment_count(default, segment_seconds=segment_seconds)
    if words < 8:
        return base
    per = _WORDS_PER_SEGMENT * max(1, int(segment_seconds or SEGMENT_SECONDS)) / SEGMENT_SECONDS
    n = round(words / per)
    return clamp_segment_count(n, default=base, segment_seconds=segment_seconds)


def _visual_brief(topic: str, script: str | None) -> str:
    """WanGP/Fooocus icin birincil girdi: senaryo (varsa), yoksa konu."""
    topic = (topic or "").strip()
    script = (script or "").strip()
    if len(script) >= 20:
        return (
            f"Topic: {topic}\n\n"
            "Spoken narration script — generate visuals that match this story beat by beat:\n"
            f"{script[:2800]}"
        )
    return topic


async def build_prompt_pack(
    *,
    topic: str,
    niche_id: str = "tarih_gizem",
    segment_count: int | None = None,
    continue_mode: bool = False,
    script: str | None = None,
    wangp_style: str = "dark_mystery",
    fooocus_style: str = "cinematic",
    fooocus_purpose: str = "scene",
    segment_seconds: int = SEGMENT_SECONDS,
) -> dict[str, Any]:
    topic = (topic or "").strip()
    script = (script or "").strip() or None
    if len(topic) < 2 and not (script and len(script) >= 20):
        raise ValueError("Konu veya senaryo gerekli")
    if not topic and script:
        topic = script.split(".")[0][:80].strip() or "video"

    seg_s = max(1, int(segment_seconds or SEGMENT_SECONDS))
    if segment_count is None:
        segment_count = estimate_segment_count(script or "", segment_seconds=seg_s)
    segment_count = clamp_segment_count(segment_count, segment_seconds=seg_s)

    brief = _visual_brief(topic, script)

    from akifactory import h3_scene_writer as h3w

    written: dict[str, Any] | None = None
    try:
        written = await h3w.write_scenes(
            topic=topic,
            script=script or "",
            niche_id=niche_id,
            style=wangp_style,
            scene_count=segment_count,
            aspect="9:16",
            continue_mode=continue_mode,
            clip_seconds=seg_s,
        )
    except Exception:
        written = None
    if written:
        scenes = list(written["scenes"])
        segments = _format_wan_segments(scenes, continue_mode=False, segment_seconds=seg_s)
        for seg, mode in zip(segments, written["modes"]):
            seg["mode"] = mode
            seg["label"] += " · continue" if mode == "continue" else " · yeni"
        foo = await fooocus_mod.generate_fooocus_prompt(
            topic=brief[:900],
            niche_id=niche_id,
            style=fooocus_style,
            purpose=fooocus_purpose,
            aspect="9:16",
            variant_count=1,
        )
        total_s = segment_count * seg_s
        cuts = written["modes"].count("t2v")
        return {
            "ok": True,
            "segment_seconds": seg_s,
            "segment_count": segment_count,
            "total_seconds": total_s,
            "continue_mode": continue_mode,
            "from_script": bool(script and len(script) >= 20),
            "wan": {
                "raw_scenes": scenes,
                "modes": written["modes"],
                "visual_bible": written["visual_bible"],
                "segments": segments,
                "prompt_block": segments_to_block(segments),
                "negative_prompt": wangp_mod.DEFAULT_NEGATIVE,
                "wgp_notes": (
                    f"Resmi H3 formati + ortak gorsel kimlik. {segment_count}×{seg_s} sn "
                    f"≈ {total_s} sn; {cuts} yeni plan, {segment_count - cuts} continue "
                    "(ayni mekanda devam, mekan degisince temiz kesme)."
                ),
            },
            "fooocus": {
                "prompt": foo.get("prompt") or "",
                "negative_prompt": foo.get("negative_prompt") or "",
                "variants": foo.get("variants") or [],
            },
            "hint": (
                "Otomatik H3 Studio: ayni mekanda continue, mekan degisince yeni plan — 45–60 sn. "
                "Elle: her SCENE'i sirayla, belirtilen modda (yeni/continue) uretip Montaja devam."
            ),
        }

    # Yedek: serbest metin SCENE yazari
    wan = await wangp_mod.generate_wangp_prompt(
        topic=brief,
        niche_id=niche_id,
        scene_count=segment_count,
        style=wangp_style,
        line_mode="sliding_window" if continue_mode else "queue",
        aspect="9:16",
        batch_count=1,
        script=(script or "")[:2800],
    )
    scenes = list(wan.get("scenes") or [])
    if not scenes and wan.get("prompt_block"):
        scenes = [
            ln.strip()
            for ln in str(wan["prompt_block"]).splitlines()
            if ln.strip() and not ln.strip().startswith("[") and not ln.strip().startswith("===")
        ]
    # Eksik / filler sahneleri ikinci LLM veya senaryo beat ile tamamla
    need_fill = len(scenes) < segment_count or any(
        wangp_mod.is_filler_scene(s) for s in scenes
    )
    if need_fill:
        scenes = await wangp_mod.fill_continue_scenes(
            existing=scenes,
            need=segment_count,
            topic=topic,
            script=script or "",
            niche_id=niche_id,
            style=wangp_style,
        )
    scenes = wangp_mod.pad_scenes_locally(
        scenes, need=segment_count, topic=topic, script=script or ""
    )
    scenes = scenes[:segment_count]

    segments = _format_wan_segments(scenes, continue_mode=continue_mode, segment_seconds=seg_s)
    wan_block = segments_to_block(segments)

    foo = await fooocus_mod.generate_fooocus_prompt(
        topic=brief[:900],
        niche_id=niche_id,
        style=fooocus_style,
        purpose=fooocus_purpose,
        aspect="9:16",
        variant_count=1,
    )

    total_s = segment_count * seg_s
    return {
        "ok": True,
        "segment_seconds": seg_s,
        "segment_count": segment_count,
        "total_seconds": total_s,
        "continue_mode": continue_mode,
        "from_script": bool(script and len(script) >= 20),
        "wan": {
            "raw_scenes": scenes,
            "segments": segments,
            "prompt_block": wan_block,
            "negative_prompt": wan.get("negative_prompt") or "",
            "wgp_notes": (
                f"Kesintisiz zincir: 1. SCENE = yeni video, 2+ = continue. "
                f"Her SCENE {seg_s} sn → toplam ≈ {total_s} sn "
                f"({segment_count}×{seg_s}, hedef 45–60 sn)."
            ),
        },
        "fooocus": {
            "prompt": foo.get("prompt") or "",
            "negative_prompt": foo.get("negative_prompt") or "",
            "variants": foo.get("variants") or [],
        },
        "hint": (
            "Otomatik H3 Studio: ilk klip yeni video, sonrakiler continue — kesintisiz 45–60 sn. "
            "Elle: ayni sirayla uretip Montaja devam."
        ),
    }
