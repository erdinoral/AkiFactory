"""Ollama vision model kurulumu — video analiz sekmesi icin qwen2.5vl:7b."""

from __future__ import annotations

import shutil
import subprocess
import sys

MODEL = "qwen2.5vl:7b"
ALIASES = ("qwen2.5vl:7b", "qwen2.5-vl:7b")


def _ollama() -> str:
    exe = shutil.which("ollama")
    if not exe:
        print("[HATA] ollama bulunamadi. https://ollama.com kurun.")
        sys.exit(1)
    return exe


def _installed() -> list[str]:
    try:
        r = subprocess.run(
            [_ollama(), "list"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode != 0:
            return []
        lines = (r.stdout or "").strip().splitlines()[1:]
        return [ln.split()[0] for ln in lines if ln.strip()]
    except Exception:
        return []


def main() -> None:
    print(f"=== AkiFactory Vision model: {MODEL} ===")
    have = _installed()
    if any(a in have for a in ALIASES):
        print(f"[OK] Zaten yuklu: {MODEL}")
        return
    print(f"Indiriliyor: {MODEL} (~6 GB, bir kez)")
    r = subprocess.run([_ollama(), "pull", MODEL])
    if r.returncode != 0:
        print("[HATA] ollama pull basarisiz")
        sys.exit(1)
    print("[OK] Vision model hazir — Analiz sekmesini kullanabilirsiniz.")


if __name__ == "__main__":
    main()
