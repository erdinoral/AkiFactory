"""AkiFactory — cift LLM profilleri (yazar + editor). agents.md oneri listesi."""

from __future__ import annotations

from akifactory.ollama_util import get_config_model

WRITER_DEFAULT = "qwen3.5:9b"
# Buyuk editor (14B) iyi 9B taslagi bozuyordu — varsayilan ayni model
EDITOR_DEFAULT = "qwen3.5:9b"
# Ayrı editor LLM kapali: dogrulama/cila da yazar modeliyle (VRAM + tutarlilik)
EDITOR_FOLLOWS_WRITER = True

# Yazar adayi — senaryo taslagini yazar
WRITER_CANDIDATES: list[dict[str, str]] = [
    {
        "id": "qwen3.5:9b",
        "label": "Qwen 3.5 9B (yazar, onerilen)",
        "source": "Qwen/Qwen3.5-9B",
    },
    {
        "id": "qwen3:8b",
        "label": "Qwen 3 8B",
        "source": "Qwen/Qwen3-8B",
    },
    {
        "id": "qwen2.5:7b",
        "label": "Qwen 2.5 7B Instruct",
        "source": "Qwen/Qwen2.5-7B-Instruct",
    },
    {
        "id": "llama3.1:8b",
        "label": "Llama 3.1 8B Instruct",
        "source": "meta-llama/Llama-3.1-8B-Instruct",
    },
    {
        "id": "gemma3:9b",
        "label": "Gemma 3 9B",
        "source": "google/gemma-4-12B-it (yakin boyut)",
    },
]

# Editor adayi — varsayilan yazar ile ayni (9B); 14B istege bagli / deneysel
EDITOR_CANDIDATES: list[dict[str, str]] = [
    {
        "id": "qwen3.5:9b",
        "label": "Qwen 3.5 9B (editor, onerilen)",
        "source": "Qwen/Qwen3.5-9B",
    },
    {
        "id": "qwen3:14b",
        "label": "Qwen 3 14B (deneysel — taslagi bozabilir)",
        "source": "Qwen/Qwen3-14B",
    },
    {
        "id": "qwen2.5:7b",
        "label": "Qwen 2.5 7B Instruct",
        "source": "Qwen/Qwen2.5-7B-Instruct",
    },
    {
        "id": "llama3.1:8b",
        "label": "Llama 3.1 8B Instruct",
        "source": "meta-llama/Llama-3.1-8B-Instruct",
    },
    {
        "id": "gemma3:9b",
        "label": "Gemma 3 9B",
        "source": "google/gemma-4-12B-it (yakin boyut)",
    },
    {
        "id": "lfm2.5:8b",
        "label": "Liquid LFM 2.5 8B",
        "source": "LiquidAI/LFM2.5-8B-A1B",
    },
]

# Ollama tag eslesmesi — farkli pull isimleri
_ALIASES: dict[str, tuple[str, ...]] = {
    "qwen3:8b": ("qwen3:8b", "qwen3-8b", "qwen3:8b-instruct"),
    "qwen3:14b": ("qwen3:14b", "qwen3-14b", "qwen3:14b-instruct"),
    "qwen3.5:9b": ("qwen3.5:9b", "qwen3.5-9b", "qwen3.5:9b-instruct"),
    "qwen2.5:7b": ("qwen2.5:7b", "qwen2.5:7b-instruct", "qwen2.5:7b-instruct-q4_K_M"),
    "llama3.1:8b": ("llama3.1:8b", "llama3.1:8b-instruct"),
    "gemma3:9b": ("gemma3:9b", "gemma2:9b", "gemma3:12b"),
    "lfm2.5:8b": ("lfm2.5:8b", "lfm2.5:8b-a1b"),
}


def writer_model(preference: str | None = None, installed: list[str] | None = None) -> str:
    try:
        from akifactory import llm_api

        if llm_api.is_cloud():
            return llm_api.resolve_model(preference)
    except Exception:
        pass
    if preference:
        models = installed if installed is not None else None
        if models is not None:
            hit = _match_installed(preference, models)
            if hit:
                return hit
        if preference.strip():
            return preference.strip()
    cfg = (get_config_model() or WRITER_DEFAULT).strip()
    if installed is not None:
        hit = _match_installed(cfg, installed) or _match_installed(WRITER_DEFAULT, installed)
        if hit:
            return hit
        for cand in WRITER_CANDIDATES:
            hit = _match_installed(cand["id"], installed)
            if hit:
                return hit
    return cfg or WRITER_DEFAULT


def resolve_writer_model(installed: list[str], preference: str | None = None) -> str:
    try:
        from akifactory import llm_api

        if llm_api.is_cloud():
            return llm_api.resolve_model(preference)
    except Exception:
        pass
    if preference:
        hit = _match_installed(preference, installed)
        if hit:
            return hit
        if preference in installed:
            return preference
    cfg = (get_config_model() or "").strip()
    if cfg:
        hit = _match_installed(cfg, installed)
        if hit:
            return hit
    preferred = _match_installed(WRITER_DEFAULT, installed)
    if preferred:
        return preferred
    for cand in WRITER_CANDIDATES:
        hit = _match_installed(cand["id"], installed)
        if hit:
            return hit
    return cfg or WRITER_DEFAULT


def editor_model_default() -> str:
    return EDITOR_DEFAULT


def _match_installed(profile_id: str, installed: list[str]) -> str | None:
    """Exact / alias eslesme. `qwen3` → `qwen3.5` gibi yanlis prefix eslesmesi YOK."""
    aliases = _ALIASES.get(profile_id, (profile_id,))
    lower_map = {m.lower(): m for m in installed}
    for alias in aliases:
        if alias.lower() in lower_map:
            return lower_map[alias.lower()]
    want = (profile_id or "").strip().lower()
    if not want:
        return None
    # Tam id veya "aile:boyut" (qwen3:14b ↔ qwen3:14b-instruct)
    want_base, _, want_size = want.partition(":")
    for m in installed:
        ml = m.lower()
        if ml == want:
            return m
        m_base, _, m_rest = ml.partition(":")
        if m_base != want_base:
            continue
        # Ayni aile: boyut etiketi (14b) baslangicta eslesmeli — 3.5:9b ≠ 3:14b
        if want_size and (
            m_rest == want_size
            or m_rest.startswith(want_size + "-")
            or m_rest.startswith(want_size + "_")
        ):
            return m
    return None


def resolve_editor_model(installed: list[str], preference: str | None = None) -> str:
    if EDITOR_FOLLOWS_WRITER:
        # Ayrı editor yok — preference yazar tercihi gibi cozulur (14b listesi UI'da yok)
        # Bilerek buyuk editor id'si geldiyse yazar varsayilanina dus
        pref = (preference or "").strip()
        if pref and ("14b" in pref.lower() or pref.lower().startswith("qwen3:14")):
            pref = ""
        return resolve_writer_model(installed, pref or None)
    if preference:
        hit = _match_installed(preference, installed)
        if hit:
            return hit
        if preference in installed:
            return preference
    preferred = _match_installed(EDITOR_DEFAULT, installed)
    if preferred:
        return preferred
    for cand in EDITOR_CANDIDATES:
        hit = _match_installed(cand["id"], installed)
        if hit:
            return hit
    return writer_model()


def resolve_script_models(
    installed: list[str],
    writer_preference: str | None = None,
    editor_preference: str | None = None,
) -> tuple[str, str]:
    """(yazar, editor). EDITOR_FOLLOWS_WRITER iken ikisi ayni tag."""
    writer = resolve_writer_model(installed, writer_preference)
    if EDITOR_FOLLOWS_WRITER:
        return writer, writer
    editor = resolve_editor_model(installed, editor_preference)
    return writer, editor


def list_writer_models_for_ui(installed: list[str]) -> list[dict[str, str | bool]]:
    out: list[dict[str, str | bool]] = []
    seen: set[str] = set()
    for cand in WRITER_CANDIDATES:
        resolved = _match_installed(cand["id"], installed)
        if resolved and resolved not in seen:
            seen.add(resolved)
            out.append(
                {
                    "id": resolved,
                    "profile_id": cand["id"],
                    "label": cand["label"],
                    "available": True,
                }
            )
        else:
            out.append(
                {
                    "id": cand["id"],
                    "profile_id": cand["id"],
                    "label": cand["label"],
                    "available": False,
                }
            )
    return out


def list_editor_models_for_ui(installed: list[str]) -> list[dict[str, str | bool]]:
    out: list[dict[str, str | bool]] = []
    seen: set[str] = set()
    for cand in EDITOR_CANDIDATES:
        resolved = _match_installed(cand["id"], installed)
        if resolved and resolved not in seen:
            seen.add(resolved)
            out.append(
                {
                    "id": resolved,
                    "profile_id": cand["id"],
                    "label": cand["label"],
                    "available": True,
                }
            )
        else:
            out.append(
                {
                    "id": cand["id"],
                    "profile_id": cand["id"],
                    "label": cand["label"],
                    "available": False,
                }
            )
    return out


def default_editor_profile_id() -> str:
    return EDITOR_DEFAULT


def default_writer_profile_id() -> str:
    return WRITER_DEFAULT


# Vision — galeri video kare analizi (YouTube performans geri bildirimi)
VISION_CANDIDATES: list[dict[str, str]] = [
    {
        "id": "qwen2.5vl:7b",
        "label": "Qwen 2.5 VL 7B (onerilen)",
        "source": "Qwen/Qwen2.5-VL-7B-Instruct",
    },
    {
        "id": "llava:7b",
        "label": "LLaVA 7B",
        "source": "llava-hf/llava-1.5-7b-hf",
    },
    {
        "id": "llava:13b",
        "label": "LLaVA 13B",
        "source": "llava-hf/llava-1.5-13b-hf",
    },
]

_VISION_ALIASES: dict[str, tuple[str, ...]] = {
    "qwen2.5vl:7b": ("qwen2.5vl:7b", "qwen2.5-vl:7b", "qwen2.5vl:7b-instruct"),
    "llava:7b": ("llava:7b", "llava:7b-v1.6", "llava:7b-v1.6-mistral-q4_K_M"),
    "llava:13b": ("llava:13b", "llava:13b-v1.6"),
}


def resolve_vision_model(installed: list[str], preference: str | None = None) -> str:
    if preference:
        aliases = _VISION_ALIASES.get(preference, (preference,))
        lower_map = {m.lower(): m for m in installed}
        for alias in aliases:
            if alias.lower() in lower_map:
                return lower_map[alias.lower()]
        if preference in installed:
            return preference
    for cand in VISION_CANDIDATES:
        aliases = _VISION_ALIASES.get(cand["id"], (cand["id"],))
        lower_map = {m.lower(): m for m in installed}
        for alias in aliases:
            if alias.lower() in lower_map:
                return lower_map[alias.lower()]
    return ""


def list_vision_models_for_ui(installed: list[str]) -> list[dict[str, str | bool]]:
    out: list[dict[str, str | bool]] = []
    seen: set[str] = set()
    for cand in VISION_CANDIDATES:
        resolved = resolve_vision_model(installed, cand["id"])
        if resolved and resolved not in seen:
            seen.add(resolved)
            out.append(
                {
                    "id": resolved,
                    "profile_id": cand["id"],
                    "label": cand["label"],
                    "available": True,
                }
            )
        else:
            out.append(
                {
                    "id": cand["id"],
                    "profile_id": cand["id"],
                    "label": cand["label"],
                    "available": False,
                }
            )
    return out


def default_vision_profile_id() -> str:
    return VISION_CANDIDATES[0]["id"]
