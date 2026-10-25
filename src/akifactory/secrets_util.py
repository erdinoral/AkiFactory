"""Opsiyonel API anahtari sifreleme — Fernet, data/.secrets_key."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any

from akifactory.paths import data_dir

KEY_FILE = ".secrets_key"
ENC_PREFIX = "enc:v1:"


def _key_path() -> Path:
    return data_dir() / KEY_FILE


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise RuntimeError(
            "cryptography paketi yok — encrypt_api_keys icin: pip install cryptography"
        ) from exc
    path = _key_path()
    if path.is_file():
        raw = path.read_bytes().strip()
    else:
        raw = Fernet.generate_key()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        try:
            path.chmod(0o600)
        except Exception:
            pass
    return Fernet(raw)


def is_encrypted_value(value: str) -> bool:
    return (value or "").startswith(ENC_PREFIX)


def encrypt_str(plain: str) -> str:
    p = (plain or "").strip()
    if not p or is_encrypted_value(p):
        return p
    token = _fernet().encrypt(p.encode("utf-8")).decode("ascii")
    return ENC_PREFIX + token


def decrypt_str(value: str) -> str:
    v = (value or "").strip()
    if not is_encrypted_value(v):
        return v
    token = v[len(ENC_PREFIX) :].encode("ascii")
    return _fernet().decrypt(token).decode("utf-8")


def maybe_encrypt_fields(data: dict[str, Any], *, enabled: bool) -> dict[str, Any]:
    out = dict(data)
    if not enabled:
        return out
    for key in ("pexels_key", "pixabay_key"):
        val = out.get(key)
        if isinstance(val, str) and val.strip() and not is_encrypted_value(val):
            out[key] = encrypt_str(val)
    return out


def maybe_decrypt_fields(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    for key in ("pexels_key", "pixabay_key"):
        val = out.get(key)
        if isinstance(val, str) and is_encrypted_value(val):
            try:
                out[key] = decrypt_str(val)
            except Exception:
                out[key] = ""
    return out
