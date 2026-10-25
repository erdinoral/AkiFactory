"""
Chatterbox Multilingual (Resemble) — yerel TR TTS.

  python scripts/bootstrap.py --chatterbox
  python scripts/setup_chatterbox.py

ONEMLI: chatterbox-tts PyPI torch==2.6.0 (CPU) dayatir — AkiFactory CUDA
torch'unu BOZAR. Bu script paketi --no-deps kurar; mevcut GPU torch korunur.

Model Hugging Face'den ilk kullanimda iner.
Referans: Edge Ahmet/Emel wav (models/chatterbox/ref/).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _p(msg: str) -> None:
    print(msg, flush=True)


def _pip(*args: str, index_url: str | None = None) -> bool:
    cmd = [sys.executable, "-m", "pip", "install", *args]
    if index_url:
        cmd.extend(["--index-url", index_url])
    return (
        subprocess.run(
            cmd,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        ).returncode
        == 0
    )


def _torch_snapshot() -> tuple[str, bool]:
    try:
        import torch

        return str(torch.__version__), bool(torch.cuda.is_available())
    except Exception:
        return "", False


def _restore_cuda_torch_if_needed(before_ver: str, before_cuda: bool) -> None:
    """chatterbox pip yanlislikla CPU torch indirdiyse cu128 geri yukle."""
    after_ver, after_cuda = _torch_snapshot()
    if before_cuda and after_cuda and "+cu" in after_ver:
        return
    if before_cuda and (not after_cuda or "+cpu" in after_ver.lower() or after_ver.startswith("2.6.0")):
        _p("[UYARI] CUDA torch bozuldu — cu128 geri yukleniyor...")
        _pip(
            "--force-reinstall",
            "torch",
            "torchvision",
            "torchaudio",
            index_url="https://download.pytorch.org/whl/cu128",
        )
        # AkiFactory pinleri
        _pip("numpy==1.26.0", "pillow>=9.2,<11")
        ver, cuda = _torch_snapshot()
        _p(f"[torch] simdi: {ver} cuda={cuda}")


async def _edge_reference_wav(dest: Path, *, voice: str, text: str) -> bool:
    try:
        import edge_tts
    except ImportError:
        if not _pip("edge-tts"):
            return False
        import edge_tts

    try:
        comm = edge_tts.Communicate(text, voice)
        await comm.save(str(dest))
        return dest.is_file() and dest.stat().st_size > 2000
    except Exception as e:
        _p(f"[UYARI] Edge referans sesi alinamadi ({voice}): {e}")
        return False


def _install_chatterbox_safe() -> bool:
    """torch/transformers/diffusers PINLERINI dokunmadan kur."""
    # Cekirdek paket — bagimliliklari atla (torch==2.6.0 dayatmasini engelle)
    if not _pip("--no-deps", "chatterbox-tts"):
        return False

    # Inference icin gerekli ekstra paketler (gradio gerekmez)
    extras = [
        "conformer==0.3.2",
        "resemble-perth>=1.0.0",
        "s3tokenizer",
        "pykakasi==2.3.0",
        "spacy-pkuseg",
        "pyloudnorm",
        "einops>=0.6.1",
        "omegaconf",
    ]
    # Mevcut librosa/transformers/diffusers yeterli; zorla dusurme
    return _pip(*extras)


def main() -> int:
    # Windows: HF symlink ayricaligi yoksa WinError 1314 — kopya kullan
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    root = _root()
    cache = root / "models" / "chatterbox"
    ref_dir = cache / "ref"
    ref_dir.mkdir(parents=True, exist_ok=True)

    _p("=== AkiFactory — Chatterbox Multilingual (TR + RVC) ===")
    _p(f"[bilgi] Model/ref klasoru: {cache}")
    _p("[bilgi] Guvenli kurulum: chatterbox-tts --no-deps (CUDA torch korunur).")

    before_ver, before_cuda = _torch_snapshot()
    _p(f"[torch] once: {before_ver or '?'} cuda={before_cuda}")
    if not before_cuda:
        _p("[UYARI] CUDA torch yok — once GPU torch kurun (cu128). Yine de denenecek.")

    if not _install_chatterbox_safe():
        _p("[HATA] chatterbox-tts kurulamadi — pip ve interneti kontrol edin.")
        return 1

    _restore_cuda_torch_if_needed(before_ver, before_cuda)
    after_ver, after_cuda = _torch_snapshot()
    _p(f"[torch] sonra: {after_ver or '?'} cuda={after_cuda}")

    male = ref_dir / "tr_speaker_male.wav"
    female = ref_dir / "tr_speaker_female.wav"
    male_text = (
        "Merhaba. Bu AkiFactory icin Turkce erkek anlatim referansidir. "
        "Tarih ve gizem videolari icin net ve akici bir ses tonu."
    )
    female_text = (
        "Merhaba. Bu AkiFactory icin Turkce kadin anlatim referansidir. "
        "Tarih ve gizem icerikleri icin dogal bir konusma ornegi."
    )
    if not male.is_file():
        _p("[referans] Edge Ahmet → tr_speaker_male.wav...")
        if asyncio.run(
            _edge_reference_wav(male, voice="tr-TR-AhmetNeural", text=male_text)
        ):
            _p(f"[OK] {male}")
        else:
            _p("[UYARI] Erkek referans atlandi.")
    else:
        _p(f"[OK] Referans mevcut: {male.name}")
    if not female.is_file():
        _p("[referans] Edge Emel → tr_speaker_female.wav...")
        if asyncio.run(
            _edge_reference_wav(female, voice="tr-TR-EmelNeural", text=female_text)
        ):
            _p(f"[OK] {female}")
        else:
            _p("[UYARI] Kadin referans atlandi.")
    else:
        _p(f"[OK] Referans mevcut: {female.name}")

    _p("[test] Chatterbox Multilingual import + kisa sentez...")
    try:
        import torch

        sys.path.insert(0, str(root / "src"))
        from akifactory.chatterbox_util import _get_model

        device = "cuda" if torch.cuda.is_available() else "cpu"
        _p(f"[cihaz] {device} — model yukleniyor (ilk sefer uzun surebilir)...")
        model = _get_model(device)
        test_out = cache / "_kurulum_test.wav"
        text = "Merhaba. Bu Chatterbox Multilingual Turkce kurulum testidir."
        kwargs: dict = {"language_id": "tr"}
        if male.is_file():
            kwargs["audio_prompt_path"] = str(male)
        wav = model.generate(text, **kwargs)
        # torchaudio.save (torch 2.11) torchcodec ister — soundfile kullan
        import numpy as np
        import soundfile as sf

        audio = wav.detach().cpu().numpy()
        if audio.ndim > 1:
            audio = np.squeeze(audio)
        sf.write(str(test_out), audio, int(model.sr))
        if not test_out.is_file() or test_out.stat().st_size < 500:
            _p("[HATA] Test wav olusturulamadi.")
            return 1
        (cache / ".chatterbox_ready").write_text("ok", encoding="utf-8")
        _p(f"[OK] Test ses: {test_out}")
    except Exception as e:
        _p(f"[HATA] Chatterbox test basarisiz: {e}")
        _p("  GPU / torch / internet (HF model) kontrol edin.")
        _p("  Not: pip asla 'chatterbox-tts'i bagimliliklarla kurmayin (torch CPU olur).")
        return 1

    _p("")
    _p("[OK] Chatterbox hazir. Arayuzde: Chatterbox -> RVC")
    _p("  RVC modeli secili olmali (models/rvc/).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
