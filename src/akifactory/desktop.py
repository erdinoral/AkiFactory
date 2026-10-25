"""Legacy pywebview penceresi — normal kullanim Electron (AkiFactory.bat)."""

from __future__ import annotations

import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable

DEFAULT_TITLE = "AkiFactory — Akiyom"
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 840
MIN_WIDTH = 960
MIN_HEIGHT = 640


def use_native_window() -> bool:
    """AKI_USE_BROWSER=1 ise tarayici; yoksa pywebview dene."""
    if os.environ.get("AKI_USE_BROWSER", "").strip() in ("1", "true", "yes"):
        return False
    try:
        import webview  # noqa: F401

        return True
    except ImportError:
        return False


def wait_for_url(url: str, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.25)
    return False


def run_uvicorn_thread(
    app: Any,
    host: str,
    port: int,
    *,
    log_level: str = "warning",
) -> threading.Thread:
    import uvicorn

    def _serve() -> None:
        uvicorn.run(app, host=host, port=port, log_level=log_level)

    thread = threading.Thread(target=_serve, daemon=True, name="aki-uvicorn")
    thread.start()
    return thread


def _log_desktop_error(exc: BaseException) -> None:
    try:
        from akifactory.paths import app_root

        path = app_root() / ".aki_app.log"
        with path.open("a", encoding="utf-8") as f:
            f.write(f"[desktop] {exc!r}\n")
    except OSError:
        pass


def open_native_window(
    url: str,
    *,
    title: str = DEFAULT_TITLE,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> None:
    import webview

    from akifactory.desktop_api import DesktopApi

    # pywebview 5.x create_window() icon desteklemiyor; EXE ikonu PyInstaller .ico ile gelir
    window = webview.create_window(
        title,
        url,
        width=width,
        height=height,
        min_size=(MIN_WIDTH, MIN_HEIGHT),
        text_select=True,
        js_api=DesktopApi(),
    )
    last_err: Exception | None = None
    for gui in ("edgechromium", None):
        try:
            if gui:
                webview.start(gui=gui)
            else:
                webview.start()
            del window
            return
        except Exception as exc:
            last_err = exc
    raise RuntimeError(
        "Masaustu penceresi acilamadi. AkiFactory.bat ile acin."
    ) from last_err


def open_app_window(
    url: str,
    *,
    on_fallback_browser: Callable[[str], None] | None = None,
) -> None:
    """Uvicorn zaten calisiyor — yalnizca masaustu penceresini ac."""
    if os.environ.get("AKI_ELECTRON", "").strip().lower() in ("1", "true", "yes"):
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return

    if use_native_window():
        try:
            open_native_window(url)
            return
        except Exception as exc:
            _log_desktop_error(exc)

    if on_fallback_browser:
        on_fallback_browser(url)
    else:
        import webbrowser

        webbrowser.open(url)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def run_app_loop(
    app: Any,
    host: str,
    port: int,
    *,
    on_fallback_browser: Callable[[str], None] | None = None,
) -> None:
    """Uvicorn arka planda; arayuz pywebview veya tarayici."""
    url = f"http://{host}:{port}"

    run_uvicorn_thread(app, host, port)

    if not wait_for_url(url):
        raise RuntimeError(f"Arayuz acilmadi: {url}")

    if use_native_window():
        print("[AkiFactory] Masaustu penceresi aciliyor...", flush=True)
        open_native_window(url)
        return

    print("[AkiFactory] pywebview yok — tarayici aciliyor.", flush=True)
    print("  Kurulum: pip install pywebview", flush=True)
    if on_fallback_browser:
        on_fallback_browser(url)
    else:
        import webbrowser

        webbrowser.open(url)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
