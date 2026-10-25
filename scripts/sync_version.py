"""Tek surum kaynagi: src/akifactory/__version__.py -> electron, installer, web cache."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_app_version(root: Path | None = None) -> str:
    base = root or _root()
    path = base / "src" / "akifactory" / "__version__.py"
    text = path.read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    if not m:
        raise RuntimeError(f"Surum okunamadi: {path}")
    return m.group(1).strip()


def sync_electron_package_json(version: str, root: Path | None = None) -> None:
    base = root or _root()
    path = base / "electron" / "package.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = version
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lock_path = base / "electron" / "package-lock.json"
    if lock_path.is_file():
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["version"] = version
        root_pkg = lock.get("packages", {}).get("", {})
        if isinstance(root_pkg, dict):
            root_pkg["version"] = version
        lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sync_inno_setup(version: str, root: Path | None = None) -> None:
    base = root or _root()
    path = base / "installer" / "AkiFactory.iss"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    new_text, n = re.subn(
        r'(#define\s+MyAppVersion\s+")[^"]+(")',
        rf'\g<1>{version}\2',
        text,
        count=1,
    )
    if n and new_text != text:
        path.write_text(new_text, encoding="utf-8")


def sync_web_asset_cache(version: str, root: Path | None = None) -> None:
    base = root or _root()
    path = base / "web" / "index.html"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    new_text = text
    for asset in ("app.css", "app.js"):
        new_text, _ = re.subn(
            rf'(/assets/{re.escape(asset)}\?v=)[^"\']+',
            rf"\g<1>{version}",
            new_text,
            count=1,
        )
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")


def sync_all(root: Path | None = None) -> str:
    version = read_app_version(root)
    sync_electron_package_json(version, root)
    sync_inno_setup(version, root)
    sync_web_asset_cache(version, root)
    return version


def main() -> int:
    try:
        version = sync_all()
        print(f"[OK] Surum senkron: v{version}", flush=True)
        return 0
    except Exception as exc:
        print(f"[HATA] Surum senkronu: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
