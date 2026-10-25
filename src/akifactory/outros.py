"""Kanal outrolari — data/outros/ altinda; videonun sonuna ffmpeg ile eklenir."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from akifactory.gpu import resolve_video_encoder
from akifactory.paths import app_root

VIDEO_EXTENSIONS = (".mp4", ".mov", ".webm", ".mkv")
TASK_MAP_FILE = "_task_outro.json"
META_FILE = "meta.json"


def outros_dir() -> Path:
    d = app_root() / "data" / "outros"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _task_map_path() -> Path:
    return outros_dir() / TASK_MAP_FILE


def _which(name: str) -> str | None:
    return shutil.which(name)


def _ffmpeg_exe() -> str | None:
    exe = _which("ffmpeg") or __import__("os").environ.get("IMAGEIO_FFMPEG_EXE")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _ffprobe_exe() -> str | None:
    return _which("ffprobe")


def _read_meta(channel_dir: Path) -> dict:
    meta = channel_dir / META_FILE
    if not meta.is_file():
        return {}
    try:
        return json.loads(meta.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _channel_label(channel_id: str, meta: dict) -> str:
    label = (meta.get("label") or "").strip()
    if label:
        return label
    return channel_id.replace("_", " ").replace("-", " ").title()


def _channel_videos(channel_dir: Path) -> list[Path]:
    return [
        f
        for ext in VIDEO_EXTENSIONS
        for f in sorted(channel_dir.glob(f"*{ext}"), key=lambda p: p.name.lower())
        if f.is_file() and f.stat().st_size > 1000
    ]


def _find_outro_file(channel_dir: Path) -> Path | None:
    """outro.* once; yoksa intro olmayan ilk video (eski klasorler)."""
    videos = [f for f in _channel_videos(channel_dir) if not f.stem.lower().startswith("intro")]
    named = [f for f in videos if f.stem.lower() == "outro"]
    return (named or videos or [None])[0]


def _find_intro_file(channel_dir: Path) -> Path | None:
    intros = [f for f in _channel_videos(channel_dir) if f.stem.lower().startswith("intro")]
    return intros[0] if intros else None


def ensure_channel_folders() -> None:
    root = outros_dir()
    readme = root / "OKU-BENI.txt"
    if not readme.is_file():
        readme.write_text(
            "Kanal outrolari\n"
            "================\n\n"
            "Her YouTube / TikTok kanali icin bir klasor ac:\n\n"
            "  data/outros/yt_tarih_gizem/outro.mp4\n"
            "  data/outros/yt_teknoloji/outro.mp4\n\n"
            "Dosya adi outro.mp4 olmasa da ilk bulunan .mp4/.mov kullanilir.\n"
            "Ayni klasore intro.mp4 koyarsan videonun basina eklenir (yalniz intro da olur).\n"
            "Istege bagli meta.json:\n"
            '  {"label": "Tarih Gizem YT", "note": "9:16 dikey outro"}\n\n'
            "Uretim ekraninda kanali sec — intro basa, outro sona otomatik eklenir.\n"
            "Kolay yol: Ayarlar > Dosyalar > Intro yukle / Outro yukle.\n",
            encoding="utf-8",
        )
    sample = root / "_ornek_kanal"
    sample.mkdir(exist_ok=True)
    (sample / "meta.json").write_text(
        '{"label": "Ornek Kanal (outro.mp4 buraya)"}\n',
        encoding="utf-8",
    )


def list_for_ui() -> list[dict[str, str | float | None]]:
    ensure_channel_folders()
    items: list[dict[str, str | float | None]] = []
    for d in sorted(outros_dir().iterdir(), key=lambda p: p.name.lower()):
        if not d.is_dir() or d.name.startswith("_") or d.name.startswith("."):
            continue
        outro = _find_outro_file(d)
        intro = _find_intro_file(d)
        if not outro and not intro:
            continue
        meta = _read_meta(d)
        dur = _probe_duration(outro) if outro else 0.0
        intro_dur = _probe_duration(intro) if intro else 0.0
        items.append(
            {
                "id": d.name,
                "label": _channel_label(d.name, meta),
                "file": outro.name if outro else "",
                "duration_sec": round(dur, 2) if dur else None,
                "intro_file": intro.name if intro else "",
                "intro_duration_sec": round(intro_dur, 2) if intro_dur else None,
            }
        )
    return items


def _channel_dir(outro_id: str) -> Path | None:
    oid = (outro_id or "").strip()
    if not oid or ".." in oid or "/" in oid or "\\" in oid:
        return None
    channel = outros_dir() / oid
    return channel if channel.is_dir() else None


def resolve_path(outro_id: str) -> Path | None:
    channel = _channel_dir(outro_id)
    return _find_outro_file(channel) if channel else None


def resolve_intro_path(outro_id: str) -> Path | None:
    channel = _channel_dir(outro_id)
    return _find_intro_file(channel) if channel else None


def _load_task_map() -> dict[str, str]:
    path = _task_map_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_task_map(data: dict[str, str]) -> None:
    path = _task_map_path()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def register_task_outro(task_id: str, outro_id: str | None) -> None:
    tid = (task_id or "").strip()
    oid = (outro_id or "").strip()
    if not tid or not oid:
        return
    if not resolve_path(oid) and not resolve_intro_path(oid):
        return
    data = _load_task_map()
    data[tid] = oid
    _save_task_map(data)


def pop_task_outro(task_id: str) -> str | None:
    tid = (task_id or "").strip()
    if not tid:
        return None
    data = _load_task_map()
    oid = data.pop(tid, None)
    _save_task_map(data)
    return (oid or "").strip() or None


def _probe_json(path: Path) -> dict:
    ffprobe = _ffprobe_exe()
    if not ffprobe:
        return {}
    try:
        r = subprocess.run(
            [
                ffprobe,
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode != 0:
            return {}
        return json.loads(r.stdout or "{}")
    except Exception:
        return {}


def _probe_duration(path: Path) -> float:
    data = _probe_json(path)
    try:
        return float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        return 0.0


def _probe_video_meta(path: Path) -> tuple[int, int, float]:
    data = _probe_json(path)
    for stream in data.get("streams") or []:
        if stream.get("codec_type") != "video":
            continue
        w = int(stream.get("width") or 1080)
        h = int(stream.get("height") or 1920)
        fps = 30.0
        rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "30/1"
        if isinstance(rate, str) and "/" in rate:
            num, den = rate.split("/", 1)
            try:
                fps = float(num) / max(float(den), 1)
            except ValueError:
                fps = 30.0
        return w, h, max(fps, 1.0)
    return 1080, 1920, 30.0


def _has_audio(path: Path) -> bool:
    data = _probe_json(path)
    return any(s.get("codec_type") == "audio" for s in (data.get("streams") or []))


def append_outro(main_video: Path, outro_id: str) -> Path:
    """Kanal introsunu basa, outrosunu sona ekler; ayni dosyanin uzerine yazar."""
    main_video = Path(main_video)
    intro = resolve_intro_path(outro_id)
    outro = resolve_path(outro_id)
    if not (intro or outro) or not main_video.is_file():
        raise FileNotFoundError("Intro/outro veya ana video bulunamadi")

    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        raise RuntimeError("ffmpeg bulunamadi")

    w, h, fps = _probe_video_meta(main_video)
    fps_s = f"{fps:.3f}".rstrip("0").rstrip(".")
    encoder = resolve_video_encoder()
    tmp = main_video.with_name(f"{main_video.stem}._aki_outro.mp4")

    inputs = [p for p in (intro, main_video, outro) if p]
    filters: list[str] = []
    segments = ""
    for i, src in enumerate(inputs):
        if src == main_video:
            filters.append(f"[{i}:v]setsar=1[v{i}]")
        else:
            filters.append(
                f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps_s}[v{i}]"
            )
        if _has_audio(src):
            filters.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo[a{i}]")
        else:
            dur = max(_probe_duration(src), 0.1)
            filters.append(f"anullsrc=r=44100:cl=stereo,atrim=duration={dur:.3f}[a{i}]")
        segments += f"[v{i}][a{i}]"
    filters.append(f"{segments}concat=n={len(inputs)}:v=1:a=1[v][a]")

    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for src in inputs:
        cmd.extend(["-i", str(src)])
    cmd += [
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        encoder,
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
    ]
    if encoder == "h264_nvenc":
        cmd.extend(["-preset", "p4", "-rc", "vbr", "-cq", "23"])
    else:
        cmd.extend(["-preset", "medium", "-crf", "23"])
    cmd.append(str(tmp))

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "ffmpeg hatasi")[:400]
        if tmp.is_file():
            tmp.unlink(missing_ok=True)
        raise RuntimeError(err)

    tmp.replace(main_video)
    return main_video


def apply_outro_to_paths(paths: list[str], outro_id: str) -> list[str]:
    out: list[str] = []
    for raw in paths:
        p = Path(raw)
        if not p.is_file():
            out.append(raw)
            continue
        try:
            append_outro(p, outro_id)
            out.append(str(p))
        except Exception as exc:
            from loguru import logger

            logger.warning(f"Outro eklenemedi ({outro_id}): {exc}")
            out.append(raw)
    return out
