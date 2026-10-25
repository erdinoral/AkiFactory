"""Crawl4AI kurulum — senaryo web arastirmasini derinlestirir.

  python scripts/bootstrap.py --crawl4ai
  # veya
  python scripts/setup_crawl4ai.py
"""

from __future__ import annotations

import subprocess
import sys


def _p(msg: str) -> None:
    print(msg, flush=True)


def main() -> int:
    py = sys.executable
    _p("[crawl4ai] paket kuruluyor...")
    r = subprocess.run(
        [py, "-m", "pip", "install", "-U", "crawl4ai"],
        check=False,
    )
    if r.returncode != 0:
        _p("[HATA] crawl4ai pip kurulumu basarisiz")
        return r.returncode

    _p("[crawl4ai] Playwright Chromium (tarayici) kuruluyor...")
    browser_ok = False
    # Once resmi CLI, sonra playwright dogrudan
    for cmd in (
        [py, "-m", "playwright", "install", "chromium"],
    ):
        rr = subprocess.run(cmd, check=False)
        if rr.returncode == 0:
            browser_ok = True
            break
    # crawl4ai-setup varsa ek tamamlayici
    setup_cli = None
    try:
        import shutil

        setup_cli = shutil.which("crawl4ai-setup")
    except Exception:
        setup_cli = None
    if setup_cli:
        subprocess.run([setup_cli], check=False)
    if not browser_ok:
        _p(
            "[UYARI] Tarayici kurulumu belirsiz. Elle dene:\n"
            "  python -m playwright install chromium"
        )

    try:
        import crawl4ai  # noqa: F401

        _p("[OK] Crawl4AI hazir — senaryo arastirmasinda otomatik kullanilir.")
        _p("Kapatmak icin: set AKI_CRAWL4AI=0")
        return 0
    except Exception as exc:
        _p(f"[HATA] import basarisiz: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
