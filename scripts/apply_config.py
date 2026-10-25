"""engine.toml olusturur: Pexels, Ollama, Whisper (torch import YOK — hizli baslangic)."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import os

OLLAMA_MODEL = "qwen3.5:9b"


def _api_keys() -> tuple[str, str]:
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        from akifactory.stock_api_keys import get_pexels_key, get_pixabay_key

        return get_pexels_key(), get_pixabay_key()
    except Exception:
        return os.environ.get("AKI_PEXELS_KEY", "").strip(), os.environ.get("AKI_PIXABAY_KEY", "").strip()


def _p(msg: str) -> None:
    print(msg, flush=True)


def _whisper_device() -> tuple[str, str]:
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        from akifactory.win_subprocess import install_no_console_patch

        install_no_console_patch()
    except Exception:
        pass
    try:
        from akifactory.gpu import whisper_settings

        return whisper_settings()
    except Exception:
        pass
    if not shutil.which("nvidia-smi"):
        return "cpu", "int8"
    try:
        from akifactory.win_subprocess import run as _run_hidden

        r = _run_hidden(
            ["nvidia-smi"],
            capture_output=True,
            timeout=8,
        )
        if r.returncode == 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def _sync_ollama_model(target: Path) -> None:
    if not target.is_file():
        return
    text = target.read_text(encoding="utf-8")
    if f'ollama_model_name = "{OLLAMA_MODEL}"' in text:
        return
    text = re.sub(
        r'ollama_model_name\s*=\s*"[^"]*"',
        f'ollama_model_name = "{OLLAMA_MODEL}"',
        text,
        count=1,
    )
    target.write_text(text, encoding="utf-8")
    _p(f"[OK] Ollama model: {OLLAMA_MODEL}")


def _sync_max_concurrent_tasks(target: Path) -> None:
    """Seri uretim bellegi: motor ayni anda tek video task'i."""
    if not target.is_file():
        return
    text = target.read_text(encoding="utf-8")
    if re.search(r"max_concurrent_tasks\s*=\s*1\b", text):
        return
    if re.search(r"max_concurrent_tasks\s*=\s*\d+", text):
        text = re.sub(
            r"max_concurrent_tasks\s*=\s*\d+",
            "max_concurrent_tasks = 1",
            text,
            count=1,
        )
        target.write_text(text, encoding="utf-8")
        _p("[OK] max_concurrent_tasks = 1 (bellek)")


def _sync_stock_keys(target: Path) -> None:
    """Kullanicinin data/api_keys.json anahtarlarini engine.toml ile senkronla."""
    if not target.is_file():
        return
    pexels_key, pixabay_key = _api_keys()
    text = target.read_text(encoding="utf-8")
    if pexels_key:
        if "pexels_api_keys = []" in text:
            text = text.replace(
                "pexels_api_keys = []",
                f'pexels_api_keys = ["{pexels_key}"]',
                1,
            )
        elif pexels_key not in text:
            text = re.sub(
                r'pexels_api_keys\s*=\s*\[[^\]]*\]',
                f'pexels_api_keys = ["{pexels_key}"]',
                text,
                count=1,
            )
    else:
        text = re.sub(r'pexels_api_keys\s*=\s*\[[^\]]*\]', "pexels_api_keys = []", text, count=1)
    if pixabay_key:
        if "pixabay_api_keys = []" in text:
            text = text.replace(
                "pixabay_api_keys = []",
                f'pixabay_api_keys = ["{pixabay_key}"]',
                1,
            )
        elif pixabay_key not in text:
            text = re.sub(
                r"pixabay_api_keys\s*=\s*\[[^\]]*\]",
                f'pixabay_api_keys = ["{pixabay_key}"]',
                text,
                count=1,
            )
    else:
        text = re.sub(
            r"pixabay_api_keys\s*=\s*\[[^\]]*\]",
            "pixabay_api_keys = []",
            text,
            count=1,
        )
    target.write_text(text, encoding="utf-8")


def _sync_pixabay_key(target: Path) -> None:
    _, pixabay_key = _api_keys()
    if not pixabay_key or not target.is_file():
        return
    text = target.read_text(encoding="utf-8")
    if pixabay_key in text:
        return
    if "pixabay_api_keys = []" in text:
        text = text.replace(
            "pixabay_api_keys = []",
            f'pixabay_api_keys = ["{pixabay_key}"]',
            1,
        )
    else:
        text = re.sub(
            r"pixabay_api_keys\s*=\s*\[[^\]]*\]",
            f'pixabay_api_keys = ["{pixabay_key}"]',
            text,
            count=1,
        )
    target.write_text(text, encoding="utf-8")
    _p(f"[OK] Pixabay API key eklendi: {target}")


def _sync_material_directory(target: Path) -> None:
    """Stok klipleri gorev klasorune indir — cift dil EN icin ayni klipleri bulmak kolay."""
    if not target.is_file():
        return
    text = target.read_text(encoding="utf-8")
    if re.search(r'^material_directory\s*=\s*"task"', text, re.M):
        return
    new_text, n = re.subn(
        r'^material_directory\s*=\s*""',
        'material_directory = "task"',
        text,
        count=1,
        flags=re.M,
    )
    if n == 0:
        new_text, n = re.subn(
            r'^material_directory\s*=\s*"[^"]*"',
            'material_directory = "task"',
            text,
            count=1,
            flags=re.M,
        )
    if n:
        target.write_text(new_text, encoding="utf-8")
        _p("[OK] material_directory = task (cift dil klip paylasimi)")


def _config_ready(target: Path) -> bool:
    if not target.is_file():
        return False
    t = target.read_text(encoding="utf-8")
    return (
        'llm_provider = "ollama"' in t
        and "pexels_api_keys" in t
        and f'ollama_model_name = "{OLLAMA_MODEL}"' in t
    )


def _validate_config(target: Path) -> list[str]:
    """Zorunlu alanlari kontrol et — Turkce uyari listesi dondurur."""
    errors: list[str] = []
    if not target.is_file():
        return ["engine.toml bulunamadi"]
    try:
        text = target.read_text(encoding="utf-8")
    except Exception as exc:
        return [f"engine.toml okunamadi: {exc}"]
    if not text.strip():
        return ["engine.toml bos"]
    # Basit TOML: eslesmeyen tirnak / bos dosya
    if text.count('"') % 2 != 0:
        errors.append("engine.toml tirnak isaretleri eslesmiyor (bozuk TOML olabilir)")

    def _has(field: str) -> bool:
        return bool(re.search(rf"^{re.escape(field)}\s*=", text, re.M))

    def _val(field: str) -> str:
        m = re.search(rf'^{re.escape(field)}\s*=\s*"([^"]*)"', text, re.M)
        return (m.group(1).strip() if m else "")

    required = (
        "llm_provider",
        "ollama_base_url",
        "ollama_model_name",
        "subtitle_provider",
    )
    for field in required:
        if not _has(field):
            errors.append(f"Eksik alan: {field}")
            continue
        if field in ("ollama_base_url", "ollama_model_name", "llm_provider", "subtitle_provider"):
            if not _val(field):
                errors.append(f"Bos deger: {field}")

    provider = _val("llm_provider")
    if provider and provider != "ollama":
        errors.append(f'llm_provider "{provider}" — AkiFactory icin "ollama" olmali')

    model = _val("ollama_model_name")
    if model and model != OLLAMA_MODEL:
        _p(f"[UYARI] ollama_model_name={model} (beklenen {OLLAMA_MODEL}) — senkronlanacak")

    sub = _val("subtitle_provider")
    if sub and sub not in {"edge", "whisper"}:
        errors.append(f'subtitle_provider "{sub}" gecersiz (edge veya whisper)')

    if "pexels_api_keys" not in text:
        errors.append("Eksik alan: pexels_api_keys")

    return errors


def _ensure_features_block(target: Path) -> None:
    if not target.is_file():
        return
    text = target.read_text(encoding="utf-8")
    if "[features]" in text:
        return
    text = text.rstrip() + (
        "\n\n[features]\n"
        "stock_local_failover = false\n"
        "estimate_api = false\n"
        "topic_similarity_warn = false\n"
        "encrypt_api_keys = false\n"
    )
    target.write_text(text, encoding="utf-8")
    _p("[OK] [features] blogu eklendi (varsayilan kapali)")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    example = root / "src" / "akifactory" / "engine" / "config.example.toml"
    target = root / "data" / "engine.toml"
    target.parent.mkdir(parents=True, exist_ok=True)

    if _config_ready(target):
        _sync_ollama_model(target)
        _sync_max_concurrent_tasks(target)
        _sync_stock_keys(target)
        _sync_material_directory(target)
        _ensure_features_block(target)
        errs = _validate_config(target)
        if errs:
            for e in errs:
                _p(f"[HATA] {e}")
            return 1
        _p(f"[OK] engine.toml hazir: {target}")
        return 0

    _p("[config] engine.toml yaziliyor...")
    if not example.is_file():
        _p(f"[HATA] {example} yok")
        return 1

    pexels_key, pixabay_key = _api_keys()
    text = example.read_text(encoding="utf-8")
    text = text.replace('llm_provider = "openai"', 'llm_provider = "ollama"', 1)
    # Varsayilan Edge TTS — edge altyazi senkronu; yerel TTS (chatterbox/rvc) icin whisper tercih edilir
    text = text.replace('subtitle_provider = "whisper"', 'subtitle_provider = "edge"', 1)
    text = text.replace('ollama_base_url = ""', 'ollama_base_url = "http://127.0.0.1:11434/v1"', 1)
    text = text.replace('ollama_model_name = ""', f'ollama_model_name = "{OLLAMA_MODEL}"', 1)

    if pexels_key and "pexels_api_keys = []" in text:
        text = text.replace(
            "pexels_api_keys = []",
            f'pexels_api_keys = ["{pexels_key}"]',
            1,
        )
    elif pexels_key and pexels_key not in text:
        text = re.sub(
            r'pexels_api_keys\s*=\s*\[[^\]]*\]',
            f'pexels_api_keys = ["{pexels_key}"]',
            text,
            count=1,
        )

    if pixabay_key and "pixabay_api_keys = []" in text:
        text = text.replace(
            "pixabay_api_keys = []",
            f'pixabay_api_keys = ["{pixabay_key}"]',
            1,
        )
    elif pixabay_key:
        text = re.sub(
            r"pixabay_api_keys\s*=\s*\[[^\]]*\]",
            f'pixabay_api_keys = ["{pixabay_key}"]',
            text,
            count=1,
        )

    w_dev, w_cmp = _whisper_device()
    text = text.replace('device = "CPU"', f'device = "{w_dev}"', 1)
    text = text.replace('device = "cpu"', f'device = "{w_dev}"', 1)
    text = text.replace('compute_type = "int8"', f'compute_type = "{w_cmp}"', 1)

    ui = (
        "\n# AkiFactory\n"
        'tts_server = "azure-tts-v1"\n'
        'voice_name = "tr-TR-AhmetNeural-Male"\n'
        'language = "tr"\n'
        'subtitle_position = "bottom"\n'
    )
    if "tts_server" not in text:
        text = text.replace("[ui]", "[ui]" + ui, 1)
    else:
        text = re.sub(r'tts_server\s*=\s*"[^"]*"', 'tts_server = "azure-tts-v1"', text, count=1)
        if "voice_name" in text:
            text = re.sub(
                r'voice_name\s*=\s*"[^"]*"',
                'voice_name = "tr-TR-AhmetNeural-Male"',
                text,
                count=1,
            )
        else:
            text = text.replace("[ui]", "[ui]" + ui, 1)

    # Feature flags — varsayilan kapali (Faz 4)
    if "[features]" not in text:
        text += (
            "\n[features]\n"
            "stock_local_failover = false\n"
            "estimate_api = false\n"
            "topic_similarity_warn = false\n"
            "encrypt_api_keys = false\n"
        )

    target.write_text(text, encoding="utf-8")
    _sync_material_directory(target)
    errs = _validate_config(target)
    if errs:
        for e in errs:
            _p(f"[HATA] {e}")
        return 1
    _p(f"[OK] {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
