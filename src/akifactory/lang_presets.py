"""Turkce / Ingilizce uretim ses ve altyazi hazir ayarlari."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from akifactory.paths import data_dir

SUPPORTED = frozenset({"tr", "en"})
PRESETS_FILE = data_dir() / "lang_presets.json"

DEFAULTS: dict[str, dict[str, Any]] = {
    "tr": {
        "tts_engine": "rvc",
        "edge_voice": "tr-TR-EmelNeural-Female",
        "rvc_voice": None,
        "rvc_pitch": 0,
        "rvc_index_rate": 1.0,
        "voice_rate": 1.08,
        "subtitle_style_id": "tiktok_classic",
    },
    "en": {
        "tts_engine": "rvc",
        "edge_voice": "en-US-JennyNeural-Female",
        "rvc_voice": None,
        "rvc_pitch": 0,
        "rvc_index_rate": 1.0,
        "voice_rate": 1.08,
        "subtitle_style_id": "tiktok_classic",
    },
}


def _load_raw() -> dict[str, Any]:
    if not PRESETS_FILE.is_file():
        return {}
    try:
        data = json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_raw(data: dict[str, Any]) -> None:
    PRESETS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _merge_defaults(lang_id: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    base = deepcopy(DEFAULTS.get(lang_id, {}))
    if raw:
        for k, v in raw.items():
            if v is not None and k in base:
                base[k] = v
    return base


def get(lang_id: str) -> dict[str, Any]:
    key = (lang_id or "tr").strip().lower()
    if key not in SUPPORTED:
        key = "tr"
    raw = _load_raw().get(key) or {}
    return _merge_defaults(key, raw if isinstance(raw, dict) else None)


def get_all() -> dict[str, dict[str, Any]]:
    raw = _load_raw()
    return {lid: _merge_defaults(lid, raw.get(lid) if isinstance(raw.get(lid), dict) else None) for lid in SUPPORTED}


def save(lang_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    key = (lang_id or "").strip().lower()
    if key not in SUPPORTED:
        raise ValueError("Dil: tr veya en")
    allowed = set(DEFAULTS[key].keys())
    cleaned: dict[str, Any] = {}
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "rvc_voice" and v in ("", None):
            cleaned[k] = None
        elif k in ("rvc_pitch",):
            cleaned[k] = max(-12, min(12, int(v)))
        elif k in ("rvc_index_rate", "voice_rate"):
            cleaned[k] = float(v)
        elif k == "tts_engine" and str(v).lower() in ("edge", "rvc"):
            cleaned[k] = str(v).lower()
        elif v is not None:
            cleaned[k] = v
    data = _load_raw()
    merged = _merge_defaults(key, data.get(key) if isinstance(data.get(key), dict) else None)
    merged.update(cleaned)
    data[key] = {k: merged[k] for k in allowed}
    _save_raw(data)
    return merged


def list_for_ui() -> dict[str, dict[str, Any]]:
    return get_all()
