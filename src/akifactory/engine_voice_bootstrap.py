"""motor subprocess — Chatterbox / RVC patch'lerini app.services yuklendikten sonra uygula."""

from __future__ import annotations

_applied = False


def prepare() -> None:
    """Motor sureci bootstrap'inden cagrilir (sunucu baslamadan once)."""
    global _applied
    if _applied:
        return
    from akifactory import edge_tts_retry

    edge_tts_retry.install()
    try:
        import akifactory.engine.services.voice  # noqa: F401
    except ImportError:
        return
    try:
        from akifactory.chatterbox_util import apply_chatterbox_runtime_patch

        apply_chatterbox_runtime_patch()
    except Exception:
        pass
    try:
        from akifactory.rvc_util import apply_rvc_runtime_patch

        apply_rvc_runtime_patch()
    except Exception:
        pass
    _applied = True
