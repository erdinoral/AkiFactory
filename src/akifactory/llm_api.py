"""Coklu LLM saglayici — Ollama (varsayilan) + OpenAI / NVIDIA / Gemini / Grok / Claude.

Anahtarlar: data/llm_settings.json (kurulum paketine girmez).
Senaryo/chat yolu ollama_util.chat uzerinden buraya yonlenir.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx

from akifactory.paths import data_dir

SETTINGS_FILE = data_dir() / "llm_settings.json"
# Anahtardan cekilen model listeleri; anahtarin kendisi degil yalnizca kisa ozeti saklanir
MODELS_CACHE_FILE = data_dir() / "llm_models_cache.json"

PROVIDERS = ("ollama", "openai", "nvidia", "gemini", "grok", "claude")
NVIDIA_API_BASE = "https://integrate.api.nvidia.com/v1"
GROK_API_BASE = "https://api.x.ai/v1"

OPENAI_MODELS = ("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1", "o4-mini")
NVIDIA_MODELS = (
    "meta/llama-3.3-70b-instruct",
    "meta/llama-3.1-70b-instruct",
    "meta/llama-3.1-8b-instruct",
    "google/gemma-2-9b-it",
    "mistralai/mistral-nemo-12b-instruct",
)
# 2.5 / 2.0 / 1.5 artik eski — yeni anahtarlarda 404 verebilir
GEMINI_MODELS = (
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
)
GEMINI_MODEL_ALIASES = {
    "gemini-2.5-flash": "gemini-3.6-flash",
    "gemini-2.5-flash-lite": "gemini-3.5-flash-lite",
    "gemini-2.5-pro": "gemini-3.5-flash",
    "gemini-2.0-flash": "gemini-3.6-flash",
    "gemini-2.0-flash-lite": "gemini-3.5-flash-lite",
    "gemini-1.5-flash": "gemini-3.6-flash",
    "gemini-1.5-pro": "gemini-3.5-flash",
    "gemini-3.5-lite": "gemini-3.5-flash-lite",
}
GROK_MODELS = ("grok-3-mini", "grok-3", "grok-2-latest")
CLAUDE_MODELS = (
    "claude-sonnet-4-20250514",
    "claude-3-5-haiku-latest",
    "claude-3-5-sonnet-latest",
)

KEY_FIELDS = (
    "openai_api_key",
    "nvidia_api_key",
    "gemini_api_key",
    "grok_api_key",
    "claude_api_key",
)

DEFAULT_SETTINGS: dict[str, Any] = {
    "provider": "ollama",
    "openai_api_key": "",
    "nvidia_api_key": "",
    "gemini_api_key": "",
    "grok_api_key": "",
    "claude_api_key": "",
    "openai_model": OPENAI_MODELS[0],
    "nvidia_model": NVIDIA_MODELS[0],
    "gemini_model": GEMINI_MODELS[0],
    "grok_model": GROK_MODELS[0],
    "claude_model": CLAUDE_MODELS[0],
}


KEY_FIELD_BY_PROVIDER = {
    "openai": "openai_api_key",
    "nvidia": "nvidia_api_key",
    "gemini": "gemini_api_key",
    "grok": "grok_api_key",
    "claude": "claude_api_key",
}
MODEL_FIELD_BY_PROVIDER = {p: f"{p}_model" for p in KEY_FIELD_BY_PROVIDER}
STATIC_MODELS = {
    "openai": OPENAI_MODELS,
    "nvidia": NVIDIA_MODELS,
    "gemini": GEMINI_MODELS,
    "grok": GROK_MODELS,
    "claude": CLAUDE_MODELS,
}
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Sohbet disi modeller (embedding, ses, gorsel, moderasyon...) listeye girmez
_NON_CHAT_RE = re.compile(
    r"embed|rerank|tts|audio|realtime|transcri|whisper|dall-e|image|imagen|veo|moderation|"
    r"search|guard|safety|reward|clip|parse|retriev|aqa|live|computer-use|robotics|"
    r"babbage|davinci|-ocr|deplot|kosmos|vila|neva|banana",
    re.I,
)


def _key_fp(key: str) -> str:
    return hashlib.sha256((key or "").strip().encode("utf-8")).hexdigest()[:12]


def _load_models_cache() -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(MODELS_CACHE_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


_models_cache: dict[str, dict[str, Any]] = _load_models_cache()


def _save_models_cache() -> None:
    try:
        MODELS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        MODELS_CACHE_FILE.write_text(
            json.dumps(_models_cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def _provider_key(provider: str, cfg: dict[str, Any] | None = None) -> str:
    field = KEY_FIELD_BY_PROVIDER.get(provider, "")
    if not field:
        return ""
    return ((cfg or load_settings()).get(field) or "").strip()


def cached_models(provider: str, cfg: dict[str, Any] | None = None) -> list[str]:
    """Kayitli anahtarla daha once cekilmis canli liste (anahtar degistiyse bos)."""
    ent = _models_cache.get(provider) or {}
    models = ent.get("models") or []
    if not models or ent.get("fp") != _key_fp(_provider_key(provider, cfg)):
        return []
    return [str(m) for m in models]


def _mask(key: str) -> str:
    k = (key or "").strip()
    if not k:
        return ""
    if len(k) <= 8:
        return "••••"
    return f"{k[:4]}…{k[-4:]}"


def _normalize_gemini_model(model: str | None) -> str:
    name = (model or "").strip().replace("models/", "")
    if not name:
        return GEMINI_MODELS[0]
    if name in ((_models_cache.get("gemini") or {}).get("models") or []):
        return name
    return GEMINI_MODEL_ALIASES.get(name, name)


def _is_nvidia_key(key: str) -> bool:
    return (key or "").strip().lower().startswith("nvapi-")


def _migrate_keys(cfg: dict[str, Any]) -> bool:
    changed = False
    oa = (cfg.get("openai_api_key") or "").strip()
    nv = (cfg.get("nvidia_api_key") or "").strip()
    if oa and _is_nvidia_key(oa):
        if not nv:
            cfg["nvidia_api_key"] = oa
        cfg["openai_api_key"] = ""
        if (cfg.get("provider") or "").lower() == "openai":
            cfg["provider"] = "nvidia"
        changed = True
    if (cfg.get("provider") or "").lower() == "openai" and not oa and nv:
        cfg["provider"] = "nvidia"
        changed = True
    return changed


def load_settings() -> dict[str, Any]:
    cfg = dict(DEFAULT_SETTINGS)
    env_map = {
        "openai_api_key": ("OPENAI_API_KEY",),
        "nvidia_api_key": ("NVIDIA_API_KEY", "NVAPI_API_KEY"),
        "gemini_api_key": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "grok_api_key": ("XAI_API_KEY", "GROK_API_KEY"),
        "claude_api_key": ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY"),
    }
    for field, envs in env_map.items():
        for e in envs:
            val = (os.environ.get(e) or "").strip()
            if val:
                cfg[field] = val
                break
    migrated = False
    try:
        if SETTINGS_FILE.is_file():
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k in DEFAULT_SETTINGS:
                    if k in raw:
                        cfg[k] = raw[k]
    except Exception:
        pass
    if _migrate_keys(cfg):
        migrated = True
    old_g = (cfg.get("gemini_model") or "").strip()
    new_g = _normalize_gemini_model(old_g)
    if new_g != old_g:
        cfg["gemini_model"] = new_g
        migrated = True
    prov = (cfg.get("provider") or "ollama").strip().lower()
    if prov not in PROVIDERS:
        prov = "ollama"
    cfg["provider"] = prov
    if migrated:
        try:
            save_settings(cfg, merge=False)
        except Exception:
            pass
    return cfg


def save_settings(patch: dict[str, Any], *, merge: bool = True) -> dict[str, Any]:
    cfg = load_settings() if merge else dict(DEFAULT_SETTINGS)
    if not merge:
        cfg.update({k: patch.get(k, DEFAULT_SETTINGS[k]) for k in DEFAULT_SETTINGS})
    else:
        for k, v in patch.items():
            if k not in DEFAULT_SETTINGS:
                continue
            if k in KEY_FIELDS and (
                v is None or str(v).strip() in ("", "••••", "keep", "__keep__")
            ):
                continue
            cfg[k] = v.strip() if isinstance(v, str) else v
    prov = (cfg.get("provider") or "ollama").strip().lower()
    if prov not in PROVIDERS:
        prov = "ollama"
    cfg["provider"] = prov
    _migrate_keys(cfg)
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return cfg


def active_provider() -> str:
    return (load_settings().get("provider") or "ollama").strip().lower()


def is_cloud() -> bool:
    return active_provider() != "ollama"


def provider_key_set(provider: str | None = None) -> bool:
    p = (provider or active_provider()).strip().lower()
    if p == "ollama":
        return True
    cfg = load_settings()
    field = {
        "openai": "openai_api_key",
        "nvidia": "nvidia_api_key",
        "gemini": "gemini_api_key",
        "grok": "grok_api_key",
        "claude": "claude_api_key",
    }.get(p)
    if not field:
        return False
    return bool((cfg.get(field) or "").strip())


def models_for_provider(provider: str | None = None, cfg: dict[str, Any] | None = None) -> list[str]:
    p = (provider or active_provider()).strip().lower()
    return cached_models(p, cfg) or list(STATIC_MODELS.get(p) or ())


def _order_models(provider: str, ids: list[str]) -> list[str]:
    """Bilinen onerilenler once, kalanlar yeni surum ustte."""
    uniq = list(dict.fromkeys(i for i in ids if i))
    preferred = [m for m in STATIC_MODELS.get(provider, ()) if m in uniq]

    def version(mid: str) -> tuple[float, ...]:
        return tuple(float(x) for x in re.findall(r"\d+(?:\.\d+)?", mid.split("/")[-1])[:2])

    rest = sorted((m for m in uniq if m not in preferred), key=lambda m: (version(m), m), reverse=True)
    return preferred + rest


def _chat_model_ids(provider: str, ids: list[str]) -> list[str]:
    out = [i for i in ids if i and not _NON_CHAT_RE.search(i)]
    if provider == "openai":
        out = [i for i in out if i.startswith(("gpt-", "o1", "o3", "o4", "o5", "chatgpt"))]
    elif provider == "gemini":
        out = [i for i in out if i.startswith("gemini")]
    return _order_models(provider, out)


async def _list_remote_models(provider: str, key: str) -> list[str]:
    async with httpx.AsyncClient(timeout=20.0) as c:
        if provider == "gemini":
            ids: list[str] = []
            token = ""
            for _ in range(5):
                params: dict[str, Any] = {"pageSize": 1000}
                if token:
                    params["pageToken"] = token
                r = await c.get(
                    f"{GEMINI_API_BASE}/models", params=params, headers={"x-goog-api-key": key}
                )
                if r.status_code >= 400:
                    raise RuntimeError(_http_err(r, label="Gemini"))
                data = r.json()
                for m in data.get("models") or []:
                    if "generateContent" in (m.get("supportedGenerationMethods") or []):
                        ids.append(str(m.get("name") or "").replace("models/", ""))
                token = data.get("nextPageToken") or ""
                if not token:
                    break
            return ids
        if provider == "claude":
            r = await c.get(
                "https://api.anthropic.com/v1/models",
                params={"limit": 100},
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            )
        else:
            base = {
                "openai": "https://api.openai.com/v1",
                "nvidia": NVIDIA_API_BASE,
                "grok": GROK_API_BASE,
            }[provider]
            r = await c.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"})
        if r.status_code >= 400:
            raise RuntimeError(_http_err(r, label=provider))
        return [str(m.get("id")) for m in r.json().get("data") or [] if m.get("id")]


async def fetch_models(provider: str | None = None, key: str | None = None) -> dict[str, Any]:
    """Anahtarin eristigi sohbet modellerini saglayicidan cek; olmazsa onbellek / sabit liste."""
    p = (provider or active_provider()).strip().lower()
    if p not in KEY_FIELD_BY_PROVIDER:
        return {"ok": False, "provider": p, "models": [], "source": "none", "detail": "Ollama icin Ollama modelleri kullanilir"}
    k = (key or "").strip() or _provider_key(p)
    current = (load_settings().get(MODEL_FIELD_BY_PROVIDER[p]) or "").strip()
    if not k:
        return {
            "ok": False,
            "provider": p,
            "models": list(STATIC_MODELS[p]),
            "current": current,
            "source": "static",
            "detail": "Anahtar yok — once API anahtarini gir",
        }
    try:
        models = _chat_model_ids(p, await _list_remote_models(p, k))
    except Exception as e:
        fallback = cached_models(p) if not key else []
        return {
            "ok": False,
            "provider": p,
            "models": fallback or list(STATIC_MODELS[p]),
            "current": current,
            "source": "cache" if fallback else "static",
            "detail": str(e)[:280] or type(e).__name__,
        }
    if not models:
        return {
            "ok": False,
            "provider": p,
            "models": list(STATIC_MODELS[p]),
            "current": current,
            "source": "static",
            "detail": "Anahtar gecerli ama sohbet modeli bulunamadi",
        }
    _models_cache[p] = {"fp": _key_fp(k), "models": models, "ts": int(time.time())}
    _save_models_cache()
    return {"ok": True, "provider": p, "models": models, "current": current, "source": "live", "detail": "ok"}


def writer_models_for_ui() -> list[dict[str, str | bool]]:
    """Uretim sekmesi yazar modeli listesi — bulut veya Ollama."""
    p = active_provider()
    if p == "ollama":
        return []
    current = resolve_model()
    labels = {
        "gemini-3.6-flash": "Gemini 3.6 Flash (onerilen)",
        "gemini-3.5-flash-lite": "Gemini 3.5 Flash Lite",
        "gemini-3.5-flash": "Gemini 3.5 Flash",
        "gemini-3.1-flash-lite": "Gemini 3.1 Flash Lite",
        "gpt-4o-mini": "GPT-4o mini",
        "gpt-4o": "GPT-4o",
        "gpt-4.1-mini": "GPT-4.1 mini",
        "gpt-4.1": "GPT-4.1",
        "o4-mini": "o4-mini",
    }
    out: list[dict[str, str | bool]] = []
    for mid in models_for_provider(p):
        out.append(
            {
                "id": mid,
                "profile_id": mid,
                "label": labels.get(mid) or mid,
                "available": True,
                "provider": p,
            }
        )
    # Kayitli model listede yoksa ekle (alias / ozel)
    if current and not any(m["id"] == current for m in out):
        out.insert(
            0,
            {
                "id": current,
                "profile_id": current,
                "label": f"{current} (aktif)",
                "available": True,
                "provider": p,
            },
        )
    return out


def set_provider_model(model_id: str) -> dict[str, Any]:
    """Aktif saglayicinin model alanini guncelle (yazar modeli ile senkron)."""
    mid = (model_id or "").strip()
    if not mid:
        return load_settings()
    p = active_provider()
    field = {
        "openai": "openai_model",
        "nvidia": "nvidia_model",
        "gemini": "gemini_model",
        "grok": "grok_model",
        "claude": "claude_model",
    }.get(p)
    if not field:
        return load_settings()
    if p == "gemini":
        mid = _normalize_gemini_model(mid)
    return save_settings({field: mid})


def public_settings() -> dict[str, Any]:
    cfg = load_settings()
    p = cfg.get("provider") or "ollama"
    pub = {
        "provider": p,
        "providers": list(PROVIDERS),
        "openai_model": cfg.get("openai_model") or OPENAI_MODELS[0],
        "nvidia_model": cfg.get("nvidia_model") or NVIDIA_MODELS[0],
        "gemini_model": _normalize_gemini_model(
            cfg.get("gemini_model") or GEMINI_MODELS[0]
        ),
        "grok_model": cfg.get("grok_model") or GROK_MODELS[0],
        "claude_model": cfg.get("claude_model") or CLAUDE_MODELS[0],
        "openai_api_key_set": bool((cfg.get("openai_api_key") or "").strip()),
        "nvidia_api_key_set": bool((cfg.get("nvidia_api_key") or "").strip()),
        "gemini_api_key_set": bool((cfg.get("gemini_api_key") or "").strip()),
        "grok_api_key_set": bool((cfg.get("grok_api_key") or "").strip()),
        "claude_api_key_set": bool((cfg.get("claude_api_key") or "").strip()),
        "openai_api_key_masked": _mask(cfg.get("openai_api_key") or ""),
        "nvidia_api_key_masked": _mask(cfg.get("nvidia_api_key") or ""),
        "gemini_api_key_masked": _mask(cfg.get("gemini_api_key") or ""),
        "grok_api_key_masked": _mask(cfg.get("grok_api_key") or ""),
        "claude_api_key_masked": _mask(cfg.get("claude_api_key") or ""),
        **{f"{prov}_models": models_for_provider(prov, cfg) for prov in STATIC_MODELS},
        **{f"{prov}_models_live": bool(cached_models(prov, cfg)) for prov in STATIC_MODELS},
        "active_model": resolve_model() if p != "ollama" else "",
        "key_set": provider_key_set(p),
        "writer_models": writer_models_for_ui() if p != "ollama" else [],
    }
    return pub


def resolve_model(preferred: str | None = None) -> str:
    cfg = load_settings()
    p = active_provider()
    defaults = {
        "openai": (cfg.get("openai_model") or OPENAI_MODELS[0], OPENAI_MODELS),
        "nvidia": (cfg.get("nvidia_model") or NVIDIA_MODELS[0], NVIDIA_MODELS),
        "gemini": (
            _normalize_gemini_model(cfg.get("gemini_model") or GEMINI_MODELS[0]),
            GEMINI_MODELS,
        ),
        "grok": (cfg.get("grok_model") or GROK_MODELS[0], GROK_MODELS),
        "claude": (cfg.get("claude_model") or CLAUDE_MODELS[0], CLAUDE_MODELS),
    }
    if p in defaults:
        default, known = defaults[p]
        known = tuple(known) + tuple(cached_models(p, cfg))
        pref = (preferred or "").strip()
        if not pref:
            return str(default).strip()
        # Ollama etiketleri (qwen3.5:9b) buluta gonderme
        if pref in known or pref.startswith(
            ("gpt-", "o1", "o3", "o4", "claude", "gemini", "grok", "meta/", "google/", "mistral", "nvidia/")
        ):
            return pref
        return str(default).strip()
    if preferred and preferred.strip():
        return preferred.strip()
    from akifactory.ollama_util import get_config_model

    return (get_config_model() or "qwen3.5:9b").strip()


def _http_err(r: httpx.Response, *, label: str = "") -> str:
    prefix = f"{label} " if label else ""
    try:
        data = r.json()
        err = data.get("error")
        if isinstance(err, dict):
            return f"{prefix}HTTP {r.status_code}: {err.get('message') or err}"[:400]
        if isinstance(err, str):
            return f"{prefix}HTTP {r.status_code}: {err}"[:400]
        if data.get("detail"):
            return f"{prefix}HTTP {r.status_code}: {data.get('detail')}"[:400]
        return f"{prefix}HTTP {r.status_code}: {str(data)[:280]}"
    except Exception:
        return f"{prefix}HTTP {r.status_code}: {(r.text or '')[:280]}"


async def ensure_ready(*, probe_ollama: bool = False) -> tuple[bool, str, dict[str, Any]]:
    """(ok, error_message, status_dict). Bulut: key yeterli; Ollama: servis acik olmali."""
    p = active_provider()
    if p == "ollama":
        from akifactory import ollama_util

        st = await ollama_util.fetch_status(probe=probe_ollama)
        if not st.get("running"):
            return False, "Ollama calismiyor. Terminalde: ollama serve", st
        return True, "", st

    cfg = load_settings()
    key_map = {
        "openai": "openai_api_key",
        "nvidia": "nvidia_api_key",
        "gemini": "gemini_api_key",
        "grok": "grok_api_key",
        "claude": "claude_api_key",
    }
    field = key_map.get(p, "")
    key = (cfg.get(field) or "").strip() if field else ""
    if not key:
        return (
            False,
            f"{p} API anahtari yok — Ayarlar → API'ler → LLM API",
            {"provider": p, "running": False},
        )
    return True, "", {
        "provider": p,
        "running": True,
        "models": [],
        "model_ok": True,
        "model_name": resolve_model(),
        "cloud": True,
    }


async def test_provider() -> dict[str, Any]:
    """Kisa ping — aktif provider icin."""
    ok, err, st = await ensure_ready(probe_ollama=True)
    if not ok:
        return {"ok": False, "provider": active_provider(), "detail": err, **st}
    p = active_provider()
    if p == "ollama":
        return {
            "ok": True,
            "provider": "ollama",
            "detail": "ok",
            "model": st.get("model_name") or resolve_model(),
        }
    try:
        text = await chat(
            [{"role": "user", "content": "Reply with exactly: OK"}],
            model=resolve_model(),
            think=False,
            options={"temperature": 0},
            timeout=45.0,
            clean_script=False,
            format_json=False,
        )
        if not (text or "").strip():
            return {"ok": False, "provider": p, "detail": "Bos yanit"}
        return {
            "ok": True,
            "provider": p,
            "detail": "ok",
            "model": resolve_model(),
            "sample": (text or "")[:80],
        }
    except Exception as e:
        return {"ok": False, "provider": p, "detail": str(e)[:280]}


async def chat(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    think: bool = False,
    options: dict | None = None,
    timeout: float = 300.0,
    clean_script: bool = True,
    format_json: bool = False,
) -> str:
    """Bulut saglayici chat. Ollama icin cagirma — ollama_util.chat kullan."""
    from akifactory.text_utils import clean_turkish_script

    p = active_provider()
    if p not in KEY_FIELD_BY_PROVIDER:
        return ""
    m = resolve_model(model)
    opts = options or {}
    temperature = float(opts.get("temperature", 0.7))
    num_predict = int(opts.get("num_predict") or opts.get("max_tokens") or 4096)

    text = ""
    tried: list[str] = []
    for attempt in range(4):
        try:
            text = await _provider_chat(
                p,
                m,
                messages,
                temperature=temperature,
                format_json=format_json,
                num_predict=num_predict,
                timeout=timeout,
                think=think,
            )
            break
        except Exception as e:
            kind = _error_kind(e)
            _log(f"{p} chat hata ({m}, {kind}): {str(e) or type(e).__name__}")
            if kind == "model" or (kind == "quota" and attempt > 0):
                tried.append(m)
                alt = next((x for x in models_for_provider(p) if x not in tried), "")
                if not alt:
                    return ""
                _log(f"{p}: {m} yerine {alt} deneniyor")
                m = alt
                continue
            if kind in ("transient", "quota") and attempt < 2:
                await asyncio.sleep(2.0 * (attempt + 1))
                continue
            return ""

    if clean_script:
        return clean_turkish_script(text)
    return (text or "").strip()


def _error_kind(e: Exception) -> str:
    """model: bu model kullanilamaz · quota: limit · transient: tekrar dene · fatal: anahtar vb."""
    if isinstance(e, httpx.TransportError):
        return "transient"
    msg = str(e).lower()
    if "http 404" in msg or "does not exist" in msg or "no longer available" in msg or (
        "model" in msg and ("not found" in msg or "deprecated" in msg or "not supported" in msg)
    ):
        return "model"
    if "http 429" in msg or "quota" in msg or "resource_exhausted" in msg or "rate limit" in msg:
        return "quota"
    if any(f"http {c}" in msg for c in (500, 502, 503, 504, 529)) or "overloaded" in msg or "bos yanit" in msg:
        return "transient"
    return "fatal"


async def _provider_chat(
    p: str,
    m: str,
    messages: list[dict[str, str]],
    *,
    temperature: float,
    format_json: bool,
    num_predict: int,
    timeout: float,
    think: bool,
) -> str:
    if p in ("openai", "nvidia", "grok"):
        base, label = {
            "openai": ("https://api.openai.com/v1", "OpenAI"),
            "nvidia": (NVIDIA_API_BASE, "NVIDIA"),
            "grok": (GROK_API_BASE, "Grok"),
        }[p]
        return await _openai_compat_chat(
            base_url=base,
            key=_provider_key(p),
            model=m,
            messages=messages,
            temperature=temperature,
            format_json=format_json,
            num_predict=num_predict,
            timeout=timeout,
            label=label,
        )
    if p == "gemini":
        return await _gemini_chat(
            m,
            messages,
            temperature=temperature,
            format_json=format_json,
            num_predict=num_predict,
            timeout=timeout,
            think=think,
        )
    if p == "claude":
        return await _claude_chat(
            m,
            messages,
            temperature=temperature,
            format_json=format_json,
            num_predict=num_predict,
            timeout=timeout,
        )
    return ""


def _log(msg: str) -> None:
    try:
        from akifactory.paths import app_root
        import time as _t

        path = app_root() / ".aki_app.log"
        with path.open("a", encoding="utf-8") as f:
            f.write(f"[{_t.strftime('%Y-%m-%d %H:%M:%S')}] [llm_api] {msg}\n")
    except Exception:
        pass


async def _openai_compat_chat(
    *,
    base_url: str,
    key: str,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    format_json: bool,
    num_predict: int,
    timeout: float,
    label: str,
) -> str:
    if not key:
        raise RuntimeError(f"{label} API key yok — Ayarlar → LLM API")
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": m.get("role") or "user", "content": m.get("content") or ""}
            for m in messages
            if m.get("content")
        ],
        "temperature": temperature,
        "max_tokens": max(512, min(int(num_predict), 8192)),
        "stream": False,
    }
    if format_json:
        payload["response_format"] = {"type": "json_object"}
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
        )
        if r.status_code >= 400:
            raise RuntimeError(_http_err(r, label=label))
        data = r.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"{label} bos yanit")
    msg = choices[0].get("message") or {}
    text = (msg.get("content") or "").strip()
    if not text:
        raise RuntimeError(f"{label} bos yanit")
    return text


async def _gemini_chat(
    model: str,
    messages: list[dict[str, str]],
    *,
    temperature: float,
    format_json: bool,
    num_predict: int,
    timeout: float,
    think: bool,
) -> str:
    key = (load_settings().get("gemini_api_key") or "").strip()
    if not key:
        raise RuntimeError("Gemini API key yok — Ayarlar → LLM API")
    model = _normalize_gemini_model(model or GEMINI_MODELS[0])
    system_bits = [
        m["content"]
        for m in messages
        if m.get("role") == "system" and m.get("content")
    ]
    contents: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role") or "user"
        text = (m.get("content") or "").strip()
        if not text or role == "system":
            continue
        grole = "model" if role == "assistant" else "user"
        if contents and contents[-1]["role"] == grole:
            contents[-1]["parts"][0]["text"] += "\n\n" + text
        else:
            contents.append({"role": grole, "parts": [{"text": text}]})
    if not contents:
        contents = [{"role": "user", "parts": [{"text": "Merhaba"}]}]
    if contents[0]["role"] != "user":
        contents.insert(0, {"role": "user", "parts": [{"text": "(devam)"}]})

    gen_cfg: dict[str, Any] = {
        "temperature": temperature,
        "maxOutputTokens": max(512, min(int(num_predict), 8192)),
    }
    if format_json:
        gen_cfg["responseMimeType"] = "application/json"
    payload: dict[str, Any] = {"contents": contents, "generationConfig": gen_cfg}
    if system_bits:
        payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_bits)}]}

    url = f"{GEMINI_API_BASE}/models/{model}:generateContent"
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(url, headers={"x-goog-api-key": key}, json=payload)
        if r.status_code >= 400:
            raise RuntimeError(_http_err(r, label="Gemini"))
        data = r.json()
    parts_out: list[str] = []
    for cand in data.get("candidates") or []:
        content = cand.get("content") or {}
        for part in content.get("parts") or []:
            t = (part.get("text") or "").strip()
            if t and not part.get("thought"):
                parts_out.append(t)
    text = "\n".join(parts_out).strip()
    if not text:
        raise RuntimeError("Gemini bos yanit")
    return text


async def _claude_chat(
    model: str,
    messages: list[dict[str, str]],
    *,
    temperature: float,
    format_json: bool,
    num_predict: int,
    timeout: float,
) -> str:
    key = (load_settings().get("claude_api_key") or "").strip()
    if not key:
        raise RuntimeError("Claude API key yok — Ayarlar → LLM API")
    model = model or CLAUDE_MODELS[0]
    system = "\n\n".join(
        m["content"] for m in messages if m.get("role") == "system" and m.get("content")
    )
    contents: list[dict[str, str]] = []
    for m in messages:
        role = m.get("role") or "user"
        text = (m.get("content") or "").strip()
        if not text or role == "system":
            continue
        crole = "assistant" if role == "assistant" else "user"
        if format_json and crole == "user" and m is messages[-1]:
            text += "\n\nRespond with valid JSON only."
        if contents and contents[-1]["role"] == crole:
            contents[-1]["content"] += "\n\n" + text
        else:
            contents.append({"role": crole, "content": text})
    if not contents:
        contents = [{"role": "user", "content": "Merhaba"}]
    if contents[0]["role"] != "user":
        contents.insert(0, {"role": "user", "content": "(devam)"})

    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max(512, min(int(num_predict), 8192)),
        "temperature": temperature,
        "messages": contents,
    }
    if system:
        payload["system"] = system

    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )
        if r.status_code >= 400:
            raise RuntimeError(_http_err(r, label="Claude"))
        data = r.json()
    parts = data.get("content") or []
    text = "".join(
        p.get("text", "") for p in parts if p.get("type") == "text"
    ).strip()
    if not text:
        raise RuntimeError("Claude bos yanit")
    return text
