"""Cover preference and automatic completion integration, without GPU inference."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from akifactory import ai_cover


def test_preference_persists_and_defaults_off(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_cover, "data_dir", lambda: tmp_path)
    assert ai_cover.settings()["enabled"] is False
    ai_cover.set_enabled(True)
    assert ai_cover.settings()["enabled"] is True
    ai_cover.set_enabled(False)
    assert ai_cover.settings()["enabled"] is False


def test_disabled_never_calls_generator(monkeypatch):
    monkeypatch.setattr(ai_cover, "settings", lambda: {"enabled": False})
    generator = AsyncMock()
    monkeypatch.setattr(ai_cover, "generate", generator)
    asyncio.run(ai_cover.finish_task({"task_id": "video-a"}))
    generator.assert_not_called()


def test_both_languages_and_failure_isolation(monkeypatch):
    monkeypatch.setattr(ai_cover, "settings", lambda: {"enabled": True})
    monkeypatch.setattr(ai_cover.gallery, "list_items", lambda: [
        {"id": "a", "task_id": "video-a"},
        {"id": "b", "task_id": "video-b"},
        {"id": "unrelated", "task_id": "other"},
    ])
    generator = AsyncMock(side_effect=[RuntimeError("GPU unavailable"), None])
    monkeypatch.setattr(ai_cover, "generate", generator)
    asyncio.run(ai_cover.finish_task({"task_id": "video-a", "en_task_id": "video-b"}))
    assert [c.args[0] for c in generator.await_args_list] == ["a", "b"]


def test_existing_generated_cover_is_not_replaced(monkeypatch):
    monkeypatch.setattr(ai_cover.gallery, "get_item", lambda _: {"ai_cover_status": "done"})
    update = AsyncMock()
    monkeypatch.setattr(ai_cover.gallery, "update_entry", update)
    asyncio.run(ai_cover.generate("existing"))
    update.assert_not_called()
