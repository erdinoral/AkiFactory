"""Opsiyonel ozellik bayraklari — config.toml [features], varsayilan kapali."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from akifactory.paths import engine_config_file

DEFAULTS: dict[str, bool] = {
    "stock_local_failover": False,
    "estimate_api": False,
    "topic_similarity_warn": False,
    "encrypt_api_keys": False,
}


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def _load_flags() -> dict[str, bool]:
    out = dict(DEFAULTS)
    cfg = engine_config_file()
    if not cfg.is_file():
        return out
    try:
        text = cfg.read_text(encoding="utf-8")
    except Exception:
        return out
    # [features] blogundan sonra gelen key = value satirlari
    m = re.search(r"\[features\](.*?)(?=\n\[|\Z)", text, re.S)
    if not m:
        return out
    block = m.group(1)
    for key in DEFAULTS:
        km = re.search(rf"^{re.escape(key)}\s*=\s*(\w+)", block, re.M)
        if km:
            out[key] = _parse_bool(km.group(1))
    return out


def reload() -> None:
    _load_flags.cache_clear()


def is_enabled(name: str) -> bool:
    flags = _load_flags()
    return bool(flags.get(name, DEFAULTS.get(name, False)))


def all_flags() -> dict[str, bool]:
    return dict(_load_flags())


def for_ui() -> dict[str, Any]:
    return {"features": all_flags()}
