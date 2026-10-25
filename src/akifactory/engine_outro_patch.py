"""Video sonuna kanal outrosu ekleme — motor generate_final_videos sonrasi."""

from __future__ import annotations


def apply_outro_runtime_patch() -> None:
    try:
        from akifactory.engine.services import task
    except ImportError:
        return
    if getattr(task, "_aki_outro_patched", False):
        return

    from akifactory import outros

    _orig = task.generate_final_videos

    def _generate_final_videos(
        task_id, params, downloaded_videos, audio_file, subtitle_path
    ):
        final_paths, combined_paths = _orig(
            task_id, params, downloaded_videos, audio_file, subtitle_path
        )
        outro_id = outros.pop_task_outro(task_id)
        if outro_id and final_paths:
            from loguru import logger

            logger.info(f"Kanal intro/outro ekleniyor: {outro_id}")
            final_paths = outros.apply_outro_to_paths(list(final_paths), outro_id)
        return final_paths, combined_paths

    task.generate_final_videos = _generate_final_videos
    task._aki_outro_patched = True
