"""Stok indirme — video agirlikli, araya Pexels/Pixabay fotograflari."""

from __future__ import annotations

import os
from typing import List
from urllib.parse import urlencode

import requests
from loguru import logger
from moviepy import CompositeVideoClip, ImageClip

from akifactory.engine.config import config
from akifactory.engine.models.schema import MaterialInfo, VideoAspect, VideoConcatMode
from akifactory.engine.services import material as engine_material
from akifactory.engine.utils import utils

from akifactory.stock_registry import is_url_used, mark_url_used, normalize_stock_url


def _shared_cache_dir() -> str:
    return utils.storage_dir("cache_videos")


def _ensure_in_dir(src: str, dest_dir: str, filename: str) -> str:
    """Ortak cache dosyasini task klasorune kopyala (varsa dokunma)."""
    import shutil

    if not src or not os.path.isfile(src):
        return ""
    dest_dir = (dest_dir or "").strip()
    if not dest_dir:
        return src
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, filename)
    if os.path.isfile(dest) and os.path.getsize(dest) > 0:
        return dest
    if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dest)):
        return src
    try:
        shutil.copy2(src, dest)
        return dest if os.path.isfile(dest) else src
    except OSError:
        return src


def save_video_cached(video_url: str, task_dir: str = "") -> str:
    """Once ortak cache_videos; task klasorune sadece kopya (yeniden indirme yok)."""
    cache_dir = _shared_cache_dir()
    os.makedirs(cache_dir, exist_ok=True)
    url_hash = utils.md5((video_url or "").split("?")[0])
    name = f"vid-{url_hash}.mp4"
    cached = os.path.join(cache_dir, name)
    if not (os.path.isfile(cached) and os.path.getsize(cached) > 0):
        saved = engine_material.save_video(video_url, cache_dir)
        if not saved:
            return ""
        cached = saved
    else:
        logger.info(f"stock video cache hit: {cached}")
    if task_dir and os.path.normcase(os.path.abspath(task_dir)) != os.path.normcase(
        os.path.abspath(cache_dir)
    ):
        return _ensure_in_dir(cached, task_dir, name)
    return cached


def save_image(image_url: str, save_dir: str) -> str:
    """Once ortak cache; istenirse task klasorune kopyala."""
    cache_dir = _shared_cache_dir()
    os.makedirs(cache_dir, exist_ok=True)
    url_hash = utils.md5(image_url.split("?")[0])
    name = f"img-{url_hash}.jpg"
    image_path = os.path.join(cache_dir, name)
    if not (os.path.isfile(image_path) and os.path.getsize(image_path) > 0):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        try:
            content = requests.get(
                image_url,
                headers=headers,
                proxies=config.proxy,
                verify=engine_material._get_tls_verify(),
                timeout=(60, 120),
            ).content
            if not content:
                return ""
            with open(image_path, "wb") as f:
                f.write(content)
            if os.path.getsize(image_path) <= 0:
                return ""
        except Exception as exc:
            logger.warning(f"image download failed: {exc}")
            return ""
    else:
        logger.info(f"stock image cache hit: {image_path}")
    if save_dir and os.path.normcase(os.path.abspath(save_dir)) != os.path.normcase(
        os.path.abspath(cache_dir)
    ):
        return _ensure_in_dir(image_path, save_dir, name)
    return image_path


def _image_slot_indices(n_slots: int, n_images: int) -> set[int]:
    """Ornegin 5 slot 1 gorsel -> {2} (2V 1I 2V)."""
    if n_images <= 0 or n_slots <= 0:
        return set()
    if n_images == 1 and n_slots >= 3:
        return {n_slots // 2}
    out: set[int] = set()
    for i in range(n_images):
        pos = int((i + 1) * n_slots / (n_images + 1))
        out.add(min(max(pos, 0), n_slots - 1))
    return out


def _plan_mix(audio_duration: float, max_clip_duration: int) -> tuple[int, int, set[int]]:
    clip = max(2, int(max_clip_duration or 5))
    video_segments = max(3, int((audio_duration or 30) / clip) + 1)
    video_segments = min(video_segments, 12)
    n_images = min(2, max(1, video_segments // 3))
    total = video_segments + n_images
    return video_segments, n_images, _image_slot_indices(total, n_images)


def _pick_best_pexels_video_file(
    video_files: list[dict],
    *,
    target_w: int,
    target_h: int,
    portrait: bool,
) -> dict | None:
    """Exact WxH yoksa dogru oryantasyon + yeterince buyuk en yakin dosyayi sec."""
    if not video_files:
        return None

    scored: list[tuple[float, int, dict]] = []
    for video in video_files:
        try:
            w = int(video.get("width") or 0)
            h = int(video.get("height") or 0)
        except (TypeError, ValueError):
            continue
        if w < 480 or h < 480:
            continue
        is_portrait = h >= w
        if portrait != is_portrait:
            continue
        # Exact eslesme once
        if w == target_w and h == target_h:
            return video
        # Hedef cozunurluge yakin / daha buyuk tercih
        area = w * h
        target_area = max(1, target_w * target_h)
        # Kucuk dosyalari cezalandir; buyuklere hafif tercih
        size_ratio = area / target_area
        if size_ratio < 0.45:
            continue
        dist = abs(w - target_w) + abs(h - target_h)
        scored.append((dist, -area, video))

    if not scored:
        # Oryantasyon gevset: en azindan buyuk dosya
        for video in video_files:
            try:
                w = int(video.get("width") or 0)
                h = int(video.get("height") or 0)
            except (TypeError, ValueError):
                continue
            if w >= 720 and h >= 720:
                scored.append((abs(w - target_w) + abs(h - target_h), -(w * h), video))
    if not scored:
        return None
    scored.sort(key=lambda x: (x[0], x[1]))
    return scored[0][2]


def search_videos_pexels_soft(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    """Pexels video arama — exact cozunurluk zorunlulugu yok (AkiFactory)."""
    aspect = VideoAspect(video_aspect)
    video_orientation = aspect.name
    video_width, video_height = aspect.to_resolution()
    portrait = video_height >= video_width
    api_key = engine_material.get_api_key("pexels_api_keys")
    headers = {
        "Authorization": api_key,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        ),
    }
    params = {
        "query": search_term,
        "per_page": 20,
        "orientation": video_orientation,
    }
    query_url = f"https://api.pexels.com/videos/search?{urlencode(params)}"
    logger.info(f"searching videos (soft): {query_url}")

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=engine_material._get_tls_verify(),
            timeout=(30, 60),
        )
        response = r.json()
        video_items: list[MaterialInfo] = []
        if "videos" not in response:
            logger.error(f"search videos failed: {response}")
            return video_items
        for v in response.get("videos") or []:
            duration = int(v.get("duration") or 0)
            if duration < minimum_duration:
                continue
            best = _pick_best_pexels_video_file(
                list(v.get("video_files") or []),
                target_w=video_width,
                target_h=video_height,
                portrait=portrait,
            )
            if not best or not best.get("link"):
                continue
            item = MaterialInfo()
            item.provider = "pexels"
            item.url = best["link"]
            item.duration = duration
            video_items.append(item)
        return video_items
    except Exception as e:
        logger.error(f"search videos soft failed: {e}")
        return []


def search_photos_pexels(
    search_term: str,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> list[str]:
    aspect = VideoAspect(video_aspect)
    api_key = engine_material.get_api_key("pexels_api_keys")
    headers = {
        "Authorization": api_key,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    params = {
        "query": search_term,
        "per_page": 15,
        "orientation": aspect.name,
    }
    url = f"https://api.pexels.com/v1/search?{urlencode(params)}"
    try:
        r = requests.get(
            url,
            headers=headers,
            proxies=config.proxy,
            verify=engine_material._get_tls_verify(),
            timeout=(30, 60),
        )
        data = r.json()
        urls: list[str] = []
        for photo in data.get("photos") or []:
            src = photo.get("src") or {}
            u = src.get("large2x") or src.get("large") or src.get("original")
            if u and u not in urls:
                urls.append(u)
        return urls
    except Exception as exc:
        logger.warning(f"pexels photo search failed for '{search_term}': {exc}")
        return []


def search_photos_pixabay(
    search_term: str,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> list[str]:
    aspect = VideoAspect(video_aspect)
    _, video_height = aspect.to_resolution()
    orient = "vertical" if video_height >= 720 else "horizontal"
    api_key = engine_material.get_api_key("pixabay_api_keys")
    params = {
        "q": search_term,
        "image_type": "photo",
        "orientation": orient,
        "per_page": 20,
        "key": api_key,
    }
    url = f"https://pixabay.com/api/?{urlencode(params)}"
    try:
        r = requests.get(
            url,
            proxies=config.proxy,
            verify=engine_material._get_tls_verify(),
            timeout=(30, 60),
        )
        data = r.json()
        urls: list[str] = []
        for hit in data.get("hits") or []:
            u = hit.get("largeImageURL") or hit.get("webformatURL")
            if u and u not in urls:
                urls.append(u)
        return urls
    except Exception as exc:
        logger.warning(f"pixabay photo search failed for '{search_term}': {exc}")
        return []


def convert_image_to_clip_mp4(
    image_path: str,
    clip_duration: int,
    save_dir: str,
) -> str:
    """Stok fotografi zoom klibe cevir (motor yerel resim mantigi)."""
    from akifactory.engine.services import video as vid_mod

    out_path = os.path.join(save_dir, f"{os.path.basename(image_path)}.mp4")
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
        return out_path

    clip = None
    final_clip = None
    try:
        clip, source_path = vid_mod._open_image_clip_with_fallback(image_path)
        w, h = clip.size
        if w < 480 or h < 480:
            logger.warning(f"stock image too small: {w}x{h} — {image_path}")
            vid_mod.close_clip(clip)
            return ""

        vid_mod.close_clip(clip)
        clip = (
            ImageClip(source_path)
            .with_duration(clip_duration)
            .with_position("center")
        )
        zoom_clip = clip.resized(
            lambda t: 1 + (clip_duration * 0.03) * (t / clip.duration)
        )
        final_clip = CompositeVideoClip([zoom_clip])
        vid_mod._write_clip_video(final_clip, out_path)
        return out_path if os.path.isfile(out_path) else ""
    except Exception as exc:
        logger.warning(f"image to video failed: {image_path} => {exc}")
        return ""
    finally:
        if clip is not None:
            vid_mod.close_clip(clip)
        if final_clip is not None:
            vid_mod.close_clip(final_clip)


def download_mixed_stock_materials(
    task_id: str,
    search_terms: List[str],
    source: str = "pexels",
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_contact_mode: VideoConcatMode = VideoConcatMode.random,
    audio_duration: float = 0.0,
    max_clip_duration: int = 5,
    exclude_urls: set[str] | list[str] | None = None,
    dest_dir: str | None = None,
) -> List[str]:
    """Video agirlikli indir; araya 1–2 stok fotograf (V V I V V deseni).

    source=pexels+pixabay iken her iki havuzdan arama yapilip birlestirilir.
    Indirme her zaman ortak cache_videos uzerinden; hedef klasore sadece kopya.
    dest_dir: uzun video ortak clips/ gibi tek klasor — task klasorune yazma.
    exclude_urls: bu oturumda / onceki bolumlerde kullanilan URL'ler (tekrar yok).
    """
    sources: list[str]
    if source == "pexels+pixabay":
        sources = ["pexels", "pixabay"]
    elif source == "pixabay":
        sources = ["pixabay"]
    else:
        sources = ["pexels"]

    blocked: set[str] = {
        normalize_stock_url(u) for u in (exclude_urls or []) if normalize_stock_url(u)
    }

    def _blocked(url: str) -> bool:
        key = normalize_stock_url(url)
        return (not key) or key in blocked or is_url_used(url)

    video_items: list[MaterialInfo] = []
    video_urls: set[str] = set()
    photo_urls: list[str] = []
    photo_seen: set[str] = set()

    for src_name in sources:
        # Pexels: soft resolution (exact 1080x1920 zorunlulugu yok)
        search_videos = search_videos_pexels_soft
        search_photos = search_photos_pexels
        if src_name == "pixabay":
            search_videos = engine_material.search_videos_pixabay
            search_photos = search_photos_pixabay
        for term in search_terms:
            for item in search_videos(
                search_term=term,
                minimum_duration=max_clip_duration,
                video_aspect=video_aspect,
            ):
                key = normalize_stock_url(item.url)
                if key and key not in video_urls and not _blocked(item.url):
                    video_items.append(item)
                    video_urls.add(key)
            for url in search_photos(term, video_aspect):
                key = normalize_stock_url(url)
                if key and key not in photo_seen and not _blocked(url):
                    photo_urls.append(url)
                    photo_seen.add(key)

    logger.info(
        f"stock pool ({'+'.join(sources)}): {len(video_items)} videos, {len(photo_urls)} photos "
        f"for {len(search_terms)} search terms (blocked={len(blocked)})"
    )

    # Uzun video: tek ortak klasor. Aksi halde config (task = her goreve ayri — kisa video).
    if dest_dir and str(dest_dir).strip():
        material_directory = str(dest_dir).strip()
        os.makedirs(material_directory, exist_ok=True)
    else:
        material_directory = config.app.get("material_directory", "").strip()
        if material_directory == "task":
            material_directory = utils.task_dir(task_id)
        elif material_directory and not os.path.isdir(material_directory):
            material_directory = ""

    concat_mode_value = getattr(video_contact_mode, "value", video_contact_mode)
    if concat_mode_value == VideoConcatMode.random.value:
        import random

        random.shuffle(video_items)

    n_videos, n_images, image_positions = _plan_mix(audio_duration, max_clip_duration)
    total_slots = n_videos + n_images
    logger.info(
        f"mix plan: {n_videos} video + {n_images} photo slots "
        f"(positions {sorted(image_positions)})"
    )

    paths: list[str] = []
    total_duration = 0.0
    v_i = 0
    p_i = 0
    used_this_run: set[str] = set()

    for slot in range(total_slots):
        if total_duration >= audio_duration:
            break
        use_image = slot in image_positions and p_i < len(photo_urls)
        if use_image:
            img_url = photo_urls[p_i]
            p_i += 1
            img_path = save_image(img_url, material_directory or "")
            if img_path:
                mark_url_used(img_url, img_path)
                used_this_run.add(normalize_stock_url(img_url))
                mp4 = convert_image_to_clip_mp4(
                    img_path, max_clip_duration, material_directory or os.path.dirname(img_path)
                )
                if mp4:
                    paths.append(mp4)
                    total_duration += max_clip_duration
                    logger.info(f"stock photo clip: {mp4}")
                    continue
        while v_i < len(video_items) and (
            _blocked(video_items[v_i].url)
            or normalize_stock_url(video_items[v_i].url) in used_this_run
        ):
            v_i += 1
        if v_i >= len(video_items):
            break
        item = video_items[v_i]
        v_i += 1
        saved = save_video_cached(item.url, material_directory or "")
        if saved:
            mark_url_used(item.url, saved)
            used_this_run.add(normalize_stock_url(item.url))
            paths.append(saved)
            total_duration += min(max_clip_duration, item.duration or max_clip_duration)
            logger.info(f"stock video clip: {saved}")

    while total_duration < audio_duration and v_i < len(video_items):
        while v_i < len(video_items) and (
            _blocked(video_items[v_i].url)
            or normalize_stock_url(video_items[v_i].url) in used_this_run
        ):
            v_i += 1
        if v_i >= len(video_items):
            break
        item = video_items[v_i]
        v_i += 1
        saved = save_video_cached(item.url, material_directory or "")
        if saved:
            mark_url_used(item.url, saved)
            used_this_run.add(normalize_stock_url(item.url))
            paths.append(saved)
            total_duration += min(max_clip_duration, item.duration or max_clip_duration)

    if isinstance(exclude_urls, set):
        exclude_urls.update(used_this_run)

    logger.success(
        f"downloaded mixed stock: {len(paths)} clips "
        f"(photos≈{sum(1 for p in paths if os.path.basename(p).startswith('img-') or '.jpg.mp4' in p)})"
    )
    if not paths:
        paths = _local_failover_paths(
            task_id=task_id,
            material_directory=material_directory or "",
            audio_duration=audio_duration,
            max_clip_duration=max_clip_duration,
        )
    return paths


def _broll_dirs() -> list[Path]:
    from akifactory.paths import data_dir, engine_storage_dir

    dirs = [
        engine_storage_dir() / "local_videos",
        data_dir() / "broll",
    ]
    return [d for d in dirs if d.is_dir()]


def _local_failover_paths(
    *,
    task_id: str,
    material_directory: str,
    audio_duration: float,
    max_clip_duration: int,
) -> list[str]:
    """Stok bos/hata — feature flag aciksa yerel kliplerden doldur."""
    try:
        from akifactory import features_util

        if not features_util.is_enabled("stock_local_failover"):
            return []
    except Exception:
        return []
    import random
    import shutil

    suffixes = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".jpg", ".jpeg", ".png"}
    candidates: list[Path] = []
    for d in _broll_dirs():
        for p in d.iterdir():
            if p.is_file() and p.suffix.lower() in suffixes and not p.name.startswith("_"):
                candidates.append(p)
    if not candidates:
        logger.warning("stock_local_failover acik ama yerel klip yok")
        return []
    random.shuffle(candidates)
    dest_root = material_directory or utils.task_dir(task_id)
    os.makedirs(dest_root, exist_ok=True)
    need = max(3, int((audio_duration or 30) / max(2, max_clip_duration or 5)) + 1)
    need = min(need, 8, len(candidates))
    out: list[str] = []
    for src in candidates[:need]:
        dest = os.path.join(dest_root, f"local-failover-{src.name}")
        try:
            if not os.path.isfile(dest):
                shutil.copy2(src, dest)
            if src.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                mp4 = convert_image_to_clip_mp4(dest, max_clip_duration, dest_root)
                if mp4:
                    out.append(mp4)
            else:
                out.append(dest)
        except Exception as exc:
            logger.warning(f"local failover kopya hatasi: {exc}")
    if out:
        logger.info(f"stock_local_failover: {len(out)} yerel klip kullanildi")
    return out
