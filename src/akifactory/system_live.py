"""Canli sistem durumu — API paneli ve healthcheck scripti icin ortak kaynak."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from akifactory import gpu as gpu_mod
from akifactory import ollama_util
from akifactory import production_queue as queue_mod
from akifactory import stock_api_keys
from akifactory.paths import app_root, data_dir
from akifactory.win_subprocess import run as _run_hidden

DEFAULT_ENGINE_BASE = "http://127.0.0.1:8080"
MIN_DISK_FREE_GB = 5.0


def _human_bytes(num: int) -> str:
    if num < 1024:
        return f"{num} B"
    if num < 1024 * 1024:
        return f"{num / 1024:.1f} KB"
    if num < 1024 * 1024 * 1024:
        return f"{num / (1024 * 1024):.1f} GB"
    return f"{num / (1024 * 1024 * 1024):.2f} TB"


def disk_usage_for(path: Path) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(path)
        free_gb = usage.free / (1024**3)
        return {
            "path": str(path),
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "free_gb": round(free_gb, 2),
            "free_human": _human_bytes(usage.free),
            "total_human": _human_bytes(usage.total),
            "ok": free_gb >= MIN_DISK_FREE_GB,
            "warning": None if free_gb >= MIN_DISK_FREE_GB else f"Disk alani dusuk (< {MIN_DISK_FREE_GB:.0f} GB)",
        }
    except Exception as exc:
        return {
            "path": str(path),
            "ok": False,
            "warning": str(exc),
            "free_human": "?",
            "total_human": "?",
        }


def gpu_live_stats() -> dict[str, Any]:
    if not gpu_mod.has_nvidia_gpu():
        return {
            "available": False,
            "name": None,
            "memory_used_mb": None,
            "memory_total_mb": None,
            "memory_used_pct": None,
            "utilization_pct": None,
            "temperature_c": None,
        }
    try:
        r = _run_hidden(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout or "nvidia-smi hatasi").strip())
        line = (r.stdout or "").strip().splitlines()[0]
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            raise RuntimeError("nvidia-smi beklenmeyen cikti")
        name, used, total, util, temp = parts[0], parts[1], parts[2], parts[3], parts[4]
        used_i = int(float(used))
        total_i = int(float(total))
        pct = round(100.0 * used_i / max(total_i, 1), 1)
        return {
            "available": True,
            "name": name,
            "memory_used_mb": used_i,
            "memory_total_mb": total_i,
            "memory_used_pct": pct,
            "memory_used_human": f"{used_i} / {total_i} MB",
            "utilization_pct": int(float(util)) if util not in ("", "[N/A]") else None,
            "temperature_c": int(float(temp)) if temp not in ("", "[N/A]") else None,
        }
    except Exception as exc:
        return {
            "available": True,
            "name": gpu_mod.gpu_name() or "NVIDIA GPU",
            "memory_used_mb": None,
            "memory_total_mb": None,
            "memory_used_pct": None,
            "utilization_pct": None,
            "temperature_c": None,
            "warning": str(exc),
        }


async def ollama_loaded_models() -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(ollama_util.OLLAMA_PS_URL)
        if r.status_code != 200:
            return []
        out: list[dict[str, Any]] = []
        for entry in r.json().get("models") or []:
            name = (entry.get("name") or entry.get("model") or "").strip()
            if not name:
                continue
            vram = entry.get("size_vram") or entry.get("size")
            out.append(
                {
                    "name": name,
                    "size_vram_bytes": int(vram) if vram else None,
                    "size_vram_human": _human_bytes(int(vram)) if vram else None,
                }
            )
        return out
    except Exception:
        return []


async def engine_api_ok(engine_base: str = DEFAULT_ENGINE_BASE) -> dict[str, Any]:
    base = (engine_base or DEFAULT_ENGINE_BASE).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{base}/docs")
        ok = r.status_code == 200
        return {"ok": ok, "url": base, "status_code": r.status_code}
    except Exception as exc:
        return {"ok": False, "url": base, "error": str(exc)}


async def fetch_live_status(
    *,
    engine_base: str = DEFAULT_ENGINE_BASE,
    include_quota: bool = True,
    probe_ollama: bool = False,
) -> dict[str, Any]:
    """Salt okunur canli sistem ozeti."""
    from akifactory import first_run as setup_mod

    ollama = await ollama_util.fetch_status(probe=probe_ollama)
    loaded = await ollama_loaded_models()
    ffmpeg_ok, ffmpeg_hint = setup_mod.check_ffmpeg()
    gpu_profile = gpu_mod.gpu_profile_for_ui()
    gpu_live = gpu_live_stats()
    disk_data = disk_usage_for(data_dir())
    disk_app = disk_usage_for(app_root())
    queue = queue_mod.get_snapshot()
    engine = await engine_api_ok(engine_base)

    quota: dict[str, Any] | None = None
    if include_quota:
        try:
            quota = await stock_api_keys.fetch_quota()
        except Exception:
            quota = None

    return {
        "ts": time.time(),
        "gpu": {**gpu_profile, "live": gpu_live},
        "disk": {"data": disk_data, "app_root": disk_app},
        "ollama": {
            **ollama,
            "loaded_models": loaded,
            "loaded_count": len(loaded),
        },
        "ffmpeg": {"ok": ffmpeg_ok, "hint": ffmpeg_hint},
        "engine_api": engine,
        "queue": {
            "processing": queue.get("processing"),
            "pending_count": queue.get("pending_count"),
            "active_count": queue.get("active_count"),
            "current_label": (queue.get("current") or {}).get("label"),
        },
        "stock_quota": quota,
        "pexels_configured": bool(stock_api_keys.get_pexels_key()),
        "pixabay_configured": bool(stock_api_keys.get_pixabay_key()),
    }


def healthcheck_lines(snapshot: dict[str, Any]) -> list[tuple[str, bool, str]]:
    """(baslik, ok, detay) satirlari — CLI icin."""
    lines: list[tuple[str, bool, str]] = []

    ff = snapshot.get("ffmpeg") or {}
    lines.append(("ffmpeg", bool(ff.get("ok")), str(ff.get("hint") or "")))

    oll = snapshot.get("ollama") or {}
    lines.append(
        (
            "Ollama servisi",
            bool(oll.get("running")),
            "calisiyor" if oll.get("running") else (oll.get("model_error") or "calismiyor"),
        )
    )
    model = oll.get("model_name") or ollama_util.get_config_model() or "?"
    models = oll.get("models") or []
    model_ok = model in models if oll.get("running") else False
    lines.append(
        (
            f"LLM modeli ({model})",
            model_ok,
            "yuklu" if model_ok else f"eksik — ollama pull {model}",
        )
    )

    gpu = (snapshot.get("gpu") or {}).get("live") or {}
    if gpu.get("available"):
        vram = gpu.get("memory_used_human") or "?"
        util = gpu.get("utilization_pct")
        util_s = f", GPU %{util}" if util is not None else ""
        temp = gpu.get("temperature_c")
        temp_s = f", {temp}°C" if temp is not None else ""
        lines.append(
            (
                "NVIDIA GPU",
                True,
                f"{gpu.get('name') or 'GPU'} — VRAM {vram}{util_s}{temp_s}",
            )
        )
    else:
        lines.append(("NVIDIA GPU", False, "yok veya devre disi (CPU modu)"))

    disk = ((snapshot.get("disk") or {}).get("data") or {})
    lines.append(
        (
            "Disk (data/)",
            bool(disk.get("ok")),
            f"bos: {disk.get('free_human', '?')} / {disk.get('total_human', '?')}"
            + (f" — {disk['warning']}" if disk.get("warning") else ""),
        )
    )

    engine = snapshot.get("engine_api") or {}
    if engine.get("ok"):
        lines.append(("motor API", True, str(engine.get("url") or DEFAULT_ENGINE_BASE)))
    else:
        err = engine.get("error") or "yanit yok"
        lines.append(("motor API", False, f"calismiyor — {err} (uygulama kapali olabilir)"))

    px = snapshot.get("pexels_configured")
    pb = snapshot.get("pixabay_configured")
    lines.append(("Pexels API key", bool(px), "tanimli" if px else "eksik"))
    lines.append(("Pixabay API key", bool(pb), "tanimli" if pb else "eksik"))

    quota = snapshot.get("stock_quota") or {}
    pex = quota.get("pexels")
    if isinstance(pex, dict) and pex.get("ok"):
        rem = pex.get("remaining")
        lim = pex.get("limit")
        detail = f"kalan {rem}/{lim}" if rem is not None and lim is not None else "baglanti OK"
        lines.append(("Pexels kota", True, detail))
    elif px:
        err = (pex or {}).get("error") if isinstance(pex, dict) else "test edilemedi"
        lines.append(("Pexels kota", False, str(err or "test edilemedi")))

    return lines


async def run_healthcheck_async(*, engine_base: str = DEFAULT_ENGINE_BASE) -> tuple[int, list[str]]:
    snap = await fetch_live_status(engine_base=engine_base, include_quota=True, probe_ollama=False)
    rows = healthcheck_lines(snap)
    out: list[str] = ["AkiFactory sistem kontrolu", ""]
    critical_ok = True
    for title, ok, detail in rows:
        mark = "OK" if ok else "!!"
        out.append(f"  [{mark}] {title}: {detail}")
        if title in ("ffmpeg", "Ollama servisi", "Disk (data/)") or title.startswith("LLM modeli"):
            if not ok:
                critical_ok = False

    out.append("")
    if critical_ok:
        out.append("Sonuc: Uretim icin temel gereksinimler karsilaniyor.")
    else:
        out.append("Sonuc: Eksik adimlar var — AkiFactory.bat veya Ayarlar → Sistem.")
    return (0 if critical_ok else 1), out
