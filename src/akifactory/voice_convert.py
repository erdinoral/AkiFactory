"""Ses dosyasi -> RVC donusumu — kalici kayitlar (data/voice_convert)."""

from __future__ import annotations

import json
import shutil
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from akifactory.paths import voice_convert_dir
from akifactory.rvc_registry import get_voice, list_for_ui
from akifactory.rvc_tts import convert_audio_file_sync, is_rvc_available

INDEX_NAME = "index.json"
UPLOADS_DIR = "uploads"
MAX_UPLOAD_BYTES = 80 * 1024 * 1024  # 80 MB
ALLOWED_EXT = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm", ".aac", ".wma"}


def _index_path() -> Path:
    return voice_convert_dir() / INDEX_NAME


def _uploads_path() -> Path:
    d = voice_convert_dir() / UPLOADS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_index() -> list[dict[str, Any]]:
    p = _index_path()
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_index(items: list[dict[str, Any]]) -> None:
    _index_path().write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _duration_sec(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            rate = w.getframerate()
            if rate <= 0:
                return 0.0
            return round(w.getnframes() / float(rate), 1)
    except Exception:
        return 0.0


def _voice_label(voice_id: str) -> str:
    for v in list_for_ui():
        if v.get("id") == voice_id:
            return str(v.get("label") or voice_id)
    meta = get_voice(voice_id)
    return meta.label if meta else voice_id


def list_items(*, limit: int = 50) -> list[dict[str, Any]]:
    items = _load_index()
    out: list[dict[str, Any]] = []
    for e in items[: max(1, min(limit, 200))]:
        fn = e.get("filename", "")
        path = voice_convert_dir() / fn
        if not path.is_file():
            continue
        row = dict(e)
        row["size_mb"] = round(path.stat().st_size / (1024 * 1024), 2)
        row["stream_url"] = f"/api/voice/convert/{e['id']}/stream"
        row["download_url"] = f"/api/voice/convert/{e['id']}/download"
        out.append(row)
    return out


def get_item(entry_id: str) -> dict[str, Any] | None:
    for e in _load_index():
        if e.get("id") == entry_id:
            path = voice_convert_dir() / e.get("filename", "")
            if path.is_file():
                return {**e, "path": path}
    return None


def delete_item(entry_id: str) -> bool:
    items = _load_index()
    kept: list[dict[str, Any]] = []
    removed = False
    for e in items:
        if e.get("id") == entry_id:
            path = voice_convert_dir() / e.get("filename", "")
            path.unlink(missing_ok=True)
            src = e.get("source_filename")
            if src:
                (voice_convert_dir() / src).unlink(missing_ok=True)
            removed = True
        else:
            kept.append(e)
    if removed:
        _save_index(kept)
    return removed


def convert_upload(
    *,
    data: bytes,
    original_name: str,
    rvc_voice: str,
    rvc_pitch: int = 0,
    rvc_index_rate: float = 1.0,
) -> dict[str, Any]:
    if not is_rvc_available():
        raise RuntimeError(
            "RVC kullanilamiyor. models/rvc/ klasorune .pth ekleyin."
        )
    if not data:
        raise ValueError("Bos dosya")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"Dosya cok buyuk (en fazla {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)")

    voice_id = (rvc_voice or "").strip()
    if not get_voice(voice_id):
        raise ValueError("Gecersiz RVC sesi")

    safe_name = Path(original_name or "kayit").name
    ext = Path(safe_name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise ValueError(f"Desteklenmeyen format: {ext or '(uzantisiz)'}")

    entry_id = uuid.uuid4().hex[:12]
    uploads = _uploads_path()
    source_fn = f"{entry_id}_src{ext}"
    source_path = uploads / source_fn
    source_path.write_bytes(data)

    out_fn = f"{entry_id}.wav"
    out_path = voice_convert_dir() / out_fn

    convert_audio_file_sync(
        str(source_path),
        str(out_path),
        voice_id=voice_id,
        pitch=int(rvc_pitch),
        index_rate=float(rvc_index_rate),
    )

    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise RuntimeError("Donusum tamamlandi ama cikti dosyasi olusmadi")

    entry = {
        "id": entry_id,
        "original_name": safe_name,
        "source_filename": f"{UPLOADS_DIR}/{source_fn}",
        "rvc_voice": voice_id,
        "rvc_voice_label": _voice_label(voice_id),
        "rvc_pitch": int(rvc_pitch),
        "rvc_index_rate": float(rvc_index_rate),
        "filename": out_fn,
        "duration_sec": _duration_sec(out_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    items = _load_index()
    items.insert(0, entry)
    _save_index(items)

    row = dict(entry)
    row["size_mb"] = round(out_path.stat().st_size / (1024 * 1024), 2)
    row["stream_url"] = f"/api/voice/convert/{entry_id}/stream"
    row["download_url"] = f"/api/voice/convert/{entry_id}/download"
    return row
