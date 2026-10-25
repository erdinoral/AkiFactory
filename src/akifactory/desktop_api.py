"""Legacy pywebview JS API — Electron preload kullanilir."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from akifactory.video_save import copy_video_to, resolve_video_path, safe_video_filename


class DesktopApi:
    """window.pywebview.api uzerinden cagrilir."""

    def show_notification(self, title: str, message: str) -> dict:
        """Windows toast bildirimi (masaustu penceresi acikken)."""
        t = (title or "AkiFactory").strip()[:64].replace('"', "'").replace("`", "'")
        m = (message or "").strip()[:240].replace('"', "'").replace("`", "'")
        if not m:
            return {"ok": False, "error": "bos mesaj"}
        if sys.platform != "win32":
            return {"ok": False, "error": "platform"}
        script = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
            "ContentType = WindowsRuntime] | Out-Null; "
            "$tpl = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
            "[Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
            "$nodes = $tpl.GetElementsByTagName('text'); "
            f"$nodes.Item(0).AppendChild($tpl.CreateTextNode('{t}')) | Out-Null; "
            f"$nodes.Item(1).AppendChild($tpl.CreateTextNode('{m}')) | Out-Null; "
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('AkiFactory')"
            ".Show([Windows.UI.Notifications.ToastNotification]::new($tpl))"
        )
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if r.returncode == 0:
                return {"ok": True}
            return {"ok": False, "error": (r.stderr or r.stdout or "toast hatasi")[:200]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def save_video(self, url: str, default_name: str = "akifactory.mp4") -> dict:
        import webview

        src = resolve_video_path(url)
        if not src or not src.is_file():
            return {"ok": False, "error": "Video dosyasi bulunamadi"}

        save_name = safe_video_filename(default_name or src.name)
        windows = webview.windows
        if not windows:
            return {"ok": False, "error": "Masaustu penceresi hazir degil"}

        result = windows[0].create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=save_name,
            file_types=("MP4 Video (*.mp4)", "All files (*.*)"),
        )
        if not result:
            return {"ok": False, "cancelled": True}

        dest = result[0] if isinstance(result, (list, tuple)) else result
        try:
            out = copy_video_to(src, Path(dest))
            return {"ok": True, "path": str(out)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def open_assets_folder(self, section: str) -> dict:
        from akifactory.settings_assets import open_section_folder

        key = (section or "").strip().lower()
        if key not in ("rvc", "bgm", "outros"):
            return {"ok": False, "error": "Gecersiz bolum"}
        if not open_section_folder(key):
            return {"ok": False, "error": "Klasor acilamadi"}
        return {"ok": True, "section": key}
