"""Ayarlar > Dosyalar — muzik, kanal intro/outro ve RVC ses modeli yukleme / silme."""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path

from akifactory import bgm as bgm_mod
from akifactory import outros as outro_mod
from akifactory.rvc_registry import RVC_ROOT
from akifactory.script_prompts import NICHE_ORDER

AUDIO_EXTENSIONS = (".mp3", *bgm_mod.CONVERTIBLE_AUDIO)
RVC_EXTENSIONS = (".pth", ".index", ".zip")
MAX_BYTES = {"bgm": 200 * 1024**2, "outros": 1024**3, "rvc": 3 * 1024**3}

_TR = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


def slug(text: str, fallback: str = "dosya") -> str:
    s = (text or "").translate(_TR).strip().lower()
    s = re.sub(r"[^a-z0-9._-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("._-")
    return s[:80] or fallback


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    for n in range(2, 1000):
        cand = path.with_name(f"{path.stem}-{n}{path.suffix}")
        if not cand.exists():
            return cand
    raise RuntimeError("Ayni adda cok fazla dosya var")


def _inside(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def save_bgm(tmp: Path, filename: str, category: str) -> Path:
    ext = Path(filename).suffix.lower()
    if ext not in AUDIO_EXTENSIONS:
        raise ValueError(f"Desteklenmeyen ses: {ext or '?'} — {', '.join(AUDIO_EXTENSIONS)}")
    cat = (category or "").strip().lower()
    if cat in ("ortak", ""):
        folder = bgm_mod.user_bgm_dir()
    elif cat in NICHE_ORDER:
        folder = bgm_mod.user_bgm_dir() / cat
    else:
        raise ValueError(f"Bilinmeyen niş: {category}")
    folder.mkdir(parents=True, exist_ok=True)
    dest = _unique(folder / f"{slug(Path(filename).stem, 'parca')}.mp3")
    if ext == ".mp3":
        shutil.move(str(tmp), dest)
    else:
        bgm_mod.convert_to_mp3(tmp, dest)
    bgm_mod.sync_tracks_to_engine()
    return dest


def save_channel_clip(tmp: Path, filename: str, channel: str, kind: str) -> Path:
    if kind not in ("intro", "outro"):
        raise ValueError("Tur: intro veya outro")
    ext = Path(filename).suffix.lower()
    if ext not in outro_mod.VIDEO_EXTENSIONS:
        raise ValueError(f"Desteklenmeyen video: {ext or '?'} — {', '.join(outro_mod.VIDEO_EXTENSIONS)}")
    label = (channel or "").strip()
    if not label:
        raise ValueError("Kanal adi gerekli")
    folder = outro_mod.outros_dir() / slug(label, "kanal")
    folder.mkdir(parents=True, exist_ok=True)
    meta = folder / outro_mod.META_FILE
    if not meta.is_file():
        meta.write_text(json.dumps({"label": label}, ensure_ascii=False) + "\n", encoding="utf-8")
    for old in folder.iterdir():
        if old.is_file() and old.stem.lower() == kind and old.suffix.lower() in outro_mod.VIDEO_EXTENSIONS:
            old.unlink()
    dest = folder / f"{kind}{ext}"
    shutil.move(str(tmp), dest)
    return dest


def save_rvc(files: list[tuple[Path, str]], name: str, pitch: int = 0) -> Path:
    label = (name or "").strip()
    if not label:
        zip_or_pth = next((Path(fn).stem for _, fn in files if Path(fn).suffix.lower() in (".zip", ".pth")), "")
        label = zip_or_pth or "Yeni ses"
    folder = RVC_ROOT / slug(label, "ses")
    if folder.exists() and any(folder.glob("*.pth")):
        raise ValueError(f"'{label}' adinda bir ses zaten var — once sil veya baska ad ver")
    folder.mkdir(parents=True, exist_ok=True)
    try:
        for tmp, filename in files:
            ext = Path(filename).suffix.lower()
            if ext == ".zip":
                _extract_rvc_zip(tmp, folder)
            elif ext in (".pth", ".index"):
                shutil.move(str(tmp), folder / f"{slug(Path(filename).stem, 'model')}{ext}")
            else:
                raise ValueError(f"Desteklenmeyen dosya: {filename} — .zip, .pth veya .index")
        if not any(folder.glob("*.pth")):
            raise ValueError("Yuklenenlerde .pth model dosyasi yok")
        voice_json = folder / "voice.json"
        if not voice_json.is_file():
            voice_json.write_text(
                json.dumps({"label": label, "lang": "tr", "pitch": int(pitch)}, ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return folder


def _extract_rvc_zip(tmp: Path, folder: Path) -> None:
    try:
        zf = zipfile.ZipFile(tmp)
    except zipfile.BadZipFile as e:
        raise ValueError("Zip dosyasi bozuk") from e
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename).name
            ext = Path(name).suffix.lower()
            if ext in (".pth", ".index"):
                dest = _unique(folder / f"{slug(Path(name).stem, 'model')}{ext}")
            elif name.lower() == "voice.json":
                dest = folder / "voice.json"
            else:
                continue
            with zf.open(info) as src, dest.open("wb") as out:
                shutil.copyfileobj(src, out)


def delete_asset(section: str, item_id: str) -> None:
    key = (section or "").strip().lower()
    raw = (item_id or "").strip()
    if not raw or ".." in raw:
        raise ValueError("Gecersiz kayit")
    if key == "bgm":
        src = bgm_mod.resolve_track_path(raw)
        root = bgm_mod.user_bgm_dir()
        if not src or not _inside(src, root):
            raise FileNotFoundError("Parca bulunamadi")
        src.unlink()
        for ext in bgm_mod.CONVERTIBLE_AUDIO:
            src.with_suffix(ext).unlink(missing_ok=True)
        engine_copy = bgm_mod.engine_songs_dir() / Path(raw).name
        engine_copy.unlink(missing_ok=True)
        return
    if key == "outros":
        folder = outro_mod.outros_dir() / raw
        root = outro_mod.outros_dir()
    elif key == "rvc":
        folder = RVC_ROOT / raw
        root = RVC_ROOT
    else:
        raise ValueError("Bolum: bgm, outros veya rvc")
    if "/" in raw or "\\" in raw or not folder.is_dir() or not _inside(folder, root) or folder == root:
        raise FileNotFoundError("Klasor bulunamadi")
    shutil.rmtree(folder)
