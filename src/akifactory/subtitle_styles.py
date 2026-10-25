"""Altyazi stil sablonlari — motor VideoParams alanlari."""

from __future__ import annotations

from typing import Any

STYLES: dict[str, dict[str, Any]] = {
    "tiktok_classic": {
        "id": "tiktok_classic",
        "label": "TikTok Klasik",
        "font_size": 72,
        "text_fore_color": "#FFFFFF",
        "stroke_color": "#000000",
        "stroke_width": 2.5,
        "text_background_color": False,
        # Varsayilan alt — platform (Reels=orta) override eder
        "subtitle_position": "bottom",
        "preview_class": "sub-preview-tiktok",
    },
    "youtube": {
        "id": "youtube",
        "label": "YouTube",
        "font_size": 56,
        "text_fore_color": "#FFFF00",
        "stroke_color": "#000000",
        "stroke_width": 1.5,
        "text_background_color": True,
        "subtitle_position": "center",
        "preview_class": "sub-preview-youtube",
    },
    "minimal": {
        "id": "minimal",
        "label": "Minimal",
        "font_size": 44,
        "text_fore_color": "#FFFFFF",
        "stroke_color": "#000000",
        "stroke_width": 1.0,
        "text_background_color": False,
        "subtitle_position": "center",
        "preview_class": "sub-preview-minimal",
    },
    "off": {
        "id": "off",
        "label": "Kapali",
        "subtitle_enabled": False,
        "preview_class": "sub-preview-off",
    },
    "custom": {
        "id": "custom",
        "label": "Ozel",
        "font_size": 56,
        "text_fore_color": "#FFFFFF",
        "stroke_color": "#000000",
        "stroke_width": 1.5,
        "text_background_color": False,
        "subtitle_position": "center",
        "preview_class": "sub-preview-custom",
    },
}

FONT_SIZE_MAP = {"small": 44, "medium": 56, "large": 72}


def list_for_ui() -> list[dict[str, Any]]:
    return [
        {"id": s["id"], "label": s["label"], "preview_class": s.get("preview_class", "")}
        for s in STYLES.values()
    ]


def resolve(style_id: str | None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    key = (style_id or "tiktok_classic").strip().lower()
    base = dict(STYLES.get(key, STYLES["tiktok_classic"]))
    ov = overrides or {}
    if ov.get("font_size_key"):
        base["font_size"] = FONT_SIZE_MAP.get(ov["font_size_key"], base.get("font_size", 56))
    if ov.get("text_fore_color"):
        base["text_fore_color"] = ov["text_fore_color"]
    if ov.get("subtitle_position"):
        base["subtitle_position"] = ov["subtitle_position"]
    if "text_background_color" in ov:
        base["text_background_color"] = ov["text_background_color"]
    return base


def apply_to_payload(payload: dict[str, Any], style: dict[str, Any]) -> None:
    if style.get("subtitle_enabled") is False:
        payload["subtitle_enabled"] = False
        return
    payload["subtitle_enabled"] = True
    for key in (
        "font_size",
        "text_fore_color",
        "stroke_color",
        "stroke_width",
        "text_background_color",
        "subtitle_position",
    ):
        if key in style:
            payload[key] = style[key]
