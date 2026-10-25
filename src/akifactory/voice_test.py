"""Ses testi — yalnizca audio; ~30 sn hikaye metni."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from akifactory import edge_tts_retry
from akifactory.paths import data_dir

edge_tts_retry.install()

# ~30 sn Turkce konusma (~12 karakter/sn → ~360 karakter)
VOICE_TEST_STORY_TR = (
    "Gece yarısına doğru eski kütüphanenin kapısı kendi kendine aralandı. "
    "Tozlu rafların arasından ince bir ışık süzüldü ve yerdeki taşın üzerinde "
    "silik bir yazı belirdi. Kimse bu yazıyı daha önce görmemişti; "
    "ama her harf, unutulmuş bir sırrın kapısını aralıyordu. "
    "Meraklı bir tarihçi not defterini açtı ve o gece, "
    "yüzyıllardır bekleyen hikâyeyi ilk kez sesli okudu."
)

VOICE_TEST_STORY_EN = (
    "Just past midnight, the old library door drifted open on its own. "
    "A thin light slid between dusty shelves and settled on a stone where "
    "a faded inscription appeared. No one had seen those marks before, "
    "yet each letter seemed to unlock a forgotten secret. "
    "A curious historian opened a notebook and, for the first time, "
    "read the waiting story aloud into the quiet night."
)


def samples_dir() -> Path:
    d = data_dir() / "voice_tests"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_story(lang_id: str = "tr") -> str:
    return VOICE_TEST_STORY_EN if (lang_id or "tr").lower().startswith("en") else VOICE_TEST_STORY_TR


def _edge_rate(voice_rate: float) -> str:
    """1.0 → +0%, 1.1 → +10%."""
    try:
        rate = float(voice_rate)
    except (TypeError, ValueError):
        rate = 1.0
    pct = int(round((rate - 1.0) * 100))
    pct = max(-50, min(100, pct))
    return f"{pct:+d}%"


async def _synthesize_edge_wav(
    text: str,
    out_path: Path,
    *,
    edge_voice: str,
    voice_rate: float = 1.0,
) -> None:
    import edge_tts
    from akifactory.rvc_tts import edge_voice_from_engine_name
    from akifactory.text_utils import prepare_script_for_engine

    spoken = prepare_script_for_engine(text, "tr") or text.strip()
    voice = edge_voice_from_engine_name(edge_voice or "tr-TR-AhmetNeural-Male")
    rate = _edge_rate(voice_rate)
    comm = edge_tts.Communicate(spoken, voice, rate=rate)
    await comm.save(str(out_path))


def synthesize_voice_test(
    *,
    tts_engine: str = "edge",
    production_language: str = "tr",
    edge_voice: str | None = None,
    rvc_voice: str | None = None,
    rvc_pitch: int = 0,
    rvc_index_rate: float = 0.65,
    voice_rate: float = 1.0,
    text: str | None = None,
) -> dict[str, Any]:
    """Secili motora gore ~30 sn hikaye seslendir — yalnizca WAV."""
    from akifactory import languages as lang_mod
    from akifactory.rvc_registry import get_voice as get_rvc_voice
    from akifactory.rvc_util import apply_post_rvc_to_file, configure_tts_rvc_chain
    from akifactory.text_utils import prepare_script_for_engine

    lang_id = (production_language or "tr").strip().lower()[:2] or "tr"
    engine = (tts_engine or "edge").strip().lower()
    story = (text or "").strip() or default_story(lang_id)
    spoken = prepare_script_for_engine(story, lang_id) or story
    # ~30 sn — fazla uzun metni kes
    spoken = spoken[:520].strip()

    tts_err = lang_mod.tts_validation_error(lang_id, engine)
    if tts_err:
        raise ValueError(tts_err)

    out_dir = samples_dir()
    token = uuid.uuid4().hex[:10]
    base_wav = out_dir / f"voice-test-{token}.wav"
    final_wav = base_wav
    chain = engine
    rvc_id = (rvc_voice or "").strip()
    rvc_label = ""

    if engine == "edge":
        edge = (edge_voice or "tr-TR-AhmetNeural-Male").strip()
        asyncio.run(
            _synthesize_edge_wav(
                spoken,
                base_wav,
                edge_voice=edge,
                voice_rate=voice_rate,
            )
        )
        chain = f"edge:{edge}"

    elif engine == "rvc":
        from akifactory.rvc_tts import convert_audio_file_sync, is_rvc_available

        if not rvc_id:
            raise ValueError("RVC sesi secin")
        if not is_rvc_available():
            raise RuntimeError("RVC modeli yok — models/rvc/ klasorunu kontrol edin")
        edge = (edge_voice or "tr-TR-AhmetNeural-Male").strip()
        configure_tts_rvc_chain(
            "rvc",
            rvc_voice=rvc_id,
            rvc_pitch=int(rvc_pitch),
            rvc_index_rate=float(rvc_index_rate),
            production_language=lang_id,
            edge_voice=edge,
        )
        asyncio.run(
            _synthesize_edge_wav(
                spoken,
                base_wav,
                edge_voice=edge,
                voice_rate=voice_rate,
            )
        )
        rvc_wav = base_wav.with_name(base_wav.stem + ".rvc.wav")
        convert_audio_file_sync(
            str(base_wav),
            str(rvc_wav),
            voice_id=rvc_id,
            pitch=int(rvc_pitch),
            index_rate=float(rvc_index_rate),
        )
        final_wav = rvc_wav
        meta = get_rvc_voice(rvc_id)
        rvc_label = meta.label if meta else rvc_id
        chain = f"edge→rvc:{rvc_label or rvc_id}"

    elif engine == "chatterbox":
        from akifactory.chatterbox_util import (
            normalize_turkish_tts_text,
            status_dict,
            synthesize_chatterbox_wav,
        )
        from akifactory.rvc_tts import is_rvc_available

        st = status_dict()
        if not st.get("package_ready"):
            raise RuntimeError(
                "Chatterbox paketi yok — python scripts/bootstrap.py --chatterbox"
            )
        if not rvc_id:
            raise ValueError("Chatterbox icin RVC sesi secin")
        if not is_rvc_available():
            raise RuntimeError("RVC modeli yok — models/rvc/ klasorunu kontrol edin")
        cb_text = (
            normalize_turkish_tts_text(spoken)
            if lang_id.startswith("tr")
            else spoken
        )
        synthesize_chatterbox_wav(
            cb_text,
            base_wav,
            voice_key="tr-male",
            lang="tr" if lang_id.startswith("tr") else "en",
            normalize=False,
        )
        configure_tts_rvc_chain(
            "chatterbox",
            rvc_voice=rvc_id,
            rvc_pitch=int(rvc_pitch),
            rvc_index_rate=float(rvc_index_rate),
            production_language=lang_id,
        )
        rvc_wav = base_wav.with_name(base_wav.stem + ".rvc.wav")
        if not apply_post_rvc_to_file(
            str(base_wav), str(rvc_wav), expected_chain="chatterbox"
        ):
            raise RuntimeError("RVC donusumu basarisiz")
        final_wav = rvc_wav
        meta = get_rvc_voice(rvc_id)
        rvc_label = meta.label if meta else rvc_id
        chain = f"chatterbox→rvc:{rvc_label or rvc_id}"
        spoken = cb_text

    else:
        raise ValueError(f"Desteklenmeyen ses motoru: {engine}")

    if not final_wav.is_file() or final_wav.stat().st_size < 500:
        raise RuntimeError("Ses dosyasi olusturulamadi")

    duration_sec = 0.0
    try:
        from moviepy.audio.io.AudioFileClip import AudioFileClip

        with AudioFileClip(str(final_wav)) as clip:
            duration_sec = round(float(clip.duration or 0), 1)
    except Exception:
        duration_sec = 0.0

    return {
        "ok": True,
        "filename": final_wav.name,
        "url": f"/api/voice/test/sample/{final_wav.name}",
        "chain": chain,
        "duration_sec": duration_sec,
        "text": spoken,
        "tts_engine": engine,
        "rvc_voice": rvc_id or None,
        "rvc_label": rvc_label or None,
    }
