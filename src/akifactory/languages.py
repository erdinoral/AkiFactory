"""Uretim dili — senaryo (LLM), TTS ve Whisper altyazi eslestirmesi."""



from __future__ import annotations

import re
from dataclasses import dataclass

from akifactory.paths import engine_config_file



DEFAULT_LANGUAGE = "tr"

DEFAULT_TTS_ENGINE = "edge"

# Arayuzde gosterilen ses motorlari
UI_TTS_ENGINES: tuple[str, ...] = ("edge", "chatterbox", "rvc")



CHATTERBOX_VOICES: dict[str, str] = {
    "tr": "chatterbox:tr-male-Male",
    "en": "chatterbox:en-male-Male",
}


def _default_rvc_engine_voice(lang_id: str | None = None) -> str:
    from akifactory.rvc_registry import default_voice, engine_voice_name

    v = default_voice()
    if v:
        return engine_voice_name(v)
    return "rvc:unknown-Male"

# Edge = Microsoft sinir agi sesleri (Turkce icin en dogal secenek)
EDGE_VOICES: dict[str, list[dict[str, str]]] = {
    "tr": [
        {"id": "tr-TR-AhmetNeural-Male", "label": "Erkek — Ahmet (onerilen)"},
        {"id": "tr-TR-EmelNeural-Female", "label": "Kadin — Emel"},
    ],
    "en": [
        {"id": "en-US-JennyNeural-Female", "label": "Jenny (kadin)"},
        {"id": "en-US-GuyNeural-Male", "label": "Guy (erkek)"},
    ],
    "de": [
        {"id": "de-DE-ConradNeural-Male", "label": "Conrad (erkek)"},
        {"id": "de-DE-KatjaNeural-Female", "label": "Katja (kadin)"},
    ],
    "fr": [
        {"id": "fr-FR-HenriNeural-Male", "label": "Henri (erkek)"},
        {"id": "fr-FR-DeniseNeural-Female", "label": "Denise (kadin)"},
    ],
}





@dataclass(frozen=True)

class ProductionLanguage:

    id: str

    label: str

    video_language: str

    voice_name: str

    whisper_language: str





LANGUAGES: dict[str, ProductionLanguage] = {

    "tr": ProductionLanguage(

        id="tr",

        label="Turkce",

        video_language="tr-TR",

        voice_name="tr-TR-AhmetNeural-Male",

        whisper_language="tr",

    ),

    "en": ProductionLanguage(

        id="en",

        label="English",

        video_language="en-US",

        voice_name="en-US-JennyNeural-Female",

        whisper_language="en",

    ),

    "de": ProductionLanguage(

        id="de",

        label="Deutsch",

        video_language="de-DE",

        voice_name="de-DE-KatjaNeural-Female",

        whisper_language="de",

    ),

    "fr": ProductionLanguage(

        id="fr",

        label="Francais",

        video_language="fr-FR",

        voice_name="fr-FR-DeniseNeural-Female",

        whisper_language="fr",

    ),

}





def resolve(lang_id: str | None) -> ProductionLanguage:

    key = (lang_id or DEFAULT_LANGUAGE).strip().lower()

    return LANGUAGES.get(key, LANGUAGES[DEFAULT_LANGUAGE])





def resolve_voice(
    lang_id: str | None,
    tts_engine: str | None = None,
    edge_voice: str | None = None,
    rvc_voice: str | None = None,
) -> str:
    prod = resolve(lang_id)
    engine = (tts_engine or DEFAULT_TTS_ENGINE).strip().lower()
    key = (lang_id or DEFAULT_LANGUAGE).strip().lower()
    if engine == "chatterbox":
        if key.startswith("en"):
            return CHATTERBOX_VOICES["en"]
        return CHATTERBOX_VOICES.get(key, CHATTERBOX_VOICES["tr"])
    if engine == "rvc":
        from akifactory.rvc_registry import get_voice, engine_voice_name

        v = get_voice(rvc_voice)
        if v:
            return engine_voice_name(v)
        return _default_rvc_engine_voice(key)
    if engine == "edge" and edge_voice:
        allowed = {v["id"] for v in EDGE_VOICES.get(key, [])}
        if edge_voice in allowed:
            return edge_voice
        # Yanlis dil sesi (or. EN uretimde tr-TR-Ahmet) — varsayilana dus
        locale_prefix = {
            "tr": "tr-TR-",
            "en": "en-US-",
            "de": "de-DE-",
            "fr": "fr-FR-",
        }.get(key[:2], "")
        if locale_prefix and edge_voice.startswith(locale_prefix):
            return edge_voice
    return prod.voice_name


def edge_voices_for_ui(lang_id: str | None) -> list[dict[str, str]]:
    key = (lang_id or DEFAULT_LANGUAGE).strip().lower()
    return list(EDGE_VOICES.get(key, EDGE_VOICES.get("tr", [])))





def tts_validation_error(lang_id: str | None, tts_engine: str | None) -> str | None:

    engine = (tts_engine or DEFAULT_TTS_ENGINE).strip().lower()

    key = (lang_id or DEFAULT_LANGUAGE).strip().lower()

    if engine == "chatterbox" and not chatterbox_installed():
        return (
            "Chatterbox kurulu degil. Kurulum: "
            "python scripts/bootstrap.py --chatterbox"
        )

    if engine == "chatterbox" and chatterbox_installed() and not chatterbox_model_ready():
        return (
            "Chatterbox modeli henuz hazir degil. "
            "python scripts/bootstrap.py --chatterbox"
        )

    if engine == "chatterbox":
        from akifactory.rvc_tts import is_rvc_available

        if not is_rvc_available():
            return (
                "Chatterbox → RVC icin RVC modeli gerekli. "
                "models/rvc/<SesAdi>/ klasorune .pth koyun."
            )

    if engine == "rvc":
        from akifactory.rvc_tts import is_rvc_available

        if not is_rvc_available():
            return "RVC modeli bulunamadi. models/rvc/<SesAdi>/ klasorune .pth koyun veya: AkiFactory.bat rvc"
        if key not in ("tr", "en"):
            return "RVC sesleri simdilik Turkce ve Ingilizce uretim icin uygundur."

    return None


def chatterbox_installed() -> bool:
    try:
        from akifactory.chatterbox_util import chatterbox_package_ready

        return chatterbox_package_ready()
    except Exception:
        return False


def chatterbox_model_ready() -> bool:
    try:
        from akifactory.chatterbox_util import chatterbox_model_ready as _ready

        return _ready()
    except Exception:
        return False


def tts_engines_for_ui(*, rvc_ok: bool | None = None) -> list[dict[str, object]]:
    if rvc_ok is None:
        from akifactory.rvc_tts import is_rvc_available

        rvc_ok = is_rvc_available()

    catalog: dict[str, dict[str, object]] = {
        "edge": {
            "id": "edge",
            "label": "Edge TTS (bulut)",
            "available": True,
            "hint": "En dogal Turkce (Microsoft sinir agi). Internet gerekir.",
        },
        "chatterbox": {
            "id": "chatterbox",
            "label": "Chatterbox → RVC",
            "available": chatterbox_installed() and chatterbox_model_ready(),
            "hint": chatterbox_installed()
            and (
                chatterbox_model_ready()
                and "Chatterbox Multilingual (TR) → RVC. Rakamlar otomatik yazıya çevrilir."
                or "Paket kurulu; model testi eksik. python scripts/bootstrap.py --chatterbox"
            )
            or "Kurulu degil. python scripts/bootstrap.py --chatterbox",
        },
        "rvc": {
            "id": "rvc",
            "label": "RVC (Edge taban — hizli)",
            "available": rvc_ok,
            "hint": rvc_ok
            and "Edge Ahmet telaffuz → RVC modeli. Hizli yol; telaffuz net, ton RVC'den gelir."
            or "Model yok. models/rvc/<SesAdi>/ klasorune .pth koyun veya: AkiFactory.bat rvc",
        },
    }
    return [catalog[eid] for eid in UI_TTS_ENGINES if eid in catalog]


def resolve_effective_tts_engine(
    tts_engine: str | None,
    *,
    rvc_voice: str | None = None,
    production_language: str | None = None,
) -> tuple[str, str | None]:
    """UI secimini gercek uretim motoruna cevir."""
    raw = (tts_engine or DEFAULT_TTS_ENGINE).strip().lower()
    note: str | None = None
    engine, fb = resolve_tts_with_fallback(production_language, raw)
    if fb:
        note = f"{note} {fb}".strip() if note else fb
    return engine, note





def list_for_ui() -> list[dict[str, str]]:

    return [{"id": p.id, "label": p.label} for p in LANGUAGES.values()]


def resolve_tts_with_fallback(lang_id: str | None, tts_engine: str | None) -> tuple[str, str | None]:
    """Yerel motor kullanilamazsa Edge'e dus; (engine, uyari_mesaji)."""
    engine = (tts_engine or DEFAULT_TTS_ENGINE).strip().lower()
    if engine not in UI_TTS_ENGINES:
        engine = DEFAULT_TTS_ENGINE
    err = tts_validation_error(lang_id, engine)
    if engine == "chatterbox" and err:
        if not tts_validation_error(lang_id, "edge"):
            return "edge", f"Chatterbox kullanilamadi ({err}). Edge TTS ile devam ediliyor."
    return engine, None


def subtitle_provider_for_tts(tts_engine: str | None) -> str:
    """Edge TTS → edge timing; yerel motorlar → whisper."""
    engine = (tts_engine or DEFAULT_TTS_ENGINE).strip().lower()
    if engine in {"edge", "azure", "azure-tts-v1"}:
        return "edge"
    return "whisper"


def sync_subtitle_provider_for_tts(tts_engine: str | None) -> str:
    """config.toml subtitle_provider alanini aktif TTS ile hizala."""
    provider = subtitle_provider_for_tts(tts_engine)
    cfg = engine_config_file()
    if not cfg.is_file():
        return provider
    try:
        text = cfg.read_text(encoding="utf-8")
        if re.search(r'subtitle_provider\s*=\s*"[^"]*"', text):
            new_text = re.sub(
                r'subtitle_provider\s*=\s*"[^"]*"',
                f'subtitle_provider = "{provider}"',
                text,
                count=1,
            )
        else:
            new_text = text.rstrip() + f'\nsubtitle_provider = "{provider}"\n'
        if new_text != text:
            cfg.write_text(new_text, encoding="utf-8")
    except Exception:
        pass
    return provider


