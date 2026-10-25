"""Ollama durum kontrolu (model: config.toml ollama_model_name)."""

from __future__ import annotations

import re
from pathlib import Path

import httpx

from akifactory.paths import engine_config_file

_DEFAULT_HOST = "http://127.0.0.1:11434"
_TAGS_TIMEOUT = 10.0


def ollama_api_root() -> str:
    """Ollama HTTP kok URL — config.toml, OLLAMA_HOST veya varsayilan."""
    import os

    host = (os.environ.get("OLLAMA_HOST") or "").strip().rstrip("/")
    if host:
        if not host.startswith(("http://", "https://")):
            host = f"http://{host}"
        return host
    cfg = engine_config_file()
    if cfg.is_file():
        text = cfg.read_text(encoding="utf-8")
        m = re.search(r'ollama_base_url\s*=\s*"([^"]*)"', text)
        if m:
            base = m.group(1).strip().rstrip("/")
            if base.endswith("/v1"):
                base = base[:-3]
            if base:
                return base
    return _DEFAULT_HOST


def _ollama_url(path: str) -> str:
    return f"{ollama_api_root()}{path}"


OLLAMA_TAGS_URL = _ollama_url("/api/tags")
OLLAMA_GENERATE_URL = _ollama_url("/api/generate")
OLLAMA_CHAT_URL = _ollama_url("/api/chat")
OLLAMA_PS_URL = _ollama_url("/api/ps")
OLLAMA_VERSION_URL = _ollama_url("/api/version")
# Is bitince modeli VRAM'den bosalt (varsayilan ~5dk bekler)
OLLAMA_KEEP_ALIVE = "0"
DEFAULT_MODELS_DIR = r"C:\OllamaData\models"
_probe_cache: dict = {}

# Senaryo uretimi — yaratıcı ama kontrollu
SCRIPT_CHAT_OPTIONS: dict[str, float] = {
    "temperature": 0.7,
    "top_p": 0.9,
    "repeat_penalty": 1.1,
}

# Gorsel/video prompt uretimi — daha cesitli cikti
CREATIVE_PROMPT_OPTIONS: dict[str, float] = {
    "temperature": 0.92,
    "top_p": 0.93,
    "repeat_penalty": 1.15,
}


def creative_chat_options() -> dict[str, float | int]:
    """Her cagrida farkli seed + yuksek temperature."""
    import random

    return {
        **CREATIVE_PROMPT_OPTIONS,
        "seed": random.randint(1, 2_147_483_646),
    }


def _parse_ollama_error(body: str) -> str:
    text = (body or "").strip()
    if not text:
        return "Ollama model yaniti alinamadi"
    try:
        import json

        data = json.loads(text)
        err = data.get("error") or data.get("message") or ""
        if err:
            if "failed to load model" in err.lower():
                cfg = get_config_model() or "model"
                if ".ollama" in err or "\\Users\\" in err:
                    return (
                        "Ollama hala eski kullanici klasorunu kullaniyor (ERDIN/.ollama). "
                        "Proje klasorunde AkiFactory.bat calistirin, sonra AkiFactory.bat."
                    )
                return (
                    f"Ollama modeli yuklenemedi ({cfg}). "
                    f"AkiFactory.bat calistirin veya: ollama pull {cfg}"
                )
            return err[:280]
    except Exception:
        pass
    return text[:280]


async def unload_all_models() -> None:
    """Yuklu Ollama modellerini bellekten cikar (VRAM bosaltir)."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(OLLAMA_PS_URL)
            if r.status_code != 200:
                return
            data = r.json()
            for entry in data.get("models") or []:
                name = (entry.get("name") or entry.get("model") or "").strip()
                if not name:
                    continue
                await client.post(
                    OLLAMA_GENERATE_URL,
                    json={
                        "model": name,
                        "prompt": "",
                        "stream": False,
                        "keep_alive": OLLAMA_KEEP_ALIVE,
                    },
                )
    except Exception:
        pass


async def release_vram_for_model_swap() -> None:
    """Yazar (9B) -> editor (14B) gecisinde VRAM bosalt (keep_alive=0 yaninda)."""
    await unload_all_models()


def unload_all_models_sync() -> None:
    try:
        import asyncio

        asyncio.run(unload_all_models())
    except Exception:
        pass


async def probe_model(model: str, *, force: bool = False) -> dict:
    """Secili modelin gercekten calistigini dogrula (tags yeterli degil)."""
    import time

    model = (model or "").strip()
    if not model:
        return {"ok": False, "error": "Model secilmedi"}

    now = time.time()
    if (
        not force
        and _probe_cache.get("model") == model
        and now - float(_probe_cache.get("ts", 0)) < 45
    ):
        return {"ok": bool(_probe_cache.get("ok")), "error": _probe_cache.get("error", "")}

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            r = await client.post(
                OLLAMA_GENERATE_URL,
                json={
                    "model": model,
                    "prompt": "Merhaba",
                    "stream": False,
                    "keep_alive": OLLAMA_KEEP_ALIVE,
                    "options": {"num_predict": 8},
                },
            )
        if r.status_code == 200 and r.json().get("response") is not None:
            result = {"ok": True, "error": ""}
        else:
            result = {"ok": False, "error": _parse_ollama_error(r.text)}
    except httpx.TimeoutException:
        result = {"ok": False, "error": "Ollama model testi zaman asimi (model cok buyuk olabilir)"}
    except Exception as e:
        result = {"ok": False, "error": f"Ollama baglantisi: {e}"}

    _probe_cache.update({"model": model, "ts": now, **result})
    return result


async def fetch_status(*, probe: bool = True) -> dict:
    cfg = get_config_model()
    try:
        if not await _ollama_alive():
            return {
                "running": False,
                "models": [],
                "model_ok": False,
                "model_loaded": False,
                "model_name": cfg,
                "model_error": (
                    f"Ollama yanit vermiyor ({ollama_api_root()}). "
                    "Ollama uygulamasini acin veya terminalde: ollama serve"
                ),
                "fix_hint": "AkiFactory.bat (proje klasoru)",
            }
        models = await _fetch_tags()
        out: dict = {"running": True, "models": models, "model_name": cfg, "model_loaded": False}
        installed = model_installed(cfg, models) if cfg else True
        if probe and cfg:
            if not installed:
                out["model_ok"] = False
                out["model_error"] = f"Model yuklu degil. ollama pull {cfg}"
            else:
                pr = await probe_model(cfg)
                out["model_ok"] = pr["ok"]
                out["model_loaded"] = pr["ok"]
                out["model_error"] = pr.get("error", "")
        else:
            out["model_ok"] = installed if cfg else True
            out["model_loaded"] = installed if cfg else False
            out["model_error"] = (
                f"Model yuklu degil. ollama pull {cfg}" if cfg and not installed else ""
            )
        if not out.get("model_ok"):
            out["fix_hint"] = "AkiFactory.bat (proje klasoru)"
            out["models_dir"] = DEFAULT_MODELS_DIR
        return out
    except httpx.TimeoutException:
        return {
            "running": False,
            "models": [],
            "model_ok": False,
            "model_loaded": False,
            "model_name": cfg,
            "model_error": (
                "Ollama cok yavas yanit verdi (model yukleniyor olabilir). "
                "Biraz bekleyip yenileyin."
            ),
            "fix_hint": "AkiFactory.bat",
        }
    except Exception as e:
        return {
            "running": False,
            "models": [],
            "model_ok": False,
            "model_loaded": False,
            "model_name": cfg,
            "model_error": f"Ollama baglantisi: {e}",
            "fix_hint": "AkiFactory.bat",
        }


async def list_installed_models() -> list[str]:
    """Ollama'da yuklu model adlarini dondurur (editor model cozumlemesi icin)."""
    status = await fetch_status(probe=False)
    return list(status.get("models") or [])


def get_config_model() -> str:
    cfg = engine_config_file()
    if not cfg.is_file():
        return ""
    text = cfg.read_text(encoding="utf-8")
    m = re.search(r'ollama_model_name\s*=\s*"([^"]*)"', text)
    return m.group(1) if m else ""


def model_installed(model: str, installed: list[str]) -> bool:
    """Ollama tags listesinde model var mi (qwen3.5:9b / qwen3.5:9b-latest vb.)."""
    want = (model or "").strip()
    if not want:
        return False
    names = [n.strip() for n in installed if n and n.strip()]
    if want in names:
        return True
    want_base = want.split(":")[0].lower()
    for name in names:
        if name.lower() == want.lower():
            return True
        if name.lower().startswith(want.lower() + ":"):
            return True
        if name.split(":")[0].lower() == want_base and want_base:
            return True
    return False


async def _ollama_alive(timeout: float = _TAGS_TIMEOUT) -> bool:
    """Hafif canli kontrol — /api/version, gerekirse /api/tags."""
    for url in (OLLAMA_VERSION_URL, OLLAMA_TAGS_URL):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(url)
            if r.status_code == 200:
                return True
        except Exception:
            continue
    return False


async def _fetch_tags(timeout: float = _TAGS_TIMEOUT) -> list[str]:
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(OLLAMA_TAGS_URL)
            if r.status_code != 200:
                return []
            data = r.json()
            return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        except Exception as e:
            last_err = e
            if attempt == 0:
                import asyncio

                await asyncio.sleep(0.4)
    if last_err:
        raise last_err
    return []


def ping_sync() -> bool:
    try:
        import urllib.request

        urllib.request.urlopen(OLLAMA_VERSION_URL, timeout=3)
        return True
    except Exception:
        try:
            import urllib.request

            urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=3)
            return True
        except Exception:
            return False


async def chat_vision(
    prompt: str,
    *,
    images_b64: list[str],
    model: str,
    think: bool = False,
    options: dict | None = None,
    timeout: float = 180.0,
) -> str:
    """Ollama /api/chat — gorsel + metin (vision modeller)."""
    m = (model or "").strip()
    if not m:
        return ""
    body: dict = {
        "model": m,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": images_b64,
            }
        ],
        "stream": False,
        "think": think,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {**SCRIPT_CHAT_OPTIONS, **(options or {})},
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(OLLAMA_CHAT_URL, json=body)
        if r.status_code != 200:
            err = _parse_ollama_error(r.text)
            raise RuntimeError(err or f"Ollama vision HTTP {r.status_code}")
        data = r.json()
        msg = data.get("message") or {}
        return (msg.get("content") or "").strip()
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Ollama vision baglantisi: {e}") from e


def _log_chat_error(msg: str) -> None:
    """Senaryo/chat hatasi sessizce yutulmasin — karsi PC'de teshis icin dosyaya yaz."""
    try:
        from akifactory.paths import app_root

        path = app_root() / ".aki_app.log"
        import time as _t

        with path.open("a", encoding="utf-8") as f:
            f.write(f"[{_t.strftime('%Y-%m-%d %H:%M:%S')}] [ollama.chat] {msg}\n")
    except Exception:
        pass


def _recover_text_from_thinking(thinking: str) -> str:
    """Qwen3 bazen cevabi content yerine thinking'e yazar — kullanilabilir metni kurtar."""
    from akifactory.text_utils import clean_turkish_script

    raw = (thinking or "").strip()
    if not raw:
        return ""

    cleaned = clean_turkish_script(raw)
    parts = [p.strip() for p in re.split(r"\n{2,}", cleaned or raw) if p.strip()]
    meta_starts = (
        "düşün",
        "dusun",
        "önce",
        "once",
        "thinking",
        "drafting",
        "draft:",
        "draft ",
        "outline",
        "taslak",
        "let me",
        "the user",
        "kullanıcı",
        "kullanici",
        "i need",
        "i should",
        "wait,",
        "wait:",
        "okay,",
        "okay i",
        "tamam,",
        "şimdi",
        "simdi",
        "instruction",
        "usually turkish",
        "strict formatting",
        "from prompt",
        "görev",
        "compliance",
        "**drafting",
        "**thinking",
    )
    # Sondan basla: genelde asil cevap thinking'in sonunda
    for part in reversed(parts):
        cand = clean_turkish_script(part) or part
        if not cand or len(cand) < 8:
            continue
        low = cand[:64].lower()
        if any(low.startswith(m) for m in meta_starts):
            continue
        if "instruction says" in cand.lower() or "yazma —" in cand.lower():
            continue
        return cand
    if cleaned and len(cleaned) >= 8:
        return cleaned
    return ""


def _message_content(msg: dict) -> tuple[str, bool]:
    """(text, recovered_from_thinking)."""
    content = (msg.get("content") or "").strip()
    if content:
        return content, False
    thinking = (msg.get("thinking") or "").strip()
    if not thinking:
        return "", False
    recovered = _recover_text_from_thinking(thinking)
    return recovered, bool(recovered)


async def chat(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    think: bool = False,
    options: dict | None = None,
    timeout: float = 300.0,
    clean_script: bool = True,
    format_json: bool = False,
    _retry_depth: int = 0,
) -> str:
    """Ollama /api/chat — varsayilan thinking kapali (senaryo); fact-check ayri cagrilir.

    Ayarlar → LLM API provider ollama degilse bulut (OpenAI/NVIDIA/Gemini/Grok/Claude).
    Qwen3.5 bazen think=false olsa bile cevabi `thinking` alanina yazar.
    Bu durumda metin kurtarilir; kurtarma olmazsa think=false ile bir kez daha denenir.
    """
    from akifactory.text_utils import clean_turkish_script

    try:
        from akifactory import llm_api

        if llm_api.is_cloud():
            return await llm_api.chat(
                messages,
                model=model,
                think=think,
                options=options,
                timeout=timeout,
                clean_script=clean_script,
                format_json=format_json,
            )
    except Exception as e:
        _log_chat_error(f"llm_api yonlendirme: {e}")

    m = (model or get_config_model() or "qwen3.5:9b").strip()
    body: dict = {
        "model": m,
        "messages": messages,
        "stream": False,
        "think": bool(think),
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {**SCRIPT_CHAT_OPTIONS, **(options or {})},
    }
    if format_json:
        body["format"] = "json"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(OLLAMA_CHAT_URL, json=body)
        if r.status_code != 200:
            err = _parse_ollama_error(r.text)
            _log_chat_error(f"HTTP {r.status_code} (model={m}): {err}")
            # "does not support thinking" → think kapali tekrar
            if (
                think
                and _retry_depth < 1
                and "thinking" in (err or "").lower()
            ):
                return await chat(
                    messages,
                    model=m,
                    think=False,
                    options=options,
                    timeout=timeout,
                    clean_script=clean_script,
                    format_json=format_json,
                    _retry_depth=_retry_depth + 1,
                )
            return ""
        data = r.json()
        msg = data.get("message") or {}
        content, from_thinking = _message_content(msg)
        if from_thinking:
            _log_chat_error(
                f"thinking->content kurtarildi (model={m}, chars={len(content)})."
            )
        if not content:
            _log_chat_error(f"Bos yanit (model={m}, think={think}).")
            # think=True bos kaldiysa kapali dene; think=False bos ise bir kez daha zorla
            if _retry_depth < 1:
                return await chat(
                    messages,
                    model=m,
                    think=False,
                    options=options,
                    timeout=timeout,
                    clean_script=clean_script,
                    format_json=format_json,
                    _retry_depth=_retry_depth + 1,
                )
        if clean_script:
            return clean_turkish_script(content)
        return content
    except httpx.TimeoutException:
        _log_chat_error(f"Zaman asimi {timeout}s (model={m}) — yavas GPU/CPU olabilir.")
        return ""
    except Exception as e:
        _log_chat_error(f"Baglanti hatasi (model={m}): {e}")
        return ""
