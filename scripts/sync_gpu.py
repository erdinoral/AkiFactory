"""GPU profilini config.toml ve ortam degiskenlerine yazar (hizli, torch yok)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    from akifactory.win_subprocess import install_no_console_patch

    install_no_console_patch()
except Exception:
    pass

from akifactory.gpu import (  # noqa: E402
    apply_runtime_env,
    gpu_profile_for_ui,
    sync_config_toml,
)


def _p(msg: str) -> None:
    print(msg, flush=True)


def main() -> int:
    profile = apply_runtime_env()
    sync_config_toml()
    ui = gpu_profile_for_ui()
    _p(f"[gpu] NVIDIA: {'evet' if ui['gpu_available'] else 'hayir'}")
    if ui.get("gpu_name"):
        _p(f"[gpu] Kart: {ui['gpu_name']}")
    _p(f"[gpu] Whisper: {profile['AKI_WHISPER_DEVICE']} / {profile['AKI_WHISPER_COMPUTE']}")
    _p(f"[gpu] Video encode: {profile['AKI_VIDEO_ENCODER']}")
    _p("[gpu] Ollama: GPU (servis otomatik) | Edge TTS: bulut")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
