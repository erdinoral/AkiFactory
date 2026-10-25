"""
GPU profili — bozmadan GPU kullanan isler icin ortam + config senkronu.

GPU (guvenli):
  - Ollama (LLM) — ayri servis, NVIDIA varsa otomatik GPU
  - Whisper altyazi — faster-whisper cuda
  - FFmpeg NVENC — video encode (basarisiz olursa libx264)

CPU / bulut (degismez):
  - Edge TTS — internet
  - Pexels indirme — ag
  - MoviePy kesme/birlestirme (decode) — cogu CPU
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from akifactory.paths import engine_config_file
from akifactory.win_subprocess import run as _run_hidden


def has_nvidia_gpu() -> bool:
    if os.environ.get("AKI_FORCE_CPU") == "1":
        return False
    if not _which("nvidia-smi"):
        return False
    try:
        r = _run_hidden(
            ["nvidia-smi"],
            capture_output=True,
            timeout=8,
        )
        return r.returncode == 0
    except Exception:
        return False


def gpu_name() -> str:
    if not has_nvidia_gpu():
        return ""
    try:
        r = _run_hidden(
            [
                "nvidia-smi",
                "--query-gpu=name",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if r.returncode == 0:
            return (r.stdout or "").strip().splitlines()[0].strip()
    except Exception:
        pass
    return "NVIDIA GPU"


def ffmpeg_has_nvenc() -> bool:
    ffmpeg = _which("ffmpeg") or os.environ.get("IMAGEIO_FFMPEG_EXE")
    if not ffmpeg:
        try:
            import imageio_ffmpeg

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return False
    if not ffmpeg:
        return False
    try:
        r = _run_hidden(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return r.returncode == 0 and "h264_nvenc" in (r.stdout or "")
    except Exception:
        return False


def resolve_video_encoder(mode: str | None = None) -> str:
    """nvenc | libx264"""
    pref = (mode or os.environ.get("AKI_VIDEO_ENCODER") or "auto").strip().lower()
    if pref in ("cpu", "libx264", "off", "0", "false"):
        return "libx264"
    if pref == "nvenc":
        return "h264_nvenc" if ffmpeg_has_nvenc() else "libx264"
    if has_nvidia_gpu() and ffmpeg_has_nvenc():
        return "h264_nvenc"
    return "libx264"


def whisper_settings() -> tuple[str, str]:
    if has_nvidia_gpu():
        return "cuda", "float16"
    return "cpu", "int8"


def resolve_ffmpeg_exe() -> str:
    """Sistem veya imageio-ffmpeg paketindeki ffmpeg."""
    exe = _which("ffmpeg") or os.environ.get("IMAGEIO_FFMPEG_EXE") or ""
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe() or ""
    except Exception:
        return ""


def ffmpeg_env() -> dict[str, str]:
    """RVC / pydub / MoviePy alt surecleri icin ffmpeg yolu."""
    ffmpeg = resolve_ffmpeg_exe()
    if not ffmpeg:
        return {}
    out: dict[str, str] = {"IMAGEIO_FFMPEG_EXE": ffmpeg}
    ff_dir = str(Path(ffmpeg).resolve().parent)
    path = os.environ.get("PATH", "")
    if ff_dir.lower() not in path.lower().split(os.pathsep):
        out["PATH"] = ff_dir + os.pathsep + path
    return out


def apply_runtime_env() -> dict[str, str]:
    """Alt process'lere (motor) aktarilacak ortam degiskenleri."""
    gpu_ok = has_nvidia_gpu()
    encoder = resolve_video_encoder()
    w_dev, w_cmp = whisper_settings()

    profile = {
        "AKI_GPU_AVAILABLE": "1" if gpu_ok else "0",
        "AKI_GPU_NAME": gpu_name() if gpu_ok else "",
        "AKI_VIDEO_ENCODER": encoder,
        "AKI_WHISPER_DEVICE": w_dev,
        "AKI_WHISPER_COMPUTE": w_cmp,
        # Ollama ayri servis; VRAM catismasini azaltmak icin
        "OLLAMA_MAX_LOADED_MODELS": "1",
        "OLLAMA_NUM_PARALLEL": "1",
    }
    profile.update(ffmpeg_env())
    for key, val in profile.items():
        os.environ[key] = val
    return profile


def gpu_profile_for_ui() -> dict:
    gpu_ok = has_nvidia_gpu()
    encoder = resolve_video_encoder()
    w_dev, w_cmp = whisper_settings()
    subtitle_provider = "edge"
    try:
        cfg = engine_config_file()
        if cfg.is_file():
            text = cfg.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'subtitle_provider\s*=\s*"([^"]+)"', text)
            if m:
                subtitle_provider = m.group(1).strip().lower() or "edge"
    except Exception:
        pass
    if subtitle_provider == "whisper":
        sub_name = "Altyazi (Whisper)"
        sub_device = "GPU" if w_dev == "cuda" else "CPU"
        sub_note = w_dev
    else:
        sub_name = "Altyazi (Edge timing)"
        sub_device = "Bulut"
        sub_note = subtitle_provider
    return {
        "gpu_available": gpu_ok,
        "gpu_name": gpu_name() if gpu_ok else None,
        "video_encoder": encoder,
        "whisper_device": w_dev,
        "whisper_compute_type": w_cmp,
        "subtitle_provider": subtitle_provider,
        "tasks": [
            {
                "name": "Senaryo (Ollama)",
                "device": "GPU" if gpu_ok else "CPU",
                "note": "Ollama servisi — NVIDIA varsa otomatik",
            },
            {
                "name": sub_name,
                "device": sub_device,
                "note": sub_note,
            },
            {
                "name": "Video encode (FFmpeg)",
                "device": "GPU" if encoder == "h264_nvenc" else "CPU",
                "note": encoder,
            },
            {
                "name": "Ses (Edge TTS varsayilan)",
                "device": "Bulut",
                "note": "Yerel GPU kullanmaz",
            },
            {
                "name": "Ses (Chatterbox secilirse)",
                "device": "GPU" if gpu_ok else "CPU",
                "note": "Opsiyonel",
            },
        ],
    }


def sync_config_toml() -> bool:
    """engine.toml whisper + [akifactory] GPU satirlarini gunceller."""
    target = engine_config_file()
    if not target.is_file():
        return False

    text = target.read_text(encoding="utf-8")
    w_dev, w_cmp = whisper_settings()
    gpu_ok = has_nvidia_gpu()
    encoder = resolve_video_encoder()
    name = gpu_name()

    text = re.sub(
        r'device\s*=\s*"[^"]*"',
        f'device = "{w_dev}"',
        text,
        count=1,
    )
    text = re.sub(
        r'compute_type\s*=\s*"[^"]*"',
        f'compute_type = "{w_cmp}"',
        text,
        count=1,
    )

    block = (
        "\n[akifactory]\n"
        f"gpu_enabled = {'true' if gpu_ok else 'false'}\n"
        f'gpu_name = "{name}"\n'
        f'video_encoder = "{encoder}"\n'
        f'whisper_device = "{w_dev}"\n'
        f'whisper_compute_type = "{w_cmp}"\n'
    )
    if "[akifactory]" in text:
        # [^\[]* bir sonraki [section]'a kadar yer; strip() son \n'i silerse
        # whisper_compute_type = "float16"[features] birlesmesi olusur.
        text = re.sub(r"\n\[akifactory\][^\[]*", block, text, count=1)
        if not text.endswith("\n") and "[features]" in text:
            text = text.replace("[features]", "\n[features]", 1)
    else:
        text = text.rstrip() + "\n" + block

    target.write_text(text, encoding="utf-8")
    return True


def _which(cmd: str) -> str | None:
    from shutil import which

    return which(cmd)
