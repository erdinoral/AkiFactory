"""Turkce metin duzeltme — ASCII klavye ciktisini dogru yazima cevirir."""

from __future__ import annotations

from loguru import logger

_TR_LANG_PREFIXES = ("tr",)


def is_turkish_language(video_language: str) -> bool:
    return (video_language or "").strip().lower().startswith(_TR_LANG_PREFIXES)


def apply_turkish_orthography(text: str, video_language: str = "") -> str:
    """
    qwen/Ollama bazen 'Turkiye', 'guzel', 'sehir' gibi ASCII Turkce yazar.
    Bu fonksiyon metni Türkiye, güzel, şehir gibi dogru yazima cevirir.
    """
    if not text or not is_turkish_language(video_language):
        return text

    try:
        from turkish.deasciifier import Deasciifier

        fixed = Deasciifier(text).convert_to_turkish()
        if fixed and fixed.strip():
            if fixed != text:
                logger.info("Turkish orthography applied (deasciify)")
            return fixed.strip()
    except ImportError:
        logger.warning(
            "turkish-deasciifier kurulu degil. "
            "Kurulum: pip install git+https://github.com/emres/turkish-deasciifier.git"
        )
    except Exception as exc:
        logger.warning(f"Turkish deasciify failed: {exc}")

    return text
