"""Uretim isleri icin data/logs/{job_id}.log — adim ve hata kaydi."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from akifactory.paths import data_dir


def logs_dir() -> Path:
    d = data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_path(job_id: str) -> Path:
    safe = "".join(c for c in (job_id or "unknown") if c.isalnum() or c in "-_")[:80]
    return logs_dir() / f"{safe or 'unknown'}.log"


def append(job_id: str, message: str, *, level: str = "INFO") -> None:
    """Tek satir ekle — hata olursa sessizce gec."""
    try:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        line = f"[{ts}] [{(level or 'INFO').upper()}] {(message or '').rstrip()}\n"
        path = log_path(job_id)
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def info(job_id: str, message: str) -> None:
    append(job_id, message, level="INFO")


def error(job_id: str, message: str) -> None:
    append(job_id, message, level="ERROR")


def warn(job_id: str, message: str) -> None:
    append(job_id, message, level="WARN")
