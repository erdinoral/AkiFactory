"""Global uretim kuyrugu — seri, kisa ve uzun video sirayla islenir."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from akifactory import batch as batch_mod
from akifactory import job_log
from akifactory import longform as longform_mod
from akifactory import json_io as jio
from akifactory.paths import data_dir

_log = logging.getLogger("akifactory.queue")

QUEUE_FILE = "production_queue.json"

KIND_BATCH = "batch"
KIND_SINGLE = "single"
KIND_LONGFORM = "longform"

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

_ACTIVE = {STATUS_PENDING, STATUS_RUNNING}


@dataclass
class QueueItem:
    queue_id: str
    kind: str
    ref_id: str
    label: str
    status: str = STATUS_PENDING
    created_at: float = field(default_factory=time.time)
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


_items: list[QueueItem] = []
_lock = asyncio.Lock()
_worker_task: asyncio.Task | None = None
_engine_base: str = ""
_processing = False


def _norm_topic(topic: str) -> str:
    return " ".join((topic or "").casefold().split())


def _item_topics(item: QueueItem) -> list[str]:
    rec = item.meta.get("recover") if isinstance(item.meta, dict) else None
    topics = (rec or {}).get("topics") if isinstance(rec, dict) else None
    if isinstance(topics, list):
        return [str(t).strip() for t in topics if str(t).strip()]
    return []


def active_topic_collision(
    topics: list[str],
    *,
    kinds: set[str] | None = None,
) -> QueueItem | None:
    """Ayni konu zaten pending/running ise mevcut kaydi dondur."""
    wanted = {_norm_topic(t) for t in topics if (t or "").strip()}
    wanted.discard("")
    if not wanted:
        return None
    for it in _items:
        if it.status not in _ACTIVE:
            continue
        if kinds is not None and it.kind not in kinds:
            continue
        existing = {_norm_topic(t) for t in _item_topics(it)}
        if existing & wanted:
            return it
    return None


def prune_duplicate_pending() -> int:
    """Running isle ayni konulu pending kopyalari siradan dusur."""
    running_keys: set[str] = set()
    for it in _items:
        if it.status != STATUS_RUNNING:
            continue
        running_keys |= {_norm_topic(t) for t in _item_topics(it)}
    running_keys.discard("")
    if not running_keys:
        return 0
    removed = 0
    for it in list(_items):
        if it.status != STATUS_PENDING:
            continue
        if it.kind not in (KIND_SINGLE, KIND_BATCH):
            continue
        keys = {_norm_topic(t) for t in _item_topics(it)}
        if not (keys & running_keys):
            continue
        _log.warning(
            "Tekrarlayan pending kuyruk silindi: %s (%s)",
            it.label,
            it.queue_id,
        )
        cancel_item(it.queue_id, remove=True)
        removed += 1
    return removed


def enqueue(
    kind: str,
    ref_id: str,
    label: str,
    *,
    meta: dict[str, Any] | None = None,
) -> QueueItem:
    item = QueueItem(
        queue_id=uuid.uuid4().hex[:10],
        kind=kind,
        ref_id=ref_id,
        label=label.strip() or "Uretim",
        meta=dict(meta or {}),
    )
    _items.append(item)
    _save_queue()
    return item


def _queue_path() -> Path:
    return data_dir() / QUEUE_FILE


def _save_queue() -> None:
    p = _queue_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "queue_id": it.queue_id,
            "kind": it.kind,
            "ref_id": it.ref_id,
            "label": it.label,
            "status": it.status,
            "created_at": it.created_at,
            "error": it.error,
            "meta": it.meta,
        }
        for it in _items
    ]
    jio.save_wrapped_list(p, payload)


def _row_to_item(row: dict[str, Any], *, force_pending: bool = False) -> QueueItem | None:
    ref_id = (row.get("ref_id") or "").strip()
    if not ref_id:
        return None
    st = row.get("status") or STATUS_PENDING
    if force_pending or st == STATUS_RUNNING:
        st = STATUS_PENDING
    return QueueItem(
        queue_id=row.get("queue_id") or uuid.uuid4().hex[:10],
        kind=row.get("kind") or KIND_BATCH,
        ref_id=ref_id,
        label=row.get("label") or "Uretim",
        status=st,
        created_at=float(row.get("created_at") or time.time()),
        error=row.get("error"),
        meta=dict(row.get("meta") or {}),
    )


def load_persisted_queue() -> int:
    """Eski davranis: diskten geri yuklemez — onceki oturum kuyrugu temizlenir."""
    return discard_persisted_queue()


def sync_queue_from_disk() -> int:
    """Eski davranis: diskten birlestirme yok (kapanista kuyruk temizlenir)."""
    return 0


def discard_persisted_queue() -> int:
    """Onceki oturumdan kalan production_queue.json kayitlarini sil."""
    global _processing
    if _items:
        return 0
    path = _queue_path()
    rows = jio.load_wrapped_list(path)
    n = sum(
        1
        for r in rows
        if isinstance(r, dict) and r.get("status") in _ACTIVE
    )
    jio.save_wrapped_list(path, [])
    _processing = False
    if n:
        _log.info("Onceki oturum kuyrugu temizlendi: %s is", n)
    return n


def clear_queue_on_exit() -> int:
    """Uygulama kapanirken aktif kuyrugu iptal et ve diski bosalt."""
    global _processing
    n = 0
    for it in list(_items):
        if it.status not in _ACTIVE:
            continue
        n += 1
        it.status = STATUS_CANCELLED
        if it.kind in (KIND_BATCH, KIND_SINGLE):
            try:
                batch_mod.cancel_batch(it.ref_id)
            except Exception:
                pass
        elif it.kind == KIND_LONGFORM:
            try:
                longform_mod.cancel_longform(it.ref_id)
            except Exception:
                pass
    _items.clear()
    _processing = False
    _interrupt_worker(reason="uygulama kapaniyor")
    jio.save_wrapped_list(_queue_path(), [])
    if n:
        _log.info("Kapanista kuyruk temizlendi: %s is", n)
    return n


def worker_is_alive() -> bool:
    return _worker_task is not None and not _worker_task.done()


def _interrupt_worker(*, reason: str = "iptal") -> None:
    """Calisan kuyruk iscisini kes — iptal sonrasi processing kilidini birak."""
    global _processing, _worker_task
    _processing = False
    task = _worker_task
    _worker_task = None
    if task is not None and not task.done():
        _log.warning("Kuyruk iscisi kesiliyor (%s)", reason)
        task.cancel()


def reconcile_stale_running() -> int:
    """Worker yokken RUNNING kalan isleri yeniden siraya al; hayalet kilidi temizle."""
    global _processing
    if worker_is_alive():
        # Iptal sonrasi: running yok ama bayrak True kalmissa UI kilitlenmesin.
        if _processing and not any(it.status == STATUS_RUNNING for it in _items):
            if not any(it.status == STATUS_PENDING for it in _items):
                _processing = False
        return 0
    _processing = False
    reset = 0
    for it in _items:
        if it.status == STATUS_RUNNING:
            it.status = STATUS_PENDING
            it.error = None
            reset += 1
    if reset:
        _log.warning("Takili RUNNING isler pending'e alindi: %s", reset)
        _save_queue()
    return reset


def has_active_work() -> bool:
    return any(it.status in _ACTIVE for it in _items)


def _recover_job(item: QueueItem) -> bool:
    if item.kind in (KIND_BATCH, KIND_SINGLE):
        if batch_mod.get_batch(item.ref_id):
            return True
        rec = item.meta.get("recover")
        if not rec or not rec.get("topics"):
            return False
        batch_mod.create_batch_with_id(
            item.ref_id,
            rec["topics"],
            rec.get("common") or {},
            scripts=rec.get("scripts"),
        )
        return True
    if item.kind == KIND_LONGFORM:
        return longform_mod.get_longform(item.ref_id) is not None
    return False


def queue_position(queue_id: str) -> int:
    active = [it for it in _items if it.status in _ACTIVE]
    for idx, it in enumerate(active, start=1):
        if it.queue_id == queue_id:
            return idx
    return len(active) + 1


def _next_pending() -> QueueItem | None:
    for it in _items:
        if it.status == STATUS_PENDING:
            return it
    return None


async def ensure_worker(engine_base: str) -> None:
    """Kuyruk iscisini baslat veya olmusse yeniden baslat."""
    global _worker_task, _engine_base
    _engine_base = engine_base
    # Onceki oturumdan kalan sira geri yuklenmez — temiz basla
    discard_persisted_queue()
    _compact_persisted_queue()
    reconcile_stale_running()
    prune_duplicate_pending()
    if not has_active_work():
        return
    if worker_is_alive():
        return
    _log.info("Kuyruk iscisi baslatiliyor (%s bekleyen is)", sum(1 for it in _items if it.status == STATUS_PENDING))
    _worker_task = asyncio.create_task(_worker_loop())


def shutdown_worker() -> None:
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
    _worker_task = None


def _progress_for(item: QueueItem) -> dict[str, Any] | None:
    if item.kind in (KIND_BATCH, KIND_SINGLE):
        return batch_mod.get_batch(item.ref_id)
    if item.kind == KIND_LONGFORM:
        return longform_mod.get_longform(item.ref_id)
    return None


def _item_dict(item: QueueItem, position: int) -> dict[str, Any]:
    return {
        "queue_id": item.queue_id,
        "kind": item.kind,
        "ref_id": item.ref_id,
        "label": item.label,
        "status": item.status,
        "position": position,
        "error": item.error,
        "meta": item.meta,
        "progress": _progress_for(item),
    }


def get_snapshot() -> dict[str, Any]:
    reconcile_stale_running()
    prune_duplicate_pending()
    current = next((it for it in _items if it.status == STATUS_RUNNING), None)
    visible = [it for it in _items if it.status in _ACTIVE]
    items_out = [_item_dict(it, idx + 1) for idx, it in enumerate(visible)]
    pending_count = sum(1 for it in _items if it.status == STATUS_PENDING)
    active_count = sum(1 for it in _items if it.status in _ACTIVE)
    # UI kilidi: gercekten running is yoksa processing gosterme (hayalet kilit).
    processing_now = bool(current) or (
        _processing and worker_is_alive() and pending_count > 0
    )
    return {
        "processing": processing_now,
        "worker_alive": worker_is_alive(),
        "active_count": active_count,
        "pending_count": pending_count,
        "current": _item_dict(current, queue_position(current.queue_id)) if current else None,
        "items": items_out,
    }


def cancel_item(queue_id: str, *, remove: bool = False) -> tuple[bool, list[str]]:
    item = next((it for it in _items if it.queue_id == queue_id), None)
    if not item:
        return False, []
    if item.status not in _ACTIVE:
        if remove and item in _items and item.status == STATUS_CANCELLED:
            _items.remove(item)
            _save_queue()
        return True, []
    task_ids: list[str] = []
    was_running = item.status == STATUS_RUNNING
    item.status = STATUS_CANCELLED
    if item.kind in (KIND_BATCH, KIND_SINGLE):
        task_ids = batch_mod.collect_running_task_ids(item.ref_id)
        batch_mod.cancel_batch(item.ref_id)
    elif item.kind == KIND_LONGFORM:
        longform_mod.cancel_longform(item.ref_id)
    if remove and item in _items:
        _items.remove(item)
    _save_queue()
    # Calisan isi iptal: worker Ollama/AI beklemesinde takili kalmasin.
    if was_running:
        _interrupt_worker(reason=f"item {queue_id}")
    elif not has_active_work():
        _interrupt_worker(reason="aktif is kalmadi")
    return True, task_ids


def cancel_all(*, remove: bool = True) -> tuple[int, list[str]]:
    """Aktif kuyruk islerini iptal et. remove=True ise iptal edilenleri listeden cikar."""
    n = 0
    task_ids: list[str] = []
    for it in list(_items):
        if it.status not in _ACTIVE:
            continue
        # cancel_item worker'i her running'de keser; toplu iptalde bir kez kes.
        item = it
        if item.status not in _ACTIVE:
            continue
        item.status = STATUS_CANCELLED
        n += 1
        if item.kind in (KIND_BATCH, KIND_SINGLE):
            for tid in batch_mod.collect_running_task_ids(item.ref_id):
                if tid not in task_ids:
                    task_ids.append(tid)
            batch_mod.cancel_batch(item.ref_id)
        elif item.kind == KIND_LONGFORM:
            longform_mod.cancel_longform(item.ref_id)
    if remove:
        # Iptal + bekleyen kalintilarini siradan dusur (UI ve disk temiz kalsin).
        before = len(_items)
        _items[:] = [
            it
            for it in _items
            if it.status not in (STATUS_CANCELLED, STATUS_PENDING)
        ]
        if len(_items) != before:
            _save_queue()
    else:
        _save_queue()
    _interrupt_worker(reason="cancel_all")
    return n, task_ids


def drop_completed() -> int:
    """Tamamlanan / biten isleri kuyruktan ve diskten cikar."""
    before = len(_items)
    _items[:] = [
        it
        for it in _items
        if it.status not in (STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED)
    ]
    removed = before - len(_items)
    if removed:
        _save_queue()
    return removed


def _compact_persisted_queue() -> None:
    """Diskteki tamamlanan kayitlari temizle."""
    path = _queue_path()
    rows = jio.load_wrapped_list(path)
    active = [
        r for r in rows if isinstance(r, dict) and r.get("status") in _ACTIVE
    ]
    if len(active) != len(rows):
        jio.save_wrapped_list(path, active)


def prune_finished(max_keep: int = 12) -> None:
    """Biten isleri kuyruktan dusur (sira yalnizca pending/running)."""
    del max_keep  # once failed kayit tutuyorduk; sira temiz kalsin
    drop_completed()


def _detach_finished(item: QueueItem) -> None:
    """Tek isi bitince listeden ve diskten hemen cikar."""
    if item.status not in (STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED):
        return
    if item in _items:
        _items.remove(item)
        _save_queue()


async def _run_item(item: QueueItem, engine_base: str) -> None:
    if item.status == STATUS_CANCELLED:
        return

    auto_retry = bool(item.meta.get("auto_retry_failed", True))
    rounds = int(item.meta.get("auto_retry_rounds", 2))

    if item.kind in (KIND_BATCH, KIND_SINGLE):
        if not _recover_job(item):
            item.status = STATUS_FAILED
            item.error = "Uretim kaydi bulunamadi (sunucu yeniden basladi?)"
            return
        await batch_mod.run_batch_with_retries(
            item.ref_id,
            engine_base,
            auto_retry=auto_retry,
            rounds=rounds,
            cancelled=lambda: item.status == STATUS_CANCELLED,
        )
        data = batch_mod.get_batch(item.ref_id)
        if not data:
            item.status = STATUS_FAILED
            item.error = "Uretim kaydi kayboldu (sunucu yeniden basladi?)"
            return
        if data.get("cancelled"):
            item.status = STATUS_CANCELLED
            return
        # Backend arsivleme: uygulama kapali olsa bile tamamlanan videolar galeriye gecsin.
        try:
            batch_mod.archive_completed_tasks_to_gallery(item.ref_id, engine_base)
        except Exception:
            pass
        if data.get("failed"):
            errs = data.get("errors") or []
            item.status = STATUS_FAILED
            item.error = errs[0] if errs else "Bazi videolar basarisiz"
        return

    if item.kind == KIND_LONGFORM:
        await longform_mod.run_longform(item.ref_id, engine_base)
        data = longform_mod.get_longform(item.ref_id)
        if data and data.get("cancelled"):
            item.status = STATUS_CANCELLED
            return
        if data and data.get("failed"):
            errs = data.get("errors") or []
            item.status = STATUS_FAILED
            item.error = errs[0] if errs else "Bazi bolumler basarisiz"


async def _worker_loop() -> None:
    global _processing
    while True:
        try:
            async with _lock:
                pending = _next_pending()
            if not pending:
                _processing = False
                sync_queue_from_disk()
                pending = _next_pending()
                if not pending:
                    await asyncio.sleep(1.0)
                    continue

            _processing = True
            pending.status = STATUS_RUNNING
            _save_queue()
            _log.info("Kuyruk isleniyor: %s (%s)", pending.label, pending.queue_id)
            job_log.info(pending.queue_id, f"Kuyruk basladi: {pending.kind} {pending.label}")
            try:
                await _run_item(pending, _engine_base)
                if pending.status == STATUS_RUNNING:
                    pending.status = STATUS_DONE
                job_log.info(
                    pending.queue_id,
                    f"Kuyruk bitti: status={pending.status} error={pending.error or ''}",
                )
            except asyncio.CancelledError:
                if pending.status == STATUS_RUNNING:
                    pending.status = STATUS_CANCELLED
                job_log.warn(pending.queue_id, "Kuyruk iptal")
                _processing = False
                _detach_finished(pending)
                raise
            except Exception as exc:
                if pending.status != STATUS_CANCELLED:
                    pending.status = STATUS_FAILED
                    pending.error = str(exc) or "Uretim hatasi"
                    job_log.error(pending.queue_id, pending.error)
            finally:
                if pending.status != STATUS_RUNNING:
                    # Is bitti/iptal/hata — siradan dusur; cikti galeride kalir.
                    _detach_finished(pending)
                    if not _next_pending():
                        _processing = False
                prune_finished()
                _save_queue()
                try:
                    from akifactory import telegram_notify as tg_mod

                    if not _next_pending() and not any(
                        it.status == STATUS_RUNNING for it in _items
                    ):
                        await tg_mod.notify_queue_idle(_items)
                except Exception:
                    pass
        except asyncio.CancelledError:
            _processing = False
            break
        except Exception:
            _processing = False
            await asyncio.sleep(2.0)
