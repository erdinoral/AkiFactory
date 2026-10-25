"""Uretilen videolar — kalici galeri (data/gallery)."""

from __future__ import annotations

import functools
import json
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from akifactory import json_io as jio
from akifactory.paths import gallery_dir, engine_task_dir
from akifactory import thumbnail as thumb_mod

INDEX_NAME = "index.json"

_index_cache: list[dict[str, Any]] | None = None
_index_mtime: float | None = None
# Backend arsivi (thread) ve UI arsivi ayni anda index'e yazabilir.
_index_lock = threading.RLock()


def _locked(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _index_lock:
            return fn(*args, **kwargs)

    return wrapper


def _index_path() -> Path:
    return gallery_dir() / INDEX_NAME


def _load_index() -> list[dict[str, Any]]:
    """Index'i mtime ile bellege al — thumbnail N+1 parse maliyetini kes."""
    global _index_cache, _index_mtime
    p = _index_path()
    if not p.is_file():
        _index_cache, _index_mtime = [], None
        return []
    try:
        mtime = p.stat().st_mtime
    except OSError:
        mtime = None
    if _index_cache is not None and mtime is not None and mtime == _index_mtime:
        return _index_cache
    try:
        data = jio.load_wrapped_list(p)
        items = data if isinstance(data, list) else []
    except Exception:
        items = []
    _index_cache = items
    _index_mtime = mtime
    return items


def _save_index(items: list[dict[str, Any]]) -> None:
    global _index_cache, _index_mtime
    jio.save_wrapped_list(_index_path(), items)
    _index_cache = items
    try:
        _index_mtime = _index_path().stat().st_mtime
    except OSError:
        _index_mtime = None


def invalidate_index_cache() -> None:
    global _index_cache, _index_mtime
    _index_cache = None
    _index_mtime = None


def _find_local_task_video(task_id: str) -> Path | None:
    td = engine_task_dir(task_id)
    if not td.is_dir():
        return None
    for name in ("final-1.mp4", "final-0.mp4", "combined-1.mp4"):
        p = td / name
        if p.is_file() and p.stat().st_size > 0:
            return p
    for p in sorted(td.glob("final-*.mp4")):
        if p.stat().st_size > 0:
            return p
    return None


def task_montage_paths(task_id: str | None) -> dict[str, Path]:
    """Motor gorev klasorundeki ses/altyazi dosyalari."""
    tid = (task_id or "").strip()
    if not tid:
        return {}
    td = engine_task_dir(tid)
    out: dict[str, Path] = {}
    audio = td / "audio.mp3"
    sub = td / "subtitle.srt"
    if audio.is_file() and audio.stat().st_size > 0:
        out["audio"] = audio
    if sub.is_file() and sub.stat().st_size > 0:
        out["subtitle"] = sub
    return out


def list_task_montage_media(task_id: str | None) -> list[dict[str, Any]]:
    """Gorev klasorundeki stok klipler ve kaynak gorseller (montaj icin)."""
    from akifactory.video_source import list_task_source_clips

    tid = (task_id or "").strip()
    if not tid:
        return []
    td = engine_task_dir(tid)
    if not td.is_dir():
        return []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for p in list_task_source_clips(tid):
        key = p.name.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "name": p.name,
                "kind": "video",
                "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
            }
        )
    skip_names = {"audio.mp3", "subtitle.srt", "script.txt", "script.json"}
    for p in sorted(td.iterdir()):
        if not p.is_file() or p.name in skip_names:
            continue
        if p.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            continue
        key = p.name.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "name": p.name,
                "kind": "image",
                "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
            }
        )
    return items


def _safe_task_media_name(name: str) -> str:
    safe = Path(name).name
    if not safe or safe != name or ".." in name:
        raise ValueError("Gecersiz dosya adi")
    lower = safe.lower()
    allowed = (
        lower.endswith(".mp4")
        or lower.endswith(".mov")
        or lower.endswith(".webm")
        or lower.endswith(".jpg")
        or lower.endswith(".jpeg")
        or lower.endswith(".png")
        or lower.endswith(".webp")
    )
    if not allowed:
        raise ValueError("Desteklenmeyen dosya turu")
    return safe


def resolve_task_media_path(task_id: str | None, filename: str) -> Path | None:
    tid = (task_id or "").strip()
    if not tid:
        return None
    try:
        safe = _safe_task_media_name(filename)
    except ValueError:
        return None
    path = (engine_task_dir(tid) / safe).resolve()
    root = engine_task_dir(tid).resolve()
    if root not in path.parents and path != root:
        return None
    if not path.is_file() or path.stat().st_size <= 0:
        return None
    return path


def task_montage_assets(task_id: str | None) -> dict[str, Any]:
    """Gorev ID ile ses/altyazi/gorsel indirme URL'leri."""
    tid = (task_id or "").strip()
    if not tid:
        return {}
    paths = task_montage_paths(tid)
    out: dict[str, Any] = {}
    if "audio" in paths:
        out["audio_url"] = f"/api/tasks/{tid}/audio"
    if "subtitle" in paths:
        out["subtitle_url"] = f"/api/tasks/{tid}/subtitle"
    clips = list_task_montage_media(tid)
    if clips:
        out["clips"] = [
            {**c, "url": f"/api/tasks/{tid}/clip/{c['name']}"} for c in clips
        ]
    return out


def montage_assets_for_entry(
    entry_id: str, task_id: str | None, bgm_file: str | None = None
) -> dict[str, Any]:
    """Galeri kaydi icin montaj dosyasi URL'leri."""
    eid = (entry_id or "").strip()
    if not eid:
        return {}
    paths = task_montage_paths(task_id)
    out: dict[str, Any] = {}
    if "audio" in paths:
        out["audio_url"] = f"/api/gallery/{eid}/audio"
    if "subtitle" in paths:
        out["subtitle_url"] = f"/api/gallery/{eid}/subtitle"
    if (bgm_file or "").strip():
        from akifactory import bgm as bgm_mod

        if bgm_mod.resolve_track_path(str(bgm_file)):
            out["music_url"] = f"/api/gallery/{eid}/music"
    clips = list_task_montage_media(task_id)
    if clips:
        out["clips"] = [
            {**c, "url": f"/api/gallery/{eid}/clip/{c['name']}"} for c in clips
        ]
    return out


def _download_url(url: str, dest: Path, engine_base: str) -> bool:
    try:
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
            dest.write_bytes(r.content)
        return dest.stat().st_size > 0
    except Exception:
        return False


@_locked
def update_entry(entry_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    items = _load_index()
    for e in items:
        if e.get("id") == entry_id:
            e.update(fields)
            _save_index(items)
            return e
    return None


def _slim_publish_pack(pack: dict[str, Any] | None) -> dict[str, Any]:
    if not pack:
        return {}
    keys = (
        "titles",
        "descriptions",
        "hashtag_sets",
        "youtube_tags",
        "share_tips",
        "best_title",
        "best_caption",
        "best_hashtags",
        "title_alternatives",
        "caption_alternatives",
        "wangp",
        "fooocus",
        "editor_model",
    )
    return {k: pack[k] for k in keys if k in pack}


def _list_preview_pack(pack: dict[str, Any] | None) -> dict[str, Any]:
    """Liste icin minik pack — share_tips / fooocus / wangp / alternatifler yok."""
    if not isinstance(pack, dict) or not pack:
        return {}
    out: dict[str, Any] = {}
    for key in ("best_title", "best_caption", "best_hashtags"):
        val = pack.get(key)
        if val:
            out[key] = val
    descs = pack.get("descriptions")
    if isinstance(descs, list) and descs:
        out["descriptions"] = descs[:1]
    tags = pack.get("youtube_tags")
    if isinstance(tags, list) and tags:
        out["youtube_tags"] = tags[:40]
    elif isinstance(tags, str) and tags.strip():
        out["youtube_tags"] = tags.strip()
    return out


def en_title_needs_fix(entry: dict[str, Any] | None) -> bool:
    """EN kayitta Turkce baslik/aciklama varsa True."""
    if not entry:
        return False
    lang = (entry.get("language") or "").strip().lower()
    if not lang.startswith("en"):
        return False
    from akifactory.content_studio import text_looks_turkish

    pack = entry.get("publish_pack") or {}
    title = (entry.get("title") or pack.get("best_title") or "").strip()
    caption = (entry.get("caption") or pack.get("best_caption") or "").strip()
    subject = (entry.get("subject") or "").strip()
    if not title:
        return True
    # «Konu (EN)» kalibi veya konu aynen baslik yapilmisi
    if re.search(r"\(EN\)\s*$", title, re.I):
        return True
    if title == subject and re.search(r"\(EN\)\s*$", subject, re.I):
        return True
    return text_looks_turkish(title) or text_looks_turkish(caption)


def _recover_script_from_task(task_id: str | None) -> str:
    """Index'te senaryo yoksa motor gorev klasorunden oku."""
    tid = (task_id or "").strip()
    if not tid:
        return ""
    p = engine_task_dir(tid) / "script.txt"
    if not p.is_file():
        return ""
    try:
        return p.read_text(encoding="utf-8", errors="replace").strip()[:20000]
    except OSError:
        return ""


def _entry_size_mb(e: dict[str, Any], path: Path) -> float:
    cached = e.get("size_mb")
    try:
        if cached is not None:
            return float(cached)
    except (TypeError, ValueError):
        pass
    try:
        return round(path.stat().st_size / (1024 * 1024), 2)
    except OSError:
        return 0.0


def _build_list_row(e: dict[str, Any], *, include_assets: bool = False) -> dict[str, Any] | None:
    fn = e.get("filename", "")
    path = gallery_dir() / fn
    if not path.is_file():
        return None
    eid = e.get("id")
    size_mb = _entry_size_mb(e, path)
    if include_assets:
        row = dict(e)
        row["size_mb"] = size_mb
        row["stream_url"] = f"/api/gallery/{eid}/stream"
        row["download_url"] = f"/api/gallery/{eid}/download"
        thumb_fn = e.get("thumbnail") or ""
        if thumb_fn and (gallery_dir() / thumb_fn).is_file():
            row["thumbnail_url"] = f"/api/gallery/{eid}/thumbnail"
            row["has_thumbnail"] = True
        else:
            row["thumbnail_url"] = ""
            row["has_thumbnail"] = False
        cands = e.get("thumbnail_candidates") or []
        row["thumbnail_candidates"] = [
            {**c, "url": f"/api/gallery/{eid}/thumbnail/{c.get('index', 0)}"}
            for c in cands
            if isinstance(c, dict)
        ]
        assets = montage_assets_for_entry(eid, e.get("task_id"), e.get("bgm_file"))
        if assets:
            row["assets"] = assets
        script = str(row.get("script") or "").strip()
        if len(script) < 10:
            recovered = _recover_script_from_task(row.get("task_id"))
            if recovered:
                row["script"] = recovered
                script = recovered
        row["has_script"] = len(script) >= 10
        pack = row.get("publish_pack")
        if isinstance(pack, dict):
            row["publish_pack"] = _slim_publish_pack(pack)
        return row

    # Liste: sadece kart alanlari — 600KB+ JSON ve thumbnail adaylari yok
    script = str(e.get("script") or "")
    thumb_fn = e.get("thumbnail") or ""
    has_thumb = bool(thumb_fn and (gallery_dir() / thumb_fn).is_file())
    return {
        "id": eid,
        "task_id": e.get("task_id"),
        "title": e.get("title") or "",
        "subject": e.get("subject") or "",
        "aspect": e.get("aspect") or "9:16",
        "platform": e.get("platform") or "",
        "niche": e.get("niche") or "",
        "language": e.get("language") or "",
        "voice": e.get("voice") or "",
        "tts_provider": e.get("tts_provider") or "",
        "duration_sec": e.get("duration_sec") or 0,
        "production_sec": e.get("production_sec") or 0,
        "caption": e.get("caption") or "",
        "hashtags": e.get("hashtags") or "",
        "filename": fn,
        "created_at": e.get("created_at") or "",
        "index": e.get("index"),
        "thumbnail": thumb_fn if has_thumb else "",
        "size_mb": size_mb,
        "stream_url": f"/api/gallery/{eid}/stream",
        "download_url": f"/api/gallery/{eid}/download",
        "thumbnail_url": f"/api/gallery/{eid}/thumbnail" if has_thumb else "",
        "has_thumbnail": has_thumb,
        "has_script": len(script.strip()) >= 10,
        "publish_pack": _list_preview_pack(e.get("publish_pack")),
    }


def _unlink_with_retry(path: Path, *, attempts: int = 3) -> bool:
    """Windows dosya kilidi icin kisa retry; basarisizsa False."""
    import time

    last_err: Exception | None = None
    for i in range(max(1, attempts)):
        try:
            if not path.exists():
                return True
            path.unlink(missing_ok=True)
            return not path.exists()
        except PermissionError as exc:
            last_err = exc
            time.sleep(0.25 * (i + 1))
        except OSError as exc:
            last_err = exc
            time.sleep(0.25 * (i + 1))
    if last_err and path.exists():
        return False
    return not path.exists()


def delete_item(entry_id: str) -> bool:
    result = delete_items([entry_id])
    return bool(result.get("deleted"))


@_locked
def delete_items(entry_ids: list[str]) -> dict[str, Any]:
    """Toplu silme — index bir kez yazilir. Kilitli dosyalar failed listesine dusar."""
    wanted = {str(i).strip() for i in (entry_ids or []) if str(i).strip()}
    if not wanted:
        return {"deleted": [], "failed": [], "missing": []}

    items = _load_index()
    kept: list[dict[str, Any]] = []
    deleted: list[str] = []
    failed: list[dict[str, str]] = []
    missing: list[str] = []
    seen: set[str] = set()

    for e in items:
        eid = str(e.get("id") or "")
        if eid not in wanted:
            kept.append(e)
            continue
        seen.add(eid)
        path = gallery_dir() / e.get("filename", "")
        for tp in thumb_mod.thumb_paths_for_entry(eid, gallery_dir()):
            _unlink_with_retry(tp)
        if path.is_file() and not _unlink_with_retry(path):
            failed.append({"id": eid, "error": "Dosya kullanimda — oynatmayı durdurup tekrar deneyin"})
            kept.append(e)
            continue
        deleted.append(eid)

    for eid in wanted - seen:
        missing.append(eid)

    if deleted:
        _save_index(kept)
    return {"deleted": deleted, "failed": failed, "missing": missing}


def compute_stats() -> dict[str, Any]:
    items = _load_index()
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    this_month = 0
    total_size = 0.0
    platforms: dict[str, int] = {}
    languages: dict[str, int] = {}
    voices: dict[str, int] = {}
    root = gallery_dir()
    for e in items:
        cached = e.get("size_mb")
        if cached is not None:
            try:
                total_size += float(cached) * 1024 * 1024
            except (TypeError, ValueError):
                cached = None
        if cached is None:
            fn = e.get("filename", "")
            path = root / fn
            try:
                if path.is_file():
                    total_size += path.stat().st_size
            except OSError:
                pass
        try:
            created = datetime.fromisoformat(
                e.get("created_at", "").replace("Z", "+00:00")
            )
            if created >= month_start:
                this_month += 1
        except Exception:
            pass
        p = e.get("platform") or "custom"
        platforms[p] = platforms.get(p, 0) + 1
        lang = e.get("language") or "tr"
        languages[lang] = languages.get(lang, 0) + 1
        v = e.get("voice") or ""
        if v:
            voices[v] = voices.get(v, 0) + 1

    from akifactory import languages as _lang
    from akifactory import platforms as _plat

    def _top_platform(d: dict[str, int]) -> str:
        if not d:
            return "-"
        key = max(d, key=d.get)
        return _plat.PLATFORMS.get(key, {}).get("label", key)

    def _top_lang(d: dict[str, int]) -> str:
        if not d:
            return "-"
        key = max(d, key=d.get)
        for item in _lang.list_for_ui():
            if item["id"] == key:
                return item["label"]
        return key.upper()

    return {
        "total_videos": len(items),
        "this_month": this_month,
        "total_size_mb": round(total_size / (1024 * 1024), 1),
        "most_used_platform": _top_platform(platforms),
        "most_used_language": _top_lang(languages),
        "most_used_voice": max(voices, key=voices.get) if voices else "-",
    }


def _merge_into_existing(
    items: list[dict[str, Any]],
    task_id: str,
    *,
    title: str,
    subject: str,
    caption: str,
    hashtags: str,
    script: str,
    publish_pack: dict[str, Any] | None,
    production_sec: int,
    duration_sec: int,
) -> list[dict[str, Any]]:
    """Backend kaydi once yazar; UI sonradan gelen paket/caption ile bos alanlari doldurur."""
    matches = [e for e in items if e.get("task_id") == task_id]
    slim_pack = _slim_publish_pack(publish_pack) if publish_pack else {}
    title = (title or "").strip()[:500]
    changed = False
    for e in matches:
        patch: dict[str, Any] = {}
        if slim_pack and not e.get("publish_pack"):
            patch["publish_pack"] = slim_pack
        cur_title = (e.get("title") or "").strip()
        if title and title != (subject or "").strip() and (
            not cur_title or cur_title == (e.get("subject") or "").strip()
        ):
            patch["title"] = title
        if caption and not e.get("caption"):
            patch["caption"] = caption
        if hashtags and not e.get("hashtags"):
            patch["hashtags"] = hashtags
            patch["hashtags_list"] = [
                h.strip() for h in hashtags.replace(",", " ").split() if h.strip().startswith("#")
            ]
        if script and not e.get("script"):
            patch["script"] = script.strip()[:20000]
        if production_sec and not e.get("production_sec"):
            patch["production_sec"] = max(0, int(production_sec))
        if duration_sec and not e.get("duration_sec"):
            patch["duration_sec"] = duration_sec
        if patch:
            e.update(patch)
            changed = True
    if changed:
        _save_index(items)
    return matches


@_locked
def archive_from_task(
    *,
    task_id: str,
    subject: str,
    video_urls: list[str],
    engine_base: str,
    aspect: str = "9:16",
    platform: str = "",
    language: str = "",
    voice: str = "",
    caption: str = "",
    hashtags: str = "",
    niche: str = "",
    tts_provider: str = "",
    duration_sec: int = 0,
    production_sec: int = 0,
    title: str = "",
    script: str = "",
    publish_pack: dict[str, Any] | None = None,
    bgm_file: str = "",
) -> list[dict[str, Any]]:
    """Tamamlanan gorevden videolari galeriye kopyalar; yeni kayitlari dondurur."""
    items = _load_index()
    existing_tasks = {e.get("task_id") for e in items}
    if task_id in existing_tasks:
        return _merge_into_existing(
            items,
            task_id,
            title=title,
            subject=subject,
            caption=caption,
            hashtags=hashtags,
            script=script,
            publish_pack=publish_pack,
            production_sec=production_sec,
            duration_sec=duration_sec,
        )

    created: list[dict[str, Any]] = []
    local_src = _find_local_task_video(task_id)
    sources: list[Path | str] = []

    if local_src:
        sources.append(local_src)
    else:
        sources.extend(video_urls or [])

    if not sources:
        return []

    for i, src in enumerate(sources):
        entry_id = uuid.uuid4().hex[:12]
        filename = f"{entry_id}.mp4"
        dest = gallery_dir() / filename

        ok = False
        if isinstance(src, Path):
            shutil.copy2(src, dest)
            ok = dest.stat().st_size > 0
        elif isinstance(src, str):
            if src.startswith("http"):
                ok = _download_url(src, dest, engine_base)
            else:
                rel = src.lstrip("/")
                if rel.startswith("tasks/"):
                    parts = rel.split("/", 2)
                    if len(parts) >= 3:
                        lp = engine_task_dir(parts[1]) / parts[2]
                        if lp.is_file():
                            shutil.copy2(lp, dest)
                            ok = True

        if not ok or not dest.is_file():
            dest.unlink(missing_ok=True)
            continue

        hashtags_list = (
            [h.strip() for h in hashtags.replace(",", " ").split() if h.strip().startswith("#")]
            if hashtags
            else []
        )
        try:
            size_mb = round(dest.stat().st_size / (1024 * 1024), 2)
        except OSError:
            size_mb = 0.0
        entry = {
            "id": entry_id,
            "task_id": task_id,
            "title": (title or subject or "Video").strip()[:500],
            "subject": (subject or "Video").strip()[:500],
            "aspect": aspect,
            "platform": platform,
            "niche": niche,
            "tts_provider": tts_provider,
            "language": language,
            "voice": voice,
            "duration_sec": duration_sec,
            "production_sec": max(0, int(production_sec or 0)),
            "caption": caption,
            "hashtags": hashtags,
            "hashtags_list": hashtags_list,
            "script": (script or "").strip()[:20000],
            "publish_pack": _slim_publish_pack(publish_pack),
            "bgm_file": (bgm_file or "").strip(),
            "filename": filename,
            "size_mb": size_mb,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "index": i + 1,
        }
        items.insert(0, entry)
        created.append(entry)

    if created:
        _save_index(items)
        for entry in created:
            try:
                vid = gallery_dir() / entry.get("filename", "")
                if vid.is_file():
                    meta = thumb_mod.generate_for_entry(
                        vid,
                        entry["id"],
                        gallery_root=gallery_dir(),
                    )
                    update_entry(
                        entry["id"],
                        {
                            "thumbnail": meta["thumbnail"],
                            "thumbnail_index": meta["thumbnail_index"],
                            "thumbnail_candidates": meta["candidates"],
                        },
                    )
                    entry.update(
                        {
                            "thumbnail": meta["thumbnail"],
                            "thumbnail_index": meta["thumbnail_index"],
                            "thumbnail_candidates": meta["candidates"],
                        }
                    )
            except Exception:
                pass
    return created


def list_items(
    *,
    platform: str | None = None,
    niche: str | None = None,
    include_assets: bool = False,
) -> list[dict[str, Any]]:
    items = _load_index()
    out = []
    orphan_ids: list[str] = []
    for e in items:
        if platform and (e.get("platform") or "") != platform:
            continue
        if niche and (e.get("niche") or "") != niche:
            continue
        row = _build_list_row(e, include_assets=include_assets)
        if row:
            out.append(row)
        else:
            eid = e.get("id")
            if eid:
                orphan_ids.append(str(eid))
    if orphan_ids and not platform and not niche:
        # Sessiz budama: dosyasi olmayan index kayitlarini temizle
        orphan_set = set(orphan_ids)
        with _index_lock:
            fresh = _load_index()
            kept = [e for e in fresh if e.get("id") not in orphan_set]
            if len(kept) < len(fresh):
                _save_index(kept)
    return out


def get_list_item(entry_id: str, *, include_assets: bool = True) -> dict[str, Any] | None:
    eid = (entry_id or "").strip()
    if not eid:
        return None
    for e in _load_index():
        if e.get("id") == eid:
            return _build_list_row(e, include_assets=include_assets)
    return None


def get_item(entry_id: str) -> dict[str, Any] | None:
    eid = (entry_id or "").strip()
    if not eid:
        return None
    for e in _load_index():
        if e.get("id") == eid:
            path = gallery_dir() / e.get("filename", "")
            if path.is_file():
                return {**e, "path": path}
    return None


def resolve_thumbnail_file(entry_id: str) -> Path | None:
    """Thumbnail dosya yolu — index cache + tek kayit; N+1 parse yok."""
    eid = (entry_id or "").strip()
    if not eid:
        return None
    root = gallery_dir()
    for e in _load_index():
        if e.get("id") != eid:
            continue
        thumb_fn = e.get("thumbnail") or ""
        if thumb_fn:
            path = root / thumb_fn
            if path.is_file():
                return path
        # Yaygin varsayilan ad
        from akifactory import thumbnail as _tm

        fallback = root / _tm.thumbnail_filename(eid)
        if fallback.is_file():
            return fallback
        return None
    return None


def open_entry_folder(entry_id: str) -> bool:
    """Galeri videosunun klasorunu dosya secili acar (Windows) veya klasoru acar."""
    item = get_item(entry_id)
    if not item:
        return False
    path = Path(item["path"])
    if not path.is_file():
        return False
    import os
    import subprocess
    import sys

    try:
        if sys.platform == "win32":
            subprocess.run(["explorer", "/select,", str(path)], check=False)
            return True
        from akifactory.settings_assets import _open_path

        return _open_path(path.parent)
    except Exception:
        return False
