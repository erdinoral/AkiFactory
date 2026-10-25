"""Platform profilleri — format, klip, altyazi konumu."""

from __future__ import annotations

from typing import Any

PLATFORMS: dict[str, dict[str, Any]] = {
    "tiktok": {
        "id": "tiktok",
        "label": "TikTok",
        "emoji": "🎵",
        "aspect_ratio": "9:16",
        "max_clip_duration": 5,
        "default_video_count": 1,
        "subtitle_position": "bottom",
    },
    "youtube": {
        "id": "youtube",
        "label": "YouTube",
        "emoji": "▶️",
        "aspect_ratio": "16:9",
        "max_clip_duration": 10,
        "default_video_count": 1,
        "subtitle_position": "bottom",
    },
    "youtube_shorts": {
        "id": "youtube_shorts",
        "label": "YouTube Shorts",
        "emoji": "📺",
        "aspect_ratio": "9:16",
        "max_clip_duration": 7,
        "default_video_count": 1,
        "subtitle_position": "bottom",
    },
    "instagram_reels": {
        "id": "instagram_reels",
        "label": "Instagram Reels",
        "emoji": "📸",
        "aspect_ratio": "9:16",
        "max_clip_duration": 5,
        "default_video_count": 1,
        "subtitle_position": "center",
    },
    "linkedin": {
        "id": "linkedin",
        "label": "LinkedIn Video",
        "emoji": "💼",
        "aspect_ratio": "16:9",
        "max_clip_duration": 8,
        "default_video_count": 1,
        "subtitle_position": "bottom",
    },
    "custom": {
        "id": "custom",
        "label": "Ozel",
        "emoji": "⚙️",
        "aspect_ratio": "9:16",
        "max_clip_duration": 5,
        "default_video_count": 1,
        "subtitle_position": "bottom",
    },
}

DEFAULT_PLATFORM = "tiktok"
DEFAULT_LONGFORM_PLATFORM = "youtube"
DEFAULT_LONGFORM_ASPECT = "16:9"


def resolve(platform_id: str | None) -> dict[str, Any]:
    key = (platform_id or DEFAULT_PLATFORM).strip().lower()
    return PLATFORMS.get(key, PLATFORMS[DEFAULT_PLATFORM])


def list_for_ui() -> list[dict[str, str]]:
    return [
        {
            "id": p["id"],
            "label": f"{p['emoji']} {p['label']}",
            "aspect_ratio": p["aspect_ratio"],
            "max_clip_duration": str(p["max_clip_duration"]),
            "default_video_count": str(p.get("default_video_count", 1)),
            "subtitle_position": p["subtitle_position"],
        }
        for p in PLATFORMS.values()
    ]


def normalize_aspect(aspect: str | None, *, default: str = "9:16") -> str:
    a = (aspect or default).strip()
    return a if a in ("9:16", "16:9", "1:1") else default


def longform_clip_duration(aspect: str | None, platform_id: str | None = None) -> int:
    """Uzun video stok klip suresi — yatayda daha uzun kesimler."""
    a = normalize_aspect(aspect, default=DEFAULT_LONGFORM_ASPECT)
    if a == "16:9":
        return 10
    if a == "1:1":
        return 8
    p = resolve(platform_id or "youtube_shorts")
    return int(p.get("max_clip_duration") or 7)
