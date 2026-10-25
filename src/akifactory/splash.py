"""Baslangic splash — animasyonlu logo (tkinter canvas, video yok)."""

from __future__ import annotations

import math
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

BG = "#0a0a0c"
FG = "#e8e8ec"
MUTED = "#6b6b78"
ACCENT = "#00d4ff"
ACCENT2 = "#7c3aed"
TROUGH = "#1a1a22"
BORDER = "#7c3aed"

ProgressFn = Callable[[str, int], None]

WIN_W = 520
WIN_H = 430
CANVAS_H = 220


def should_show_splash() -> bool:
    if getattr(sys, "frozen", False):
        return True
    return os.environ.get("AKI_SPLASH", "").strip().lower() in ("1", "true", "yes")


def _logo_path(root: Path) -> Path | None:
    candidates = (
        root / "assets" / "akifactory-256.png",
        root / "web" / "assets" / "logo.png",
        root / "assets" / "uygulama_logo.png",
        root / "uygulama_logo.png",
        root / "assets" / "akifactory-32.png",
    )
    for p in candidates:
        if p.is_file():
            return p
    return None


def _venv_python(root: Path) -> Path | None:
    py = root / ".venv" / "Scripts" / "python.exe"
    return py if py.is_file() else None


def _run_apply_config(root: Path) -> bool:
    script = root / "scripts" / "apply_config.py"
    py = _venv_python(root) or Path(sys.executable)
    if not script.is_file():
        return (root / "data" / "engine.toml").is_file()
    try:
        r = subprocess.run(
            [str(py), "-u", str(script)],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=120,
        )
        return r.returncode == 0
    except Exception:
        return (root / "data" / "engine.toml").is_file()


def _run_sync_gpu(root: Path) -> None:
    script = root / "scripts" / "sync_gpu.py"
    py = _venv_python(root) or Path(sys.executable)
    if not script.is_file():
        return
    try:
        subprocess.run(
            [str(py), "-u", str(script)],
            cwd=str(root),
            capture_output=True,
            timeout=60,
        )
    except Exception:
        pass


def run_startup_checks(root: Path, on_progress: ProgressFn) -> tuple[bool, str, list[str]]:
    warnings: list[str] = []

    on_progress("Dosyalar kontrol ediliyor…", 8)
    required = (
        root / "web" / "index.html",
        root / "src" / "akifactory" / "engine" / "server.py",
    )
    for p in required:
        if not p.is_file():
            return False, f"Eksik dosya: {p.name}", warnings

    if getattr(sys, "frozen", False):
        akifactory_src = root / "src" / "akifactory" / "__init__.py"
        if not akifactory_src.is_file():
            return (
                False,
                "EXE paketi eksik: src/akifactory bulunamadi.\n"
                "AkiFactory.bat --portable veya AkiFactory.bat ile yeniden kurun.",
                warnings,
            )

    on_progress("Python ortami hazirlaniyor…", 22)
    if not _venv_python(root):
        return (
            False,
            ".venv bulunamadi — portable paket veya AkiFactory.bat ile kurulum gerekli.",
            warnings,
        )

    on_progress("Yapilandirma uygulaniyor…", 40)
    if not _run_apply_config(root):
        return False, "config.toml olusturulamadi.", warnings

    on_progress("Ollama baglantisi deneniyor…", 58)
    try:
        from akifactory.ollama_util import ping_sync

        if ping_sync():
            on_progress("Ollama hazir.", 68)
        else:
            warnings.append(
                "Ollama yanit vermiyor — senaryo icin ayri pencerede `ollama serve` calistirin."
            )
    except Exception:
        warnings.append("Ollama kontrolu atlandi.")

    on_progress("GPU profili ayarlaniyor…", 82)
    _run_sync_gpu(root)

    on_progress("Hazir — uygulama aciliyor…", 100)
    return True, "", warnings


class AnimatedStartupSplash:
    """Koyu tema + nabiz halkalari + logo animasyonu."""

    def __init__(self, root_path: Path) -> None:
        self.root_path = root_path
        self._photo: tk.PhotoImage | None = None
        self._phase = 0.0
        self._pct = 0
        self._status_text = "Baslatiliyor…"
        self._anim_running = True
        self._after_id: str | None = None
        self._progress_q: queue.Queue[tuple[str, int]] = queue.Queue()

        self.win = tk.Tk()
        self.win.title("AkiFactory")
        self.win.configure(bg=BORDER)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)

        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        x = (sw - WIN_W) // 2
        y = (sh - WIN_H) // 2
        self.win.geometry(f"{WIN_W}x{WIN_H}+{x}+{y}")

        shell = tk.Frame(self.win, bg=BG, padx=1, pady=1)
        shell.pack(fill="both", expand=True)
        inner = tk.Frame(shell, bg=BG)
        inner.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(
            inner,
            width=WIN_W - 2,
            height=CANVAS_H,
            bg=BG,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="x")

        self._load_logo()
        self._cx = (WIN_W - 2) // 2
        self._cy = CANVAS_H // 2 - 8

        footer = tk.Frame(inner, bg=BG, padx=28, pady=14)
        footer.pack(fill="x")

        tk.Label(
            footer,
            text="AkiFactory",
            font=("Segoe UI", 18, "bold"),
            fg=FG,
            bg=BG,
        ).pack()
        tk.Label(
            footer,
            text="Kısa Video Üretim Atölyesi",
            font=("Segoe UI", 9),
            fg=MUTED,
            bg=BG,
        ).pack(pady=(2, 10))

        self.status = tk.Label(
            footer,
            text=self._status_text,
            font=("Segoe UI", 10),
            fg=FG,
            bg=BG,
        )
        self.status.pack(pady=(0, 8))

        style = ttk.Style(self.win)
        style.theme_use("clam")
        style.configure(
            "aki.Horizontal.TProgressbar",
            troughcolor=TROUGH,
            background=ACCENT,
            darkcolor=ACCENT,
            lightcolor=ACCENT,
            bordercolor=TROUGH,
            thickness=8,
        )
        self.progress = ttk.Progressbar(
            footer,
            style="aki.Horizontal.TProgressbar",
            length=WIN_W - 56,
            mode="determinate",
            maximum=100,
        )
        self.progress.pack(pady=(0, 10))

        tk.Label(
            footer,
            text="Akiyom markasına aittir.",
            font=("Segoe UI", 8),
            fg=MUTED,
            bg=BG,
        ).pack()
        tk.Label(
            footer,
            text="Tüm hakları saklıdır.",
            font=("Segoe UI", 8),
            fg=MUTED,
            bg=BG,
        ).pack(pady=(1, 0))

        self.win.update()
        self._tick()

    def _load_logo(self) -> None:
        logo = _logo_path(self.root_path)
        if logo is None:
            return
        try:
            self._photo = tk.PhotoImage(file=str(logo))
            w = self._photo.width()
            target = 96
            if w > target:
                step = max(1, w // target)
                self._photo = self._photo.subsample(step, step)
        except tk.TclError:
            self._photo = None

    def _tick(self) -> None:
        if not self._anim_running:
            return
        try:
            if not self.win.winfo_exists():
                return
        except tk.TclError:
            return

        self._phase += 0.12
        self._draw_frame()
        self._after_id = self.win.after(42, self._tick)

    def _cancel_pending_after(self) -> None:
        try:
            info = self.win.tk.call("after", "info")
            for aid in self.win.tk.splitlist(info):
                try:
                    self.win.after_cancel(aid)
                except tk.TclError:
                    pass
        except tk.TclError:
            pass
        self._after_id = None

    def _draw_frame(self) -> None:
        c = self.canvas
        c.delete("all")
        w = WIN_W - 2
        h = CANVAS_H
        t = self._phase

        # Arka plan isik lekeleri
        for i, (col, ox, oy) in enumerate(
            (
                (ACCENT2, 0.22, 0.18),
                (ACCENT, 0.78, 0.72),
            )
        ):
            pulse = 0.85 + 0.15 * math.sin(t * 0.7 + i * 1.2)
            r = int(90 * pulse)
            x = int(w * ox + 12 * math.sin(t * 0.5 + i))
            y = int(h * oy + 10 * math.cos(t * 0.45 + i))
            c.create_oval(x - r, y - r, x + r, y + r, fill=col, outline="", stipple="gray25")

        # Tarama cizgisi
        scan_y = int((t * 28) % (h + 40)) - 20
        c.create_line(0, scan_y, w, scan_y, fill=ACCENT, width=1, stipple="gray50")

        cx, cy = self._cx, self._cy + int(4 * math.sin(t * 0.9))

        # Nabiz halkalari
        for i, col in enumerate((ACCENT, ACCENT2)):
            phase = (t * 0.55 + i * 0.9) % 2.4
            if phase < 1.6:
                r = 44 + phase * 38
                alpha_stipple = "gray75" if phase < 0.8 else "gray50"
                c.create_oval(
                    cx - r,
                    cy - r,
                    cx + r,
                    cy + r,
                    outline=col,
                    width=2,
                    stipple=alpha_stipple,
                )

        # Yörünge noktalari
        for i in range(3):
            ang = t * 1.1 + i * (2 * math.pi / 3)
            orbit = 58 + 6 * math.sin(t * 0.6 + i)
            px = cx + int(orbit * math.cos(ang))
            py = cy + int(orbit * 0.45 * math.sin(ang))
            c.create_oval(px - 3, py - 3, px + 3, py + 3, fill=ACCENT, outline="")

        # Logo veya A harfi
        if self._photo is not None:
            iw, ih = self._photo.width(), self._photo.height()
            c.create_image(cx - iw // 2, cy - ih // 2, image=self._photo, anchor="nw")
        else:
            c.create_text(
                cx,
                cy,
                text="A",
                font=("Segoe UI", 52, "bold"),
                fill=ACCENT,
            )

    def apply_progress(self, text: str, pct: int) -> None:
        self._status_text = text
        self._pct = max(0, min(100, pct))
        try:
            self.status.config(text=text)
            self.progress["value"] = self._pct
            self.win.update_idletasks()
        except tk.TclError:
            pass

    def drain_progress(self) -> None:
        while True:
            try:
                text, pct = self._progress_q.get_nowait()
            except queue.Empty:
                break
            self.apply_progress(text, pct)

    def set_progress(self, text: str, pct: int) -> None:
        """Thread-safe — kuyruğa yazar, ana dongu uygular."""
        self._progress_q.put((text, pct))

    def close(self) -> None:
        self._anim_running = False
        try:
            if self.win.winfo_exists():
                self._cancel_pending_after()
                self.win.destroy()
        except tk.TclError:
            pass


def show_splash_and_boot(root: Path) -> "BootResult | None":
    """Splash uzerinde tam baslangic; motor + arayuz hazir olunca doner."""
    from akifactory.boot import BootResult, run_boot

    splash = AnimatedStartupSplash(root)
    result: dict[str, BootResult] = {}
    done = threading.Event()

    def _worker() -> None:
        try:
            result["boot"] = run_boot(root, splash.set_progress)
        except Exception as exc:
            result["boot"] = BootResult(ok=False, error=str(exc) or "Baslangic basarisiz")
        finally:
            done.set()

    threading.Thread(target=_worker, daemon=True, name="aki-splash-boot").start()

    while not done.is_set():
        try:
            splash.drain_progress()
            splash.win.update()
        except tk.TclError:
            break
        done.wait(timeout=0.04)

    splash.drain_progress()
    try:
        splash.win.update()
    except tk.TclError:
        pass

    splash.close()

    boot = result.get("boot")
    if not boot or not boot.ok:
        err = (boot.error if boot else "") or "Baslangic basarisiz"
        messagebox.showerror("AkiFactory — Baslatilamadi", err, parent=None)
        return None

    for w in boot.warnings:
        _log_boot_warning(root, w)
    return boot


def _log_boot_warning(root: Path, msg: str) -> None:
    try:
        path = root / ".aki_app.log"
        with path.open("a", encoding="utf-8") as f:
            f.write(f"[uyari] {msg}\n")
    except OSError:
        pass


def show_splash_and_check(root: Path) -> bool:
    """Eski API — yalnizca dosya/venv kontrolu (gelistirme)."""
    boot = show_splash_and_boot(root)
    return boot is not None
