"""Uzun video galerisi — klasor bazli montaj paketi (data/gallery/longform)."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from akifactory import json_io as jio
from akifactory.gallery import task_montage_paths
from akifactory.paths import data_dir, engine_task_dir
from akifactory.video_source import list_task_source_clips

INDEX_NAME = "index.json"
DELETED_EXPORTS_FILE = "deleted_exports.json"


def longform_gallery_dir() -> Path:
    from akifactory.paths import data_dir

    d = data_dir() / "gallery" / "longform"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path() -> Path:
    return longform_gallery_dir() / INDEX_NAME


def _load_index() -> list[dict[str, Any]]:
    return jio.load_wrapped_list(_index_path())


def _save_index(items: list[dict[str, Any]]) -> None:
    jio.save_wrapped_list(_index_path(), items)


def _deleted_exports_path() -> Path:
    return longform_gallery_dir() / DELETED_EXPORTS_FILE


def _load_deleted_exports() -> set[str]:
    raw = jio.read_json_file(_deleted_exports_path(), default={})
    if isinstance(raw, dict):
        ids = raw.get("longform_ids") or []
        return {str(x).strip() for x in ids if str(x).strip()}
    return set()


def _mark_export_deleted(longform_id: str) -> None:
    lf_id = (longform_id or "").strip()
    if not lf_id:
        return
    ids = _load_deleted_exports()
    ids.add(lf_id)
    jio.safe_write_json(
        _deleted_exports_path(),
        jio.stamp_schema({"longform_ids": sorted(ids)}),
    )


def _remove_tree(path: Path) -> bool:
    """Windows'ta salt-okunur dosyalar dahil klasoru sil."""
    if not path.exists():
        return True

    def _onerror(func, p, _exc_info):  # type: ignore[no-untyped-def]
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    try:
        if path.is_file():
            path.unlink(missing_ok=True)
            return not path.exists()
        shutil.rmtree(path, onerror=_onerror)
        return not path.exists()
    except Exception:
        return not path.exists()


def _safe_rel_name(name: str) -> str | None:
    safe = Path(name).name
    if not safe or safe != name or ".." in name:
        return None
    return safe


def _safe_rel_path(name: str) -> str | None:
    raw = (name or "").replace("\\", "/").strip()
    if not raw or ".." in raw.split("/"):
        return None
    parts = [p for p in raw.split("/") if p and p not in (".", "..")]
    if not parts:
        return None
    return "/".join(parts)


def chapter_folder_slug(index: int, title: str) -> str:
    """Ornek: 01-tarihcesi, 03-icerigi-ve-dili"""
    t = (title or "bolum").strip().lower()
    folded = unicodedata.normalize("NFKD", t)
    ascii_t = "".join(c for c in folded if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_t).strip("-")[:40]
    if not slug:
        slug = "bolum"
    return f"{int(index) + 1:02d}-{slug}"


def entry_dir(entry_id: str) -> Path:
    return longform_gallery_dir() / entry_id.strip()


def resolve_entry_file(entry_id: str, filename: str) -> Path | None:
    eid = (entry_id or "").strip()
    rel = _safe_rel_path(filename) or _safe_rel_name(filename or "")
    if not eid or not rel:
        return None
    path = (entry_dir(eid) / rel).resolve()
    root = entry_dir(eid).resolve()
    if root not in path.parents and path != root:
        return None
    if not path.is_file() or path.stat().st_size <= 0:
        return None
    return path


def _copy_task_file(src: Path, dest: Path) -> bool:
    if not src.is_file() or src.stat().st_size <= 0:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest.is_file() and dest.stat().st_size > 0


def _copy_clips(
    task_id: str,
    clips_dir: Path,
    *,
    name_prefix: str = "",
) -> list[dict[str, Any]]:
    clips_dir.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    seen_hash: set[str] = set()
    idx = 0
    prefix_part = f"{name_prefix}_" if (name_prefix or "").strip() else ""

    def _file_sig(src: Path) -> str:
        # Ayni cache dosyasi farkli bolumde tekrar kopyalanmasin
        return f"{src.name}:{src.stat().st_size}"

    def _add(src: Path, kind: str) -> None:
        nonlocal idx
        if not src.is_file() or src.stat().st_size <= 0:
            return
        key = str(src.resolve()).lower()
        if key in seen:
            return
        seen.add(key)
        sig = _file_sig(src)
        if sig in seen_hash:
            return
        # Mevcut clips/ icinde ayni isim+boyut varsa atla
        for existing in clips_dir.iterdir() if clips_dir.is_dir() else []:
            if existing.is_file() and existing.name.endswith(src.suffix.lower()):
                try:
                    if existing.stat().st_size == src.stat().st_size and (
                        src.stem.split("-")[-1] in existing.stem
                        or existing.stem.endswith(src.stem)
                    ):
                        seen_hash.add(sig)
                        return
                except OSError:
                    pass
        seen_hash.add(sig)
        idx += 1
        ext = src.suffix.lower() or (".mp4" if kind == "video" else ".jpg")
        kind_prefix = "clip" if kind == "video" else "gorsel"
        dest_name = f"{prefix_part}{kind_prefix}_{idx:03d}{ext}"
        dest = clips_dir / dest_name
        if _copy_task_file(src, dest):
            items.append(
                {
                    "name": f"clips/{dest_name}",
                    "kind": kind,
                    "size_mb": round(dest.stat().st_size / (1024 * 1024), 2),
                }
            )

    tid = (task_id or "").strip()
    if not tid:
        return items
    for p in list_task_source_clips(tid):
        _add(p, "video")
    td = engine_task_dir(tid)
    skip = {"audio.mp3", "subtitle.srt", "script.txt", "script.json"}
    if td.is_dir():
        for p in sorted(td.iterdir()):
            if not p.is_file() or p.name in skip:
                continue
            if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                _add(p, "image")
    return items


def normalize_entry_layout(folder: Path) -> int:
    """Bolum/*/clips dosyalarini kok clips/ altina tasi (eski paket uyumu)."""
    if not folder.is_dir():
        return 0
    moved = 0
    clips_root = folder / "clips"
    for sub in sorted(folder.iterdir()):
        if not sub.is_dir() or sub.name == "clips":
            continue
        if not re.match(r"^\d{2}-", sub.name):
            continue
        ch_clips = sub / "clips"
        if not ch_clips.is_dir():
            continue
        for p in list(ch_clips.iterdir()):
            if not p.is_file() or p.stat().st_size <= 0:
                continue
            clips_root.mkdir(parents=True, exist_ok=True)
            dest = clips_root / f"{sub.name}_{p.name}"
            if dest.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
                continue
            try:
                shutil.move(str(p), str(dest))
                moved += 1
            except OSError:
                if _copy_task_file(p, dest):
                    moved += 1
                    try:
                        p.unlink()
                    except OSError:
                        pass
        try:
            if ch_clips.is_dir() and not any(ch_clips.iterdir()):
                ch_clips.rmdir()
        except OSError:
            shutil.rmtree(ch_clips, ignore_errors=True)
    return moved


def export_chapter_bundle(
    dest_root: Path,
    *,
    slug: str,
    task_id: str,
    lang: str,
    script: str = "",
    title: str = "",
    copy_task_clips: bool = True,
) -> dict[str, Any]:
    """Bolum: {slug}/audio+altyazi+senaryo; gorsel/video: ortak clips/.

    copy_task_clips=False: uzun video gorselleri zaten dest_root/clips altina
    indirildiyse task klasorunden tekrar kopyalama.
    """
    ch_dir = dest_root / slug
    ch_dir.mkdir(parents=True, exist_ok=True)
    lang_key = (lang or "tr").strip().lower()[:5]
    out: dict[str, Any] = {"slug": slug, "lang": lang_key}
    if (title or "").strip():
        (ch_dir / "baslik.txt").write_text(title.strip(), encoding="utf-8")
    paths = task_montage_paths(str(task_id))
    if "audio" in paths:
        dest = ch_dir / f"audio-{lang_key}.mp3"
        if _copy_task_file(paths["audio"], dest):
            out["audio"] = f"{slug}/audio-{lang_key}.mp3"
    if "subtitle" in paths:
        dest = ch_dir / f"subtitle-{lang_key}.srt"
        if _copy_task_file(paths["subtitle"], dest):
            out["subtitle"] = f"{slug}/subtitle-{lang_key}.srt"
    if (script or "").strip():
        rel = f"{slug}/script-{lang_key}.txt"
        (ch_dir / f"script-{lang_key}.txt").write_text(script.strip(), encoding="utf-8")
        out["script"] = rel
    clips_root = dest_root / "clips"
    clips_root.mkdir(parents=True, exist_ok=True)
    if copy_task_clips:
        # Gorsel/video tek klasorde (hash isimli — tekrar yok)
        clip_items = _copy_clips(str(task_id), clips_root, name_prefix="")
        out["clip_count"] = len(clip_items)
    else:
        out["clip_count"] = sum(
            1 for p in clips_root.iterdir() if p.is_file() and p.stat().st_size > 0
        ) if clips_root.is_dir() else 0
    # Eski bolum/clips kalintisini temizle
    legacy = ch_dir / "clips"
    if legacy.is_dir():
        normalize_entry_layout(dest_root)
    return out


def _copy_export_tree(src: Path, dest: Path) -> None:
    if not src.is_dir():
        return
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name == "job-meta.json":
            continue
        target = dest / item.name
        if item.is_file():
            _copy_task_file(item, target)
        elif item.is_dir():
            if target.exists():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copytree(item, target)


def archive_from_job(job: Any) -> dict[str, Any] | None:
    """Tamamlanan uzun video isini galeri klasorune kaydet."""
    if getattr(job, "cancelled", False):
        return None
    chapters = list(getattr(job, "chapters", []) or [])
    has_chapter_tasks = any(ch.get("task_id") for ch in chapters)
    task_id = getattr(job, "task_id", None)
    if not has_chapter_tasks and not task_id:
        return None
    fallback_tid = str(task_id or next((ch.get("task_id") for ch in chapters if ch.get("task_id")), ""))
    return _archive_longform_bundle(
        longform_id=str(job.longform_id),
        task_id=fallback_tid,
        main_subject=(job.main_subject or "").strip(),
        chapters=chapters,
        common=dict(getattr(job, "common", {}) or {}),
        script=(getattr(job, "script", "") or "").strip(),
        en_task_id=getattr(job, "en_task_id", None),
        en_script=(getattr(job, "en_script", "") or "").strip(),
    )


def _archive_longform_bundle(
    *,
    longform_id: str,
    task_id: str,
    main_subject: str,
    chapters: list[dict[str, Any]],
    common: dict[str, Any],
    script: str = "",
    en_task_id: str | None = None,
    en_script: str = "",
) -> dict[str, Any] | None:
    lf_id = (longform_id or "").strip()
    tid = (task_id or "").strip()
    chapter_rows: list[dict[str, Any]] = []
    clip_total = 0
    export_root = data_dir() / "longform" / lf_id
    per_chapter = any(ch.get("task_id") for ch in chapters or [])

    if not lf_id or (not per_chapter and not tid):
        return None

    items = _load_index()
    for e in items:
        if e.get("longform_id") == lf_id:
            return e

    entry_id = uuid.uuid4().hex[:12]
    folder = entry_dir(entry_id)
    folder.mkdir(parents=True, exist_ok=True)

    if export_root.is_dir():
        _copy_export_tree(export_root, folder)
    elif per_chapter:
        for ch in sorted(chapters or [], key=lambda c: int(c.get("index", 0))):
            idx = int(ch.get("index", 0))
            slug = ch.get("folder_slug") or chapter_folder_slug(idx, ch.get("title") or "")
            ch_tid = (ch.get("task_id") or "").strip()
            if ch_tid:
                bundle = export_chapter_bundle(
                    folder,
                    slug=slug,
                    task_id=ch_tid,
                    lang="tr",
                    script=str(ch.get("script") or ""),
                    title=str(ch.get("display_title") or ch.get("title") or ""),
                )
                clip_total += int(bundle.get("clip_count") or 0)
            en_tid = (ch.get("en_task_id") or "").strip()
            if en_tid:
                export_chapter_bundle(
                    folder,
                    slug=slug,
                    task_id=en_tid,
                    lang="en",
                    script=str(ch.get("en_script") or ""),
                    title=str(ch.get("display_title") or ch.get("title") or ""),
                )
    else:
        paths = task_montage_paths(tid)
        if "audio" in paths:
            _copy_task_file(paths["audio"], folder / "audio-tr.mp3")
        if "subtitle" in paths:
            _copy_task_file(paths["subtitle"], folder / "subtitle-tr.srt")
        clip_total = len(_copy_clips(tid, folder / "clips"))

    # Eski bolum/clips yapisini ortak clips/ altina tasi
    normalize_entry_layout(folder)
    if (folder / "clips").is_dir():
        clip_total = sum(1 for p in (folder / "clips").iterdir() if p.is_file())

    if script.strip():
        (folder / "script-tr.txt").write_text(script.strip(), encoding="utf-8")
    elif (folder / "script-tr.txt").is_file() is False and tid:
        src_script = engine_task_dir(tid) / "script.txt"
        if src_script.is_file():
            _copy_task_file(src_script, folder / "script-tr.txt")

    en_tid = (en_task_id or "").strip() or None
    if en_script.strip():
        (folder / "script-en.txt").write_text(en_script.strip(), encoding="utf-8")
    if en_tid and not per_chapter:
        en_paths = task_montage_paths(en_tid)
        if "audio" in en_paths:
            _copy_task_file(en_paths["audio"], folder / "audio-en.mp3")
        if "subtitle" in en_paths:
            _copy_task_file(en_paths["subtitle"], folder / "subtitle-en.srt")

    for ch in sorted(chapters or [], key=lambda c: int(c.get("index", 0))):
        idx = int(ch.get("index", 0))
        slug = ch.get("folder_slug") or chapter_folder_slug(idx, ch.get("title") or "")
        chapter_rows.append(
            {
                "index": idx,
                "title": ch.get("title", ""),
                "display_title": ch.get("display_title") or ch.get("title", ""),
                "folder_slug": slug,
                "task_id": ch.get("task_id") or "",
                "en_task_id": ch.get("en_task_id") or "",
            }
        )

    if not clip_total and (folder / "clips").is_dir():
        clip_total = sum(1 for p in (folder / "clips").iterdir() if p.is_file())

    dual = bool(common.get("dual_language"))
    subject = (main_subject or "Uzun video").strip()[:500]
    entry = {
        "id": entry_id,
        "longform_id": lf_id,
        "main_subject": subject,
        "title": subject,
        "platform": common.get("platform", ""),
        "aspect": common.get("video_aspect") or "16:9",
        "niche": common.get("niche", ""),
        "language": "tr" if dual else common.get("production_language", "tr"),
        "dual_language": dual,
        "chapters": chapter_rows,
        "chapter_count": len(chapter_rows),
        "clip_count": clip_total,
        "task_id": tid,
        "en_task_id": en_tid or "",
        "per_chapter": per_chapter or bool(chapter_rows),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "folder": str(folder),
    }
    (folder / "meta.json").write_text(
        json.dumps(entry, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    missing = [
        f"{int(ch.get('index', 0)) + 1}. {ch.get('display_title') or ch.get('title') or ch.get('folder_slug')}"
        for ch in chapter_rows
        if not (folder / (ch.get("folder_slug") or "") / "audio-tr.mp3").is_file()
    ]
    if missing:
        (folder / "EKSIK-BOLUMLER.txt").write_text(
            "Bu basliklarda ses/altyazi YOK (senaryo QC veya TTS basarisiz):\n\n"
            + "\n".join(missing)
            + "\n\nCozum: Uzun video uretiminde «Tekrar dene» ile eksik bolumleri yeniden uretin.\n",
            encoding="utf-8",
        )
    (folder / "MONTAJ.txt").write_text(
        "AkiFactory uzun video montaj paketi\n"
        "==================================\n\n"
        "01-baslik/   → o bolumun audio-tr.mp3, subtitle-tr.srt, script-tr.txt\n"
        "02-baslik/   → ayni sekilde her baslik ayri klasor\n"
        "clips/       → tum gorsel ve video klipler (ortak)\n\n"
        "EKSIK-BOLUMLER.txt varsa: o basliklarda ses/altyazi uretilmemistir.\n",
        encoding="utf-8",
    )
    items.insert(0, entry)
    _save_index(items)
    return entry


def _find_task_for_script(script_text: str) -> str | None:
    needle = (script_text or "").strip()
    if len(needle) < 80:
        return None
    fingerprint = needle[:800]
    tasks_root = engine_task_dir("x").parent
    if not tasks_root.is_dir():
        return None
    best_id = ""
    best_mtime = 0.0
    for task_dir in tasks_root.iterdir():
        if not task_dir.is_dir():
            continue
        sp = task_dir / "script.txt"
        if not sp.is_file():
            continue
        try:
            body = sp.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if body[:800] != fingerprint:
            continue
        mtime = sp.stat().st_mtime
        if mtime >= best_mtime:
            best_mtime = mtime
            best_id = task_dir.name
    return best_id or None


def sync_exports() -> list[dict[str, Any]]:
    """data/longform export klasorlerinden galeriye eksik paketleri al."""
    from akifactory.paths import data_dir

    root = data_dir() / "longform"
    if not root.is_dir():
        return []
    indexed = {e.get("longform_id") for e in _load_index()}
    deleted = _load_deleted_exports()
    recovered: list[dict[str, Any]] = []
    for folder in sorted(root.iterdir()):
        if not folder.is_dir():
            continue
        lf_id = folder.name
        if lf_id in indexed or lf_id in deleted:
            continue
        meta_path = folder / "job-meta.json"
        meta: dict[str, Any] | None = None
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = None
        if not meta:
            script_path = folder / "script-tr.txt"
            if not script_path.is_file():
                continue
            try:
                script_text = script_path.read_text(encoding="utf-8")
            except Exception:
                continue
            task_id = _find_task_for_script(script_text)
            if not task_id:
                continue
            first_line = script_text.strip().splitlines()[0][:120] if script_text.strip() else lf_id
            meta = {
                "longform_id": lf_id,
                "task_id": task_id,
                "main_subject": first_line,
                "chapters": [],
                "common": {},
                "script": script_text,
            }
        entry = _archive_longform_bundle(
            longform_id=str(meta.get("longform_id") or lf_id),
            task_id=str(meta.get("task_id") or ""),
            main_subject=str(meta.get("main_subject") or "Uzun video"),
            chapters=list(meta.get("chapters") or []),
            common=dict(meta.get("common") or {}),
            script=str(meta.get("script") or ""),
            en_task_id=meta.get("en_task_id"),
            en_script=str(meta.get("en_script") or ""),
        )
        if entry:
            recovered.append(entry)
            indexed.add(lf_id)
    return recovered


def list_items(
    *,
    platform: str | None = None,
    niche: str | None = None,
) -> list[dict[str, Any]]:
    sync_exports()
    out: list[dict[str, Any]] = []
    for e in _load_index():
        if platform and (e.get("platform") or "") != platform:
            continue
        if niche and (e.get("niche") or "") != niche:
            continue
        folder = entry_dir(e["id"])
        if not folder.is_dir():
            continue
        row = dict(e)
        row["assets"] = assets_for_entry(e["id"])
        row["folder_path"] = str(folder)
        # Yayin paketi backfill icin senaryo (kartta kopyala satirlari)
        script = read_entry_script(e["id"], max_chars=12000)
        if script:
            row["script"] = script
            row["has_script"] = True
        else:
            row["has_script"] = False
        total = 0
        for p in folder.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
        row["size_mb"] = round(total / (1024 * 1024), 2)
        out.append(row)
    return out


def read_entry_script(entry_id: str, *, max_chars: int | None = None) -> str:
    """Galeri klasorundeki TR senaryoyu oku (yoksa bolum scriptlerini birlestir)."""
    folder = entry_dir(entry_id)
    if not folder.is_dir():
        return ""
    root = folder / "script-tr.txt"
    if root.is_file():
        try:
            text = root.read_text(encoding="utf-8").strip()
        except Exception:
            text = ""
        if text:
            return text[:max_chars] if max_chars else text

    parts: list[str] = []
    for sub in sorted(folder.iterdir()):
        if not sub.is_dir() or sub.name == "clips":
            continue
        sp = sub / "script-tr.txt"
        if not sp.is_file():
            continue
        try:
            body = sp.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if body:
            parts.append(body)
    text = "\n\n".join(parts).strip()
    return text[:max_chars] if max_chars and text else text


def update_entry(entry_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    """Index + meta.json guncelle; yayin metinlerini klasore de yaz."""
    eid = (entry_id or "").strip()
    if not eid or not fields:
        return None
    items = _load_index()
    updated: dict[str, Any] | None = None
    for e in items:
        if e.get("id") == eid:
            e.update(fields)
            updated = e
            break
    if not updated:
        return None
    _save_index(items)

    folder = entry_dir(eid)
    if folder.is_dir():
        meta_path = folder / "meta.json"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
        except Exception:
            meta = {}
        meta.update(updated)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        _write_publish_files(folder, updated)

    return {**updated, "assets": assets_for_entry(eid), "folder_path": str(folder)}


def _write_publish_files(folder: Path, entry: dict[str, Any]) -> None:
    """Klasorde kopyala-yapistir icin baslik / aciklama / etiket dosyalari."""
    title = (entry.get("title") or entry.get("main_subject") or "").strip()
    caption = (entry.get("caption") or "").strip()
    hashtags = (entry.get("hashtags") or "").strip()
    pack = entry.get("publish_pack") or {}
    if not hashtags:
        hashtags = (pack.get("best_hashtags") or "").strip()
    if not caption:
        caption = (pack.get("best_caption") or "").strip()
    if not title:
        title = (pack.get("best_title") or "").strip()

    script = ""
    try:
        script = read_entry_script(str(entry.get("id") or folder.name), max_chars=20000)
    except Exception:
        script = ""
    if not script:
        script = (entry.get("script") or "").strip()

    # Aciklama = merak metni + altinda tam senaryo
    description = caption
    if script and script.strip() and script.strip() != caption.strip():
        description = f"{caption}\n\n{script.strip()}" if caption else script.strip()

    try:
        if title:
            (folder / "baslik.txt").write_text(title + "\n", encoding="utf-8")
        if description:
            (folder / "aciklama.txt").write_text(description + "\n", encoding="utf-8")
        if hashtags:
            (folder / "etiketler.txt").write_text(hashtags + "\n", encoding="utf-8")
        if title or description or hashtags:
            block = []
            if title:
                block.append(f"BASLIK\n{title}")
            if description:
                block.append(f"ACIKLAMA\n{description}")
            if hashtags:
                block.append(f"ETIKETLER\n{hashtags}")
            (folder / "yayin.txt").write_text("\n\n".join(block) + "\n", encoding="utf-8")
    except Exception:
        pass


def get_item(entry_id: str) -> dict[str, Any] | None:
    for e in _load_index():
        if e.get("id") == entry_id:
            folder = entry_dir(entry_id)
            if folder.is_dir():
                row = {**e, "assets": assets_for_entry(entry_id), "folder_path": str(folder)}
                script = read_entry_script(entry_id)
                if script:
                    row["script"] = script
                return row
    return None


def assets_for_entry(entry_id: str) -> dict[str, Any]:
    eid = (entry_id or "").strip()
    if not eid:
        return {}
    folder = entry_dir(eid)
    if not folder.is_dir():
        return {}
    normalize_entry_layout(folder)
    out: dict[str, Any] = {}
    base = f"/api/gallery/longform/{eid}/file"
    if (folder / "script-tr.txt").is_file():
        out["script_url"] = f"{base}/script-tr.txt"
    if (folder / "script-en.txt").is_file():
        out["script_en_url"] = f"{base}/script-en.txt"

    chapter_assets: list[dict[str, Any]] = []
    meta_path = folder / "meta.json"
    chapter_meta: list[dict[str, Any]] = []
    if meta_path.is_file():
        try:
            chapter_meta = json.loads(meta_path.read_text(encoding="utf-8")).get("chapters") or []
        except Exception:
            chapter_meta = []

    if chapter_meta:
        for ch in chapter_meta:
            slug = ch.get("folder_slug") or ""
            idx = int(ch.get("index", 0))
            row: dict[str, Any] = {
                "index": idx,
                "title": ch.get("title", ""),
                "display_title": ch.get("display_title") or ch.get("title", ""),
                "slug": slug,
                "missing_audio": True,
                "missing_subtitle": True,
            }
            if slug and (folder / slug).is_dir():
                for lang in ("tr", "en"):
                    audio = folder / slug / f"audio-{lang}.mp3"
                    sub = folder / slug / f"subtitle-{lang}.srt"
                    scr = folder / slug / f"script-{lang}.txt"
                    if audio.is_file():
                        row[f"audio_{lang}_url"] = f"{base}/{slug}/audio-{lang}.mp3"
                        if lang == "tr":
                            row["missing_audio"] = False
                    if sub.is_file():
                        row[f"subtitle_{lang}_url"] = f"{base}/{slug}/subtitle-{lang}.srt"
                        if lang == "tr":
                            row["missing_subtitle"] = False
                    if scr.is_file():
                        row[f"script_{lang}_url"] = f"{base}/{slug}/script-{lang}.txt"
            chapter_assets.append(row)
    else:
        for sub in sorted(folder.iterdir()):
            if not sub.is_dir() or sub.name in ("clips",):
                continue
            slug = sub.name
            if not re.match(r"^\d{2}-", slug):
                continue
            row = {"slug": slug, "title": slug, "display_title": slug}
            for lang in ("tr", "en"):
                if (sub / f"audio-{lang}.mp3").is_file():
                    row[f"audio_{lang}_url"] = f"{base}/{slug}/audio-{lang}.mp3"
                if (sub / f"subtitle-{lang}.srt").is_file():
                    row[f"subtitle_{lang}_url"] = f"{base}/{slug}/subtitle-{lang}.srt"
                if (sub / f"script-{lang}.txt").is_file():
                    row[f"script_{lang}_url"] = f"{base}/{slug}/script-{lang}.txt"
            chapter_assets.append(row)

    if chapter_assets:
        out["chapters"] = chapter_assets
        first = chapter_assets[0]
        if first.get("audio_tr_url"):
            out["audio_url"] = first["audio_tr_url"]
        if first.get("subtitle_tr_url"):
            out["subtitle_url"] = first["subtitle_tr_url"]
        if first.get("script_tr_url"):
            out["script_url"] = out.get("script_url") or first["script_tr_url"]
    else:
        if (folder / "audio-tr.mp3").is_file():
            out["audio_url"] = f"{base}/audio-tr.mp3"
        if (folder / "subtitle-tr.srt").is_file():
            out["subtitle_url"] = f"{base}/subtitle-tr.srt"
        if (folder / "audio-en.mp3").is_file():
            out["audio_en_url"] = f"{base}/audio-en.mp3"
        if (folder / "subtitle-en.srt").is_file():
            out["subtitle_en_url"] = f"{base}/subtitle-en.srt"

    clips: list[dict[str, Any]] = []
    clips_dir = folder / "clips"
    if clips_dir.is_dir():
        for p in sorted(clips_dir.iterdir()):
            if not p.is_file():
                continue
            kind = "image" if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") else "video"
            clips.append(
                {
                    "name": f"clips/{p.name}",
                    "kind": kind,
                    "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
                    "url": f"{base}/clips/{p.name}",
                }
            )
    if clips:
        out["clips"] = clips
    out["open_folder_url"] = f"/api/gallery/longform/{eid}/open-folder"
    out["folder_path"] = str(folder)
    return out


def delete_item(entry_id: str) -> bool:
    result = delete_items([entry_id])
    return bool(result.get("deleted"))


def delete_items(entry_ids: list[str]) -> dict[str, Any]:
    """Toplu uzun video silme."""
    wanted = {str(i).strip() for i in (entry_ids or []) if str(i).strip()}
    if not wanted:
        return {"deleted": [], "failed": [], "missing": []}

    items = _load_index()
    kept: list[dict[str, Any]] = []
    deleted: list[str] = []
    failed: list[dict[str, str]] = []
    seen: set[str] = set()

    for e in items:
        eid = str(e.get("id") or "")
        if eid not in wanted:
            kept.append(e)
            continue
        seen.add(eid)
        try:
            _remove_tree(entry_dir(eid))
            lf_id = (e.get("longform_id") or "").strip()
            if lf_id:
                _mark_export_deleted(lf_id)
                _remove_tree(data_dir() / "longform" / lf_id)
            deleted.append(eid)
        except Exception as exc:
            failed.append({"id": eid, "error": str(exc)[:200]})
            kept.append(e)

    missing = sorted(wanted - seen)
    if deleted:
        _save_index(kept)
    return {"deleted": deleted, "failed": failed, "missing": missing}


def open_entry_folder(entry_id: str) -> dict[str, Any] | None:
    item = get_item(entry_id)
    if not item:
        return None
    folder = entry_dir(entry_id)
    if not folder.is_dir():
        return None
    normalize_entry_layout(folder)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        from akifactory.settings_assets import _open_path

        if not _open_path(folder):
            return None
        return {"ok": True, "folder_path": str(folder.resolve())}
    except Exception:
        return None
