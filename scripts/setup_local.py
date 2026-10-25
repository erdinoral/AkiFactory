"""
Tam yerel kurulum: Ollama modeli, Whisper, config.toml.

  python scripts/setup_local.py
  python scripts/setup_local.py --skip-ollama
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _p(msg: str) -> None:
    print(msg, flush=True)


def _pip(*packages: str) -> bool:
    cmd = [sys.executable, "-m", "pip", "install", "-U", *packages]
    _p(f"[pip] {' '.join(packages)}")
    return subprocess.run(cmd, env={**os.environ, "PYTHONUNBUFFERED": "1"}).returncode == 0


def _cuda_whisper_device() -> tuple[str, str]:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def _download_whisper(root: Path) -> bool:
    dest = root / "models" / "whisper-large-v3"
    if (dest / "model.bin").is_file():
        _p(f"[OK] Whisper zaten var: {dest}")
        return True
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        if not _pip("huggingface_hub"):
            return False
        from huggingface_hub import snapshot_download

    _p("[indir] faster-whisper large-v3 (~3 GB, bir kez)...")
    try:
        snapshot_download(
            repo_id="Systran/faster-whisper-large-v3",
            local_dir=str(dest),
            local_dir_use_symlinks=False,
        )
    except Exception as e:
        _p(f"[HATA] Whisper indirme: {e}")
        _p("  Manuel: https://huggingface.co/Systran/faster-whisper-large-v3 -> models/whisper-large-v3")
        return False
    _p(f"[OK] Whisper: {dest}")
    return True


def _ollama_pull(model: str) -> bool:
    if not shutil.which("ollama"):
        _p("[UYARI] Ollama kurulu degil: https://ollama.com")
        _p("  Kurduktan sonra: ollama pull " + model)
        return False
    _p(f"[ollama] Model cekiliyor: {model} (uzun surebilir)...")
    r = subprocess.run(["ollama", "pull", model], env=os.environ)
    return r.returncode == 0


def _write_config(root: Path, ollama_model: str, whisper_device: str, whisper_compute: str) -> None:
    example = root / "src" / "akifactory" / "engine" / "config.example.toml"
    target = root / "data" / "engine.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not example.is_file():
        _p("[HATA] config.example.toml yok")
        return
    text = example.read_text(encoding="utf-8")

    replacements = {
        'video_source = "pexels"': 'video_source = "local"',
        'llm_provider = "openai"': 'llm_provider = "ollama"',
        'subtitle_provider = "edge"': 'subtitle_provider = "whisper"',
        'ollama_base_url = ""': 'ollama_base_url = "http://127.0.0.1:11434/v1"',
        f'ollama_model_name = ""': f'ollama_model_name = "{ollama_model}"',
        'device = "CPU"': f'device = "{whisper_device}"',
        'compute_type = "int8"': f'compute_type = "{whisper_compute}"',
    }
    for old, new in replacements.items():
        if old in text:
            text = text.replace(old, new, 1)

    ui_block = (
        '\n# AkiFactory yerel mod (setup_local.py)\n'
        'tts_server = "azure-tts-v1"\n'
        'voice_name = "tr-TR-AhmetNeural-Male"\n'
        'language = "tr"\n'
    )
    if "tts_server" in text:
        import re

        text = re.sub(r'tts_server\s*=\s*"[^"]*"', 'tts_server = "azure-tts-v1"', text, count=1)
        if "voice_name" in text:
            text = re.sub(
                r'voice_name\s*=\s*"[^"]*"',
                'voice_name = "tr-TR-AhmetNeural-Male"',
                text,
                count=1,
            )
        else:
            text = text.replace("[ui]", "[ui]" + ui_block, 1)
    else:
        text = text.replace("[ui]", "[ui]" + ui_block, 1)

    target.write_text(text, encoding="utf-8")
    _p(f"[OK] engine.toml yazildi: {target}")


def _ensure_local_videos_dir(root: Path) -> None:
    d = root / "data" / "storage" / "local_videos"
    d.mkdir(parents=True, exist_ok=True)
    readme = d / "README.txt"
    if not readme.exists():
        readme.write_text(
            "Yerel video modu: Bu klasore .mp4 / .mov / .jpg koyun veya arayuzden yukleyin.\n"
            "Pexels/Pixabay API gerekmez.\n",
            encoding="utf-8",
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-ollama", action="store_true")
    ap.add_argument("--ollama-model", default="qwen3:8b")
    ap.add_argument("--skip-whisper", action="store_true")
    args = ap.parse_args()

    root = _root()
    if not (root / "src" / "akifactory" / "engine" / "server.py").is_file():
        _p(f"[HATA] Video motoru yok: {root}")
        return 1

    _p("=== AkiFactory — tam yerel kurulum ===")

    req = root / "requirements.txt"
    if req.is_file():
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req)],
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )

    _pip("pyttsx3", "huggingface_hub")

    w_dev, w_cmp = _cuda_whisper_device()
    _p(f"[whisper] device={w_dev}, compute_type={w_cmp}")

    if not args.skip_whisper:
        if not _download_whisper(root):
            _p("[UYARI] Whisper atlandi — altyazi uretimi basarisiz olabilir.")

    if not args.skip_ollama:
        _ollama_pull(args.ollama_model)

    _write_config(root, args.ollama_model, w_dev, w_cmp)
    _ensure_local_videos_dir(root)

    _p("")
    _p("--- Tamam ---")
    _p("1) Ollama servisi acik olsun (ollama serve / uygulama)")
    _p("2) Videolar: data/storage/local_videos veya arayuz 'Yerel dosya'")
    _p("3) Baslat: AkiFactory.bat")
    _p("4) Arayuz: TTS = Edge TTS, Video = Yerel dosya")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
