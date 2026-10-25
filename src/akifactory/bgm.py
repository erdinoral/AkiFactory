"""Arka plan muzigi — data/bgm/ altinda niş klasorleri + kullanici MP3'leri."""

from __future__ import annotations

import random
import re
import shutil
import subprocess
from pathlib import Path

from akifactory.paths import app_root, resource_dir
from akifactory.script_prompts import NICHE_LABELS, NICHE_ORDER

BGM_EXTENSIONS = (".mp3",)
# Bunlar MP3'e cevrilip oyle kullanilir (motor yalnizca MP3 okur)
CONVERTIBLE_AUDIO = (".wav", ".m4a", ".aac", ".ogg", ".flac")
SHARED_CATEGORY = "genel"


def user_bgm_dir() -> Path:
    d = app_root() / "data" / "bgm"
    d.mkdir(parents=True, exist_ok=True)
    return d


def engine_songs_dir() -> Path:
    d = resource_dir() / "songs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_category_folders() -> None:
    root = user_bgm_dir()
    for niche_id in NICHE_ORDER:
        (root / niche_id).mkdir(parents=True, exist_ok=True)


def _label_from_filename(name: str) -> str:
    stem = Path(name).stem
    if "__" in stem:
        stem = stem.split("__", 1)[1]
    stem = stem.replace("_", " ").replace("-", " ").strip()
    return stem.title() if stem else name


def _engine_filename(category: str, src: Path) -> str:
    if not category:
        return src.name
    return f"{category}__{src.name}"


def _iter_source_files() -> list[tuple[str, Path]]:
    root = user_bgm_dir()
    found: list[tuple[str, Path]] = []
    for f in sorted(root.glob("*.mp3"), key=lambda p: p.name.lower()):
        if f.is_file() and f.stat().st_size >= 1000:
            found.append(("", f))
    for sub in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not sub.is_dir():
            continue
        cat = sub.name.lower()
        for f in sorted(sub.glob("*.mp3"), key=lambda p: p.name.lower()):
            if f.is_file() and f.stat().st_size >= 1000:
                found.append((cat, f))
    return found


def convert_to_mp3(src: Path, dest: Path) -> Path:
    from akifactory.outros import _ffmpeg_exe

    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        raise RuntimeError("ffmpeg bulunamadi")
    r = subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
         "-vn", "-c:a", "libmp3lame", "-b:a", "192k", str(dest)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if r.returncode != 0 or not dest.is_file():
        dest.unlink(missing_ok=True)
        raise RuntimeError((r.stderr or "ses donusturulemedi")[:300])
    return dest


def _convert_loose_audio() -> None:
    """Klasore elle atilan WAV/M4A... dosyalarinin yanina MP3 kopyasi."""
    for src in user_bgm_dir().rglob("*"):
        if src.suffix.lower() not in CONVERTIBLE_AUDIO or not src.is_file():
            continue
        dest = src.with_suffix(".mp3")
        if dest.exists():
            continue
        try:
            convert_to_mp3(src, dest)
        except Exception:
            pass


def sync_tracks_to_engine() -> None:
    """data/bgm/**/*.mp3 -> motor resource/songs (duz dosya adlari)."""
    ensure_category_folders()
    _convert_loose_audio()
    dest_dir = engine_songs_dir()
    for category, src in _iter_source_files():
        dest = dest_dir / _engine_filename(category, src)
        if not dest.exists() or src.stat().st_mtime > dest.stat().st_mtime:
            shutil.copy2(src, dest)
    _cleanup_engine_stock_bgm(dest_dir)


def _cleanup_engine_stock_bgm(dest_dir: Path) -> None:
    """Motorun eski varsayilan output*.mp3 dosyalari — niş secimini bozar."""
    for f in dest_dir.glob("output*.mp3"):
        try:
            f.unlink(missing_ok=True)
        except OSError:
            pass


def _category_label(category: str) -> str:
    if not category:
        return "Ortak"
    return NICHE_LABELS.get(category, category.replace("_", " ").title())


def _track_entry(category: str, src: Path) -> dict[str, str]:
    filename = _engine_filename(category, src)
    return {
        "id": filename,
        "label": _label_from_filename(filename),
        "filename": filename,
        "category": category or "ortak",
        "category_label": _category_label(category),
    }


def tracks_for_category(category: str) -> list[dict[str, str]]:
    """Yalnizca belirtilen niş klasorundeki parcalar."""
    sync_tracks_to_engine()
    key = category.strip().lower()
    return [_track_entry(cat, src) for cat, src in _iter_source_files() if cat == key]


def list_tracks_for_ui(*, niche_id: str | None = None) -> list[dict[str, str]]:
    sync_tracks_to_engine()
    tracks: list[dict[str, str]] = []
    seen: set[str] = set()
    for category, src in _iter_source_files():
        entry = _track_entry(category, src)
        if entry["filename"] in seen:
            continue
        seen.add(entry["filename"])
        tracks.append(entry)
    if niche_id:
        key = niche_id.strip().lower()
        niche_only = [t for t in tracks if t["category"] == key]
        if niche_only:
            return niche_only
        genel = [t for t in tracks if t["category"] == SHARED_CATEGORY]
        if genel:
            return genel
    return tracks


def list_categories_for_ui() -> list[dict[str, object]]:
    ensure_category_folders()
    sync_tracks_to_engine()
    counts: dict[str, int] = {nid: 0 for nid in NICHE_ORDER}
    ortak = 0
    for category, _src in _iter_source_files():
        if not category:
            ortak += 1
        elif category in counts:
            counts[category] += 1
    out: list[dict[str, object]] = []
    for nid in NICHE_ORDER:
        out.append(
            {
                "id": nid,
                "label": NICHE_LABELS.get(nid, nid),
                "track_count": counts.get(nid, 0),
            }
        )
    out.append({"id": "ortak", "label": "Ortak (kok klasor)", "track_count": ortak})
    return out


def count_for_niche(niche_id: str | None) -> int:
    key = (niche_id or SHARED_CATEGORY).strip().lower()
    n = 0
    for category, _src in _iter_source_files():
        if category == key or (not category and key == SHARED_CATEGORY):
            n += 1
    return n


def pick_random_for_niche(niche_id: str | None) -> str | None:
    """Secili niş klasorunden rastgele 1 parca; bos ise genel klasore duser."""
    key = (niche_id or SHARED_CATEGORY).strip().lower()
    pool = tracks_for_category(key)
    if not pool and key != SHARED_CATEGORY:
        pool = tracks_for_category(SHARED_CATEGORY)
    if not pool:
        return None
    return random.choice(pool)["filename"]


def pick_random_user_track() -> str | None:
    """Tum kullanici MP3 klasorlerinden rastgele (motor stok output*.mp3 haric)."""
    sync_tracks_to_engine()
    pool: list[dict[str, str]] = []
    seen: set[str] = set()
    for category, src in _iter_source_files():
        entry = _track_entry(category, src)
        if entry["filename"] in seen:
            continue
        seen.add(entry["filename"])
        pool.append(entry)
    if not pool:
        return None
    return random.choice(pool)["filename"]


def _track_category(filename: str) -> str:
    safe = Path(filename).name
    if "__" in safe:
        return safe.split("__", 1)[0].lower()
    return "ortak"


def resolve_track_path(filename: str) -> Path | None:
    sync_tracks_to_engine()
    safe = re.sub(r'[<>:"/\\|?*]+', "", Path(filename).name)
    if not safe.lower().endswith(".mp3"):
        return None
    if "__" in safe:
        category, orig = safe.split("__", 1)
        src = user_bgm_dir() / category / orig
        if src.is_file():
            return src
    src = user_bgm_dir() / safe
    if src.is_file():
        return src
    engine = engine_songs_dir() / safe
    if engine.is_file():
        return engine
    return None


def resolve_bgm_payload(
    *,
    mode: str | None = "niche",
    track: str | None = None,
    niche_id: str | None = None,
) -> tuple[str, str]:
    """
    motor API icin (bgm_type, bgm_file).
    mode: niche | random | custom | none

    Her zaman acik dosya adi gonderilir (bgm_type=custom). motor'nin global
    random modu kullanilmaz — aksi halde output*.mp3 stok parcalari karisir.
    """
    m = (mode or "niche").strip().lower()
    if m in ("none", "off", "kapali", ""):
        return "", ""

    if m == "niche":
        picked = pick_random_for_niche(niche_id)
        if picked:
            return "custom", picked
        return "", ""

    if m == "random":
        picked = pick_random_user_track()
        if picked:
            return "custom", picked
        return "", ""

    if m == "custom":
        sync_tracks_to_engine()
        name = (track or "").strip()
        if not name:
            picked = pick_random_for_niche(niche_id)
            return ("custom", picked) if picked else ("", "")
        safe = re.sub(r'[<>:"/\\|?*]+', "", Path(name).name)
        if not safe.lower().endswith(".mp3"):
            safe = f"{safe}.mp3" if safe else ""
        if not safe or not resolve_track_path(safe):
            picked = pick_random_for_niche(niche_id)
            return ("custom", picked) if picked else ("", "")
        key = (niche_id or "").strip().lower()
        if key:
            cat = _track_category(safe)
            if cat not in (key, SHARED_CATEGORY, "ortak", ""):
                picked = pick_random_for_niche(niche_id)
                return ("custom", picked) if picked else ("", "")
        shutil.copy2(resolve_track_path(safe), engine_songs_dir() / safe)
        return "custom", safe

    return "", ""
