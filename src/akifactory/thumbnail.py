"""Galeri videosundan kapak (thumbnail) karesi cikarimi — FFmpeg."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from akifactory.gpu import resolve_ffmpeg_exe

# Kapak adaylari: (video sure orani, etiket)
COVER_POSITIONS: tuple[tuple[float, str], ...] = (
    (0.06, "hook"),
    (0.20, "erken"),
    (0.45, "orta"),
)

DEFAULT_COVER_INDEX = 0


def _video_duration_sec(video_path: Path) -> float:
    ffmpeg = resolve_ffmpeg_exe()
    if not ffmpeg:
        return 30.0
    try:
        r = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(video_path), "-f", "null", "-"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        import re

        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr or "")
        if m:
            h, mi, s = m.groups()
            return int(h) * 3600 + int(mi) * 60 + float(s)
    except Exception:
        pass
    return 30.0


def extract_frame_jpeg(video_path: Path, time_sec: float, out_path: Path) -> bool:
    ffmpeg = resolve_ffmpeg_exe()
    if not ffmpeg:
        return False
    try:
        r = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{max(0.0, time_sec):.3f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                "-y",
                str(out_path),
            ],
            capture_output=True,
            timeout=45,
        )
        return r.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 0
    except Exception:
        return False


def _candidate_filename(entry_id: str, index: int) -> str:
    return f"{entry_id}-thumb-{index}.jpg"


def thumbnail_filename(entry_id: str) -> str:
    return f"{entry_id}-thumb.jpg"


def extract_cover_candidates(
    video_path: Path,
    *,
    entry_id: str,
    out_dir: Path,
) -> list[dict[str, Any]]:
    """Videodan kapak adaylarini cikar; dosyalari out_dir'e yazar."""
    duration = _video_duration_sec(video_path)
    out: list[dict[str, Any]] = []
    for i, (ratio, label) in enumerate(COVER_POSITIONS):
        t = max(0.15, min(max(duration - 0.15, 0.15), duration * ratio))
        fname = _candidate_filename(entry_id, i)
        dest = out_dir / fname
        if not extract_frame_jpeg(video_path, t, dest):
            continue
        out.append(
            {
                "index": i,
                "label": label,
                "time_sec": round(t, 2),
                "filename": fname,
                "path": dest,
            }
        )
    return out


def apply_cover_choice(
    *,
    entry_id: str,
    gallery_root: Path,
    frame_index: int,
    candidates: list[dict[str, Any]],
) -> str | None:
    """Secilen adayi ana kapak dosyasina kopyala."""
    pick = next((c for c in candidates if c["index"] == frame_index), None)
    if not pick:
        pick = candidates[0] if candidates else None
    if not pick:
        return None
    src = Path(pick["path"])
    if not src.is_file():
        src = gallery_root / pick["filename"]
    if not src.is_file():
        return None
    main = gallery_root / thumbnail_filename(entry_id)
    main.write_bytes(src.read_bytes())
    return main.name


def generate_for_entry(
    video_path: Path,
    entry_id: str,
    *,
    gallery_root: Path,
    frame_index: int | None = None,
) -> dict[str, Any]:
    """Kapak adaylarini uret ve varsayilan kapagi kaydet."""
    if not video_path.is_file():
        raise ValueError("Video dosyasi bulunamadi")
    candidates = extract_cover_candidates(video_path, entry_id=entry_id, out_dir=gallery_root)
    if not candidates:
        raise ValueError("Videodan kapak karesi cikarilamadi — ffmpeg gerekli")

    idx = DEFAULT_COVER_INDEX if frame_index is None else frame_index
    main_name = apply_cover_choice(
        entry_id=entry_id,
        gallery_root=gallery_root,
        frame_index=idx,
        candidates=candidates,
    )
    if not main_name:
        raise ValueError("Kapak dosyasi olusturulamadi")

    return {
        "thumbnail": main_name,
        "thumbnail_index": idx,
        "candidates": [
            {
                "index": c["index"],
                "label": c["label"],
                "time_sec": c["time_sec"],
                "filename": c["filename"],
            }
            for c in candidates
        ],
    }


def thumb_paths_for_entry(entry_id: str, gallery_root: Path) -> list[Path]:
    paths: list[Path] = []
    main = gallery_root / thumbnail_filename(entry_id)
    if main.is_file():
        paths.append(main)
    for i in range(len(COVER_POSITIONS)):
        p = gallery_root / _candidate_filename(entry_id, i)
        if p.is_file():
            paths.append(p)
    return paths
