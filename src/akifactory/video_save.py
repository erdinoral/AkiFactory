"""Video URL -> yerel dosya ve kaydetme."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from urllib.parse import unquote, urlparse

from akifactory.gallery import get_item
from akifactory.paths import engine_task_dir


def safe_video_filename(name: str) -> str:
    s = re.sub(r'[<>:"/\\|?*]+', "", (name or "").strip()) or "akifactory"
    s = s[:80]
    return s if s.lower().endswith(".mp4") else f"{s}.mp4"


def resolve_video_path(url: str) -> Path | None:
    """HTTP veya goreceli video URL'sini yerel dosyaya cevir."""
    if not url:
        return None
    raw = url.strip()
    if raw.startswith("/"):
        raw = f"http://local{raw}"
    parsed = urlparse(raw)
    path = unquote(parsed.path or "")

    m = re.match(r"^/tasks/([^/]+)/(final-\d+\.mp4|combined-\d+\.mp4)$", path, re.I)
    if m:
        local = engine_task_dir(m.group(1)) / m.group(2)
        if local.is_file():
            return local

    m = re.match(r"^/api/gallery/([^/]+)/(download|stream)$", path, re.I)
    if m:
        item = get_item(m.group(1))
        if item:
            p = Path(item.get("path") or "")
            if p.is_file():
                return p

    # data/gallery/... dogrudan yol
    if path.startswith("/data/gallery/"):
        from akifactory.paths import app_root

        local = app_root() / path.lstrip("/").replace("/", "\\")
        if local.is_file():
            return local

    return None


def copy_video_to(src: Path, dest: Path) -> Path:
    dest = Path(dest)
    if dest.suffix.lower() != ".mp4":
        dest = dest.with_suffix(".mp4")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest
