"""H3 Studio otomatik baslatma — pterm + uvicorn yedegi.

AkiFactory uretimde Studio kapaliysa Pinokio uzerinden Start dener;
Comfy zaten aciksa yalnizca Studio uvicorn baslatir.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import httpx

APP_ID = "minimax-h3-studio.git"
DEFAULT_BASE_URL = "http://127.0.0.1:8787"
ENSURE_TIMEOUT_SEC = 420

ProgressCb = Callable[[str, dict[str, Any]], None] | None


def pinokio_home() -> Path | None:
    env = (os.environ.get("PINOKIO_HOME") or "").strip()
    if env:
        p = Path(env)
        if p.is_dir():
            return p
    cfg = Path.home() / ".pinokio" / "config.json"
    try:
        if cfg.is_file():
            data = json.loads(cfg.read_text(encoding="utf-8"))
            home = Path(str(data.get("home") or "").strip())
            if home.is_dir():
                return home
    except Exception:
        pass
    for cand in (Path("D:/pinokio"), Path("C:/pinokio")):
        if cand.is_dir():
            return cand
    return None


def pterm_exe() -> Path | None:
    home = pinokio_home()
    cands: list[Path] = []
    if home:
        cands.extend(
            [
                home / "bin" / "npm" / "pterm.cmd",
                home / "bin" / "npm" / "pterm.exe",
                home / "bin" / "npm" / "pterm",
                home / "bin" / "pterm.cmd",
                home / "bin" / "pterm",
            ]
        )
    for d in (os.environ.get("PATH") or "").split(os.pathsep):
        if not d:
            continue
        for name in ("pterm.cmd", "pterm.exe", "pterm"):
            cands.append(Path(d) / name)
    for c in cands:
        try:
            if c.is_file():
                return c
        except Exception:
            continue
    return None


def studio_install_dir() -> Path | None:
    home = pinokio_home()
    if not home:
        return None
    p = home / "api" / APP_ID
    if p.is_dir() and (p / "start.js").is_file():
        return p
    api = home / "api"
    if not api.is_dir():
        return None
    for child in api.iterdir():
        if not child.is_dir():
            continue
        name = child.name.lower()
        if "minimax" in name and "h3" in name and (child / "start.js").is_file():
            return child
    return None


def studio_python() -> Path | None:
    root = studio_install_dir()
    if not root:
        return None
    for rel in (
        Path("app") / "env" / "Scripts" / "python.exe",
        Path("app") / "env" / "bin" / "python",
    ):
        py = root / rel
        if py.is_file():
            return py
    return None


async def _pterm_json(*args: str, timeout: float = 60.0) -> dict[str, Any] | None:
    exe = pterm_exe()
    if not exe:
        return None
    try:
        kwargs: dict[str, Any] = {
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        proc = await asyncio.create_subprocess_exec(str(exe), *args, **kwargs)
        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return None
        raw = (out_b or b"").decode("utf-8", errors="replace").strip()
        if not raw:
            raw = (err_b or b"").decode("utf-8", errors="replace").strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return None
        data = json.loads(raw[start : end + 1])
        return data if isinstance(data, dict) else None
    except Exception:
        return None


async def pterm_app_status() -> dict[str, Any] | None:
    st = await _pterm_json("status", APP_ID, timeout=45.0)
    if st:
        return st
    path = studio_install_dir()
    if path:
        return await _pterm_json("status", str(path), timeout=45.0)
    return None


async def probe_health(url: str) -> dict[str, Any]:
    root = (url or "").strip().rstrip("/")
    if not root:
        root = DEFAULT_BASE_URL
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{root}/api/health")
        if r.status_code != 200:
            return {
                "ok": False,
                "online": False,
                "base_url": root,
                "detail": f"HTTP {r.status_code}",
            }
        data = r.json() if r.content else {}
        comfy = bool(data.get("comfy"))
        return {
            "ok": bool(data.get("studio")) and comfy,
            "online": bool(data.get("studio")),
            "comfy": comfy,
            "base_url": root,
            "detail": "ok" if comfy else "Studio acik ama ComfyUI kapali",
            "raw": data,
        }
    except Exception as e:
        return {
            "ok": False,
            "online": False,
            "comfy": False,
            "base_url": root,
            "detail": f"Baglanti yok: {e}",
        }


async def discover_studio_health(preferred: str | None = None) -> dict[str, Any]:
    cands: list[str] = []
    if preferred:
        cands.append(preferred)
    cands.append(DEFAULT_BASE_URL)
    st = await pterm_app_status()
    if st:
        ru = st.get("ready_url")
        if isinstance(ru, str) and ru.startswith("http"):
            cands.insert(0, ru)
        for extra in st.get("external_ready_urls") or []:
            if isinstance(extra, str) and extra.startswith("http"):
                cands.append(extra)
        for entry in st.get("local_entries") or []:
            if not isinstance(entry, dict):
                continue
            local = entry.get("local") or {}
            if isinstance(local, dict):
                lu = local.get("url")
                if isinstance(lu, str) and lu.startswith("http"):
                    cands.append(lu)
    for port in (8787, 8788, 8789, 8790, 42003, 42004, 42005, 42011):
        cands.append(f"http://127.0.0.1:{port}")

    seen: set[str] = set()
    best: dict[str, Any] | None = None
    for u in cands:
        u = (u or "").strip().rstrip("/")
        if not u or u in seen:
            continue
        seen.add(u)
        h = await probe_health(u)
        if h.get("ok"):
            return h
        if h.get("online") and not best:
            best = h
    return best or await probe_health(preferred or DEFAULT_BASE_URL)


async def comfy_up() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://127.0.0.1:8188/system_stats")
        return r.status_code == 200
    except Exception:
        return False


async def start_studio_uvicorn() -> dict[str, Any]:
    py = studio_python()
    root = studio_install_dir()
    if not py or not root:
        return {"ok": False, "detail": "Pinokio H3 Studio kurulum yolu bulunamadi"}
    if not await comfy_up():
        return {"ok": False, "detail": "ComfyUI (8188) kapali — tam Start gerekli"}
    h = await probe_health(DEFAULT_BASE_URL)
    if h.get("ok"):
        return {"ok": True, "base_url": DEFAULT_BASE_URL, "mode": "already"}
    env = os.environ.copy()
    env["COMFY_URL"] = "http://127.0.0.1:8188"
    env["STUDIO_HOST"] = "127.0.0.1"
    env["STUDIO_PORT"] = "8787"
    env["PYTHONIOENCODING"] = "utf-8"
    kwargs: dict[str, Any] = {
        "cwd": str(root / "studio"),
        "env": env,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
        )
        kwargs["close_fds"] = True
    try:
        subprocess.Popen(
            [
                str(py),
                "-m",
                "uvicorn",
                "server:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8787",
                "--timeout-graceful-shutdown",
                "8",
            ],
            **kwargs,
        )
    except Exception as e:
        return {"ok": False, "detail": f"Studio baslatilamadi: {e}"}
    return {"ok": True, "mode": "uvicorn", "base_url": DEFAULT_BASE_URL}


async def start_via_pterm() -> dict[str, Any]:
    exe = pterm_exe()
    path = studio_install_dir()
    if not exe:
        return {"ok": False, "detail": "pterm bulunamadi — Pinokio kurulu mu?"}
    target = str(path) if path else APP_ID
    cmd = [str(exe), "run", target, "--default", "start.js"]
    try:
        kwargs: dict[str, Any] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
            )
            kwargs["close_fds"] = True
        subprocess.Popen(cmd, **kwargs)
    except Exception as e:
        return {"ok": False, "detail": f"pterm run basarisiz: {e}"}
    return {"ok": True, "mode": "pterm", "target": target}


async def ensure_studio(
    *,
    preferred_url: str | None = None,
    auto_start: bool = True,
    timeout_sec: float | None = None,
    on_progress: ProgressCb = None,
    force_start: bool = False,
) -> dict[str, Any]:
    """Studio+Comfy hazir degilse baslat ve bekle. Hazir URL'yi dondurur."""

    def _emit(msg: str, **extra: Any) -> None:
        if on_progress:
            try:
                on_progress(msg, extra)
            except Exception:
                pass

    limit = float(timeout_sec if timeout_sec is not None else ENSURE_TIMEOUT_SEC)
    h = await discover_studio_health(preferred_url)
    if h.get("ok") and not force_start:
        return {**h, "ensured": True, "started": False}

    if not auto_start and not force_start:
        if h.get("online"):
            detail = h.get("detail") or "Studio acik ama ComfyUI kapali"
        else:
            detail = "H3 Studio kapali — Pinokio'dan baslat, sonra tekrar dene"
        return {**h, "ensured": False, "started": False, "detail": detail}

    _emit("H3 Studio baslatiliyor…")
    started_mode = ""
    fast = await start_studio_uvicorn()
    if fast.get("ok"):
        started_mode = str(fast.get("mode") or "uvicorn")
        _emit("Studio uvicorn — hazir olmasi bekleniyor…")
    else:
        pt = await start_via_pterm()
        if not pt.get("ok"):
            return {
                "ok": False,
                "ensured": False,
                "started": False,
                "detail": pt.get("detail") or fast.get("detail") or "Baslatilamadi",
                "base_url": preferred_url or DEFAULT_BASE_URL,
            }
        started_mode = "pterm"
        _emit("Pinokio H3 Studio Start — Comfy+Studio aciliyor (birkaç dk sürebilir)…")

    deadline = time.monotonic() + limit
    last = h
    while time.monotonic() < deadline:
        last = await discover_studio_health(preferred_url)
        if last.get("ok"):
            _emit("H3 Studio hazir", base_url=last.get("base_url"))
            return {
                **last,
                "ensured": True,
                "started": True,
                "mode": started_mode,
            }
        st = await pterm_app_status()
        state = str((st or {}).get("state") or "")
        ru = (st or {}).get("ready_url")
        if ru:
            _emit(f"Bekleniyor… ({state or 'starting'}) {ru}")
        else:
            _emit(f"Bekleniyor… ({state or last.get('detail') or 'basliyor'})")
        await asyncio.sleep(4.0)

    return {
        **last,
        "ok": False,
        "ensured": False,
        "started": True,
        "mode": started_mode,
        "detail": last.get("detail")
        or "Zaman asimi — Pinokio'da H3 Studio → Start edin",
    }
