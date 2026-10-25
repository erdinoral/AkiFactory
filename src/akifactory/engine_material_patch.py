"""Stok indirme — video + fotograf karisimi."""

from __future__ import annotations


def apply_material_runtime_patch() -> None:
    try:
        from akifactory.engine.services import material
    except ImportError:
        return
    if getattr(material, "_aki_material_patched", False):
        return

    from akifactory.stock_materials import download_mixed_stock_materials

    def download_videos(
        task_id,
        search_terms,
        source="pexels",
        video_aspect=None,
        video_contact_mode=None,
        audio_duration=0.0,
        max_clip_duration=5,
    ):
        return download_mixed_stock_materials(
            task_id=task_id,
            search_terms=search_terms,
            source=source,
            video_aspect=video_aspect,
            video_contact_mode=video_contact_mode,
            audio_duration=audio_duration,
            max_clip_duration=max_clip_duration,
        )

    material.download_videos = download_videos
    material._aki_material_patched = True
