"""H3 kliplerinde 90 derece yan yatmis goruntu tespiti (Ollama vision).

H3, 9:16 t2v sahnelerinde ara sira yatay sahneyi dikey kareye yan yatik cizer;
devam klipleri son kareden basladigi icin yatiklik zincir boyunca yayilir.
"""

from __future__ import annotations

import asyncio
import base64
import subprocess
from pathlib import Path

import httpx

from akifactory import ollama_util

PROMPT = (
    "Look at this photo. Is the scene upright, or is the whole image rotated "
    "90 degrees sideways (sky/horizon on the left or right edge, people lying "
    "sideways, buildings pointing left/right)? Answer with exactly one word: "
    "UPRIGHT or ROTATED."
)
_FRAME_WIDTH = 360
_KEEP_ALIVE = "2m"


async def _model_capabilities(model: str) -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{ollama_util.ollama_api_root()}/api/show", json={"model": model}
            )
        if r.status_code != 200:
            return []
        return [str(c) for c in (r.json().get("capabilities") or [])]
    except Exception:
        return []


async def vision_model() -> str:
    """Config modeli gorsel destekliyorsa onu, yoksa yuklu bir vision modeli."""
    model = ollama_util.get_config_model()
    if model and "vision" in await _model_capabilities(model):
        return model
    from akifactory.llm_profiles import resolve_vision_model

    try:
        installed = await ollama_util.list_installed_models()
    except Exception:
        return ""
    return resolve_vision_model(installed)


def _ffmpeg_exe() -> str | None:
    from akifactory.outros import _ffmpeg_exe as find

    return find()


def _frame_b64(ffmpeg: str, clip: Path, t: float) -> str | None:
    try:
        r = subprocess.run(
            [
                ffmpeg, "-v", "error", "-ss", f"{t:.2f}", "-i", str(clip),
                "-frames:v", "1", "-vf", f"scale={_FRAME_WIDTH}:-2",
                "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
            ],
            capture_output=True,
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return None
    if r.returncode != 0 or len(r.stdout) < 500:
        return None
    return base64.b64encode(r.stdout).decode()


async def _is_rotated_frame(model: str, image_b64: str) -> bool:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT, "images": [image_b64]}],
        "stream": False,
        "think": False,
        "keep_alive": _KEEP_ALIVE,
        "options": {"temperature": 0, "num_predict": 8},
    }
    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post(ollama_util.OLLAMA_CHAT_URL, json=body)
    r.raise_for_status()
    answer = ((r.json().get("message") or {}).get("content") or "").upper()
    return "ROTATED" in answer


async def find_rotated(clips: list[Path], clip_sec: float = 5.0) -> list[int] | None:
    """Yan yatik kliplerin indeksleri; vision model/ffmpeg yoksa None.

    Klip basina 3 kare bakilir, cogunluk ROTATED derse klip yatik sayilir.
    """
    model = await vision_model()
    ffmpeg = _ffmpeg_exe()
    if not model or not ffmpeg:
        return None
    sec = max(1.5, float(clip_sec or 5.0))
    times = (0.5, sec / 2, sec - 0.5)
    rotated: list[int] = []
    try:
        for i, clip in enumerate(clips):
            votes = checked = 0
            for t in times:
                b64 = await asyncio.to_thread(_frame_b64, ffmpeg, clip, t)
                if not b64:
                    continue
                checked += 1
                votes += await _is_rotated_frame(model, b64)
            if checked and votes * 2 > checked:
                rotated.append(i)
    except Exception:
        return None
    finally:
        await ollama_util.unload_all_models()
    return rotated
