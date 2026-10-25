"""Video kaynagi — Pexels, Pixabay, birlesik secim."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from akifactory.paths import engine_task_dir, engine_config_file, engine_storage_dir

VALID_SOURCES = frozenset({"pexels", "pixabay", "local", "pexels+pixabay", "pinokio"})
_LOCAL_SUFFIXES = (".mp4", ".mov", ".avi", ".flv", ".mkv", ".jpg", ".jpeg", ".png")
PINOKIO_SOURCE_IDS = frozenset({"pinokio", "minimax", "minimax_h3", "h3"})


def is_pinokio_source(source: str | None) -> bool:
    return (source or "").strip().lower() in PINOKIO_SOURCE_IDS


def local_videos_dir() -> Path:
    return engine_storage_dir() / "local_videos"


def list_local_materials() -> list[dict[str, str]]:
    """local_videos klasorundeki dosyalar — motor video_materials formati."""
    d = local_videos_dir()
    d.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for p in d.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() in _LOCAL_SUFFIXES:
            files.append(p)
    files.sort(key=lambda x: x.name.lower())
    return [{"provider": "local", "url": f.name} for f in files]


def _read_pexels_keys() -> list[str]:
    cfg = engine_config_file()
    if not cfg.is_file():
        return []
    text = cfg.read_text(encoding="utf-8")
    m = re.search(r'pexels_api_keys\s*=\s*\[([^\]]*)\]', text)
    if not m:
        return []
    return re.findall(r'"([^"]+)"', m.group(1))


def pexels_configured() -> bool:
    return bool(_read_pexels_keys())


def _read_pixabay_keys() -> list[str]:
    cfg = engine_config_file()
    if not cfg.is_file():
        return []
    text = cfg.read_text(encoding="utf-8")
    m = re.search(r"pixabay_api_keys\s*=\s*\[([^\]]*)\]", text)
    if not m:
        return []
    return re.findall(r'"([^"]+)"', m.group(1))


def pixabay_configured() -> bool:
    return bool(_read_pixabay_keys())


async def search_pixabay_videos(query: str, count: int = 5) -> list[str]:
    keys = _read_pixabay_keys()
    if not keys or not query.strip():
        return []
    params = {
        "q": query.strip(),
        "video_type": "film",
        "per_page": min(50, max(3, count * 3)),
        "key": keys[0],
    }
    url = f"https://pixabay.com/api/videos/?{urlencode(params)}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            hits = r.json().get("hits") or []
    except Exception:
        return []
    urls: list[str] = []
    for hit in hits:
        videos = hit.get("videos") or {}
        for quality in ("large", "medium", "small", "tiny"):
            v = videos.get(quality)
            if v and v.get("url"):
                urls.append(v["url"])
                break
        if len(urls) >= count:
            break
    return urls


async def _pexels_count(query: str) -> int:
    cfg = engine_config_file()
    if not cfg.is_file():
        return 0
    text = cfg.read_text(encoding="utf-8")
    m = re.search(r'pexels_api_keys\s*=\s*\["([^"]+)"', text)
    if not m:
        return 0
    key = m.group(1)
    headers = {"Authorization": key}
    url = f"https://api.pexels.com/videos/search?{urlencode({'query': query, 'per_page': 5})}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url, headers=headers)
            if r.status_code == 200:
                return len(r.json().get("videos") or [])
    except Exception:
        pass
    return 0


async def resolve_video_source(source: str, query: str = "") -> str:
    """motor'ye gidecek kaynak: pexels | pixabay | local | pexels+pixabay.

    pinokio/minimax stok degil — AI gorsel adiminda local materials gelir.
    """
    src = (source or "pexels").strip().lower()
    if is_pinokio_source(src):
        return "local"
    if src == "local":
        return "local"
    if src == "pixabay":
        return "pixabay" if pixabay_configured() else "pexels"
    if src == "pexels+pixabay":
        px_ok = pexels_configured()
        pb_ok = pixabay_configured()
        if px_ok and pb_ok:
            return "pexels+pixabay"
        if pb_ok:
            return "pixabay"
        return "pexels"
    return "pexels"


def list_for_ui() -> list[dict[str, Any]]:
    px_ok = pexels_configured()
    pb_ok = pixabay_configured()
    return [
        {
            "id": "pexels",
            "label": "Pexels (stok)",
            "available": px_ok,
            "hint": "" if px_ok else "Pexels API key gerekli — Ayarlar → Stok API",
        },
        {
            "id": "pixabay",
            "label": "Pixabay (stok)",
            "available": pb_ok,
            "hint": "" if pb_ok else "Pixabay API key gerekli — Ayarlar → Stok API",
        },
        {
            "id": "pexels+pixabay",
            "label": "Her ikisi (karisik havuz)",
            "available": px_ok and pb_ok,
            "hint": "Pexels ve Pixabay anahtari gerekli — Ayarlar → Stok API",
        },
        {
            "id": "pinokio",
            "label": "Pinokio H3 Studio (AI)",
            "available": True,
            "hint": "SCENE → H3 Studio uretim (45–60 sn continue zinciri)",
        },
        {
            "id": "local",
            "label": "Yerel dosya",
            "available": True,
            "hint": "storage/local_videos — kendi video + resimler birlikte",
        },
    ]


def list_task_source_clips(task_id: str) -> list[Path]:
    """Ilk gorevde indirilen stok klipleri (combined/final haric)."""
    td = engine_task_dir(task_id)
    if not td.is_dir():
        return []
    skip_prefixes = ("combined-", "final-")
    skip_names = {"audio.mp3", "subtitle.srt", "script.txt"}
    out: list[Path] = []
    for p in sorted(td.iterdir()):
        if not p.is_file():
            continue
        if p.name in skip_names:
            continue
        if p.suffix.lower() not in (".mp4", ".mov", ".webm"):
            continue
        if any(p.name.startswith(px) for px in skip_prefixes):
            continue
        if p.stat().st_size > 0:
            out.append(p)
    return out


def stage_paths_for_reuse(clip_paths: list[str | Path], tag: str) -> list[dict[str, str]]:
    """Dosya yollarini local_videos altina kopyala — EN gorev ayni klipleri kullanir."""
    paths: list[Path] = []
    seen: set[str] = set()
    for raw in clip_paths:
        p = Path(raw)
        if not p.is_file():
            continue
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        paths.append(p)
    if not paths:
        return []
    base = local_videos_dir()
    folder = f"_reuse_{tag}"
    dest_dir = base / folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    materials: list[dict[str, str]] = []
    for i, src in enumerate(paths, start=1):
        dest_name = f"clip_{i:02d}{src.suffix.lower()}"
        dest = dest_dir / dest_name
        shutil.copy2(src, dest)
        materials.append({"provider": "local", "url": str(dest.resolve())})
    return materials


def stage_task_clips_for_reuse(
    source_task_id: str,
    tag: str,
    extra_paths: list[str] | None = None,
) -> list[dict[str, str]]:
    """TR gorev kliplerini staging — task klasoru veya motor materials listesi."""
    clips = list_task_source_clips(source_task_id)
    if extra_paths:
        seen = {str(c.resolve()) for c in clips}
        for raw in extra_paths:
            p = Path(raw)
            if p.is_file():
                key = str(p.resolve())
                if key not in seen:
                    clips.append(p)
                    seen.add(key)
    return stage_paths_for_reuse(clips, tag)


def cleanup_reuse_folder(tag: str) -> None:
    folder = local_videos_dir() / f"_reuse_{tag}"
    if folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)
