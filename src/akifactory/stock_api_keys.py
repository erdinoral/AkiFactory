"""Pexels / Pixabay API anahtarlari — data/api_keys.json + config.toml senkronu."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import httpx

from akifactory.paths import data_dir, engine_config_file

CONFIG_FILE = data_dir() / "api_keys.json"

PEXELS_SIGNUP_URL = "https://www.pexels.com/api/new/"
PEXELS_DOCS_URL = "https://www.pexels.com/api/documentation/"
PIXABAY_DOCS_URL = "https://pixabay.com/api/docs/"
# Motor config.example.toml ornek anahtarlari — gercek degil
_PLACEHOLDER_STOCK_KEYS = frozenset(
    {
        "123adsf4567adf89",
        "abd1321cd13efgfdfhi",
    }
)
PIXABAY_VIDEO_MIN_PER_PAGE = 3


def _pixabay_key_issue(key: str) -> str | None:
    k = (key or "").strip()
    if not k:
        return "Pixabay API anahtari bos — Ayarlar → API'ler'den gercek anahtari kaydedin"
    if k in _PLACEHOLDER_STOCK_KEYS:
        return (
            "Ornek/placeholder anahtar kayitli (gecersiz). "
            "pixabay.com/api/docs sayfasindan kendi anahtarinizi kopyalayin"
        )
    return None


def _http_error_detail(response: httpx.Response) -> str:
    try:
        body = (response.text or "").strip()
        if body:
            if body.startswith("[ERROR"):
                return body
            data = response.json()
            if isinstance(data, dict):
                for field in ("error", "message", "errors"):
                    val = data.get(field)
                    if val:
                        return str(val)
    except Exception:
        pass
    return f"HTTP {response.status_code}"


def _load_raw() -> dict[str, Any]:
    if not CONFIG_FILE.is_file():
        return {}
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        from akifactory import secrets_util

        return secrets_util.maybe_decrypt_fields(raw)
    except Exception:
        return {}


def _save_raw(data: dict[str, Any]) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    try:
        from akifactory import features_util
        from akifactory import secrets_util

        if features_util.is_enabled("encrypt_api_keys"):
            payload = secrets_util.maybe_encrypt_fields(payload, enabled=True)
    except Exception:
        pass
    CONFIG_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def get_saved_pexels_key() -> str:
    return (_load_raw().get("pexels_key") or "").strip()


def get_saved_pixabay_key() -> str:
    return (_load_raw().get("pixabay_key") or "").strip()


def get_pexels_key() -> str:
    saved = get_saved_pexels_key()
    if saved:
        return saved
    return os.environ.get("AKI_PEXELS_KEY", "").strip()


def get_pixabay_key() -> str:
    saved = get_saved_pixabay_key()
    if saved:
        return saved
    return os.environ.get("AKI_PIXABAY_KEY", "").strip()


def _mask_key(key: str) -> str:
    k = (key or "").strip()
    if len(k) > 12:
        return k[:6] + "…" + k[-4:]
    if k:
        return "••••"
    return ""


def get_settings_public() -> dict[str, Any]:
    saved_p = get_saved_pexels_key()
    saved_x = get_saved_pixabay_key()
    eff_p = get_pexels_key()
    eff_x = get_pixabay_key()
    return {
        "pexels_key_masked": _mask_key(eff_p),
        "pixabay_key_masked": _mask_key(eff_x),
        "has_pexels_key": bool(eff_p),
        "has_pixabay_key": bool(eff_x),
        "pexels_saved": bool(saved_p),
        "pixabay_saved": bool(saved_x),
        "pexels_configured": bool(eff_p),
        "pixabay_configured": bool(eff_x),
        "pexels_from_env": bool(not saved_p and os.environ.get("AKI_PEXELS_KEY", "").strip()),
        "pixabay_from_env": bool(not saved_x and os.environ.get("AKI_PIXABAY_KEY", "").strip()),
    }


def get_api_guide() -> dict[str, Any]:
    """UI icin API alma rehberi — linkler ve adimlar."""
    return {
        "pexels": {
            "name": "Pexels",
            "signup_url": PEXELS_SIGNUP_URL,
            "docs_url": PEXELS_DOCS_URL,
            "limits": "Ucretsiz: ~200 istek/saat, 20.000 istek/ay (anahtar basina)",
            "steps": [
                "pexels.com/api/new adresine git",
                "Ucretsiz hesap olustur veya giris yap",
                "Formu doldur (proje adi: AkiFactory / kisisel kullanim yeterli)",
                "E-posta ile gelen API anahtarini kopyala",
                "Asagidaki Pexels kutusuna yapistir → Kaydet → Test et",
            ],
        },
        "pixabay": {
            "name": "Pixabay",
            "signup_url": "https://pixabay.com/accounts/register/",
            "docs_url": PIXABAY_DOCS_URL,
            "limits": "Ucretsiz: ~100 istek / 60 saniye (anahtar basina)",
            "steps": [
                "pixabay.com uzerinde ucretsiz hesap ac",
                "pixabay.com/api/docs sayfasina git (giris yapili olmali)",
                "Sayfanin ustundeki ornek kodda senin API anahtarin gorunur",
                "Anahtari kopyala (rakam ve harfler, tireli uzun metin)",
                "Pixabay kutusuna yapistir → Kaydet → Test et",
            ],
        },
        "notes": [
            "Her kullanici kendi ucretsiz anahtarini almali — paylasilan anahtar kota biter.",
            "Anahtarlar yalnizca bu bilgisayarda data/api_keys.json icinde saklanir; kurulum paketine girmez.",
            "Motor calisirken anahtarlar data/engine.toml dosyasina kopyalanir; paketleme oncesi temizlenir.",
            "Iki servis de ucretsiz; kredi karti gerekmez.",
        ],
    }


def update_settings(
    *,
    pexels_key: str | None = None,
    pixabay_key: str | None = None,
) -> dict[str, Any]:
    data = _load_raw()
    if pexels_key is not None:
        data["pexels_key"] = pexels_key.strip()
    if pixabay_key is not None:
        data["pixabay_key"] = pixabay_key.strip()
    _save_raw(data)
    sync_engine_config()
    return get_settings_public()


def _patch_toml_array(text: str, field: str, keys: list[str]) -> str:
    arr = ", ".join(f'"{k}"' for k in keys if k)
    replacement = f"{field} = [{arr}]"
    if re.search(rf"^{field}\s*=", text, re.M):
        return re.sub(rf"^{field}\s*=\s*\[[^\]]*\]", replacement, text, count=1, flags=re.M)
    return text + f"\n{replacement}\n"


def clear_engine_stock_keys() -> bool:
    """Paketleme oncesi — config.toml icindeki stok API anahtarlarini temizle."""
    target = engine_config_file()
    if not target.is_file():
        return False
    text = target.read_text(encoding="utf-8")
    text = _patch_toml_array(text, "pexels_api_keys", [])
    text = _patch_toml_array(text, "pixabay_api_keys", [])
    target.write_text(text, encoding="utf-8")
    return True


def sync_engine_config() -> bool:
    target = engine_config_file()
    if not target.is_file():
        return False
    p = get_pexels_key()
    x = get_pixabay_key()
    text = target.read_text(encoding="utf-8")
    text = _patch_toml_array(text, "pexels_api_keys", [p] if p else [])
    text = _patch_toml_array(text, "pixabay_api_keys", [x] if x else [])
    target.write_text(text, encoding="utf-8")
    return True


async def test_pexels(key: str | None = None) -> dict[str, Any]:
    k = (key or get_pexels_key()).strip()
    if not k:
        return {"ok": False, "error": "Pexels API key bos — once anahtar alip kaydedin"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                "https://api.pexels.com/videos/search",
                params={"query": "nature", "per_page": 1},
                headers={"Authorization": k},
            )
        if r.status_code == 200:
            remaining = r.headers.get("X-Ratelimit-Remaining", "")
            limit = r.headers.get("X-Ratelimit-Limit", "")
            reset = r.headers.get("X-Ratelimit-Reset", "")
            out: dict[str, Any] = {"ok": True, "count": len(r.json().get("videos") or [])}
            if remaining:
                out["rate_remaining"] = remaining
            if limit:
                out["rate_limit"] = limit
            if reset:
                out["rate_reset"] = reset
            return out
        return {"ok": False, "error": f"Pexels HTTP {r.status_code}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def test_pixabay(key: str | None = None) -> dict[str, Any]:
    k = (key or get_pixabay_key()).strip()
    issue = _pixabay_key_issue(k)
    if issue:
        return {"ok": False, "error": issue}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                "https://pixabay.com/api/videos/",
                params={"key": k, "q": "nature", "per_page": PIXABAY_VIDEO_MIN_PER_PAGE},
            )
        if r.status_code == 200:
            return {"ok": True, "count": len(r.json().get("hits") or [])}
        return {"ok": False, "error": _http_error_detail(r)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _parse_int_header(val: str | None) -> int | None:
    if val is None:
        return None
    s = str(val).strip()
    if s.isdigit():
        return int(s)
    return None


async def fetch_quota() -> dict[str, Any]:
    """Pexels/Pixabay kota bilgisi — hafif test istegi."""
    out: dict[str, Any] = {"pexels": None, "pixabay": None}
    p_key = get_pexels_key()
    x_key = get_pixabay_key()
    if p_key:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    "https://api.pexels.com/videos/search",
                    params={"query": "nature", "per_page": 1},
                    headers={"Authorization": p_key},
                )
            remaining = _parse_int_header(r.headers.get("X-Ratelimit-Remaining"))
            limit = _parse_int_header(r.headers.get("X-Ratelimit-Limit"))
            reset = _parse_int_header(r.headers.get("X-Ratelimit-Reset"))
            out["pexels"] = {
                "ok": r.status_code == 200,
                "remaining": remaining,
                "limit": limit,
                "reset_at": reset,
                "error": None if r.status_code == 200 else f"HTTP {r.status_code}",
            }
        except Exception as exc:
            out["pexels"] = {"ok": False, "error": str(exc)}
    if x_key:
        issue = _pixabay_key_issue(x_key)
        if issue:
            out["pixabay"] = {"ok": False, "error": issue}
        else:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    r = await client.get(
                        "https://pixabay.com/api/videos/",
                        params={"key": x_key, "q": "nature", "per_page": PIXABAY_VIDEO_MIN_PER_PAGE},
                    )
                out["pixabay"] = {
                    "ok": r.status_code == 200,
                    "limit_per_minute": 100,
                    "note": "Pixabay API kota basliginda donmeyebilir",
                    "error": None if r.status_code == 200 else _http_error_detail(r),
                }
            except Exception as exc:
                out["pixabay"] = {"ok": False, "error": str(exc)}
    return out
