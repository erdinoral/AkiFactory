"""H3 Studio koprusu — prompt → /api/batch → klip indir → montaj.

Pinokio MiniMax H3 Studio varsayilan: http://127.0.0.1:8787
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import httpx

from akifactory.paths import data_dir

SETTINGS_FILE = data_dir() / "minimax_h3.json"
DEFAULT_BASE_URL = "http://127.0.0.1:8787"
# Tek 5 sn klip GPU'da uzun surebilir — toplam ust sinir
DEFAULT_TIMEOUT_SEC = 90 * 60
POLL_INTERVAL_SEC = 4.0

DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "auto_start": True,
    "base_url": DEFAULT_BASE_URL,
    "aspect": "9:16",
    "quality": "736",
    "duration": 5,
    "steps": 20,
    "silent_audio": True,
    "timeout_sec": DEFAULT_TIMEOUT_SEC,
}


ProgressCb = Callable[[str, dict[str, Any]], None] | None


def load_settings() -> dict[str, Any]:
    cfg = dict(DEFAULT_SETTINGS)
    try:
        if SETTINGS_FILE.is_file():
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k in DEFAULT_SETTINGS:
                    if k in raw:
                        cfg[k] = raw[k]
    except Exception:
        pass
    url = str(cfg.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        url = f"http://{url}"
    cfg["base_url"] = url or DEFAULT_BASE_URL
    cfg["enabled"] = bool(cfg.get("enabled"))
    cfg["auto_start"] = bool(cfg.get("auto_start", True))
    cfg["duration"] = int(cfg.get("duration") or 5)
    if cfg["duration"] not in (4, 5, 6, 8, 10, 15):
        cfg["duration"] = 5
    cfg["quality"] = str(cfg.get("quality") or "736")
    cfg["aspect"] = str(cfg.get("aspect") or "9:16")
    cfg["steps"] = max(8, min(40, int(cfg.get("steps") or 20)))
    cfg["silent_audio"] = bool(cfg.get("silent_audio", True))
    cfg["timeout_sec"] = max(300, int(cfg.get("timeout_sec") or DEFAULT_TIMEOUT_SEC))
    return cfg


def save_settings(patch: dict[str, Any]) -> dict[str, Any]:
    cfg = load_settings()
    for k, v in patch.items():
        if k not in DEFAULT_SETTINGS:
            continue
        cfg[k] = v
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return load_settings()


def public_settings() -> dict[str, Any]:
    cfg = load_settings()
    return {
        "enabled": bool(cfg["enabled"]),
        "auto_start": bool(cfg["auto_start"]),
        "base_url": cfg["base_url"],
        "aspect": cfg["aspect"],
        "quality": cfg["quality"],
        "duration": cfg["duration"],
        "steps": cfg["steps"],
        "silent_audio": bool(cfg["silent_audio"]),
        "timeout_sec": cfg["timeout_sec"],
        "default_base_url": DEFAULT_BASE_URL,
    }


def base_url(override: str | None = None) -> str:
    if override and override.strip():
        u = override.strip().rstrip("/")
        if not u.startswith(("http://", "https://")):
            u = f"http://{u}"
        return u
    return load_settings()["base_url"]


async def health(url: str | None = None) -> dict[str, Any]:
    root = base_url(url)
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


_STUDIO_QUALITIES = ("352", "480", "608", "736", "768", "1088")
_CLIP_DURATIONS = (4, 5, 6, 8, 10, 15)


async def studio_production_settings(url: str | None = None) -> dict[str, Any] | None:
    """Studio arayuzunde o an secili uretim ayarlari (/api/production). Yoksa None.

    aspect ve prompt rewriter alinmaz: format platformdan gelir, rewriter H3 promptlarini bozar.
    """
    root = base_url(url)
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(f"{root}/api/production")
        if r.status_code != 200:
            return None
        data = r.json() or {}
    except Exception:
        return None
    p = data.get("production")
    if not data.get("saved") or not isinstance(p, dict):
        return None
    out: dict[str, Any] = {}
    q = str(p.get("quality") or "").strip()
    if q in _STUDIO_QUALITIES:
        out["quality"] = q
    try:
        d = int(p.get("duration"))
        if d in _CLIP_DURATIONS:
            out["duration"] = d
    except (TypeError, ValueError):
        pass
    try:
        out["steps"] = max(4, min(60, int(p.get("steps"))))
    except (TypeError, ValueError):
        pass
    try:
        out["seed"] = int(p.get("seed"))
    except (TypeError, ValueError):
        pass
    for key in ("sampler", "scheduler"):
        v = str(p.get(key) or "").strip()
        if v:
            out[key] = v
    out["lora_id"] = str(p.get("loraId") or "").strip()
    return out


async def effective_settings(url: str | None = None) -> dict[str, Any]:
    """Uretim ayarlari: Studio'da secili olanlar; Studio kapali/kayitsizsa AkiFactory ayarlari."""
    cfg = load_settings()
    cfg.update({"seed": -1, "sampler": "", "scheduler": "", "lora_id": "", "source": "akifactory"})
    studio = await studio_production_settings(url or cfg["base_url"])
    if studio:
        cfg.update(studio)
        cfg["source"] = "studio"
    return cfg


def describe_settings(s: dict[str, Any]) -> str:
    parts = [f"{s.get('quality')}p", f"{s.get('duration')} sn", f"{s.get('steps')} adim"]
    if s.get("sampler"):
        parts.append(f"{s['sampler']}/{s.get('scheduler') or '-'}")
    seed = int(s.get("seed", -1))
    parts.append("seed rastgele" if seed < 0 else f"seed {seed}")
    if s.get("lora_id"):
        parts.append(f"LoRA {s['lora_id']}")
    src = "Studio" if s.get("source") == "studio" else "AkiFactory (Studio ayari okunamadi)"
    return f"{' · '.join(parts)} — kaynak: {src}"


async def _studio_busy(root: str) -> bool | None:
    """True: Studio render ediyor · False: bos · None: Studio kapali/erisilemiyor."""
    h = await health(root)
    if not h.get("online"):
        return None
    return bool((h.get("raw") or {}).get("queue_busy"))


async def wait_studio_idle(
    url: str | None = None,
    *,
    timeout_sec: float = 45 * 60,
    on_wait: Callable[[str], None] | None = None,
) -> bool:
    """Studio GPU'da render ederken AkiFactory'nin agir isini (montaj/encode) baslatma.

    Studio kapaliysa beklemez. Iki ardisik bos okuma ister (isler arasi kisa bosluk).
    """
    root = base_url(url)
    deadline = time.monotonic() + timeout_sec
    idle_reads = 0
    warned = False
    while time.monotonic() < deadline:
        busy = await _studio_busy(root)
        if busy is None:
            return True
        if busy:
            idle_reads = 0
            if on_wait and not warned:
                on_wait("H3 Studio GPU'da render ediyor — bitince devam edilecek")
                warned = True
        else:
            idle_reads += 1
            if idle_reads >= 2:
                return True
        await asyncio.sleep(5.0 if busy else 1.5)
    return False


async def release_comfy_vram(url: str | None = None) -> bool:
    """H3 Studio bitti → Studio bossa Comfy/H3 modellerini GPU'dan bosalt (montaj icin).

    Studio da bunu yapar ama klibi 'done' isaretledikten sonra; burada bitmesini bekleriz.
    """
    root = base_url(url)
    if not await wait_studio_idle(root, timeout_sec=60):
        return False
    h = await health(root)
    comfy_url = str((h.get("raw") or {}).get("comfy_url") or "http://127.0.0.1:8188").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{comfy_url}/free", json={"unload_models": True, "free_memory": True}
            )
        return r.status_code < 400
    except Exception:
        return False


def extract_scene_prompts(pack: dict[str, Any]) -> list[str]:
    """AI prompt paketinden H3 Studio'ya gidecek SCENE metinleri."""
    wan = pack.get("wan") or {}
    raw = wan.get("raw_scenes") or pack.get("raw_scenes") or []
    out: list[str] = []
    for s in raw:
        t = (s or "").strip()
        if t:
            out.append(t)
    if out:
        return out

    for seg in wan.get("segments") or []:
        t = (seg.get("prompt") or "").strip()
        if not t:
            continue
        # Continue on-eki AkiFactory tarafinda eklenmis olabilir — H3 last-frame ile yonetir
        if t.lower().startswith("continuation of previous"):
            m = re.search(r"Next action:\s*(.*)$", t, flags=re.I | re.S)
            if m:
                t = m.group(1).strip()
        out.append(t)
    if out:
        return out

    block = (wan.get("prompt_block") or "").strip()
    if not block:
        return []
    parts = re.split(r"===\s*SCENE\s*\d+\s*===", block, flags=re.I)
    for p in parts:
        t = p.strip()
        if t:
            out.append(t)
    if out:
        return out
    # Satir satir yedek
    for line in block.splitlines():
        line = line.strip()
        if line and not line.startswith("["):
            out.append(re.sub(r"^\[\d+[–-]\d+s\]\s*", "", line).strip())
    return [x for x in out if x]


def extract_scene_modes(pack: dict[str, Any], count: int) -> list[str] | None:
    """Sahne basina t2v/continue — paket bunu belirttiyse ve sayi tutuyorsa."""
    modes = (pack.get("wan") or {}).get("modes") or []
    modes = [str(m).strip().lower() for m in modes]
    if len(modes) != count or any(m not in ("t2v", "continue") for m in modes):
        return None
    return modes


# Studio, "no generated music" iceren prompta kendi "music video … performance"
# kilidini eklemez; o kilit sahneye istenmeyen insan figuru sokuyor.
SILENT_BROLL_TAIL = (
    "Picture-only documentary B-roll: show only what is described above. "
    "No on-screen text, no spoken dialogue, no generated music, no sound effects. "
    "One continuous shot, no cuts."
)


def _with_silent_tail(prompt: str) -> str:
    p = (prompt or "").strip()
    if "no generated music" in p.lower():
        return p
    return f"{p}\n\n{SILENT_BROLL_TAIL}"


async def _submit_batch(
    *,
    root: str,
    prompts: list[str],
    continue_chain: bool,
    aspect: str,
    quality: str,
    duration: int,
    steps: int,
    silent_audio: bool,
    modes_override: list[str] | None = None,
    seed: int = -1,
    sampler: str = "",
    scheduler: str = "",
    lora_id: str = "",
) -> list[dict[str, Any]]:
    modes = None
    if modes_override and len(modes_override) == len(prompts):
        modes = list(modes_override)
    elif continue_chain and len(prompts) > 1:
        # 1. shot yeni video (t2v), sonrakiler last-frame continue — kesintisiz
        modes = ["t2v"] + ["continue"] * (len(prompts) - 1)
    elif not continue_chain:
        modes = ["t2v"] * len(prompts)
    if silent_audio:
        prompts = [_with_silent_tail(p) for p in prompts]
    body: dict[str, Any] = {
        "prompts": prompts,
        "duration": duration,
        "aspect": aspect,
        "quality": quality,
        "steps": steps,
        "silent_audio": silent_audio,
        "purpose": "short_film",
        "link_continue": True,
        "append_to_chain": False,
        "face_lock": False,
        "prompt_rewriter_enabled": False,
        "seed": int(seed),
    }
    if sampler:
        body["sampler"] = sampler
    if scheduler:
        body["scheduler"] = scheduler
    if lora_id:
        body["lora_id"] = lora_id
    if modes is not None:
        body["modes"] = modes

    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(f"{root}/api/batch", json=body)
        if r.status_code >= 400:
            detail = ""
            try:
                detail = str((r.json() or {}).get("detail") or r.text)[:300]
            except Exception:
                detail = (r.text or "")[:300]
            raise RuntimeError(f"H3 Studio batch HTTP {r.status_code}: {detail}")
        data = r.json()
    jobs = data.get("jobs") or []
    if not jobs:
        raise RuntimeError("H3 Studio batch bos — job uretilmedi")
    return jobs


async def _poll_jobs(
    *,
    root: str,
    job_ids: list[str],
    timeout_sec: float,
    on_progress: ProgressCb = None,
) -> list[dict[str, Any]]:
    # timeout_sec = ilerleme olmadan beklenecek sure (tek klip ~10 dk surebilir);
    # toplam sure klip sayisiyla buyur, sadece takilma iptal eder
    stall_sec = float(timeout_sec)
    hard_deadline = time.monotonic() + max(stall_sec, len(job_ids) * 25 * 60)
    deadline = time.monotonic() + stall_sec
    last_sig: tuple[Any, ...] | None = None
    pending = set(job_ids)
    done_map: dict[str, dict[str, Any]] = {}

    def _emit(msg: str, **extra: Any) -> None:
        if on_progress:
            try:
                on_progress(msg, extra)
            except Exception:
                pass

    while pending:
        now = time.monotonic()
        if now > deadline or now > hard_deadline:
            why = "ilerleme yok" if now > deadline else "toplam sure"
            raise TimeoutError(
                f"H3 Studio zaman asimi ({why}) — bitmeyen: {len(pending)}/{len(job_ids)}"
            )
        sig_parts: list[Any] = [len(done_map)]
        async with httpx.AsyncClient(timeout=20.0) as client:
            for jid in list(pending):
                try:
                    r = await client.get(f"{root}/api/jobs/{jid}")
                    if r.status_code != 200:
                        continue
                    job = r.json()
                except Exception:
                    continue
                st = (job.get("status") or "").lower()
                if st == "done":
                    done_map[jid] = job
                    pending.discard(jid)
                    _emit(
                        f"Klip hazir ({len(done_map)}/{len(job_ids)})",
                        done=len(done_map),
                        total=len(job_ids),
                        job_id=jid,
                    )
                elif st in ("error", "cancelled"):
                    err = job.get("error") or st
                    raise RuntimeError(f"H3 Studio job hata ({jid[:8]}): {err}")
                else:
                    label = job.get("progress_label") or st
                    prog = job.get("progress")
                    sig_parts.append((jid, st, prog, job.get("comfy_step")))
                    _emit(
                        f"H3 Studio: {label}",
                        done=len(done_map),
                        total=len(job_ids),
                        progress=prog,
                        job_id=jid,
                    )
        sig = tuple(sig_parts)
        if sig != last_sig:
            last_sig = sig
            deadline = time.monotonic() + stall_sec
        if pending:
            await asyncio.sleep(POLL_INTERVAL_SEC)

    # Sirayi koru
    return [done_map[jid] for jid in job_ids if jid in done_map]


async def _download_clip(
    *,
    root: str,
    job_id: str,
    dest: Path,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"{root}/api/clips/{job_id}/video?dl=1"
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.get(url)
        if r.status_code >= 400:
            # Galeri yedegi
            r = await client.get(f"{root}/api/gallery/{job_id}/video?dl=1")
        if r.status_code >= 400:
            raise RuntimeError(f"H3 Studio video indirilemedi ({job_id[:8]}): HTTP {r.status_code}")
        dest.write_bytes(r.content)
    if dest.stat().st_size < 1000:
        raise RuntimeError(f"H3 Studio video cok kucuk/bos: {dest.name}")
    return dest


async def produce_and_stage(
    *,
    prompts: list[str],
    continue_chain: bool = True,
    aspect: str | None = None,
    on_progress: ProgressCb = None,
    modes: list[str] | None = None,
    settings: dict[str, Any] | None = None,
) -> tuple[list[str], list[dict[str, str]], str]:
    """SCENE promptlarini H3 Studio'te uret, ai_visuals'a kaydet, stage materials dondur.

    settings: effective_settings() sonucu (prompt yazilirken kullanilan klip suresiyle ayni olmali).
    Returns: (asset_ids, materials, tag)
    """
    from akifactory import ai_visuals as ai_vis

    prompts = [p.strip() for p in prompts if p and p.strip()]
    if not prompts:
        raise ValueError("H3 Studio icin SCENE promptu yok")

    cfg = load_settings()
    root = cfg["base_url"]

    def _emit(msg: str, **extra: Any) -> None:
        if on_progress:
            try:
                on_progress(msg, extra)
            except Exception:
                pass

    from akifactory import minimax_studio_launch as launch

    h = await launch.ensure_studio(
        preferred_url=root,
        auto_start=bool(cfg.get("auto_start", True)),
        on_progress=on_progress,
    )
    if not h.get("ok"):
        raise RuntimeError(
            h.get("detail")
            or "H3 Studio/Comfy kapali — Ayarlar → H3 Studio → Studio'yu baslat"
        )
    root = str(h.get("base_url") or root)
    if root != cfg["base_url"]:
        save_settings({"base_url": root})

    s = settings
    if not s or s.get("source") != "studio":
        fresh = await effective_settings(root)
        if s and s.get("duration"):
            fresh["duration"] = int(s["duration"])
        s = fresh
    _emit(f"H3 Studio ayarlari: {describe_settings(s)}")
    _emit(f"H3 Studio kuyruga {len(prompts)} SCENE…", total=len(prompts))
    jobs = await _submit_batch(
        root=root,
        prompts=prompts,
        continue_chain=continue_chain,
        aspect=aspect or cfg["aspect"],
        quality=str(s.get("quality") or cfg["quality"]),
        duration=int(s.get("duration") or cfg["duration"]),
        steps=int(s.get("steps") or cfg["steps"]),
        silent_audio=bool(cfg["silent_audio"]),
        modes_override=modes,
        seed=int(s.get("seed", -1)),
        sampler=str(s.get("sampler") or ""),
        scheduler=str(s.get("scheduler") or ""),
        lora_id=str(s.get("lora_id") or ""),
    )
    job_ids = [str(j["id"]) for j in jobs if j.get("id")]
    _emit(f"H3 Studio uretiyor ({len(job_ids)} klip)…", total=len(job_ids))

    finished = await _poll_jobs(
        root=root,
        job_ids=job_ids,
        timeout_sec=float(cfg["timeout_sec"]),
        on_progress=on_progress,
    )

    clip_paths: list[Path] = []
    for i, job in enumerate(finished):
        _emit(f"Klip indiriliyor {i + 1}/{len(finished)}…", index=i + 1)
        clip_paths.append(await _download_job(root=root, job=job, index=i))

    _emit("H3 Studio GPU bellegi bosaltiliyor…")
    await release_comfy_vram(root)

    if len(clip_paths) == len(prompts):
        clip_paths = await _fix_rotated_clips(
            root=root,
            prompts=prompts,
            modes=_effective_modes(len(prompts), continue_chain, modes),
            paths=clip_paths,
            submit_kwargs={
                "aspect": aspect or cfg["aspect"],
                "quality": str(s.get("quality") or cfg["quality"]),
                "duration": int(s.get("duration") or cfg["duration"]),
                "steps": int(s.get("steps") or cfg["steps"]),
                "silent_audio": bool(cfg["silent_audio"]),
                "sampler": str(s.get("sampler") or ""),
                "scheduler": str(s.get("scheduler") or ""),
                "lora_id": str(s.get("lora_id") or ""),
            },
            timeout_sec=float(cfg["timeout_sec"]),
            on_progress=on_progress,
        )

    asset_ids = [p.name for p in clip_paths]
    materials, tag = ai_vis.stage_selected(asset_ids)
    _emit(f"H3 Studio tamam — {len(asset_ids)} klip montaja hazir", count=len(asset_ids))
    return asset_ids, materials, tag


async def _download_job(*, root: str, job: dict[str, Any], index: int) -> Path:
    from akifactory import ai_visuals as ai_vis

    stamp = time.strftime("%Y%m%d_%H%M%S")
    name = f"{stamp}_h3_{index:02d}_{uuid.uuid4().hex[:6]}.mp4"
    return await _download_clip(root=root, job_id=str(job["id"]), dest=ai_vis.assets_dir() / name)


def _effective_modes(count: int, continue_chain: bool, override: list[str] | None) -> list[str]:
    """_submit_batch'in Studio'ya gonderdigi sahne modlari (t2v = yeni zincir basi)."""
    if override and len(override) == count:
        return [str(m).strip().lower() for m in override]
    if continue_chain:
        return ["t2v"] + ["continue"] * (count - 1)
    return ["t2v"] * count


ROTATION_RETRIES = 2


async def _fix_rotated_clips(
    *,
    root: str,
    prompts: list[str],
    modes: list[str],
    paths: list[Path],
    submit_kwargs: dict[str, Any],
    timeout_sec: float,
    on_progress: ProgressCb = None,
) -> list[Path]:
    """Yan yatik klipleri bul, zincirlerini (t2v basindan itibaren) yeni seed ile yeniden uret."""
    from akifactory import clip_orientation

    def _emit(msg: str, **extra: Any) -> None:
        if on_progress:
            try:
                on_progress(msg, extra)
            except Exception:
                pass

    clip_sec = float(submit_kwargs.get("duration") or 5)
    starts = [i for i, m in enumerate(modes) if i == 0 or m != "continue"]
    chains = list(zip(starts, starts[1:] + [len(modes)]))
    paths = list(paths)
    to_check = list(range(len(paths)))
    rotated: list[int] = []

    for attempt in range(ROTATION_RETRIES + 1):
        _emit("Klip yonleri kontrol ediliyor…")
        found = await clip_orientation.find_rotated([paths[i] for i in to_check], clip_sec)
        if found is None:
            _emit("Klip yon kontrolu atlandi (Ollama'da gorsel model yok)")
            return paths
        rotated = [to_check[k] for k in found]
        if not rotated or attempt == ROTATION_RETRIES:
            break
        bad = [(s, e) for s, e in chains if any(s <= i < e for i in rotated)]
        redo = [i for s, e in bad for i in range(s, e)]
        _emit(
            f"{len(rotated)} klip yan yatik — {len(redo)} klip yeniden uretiliyor "
            f"(deneme {attempt + 1}/{ROTATION_RETRIES})"
        )
        try:
            jobs = await _submit_batch(
                root=root,
                prompts=[prompts[i] for i in redo],
                continue_chain=True,
                modes_override=["t2v" if i in starts else "continue" for i in redo],
                seed=-1,
                **submit_kwargs,
            )
            finished = await _poll_jobs(
                root=root,
                job_ids=[str(j["id"]) for j in jobs if j.get("id")],
                timeout_sec=timeout_sec,
                on_progress=on_progress,
            )
            if len(finished) != len(redo):
                raise RuntimeError("eksik klip")
            fresh = [await _download_job(root=root, job=job, index=i) for i, job in zip(redo, finished)]
        except Exception as e:
            _emit(f"Yan yatik klip yeniden uretilemedi: {e}")
            break
        finally:
            await release_comfy_vram(root)
        for i, new_path in zip(redo, fresh):
            paths[i].unlink(missing_ok=True)
            paths[i] = new_path
        to_check = redo

    if rotated:
        keep = [p for i, p in enumerate(paths) if i not in rotated]
        if keep:
            _emit(f"{len(rotated)} klip hala yan yatik — montaja alinmadi")
            return keep
    return paths
