"""Kaynak logodan .ico, favicon ve web PNG uretir."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SOURCE_CANDIDATES = (
    ROOT / "uygulama_logo.png",
    ASSETS / "uygulama_logo.png",
    ASSETS / "akifactory-source.png",
)
SOURCE_CANONICAL = ASSETS / "uygulama_logo.png"
ICO = ASSETS / "akifactory.ico"
PNG256 = ASSETS / "akifactory-256.png"
PNG32 = ASSETS / "akifactory-32.png"
WEB_ICON = ROOT / "web" / "assets" / "icon.png"
WEB_LOGO = ROOT / "web" / "assets" / "logo.png"


def _find_source() -> Path:
    for p in SOURCE_CANDIDATES:
        if p.is_file():
            return p
    raise FileNotFoundError(
        "Logo bulunamadi. Proje kokune uygulama_logo.png koyun."
    )


def _square_crop(img):
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side))


def _resize(img, size: int):
    from PIL import Image

    out = img.resize((size, size), Image.Resampling.LANCZOS)
    if out.mode != "RGBA":
        out = out.convert("RGBA")
    return out


def main() -> int:
    try:
        from PIL import Image
    except ImportError:
        print("[HATA] Pillow gerekli: pip install pillow")
        return 1

    src = _find_source()
    ASSETS.mkdir(parents=True, exist_ok=True)
    WEB_ICON.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != SOURCE_CANONICAL.resolve():
        shutil.copy2(src, SOURCE_CANONICAL)
        print(f"[i] Kaynak kopyalandi: {SOURCE_CANONICAL}")

    base = _square_crop(Image.open(SOURCE_CANONICAL))
    if base.mode != "RGBA":
        base = base.convert("RGBA")

    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [_resize(base, s) for s in sizes]
    images[0].save(
        ICO,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[1:],
    )
    images[-1].save(PNG256, format="PNG")
    images[3].save(PNG32, format="PNG")
    images[-1].save(WEB_ICON, format="PNG")
    images[-1].save(WEB_LOGO, format="PNG")

    print(f"[OK] {ICO}")
    print(f"[OK] {PNG256}")
    print(f"[OK] {WEB_ICON}")
    print(f"[OK] {WEB_LOGO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
