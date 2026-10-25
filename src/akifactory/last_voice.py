"""Son kullanilan ses ayarlari (Electron + tarayici senkronu).

Duz alanlar geriye uyumlu; platform bazli tercihler ``per_platform`` altinda.
"""

from __future__ import annotations

import json
from typing import Any

from akifactory.paths import data_dir

FILE = "last_voice.json"
_VOICE_KEYS = (
    "tts_engine",
    "edge_voice",
    "rvc_voice",
    "rvc_pitch",
    "rvc_index_rate",
)


def _normalize_voice(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in _VOICE_KEYS:
        if key in data and data[key] is not None:
            out[key] = data[key]
    if out.get("tts_engine") in ("f5", "xtts", "voxcpm", "piper", "chattts"):
        out["tts_engine"] = "rvc" if out.get("rvc_voice") else "edge"
    pitch = out.get("rvc_pitch")
    if pitch is not None:
        try:
            p = int(pitch)
            out["rvc_pitch"] = 0 if abs(p) > 3 else p
        except (TypeError, ValueError):
            out["rvc_pitch"] = 0
    ir = out.get("rvc_index_rate")
    if ir is not None:
        try:
            rate = float(ir)
            if rate > 0.85:
                out["rvc_index_rate"] = 0.78
        except (TypeError, ValueError):
            pass
    return out


def _load_file() -> dict[str, Any]:
    p = data_dir() / FILE
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_file(data: dict[str, Any]) -> None:
    p = data_dir() / FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get(platform: str | None = None) -> dict[str, Any]:
    data = _load_file()
    plat = (platform or "").strip()
    per = data.get("per_platform") if isinstance(data.get("per_platform"), dict) else {}
    if plat and plat in per and isinstance(per[plat], dict):
        merged = {k: data[k] for k in _VOICE_KEYS if k in data}
        merged.update(per[plat])
        return _normalize_voice(merged)
    return _normalize_voice(data)


def save(data: dict[str, Any], *, platform: str | None = None) -> dict[str, Any]:
    existing = _load_file()
    voice = _normalize_voice(data)
    plat = (platform or "").strip()
    if plat:
        per = existing.get("per_platform") if isinstance(existing.get("per_platform"), dict) else {}
        per = dict(per)
        per[plat] = voice
        existing["per_platform"] = per
        # Global son tercih de guncelle (geriye uyum)
        existing.update(voice)
        _write_file(existing)
        return voice
    out = dict(existing)
    # per_platform koru
    per = out.get("per_platform") if isinstance(out.get("per_platform"), dict) else {}
    out = dict(voice)
    if per:
        out["per_platform"] = per
    _write_file(out)
    return voice
