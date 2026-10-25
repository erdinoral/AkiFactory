"""Ayarlar — RVC, BGM, outro klasorleri tarama ve yenileme."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from akifactory import bgm as bgm_mod
from akifactory import outros as outro_mod
from akifactory.paths import app_root
from akifactory.rvc_registry import RVC_ROOT, discover_voices, list_for_ui as rvc_list_for_ui


def _open_path(path: Path) -> bool:
    path.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # noqa: S606
            return True
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
            return True
        subprocess.run(["xdg-open", str(path)], check=False)
        return True
    except Exception:
        return False


def scan_rvc() -> dict[str, Any]:
    voices = discover_voices()
    items: list[dict[str, Any]] = []
    scanned_folders: set[str] = set()
    for v in voices:
        scanned_folders.add(v.folder.name.lower())
        items.append(
            {
                "id": v.id,
                "label": v.label,
                "folder": str(v.folder),
                "folder_name": v.folder.name,
                "pth": v.pth_path.name,
                "has_index": bool(v.index_path),
                "ready": True,
            }
        )
    if RVC_ROOT.is_dir():
        for folder in sorted(RVC_ROOT.iterdir(), key=lambda p: p.name.lower()):
            if not folder.is_dir() or folder.name.lower() in scanned_folders:
                continue
            pth_files = list(folder.glob("*.pth"))
            items.append(
                {
                    "id": folder.name,
                    "label": folder.name,
                    "folder": str(folder),
                    "folder_name": folder.name,
                    "pth": "",
                    "has_index": bool(list(folder.glob("*.index"))),
                    "ready": False,
                    "note": ".pth dosyasi eksik",
                }
            )
    root = app_root()
    rel = RVC_ROOT.relative_to(root) if RVC_ROOT.is_relative_to(root) else RVC_ROOT
    return {
        "section": "rvc",
        "folder": str(RVC_ROOT),
        "folder_relative": str(rel),
        "instructions": (
            "Ses adini yazip Model yukle: .zip (icinde .pth + .index) veya .pth ile .index'i birlikte sec. "
            "Elle eklemek icin: her ses icin bir alt klasor, icine .pth (+ opsiyonel .index, voice.json)."
        ),
        "example": str(RVC_ROOT / "SesAdi" / "model.pth"),
        "count_ready": sum(1 for i in items if i.get("ready")),
        "count_total": len(items),
        "items": items,
    }


def scan_bgm() -> dict[str, Any]:
    bgm_mod.ensure_category_folders()
    bgm_mod.sync_tracks_to_engine()
    items: list[dict[str, Any]] = []
    for category, src in bgm_mod._iter_source_files():
        cat = category or "ortak"
        items.append(
            {
                "category": cat,
                "category_label": bgm_mod._category_label(category),
                "label": bgm_mod._label_from_filename(bgm_mod._engine_filename(category, src)),
                "filename": bgm_mod._engine_filename(category, src),
                "path": str(src),
                "ready": True,
            }
        )
    root = bgm_mod.user_bgm_dir()
    rel = root.relative_to(app_root()) if root.is_relative_to(app_root()) else root
    return {
        "section": "bgm",
        "folder": str(root),
        "folder_relative": str(rel),
        "instructions": (
            "Niş secip Muzik yukle (MP3, WAV, M4A, AAC, OGG, FLAC — otomatik MP3'e cevrilir) "
            "veya dosyayi niş klasorune at. Ornek: data/bgm/tarih_gizem/gerilim.mp3"
        ),
        "example": str(root / "tarih_gizem" / "parca.mp3"),
        "count_ready": len(items),
        "count_total": len(items),
        "items": items,
        "categories": bgm_mod.list_categories_for_ui(),
    }


def scan_outros() -> dict[str, Any]:
    outro_mod.ensure_channel_folders()
    root = outro_mod.outros_dir()
    items: list[dict[str, Any]] = []
    if root.is_dir():
        for d in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if not d.is_dir() or d.name.startswith("_") or d.name.startswith("."):
                continue
            outro = outro_mod._find_outro_file(d)
            intro = outro_mod._find_intro_file(d)
            meta = outro_mod._read_meta(d)
            label = outro_mod._channel_label(d.name, meta)
            parts = [f"intro: {intro.name}" if intro else "", f"outro: {outro.name}" if outro else ""]
            items.append(
                {
                    "id": d.name,
                    "label": label,
                    "folder": str(d),
                    "file": " · ".join(p for p in parts if p),
                    "path": str(outro or intro or ""),
                    "ready": bool(outro or intro),
                    "note": "" if (outro or intro) else "intro / outro videosu bekleniyor",
                }
            )
    rel = root.relative_to(app_root()) if root.is_relative_to(app_root()) else root
    return {
        "section": "outros",
        "folder": str(root),
        "folder_relative": str(rel),
        "instructions": (
            "Her kanal icin bir klasor: intro.mp4 videonun basina, outro.mp4 sonuna eklenir "
            "(ikisinden biri yeterli). Asagidaki kanal adini yazip Intro / Outro yukle."
        ),
        "example": str(root / "kanal_adi" / "outro.mp4"),
        "count_ready": sum(1 for i in items if i.get("ready")),
        "count_total": len(items),
        "items": items,
    }


def scan_all() -> dict[str, Any]:
    return {
        "rvc": scan_rvc(),
        "bgm": scan_bgm(),
        "outros": scan_outros(),
    }


def refresh_section(section: str) -> dict[str, Any]:
    key = (section or "all").strip().lower()
    out: dict[str, Any] = {"ok": True, "section": key}

    if key in ("rvc", "all"):
        out["rvc"] = scan_rvc()
        out["rvc_voices"] = rvc_list_for_ui()
        from akifactory.rvc_tts import is_rvc_available

        out["rvc_available"] = is_rvc_available()

    if key in ("bgm", "all"):
        bgm_mod.sync_tracks_to_engine()
        out["bgm"] = scan_bgm()
        out["bgm_tracks"] = bgm_mod.list_tracks_for_ui()
        out["bgm_categories"] = bgm_mod.list_categories_for_ui()

    if key in ("outros", "all"):
        out["outros_scan"] = scan_outros()
        out["outros"] = outro_mod.list_for_ui()

    if key not in ("rvc", "bgm", "outros", "all"):
        out["ok"] = False
        out["error"] = "Gecersiz bolum: rvc, bgm, outros, all"

    return out


def open_section_folder(section: str) -> bool:
    key = (section or "").strip().lower()
    if key == "rvc":
        return _open_path(RVC_ROOT)
    if key == "bgm":
        bgm_mod.ensure_category_folders()
        return _open_path(bgm_mod.user_bgm_dir())
    if key == "outros":
        outro_mod.ensure_channel_folders()
        return _open_path(outro_mod.outros_dir())
    return False
