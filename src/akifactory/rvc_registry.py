"""RVC ses modelleri — models/rvc/<klasor>/ icinde .pth (+ opsiyonel .index, voice.json)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from akifactory.paths import app_root

RVC_ROOT = app_root() / "models" / "rvc"
DEFAULT_EDGE_VOICE = "tr-TR-AhmetNeural-Male"

# Eski uzun RVC id'leri -> yeni voice.json id (geriye donuk uyumluluk)
VOICE_ID_ALIASES: dict[str, str] = {
    "added-ivf330-flat-nprobe-1-brimston-v2": "brimston",
    "added-ivf150-flat-nprobe-1-spotifydinlediginicintesekkurler-v2": "spotify",
    "added-ivf391-flat-nprobe-1-experiment-butter-v2": "buttercup",
    "added-ivf264-flat-nprobe-1-enigma-rvc-erdin-v2": "erdin-oral",
    "added-ivf357-flat-nprobe-1-geralt-v2": "geralt",
    "added-ivf303-flat-nprobe-1-niloya-v2": "niloya",
    "added-ivf114-flat-nprobe-1-rigby-v2": "rigby",
    "buttercupmodel": "buttercup",
    "spotifydinlediginicintesekkurler": "spotify",
    "berkay-y-ld-z": "berkay-yildiz",
    "berkay-yıldız": "berkay-yildiz",
    "berkay-yildiz": "berkay-yildiz",
}


@dataclass(frozen=True)
class RvcVoice:
    id: str
    label: str
    lang: str
    folder: Path
    pth_path: Path
    index_path: Path | None
    pitch: int = 0
    index_rate: float = 1.0
    edge_voice: str = DEFAULT_EDGE_VOICE
    gender: str = "Male"
    default: bool = False


def _decode_folder_name(name: str) -> str:
    return unquote((name or "").strip())


def _slug(name: str) -> str:
    s = _decode_folder_name(name)
    s = re.sub(r"([a-z])([A-Z])", r"\1-\2", s)
    s = s.replace("_", "-").lower()
    s = re.sub(r"[^a-z0-9-]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-") or "voice"


def _label_from_folder(name: str) -> str:
    s = _decode_folder_name(name)
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = s.replace("_", " ").strip()
    s = re.sub(r"\s*\(\s*1\s*\)\s*$", "", s).strip()
    return s.title() if s else name


def normalize_voice_id(voice_id: str | None) -> str:
    raw = (voice_id or "").strip().lower()
    if not raw:
        return ""
    if raw in VOICE_ID_ALIASES:
        return VOICE_ID_ALIASES[raw]
    slug = _slug(raw)
    if slug in VOICE_ID_ALIASES:
        return VOICE_ID_ALIASES[slug]
    return slug or raw


def _load_meta(folder: Path) -> dict:
    for fname in ("voice.json", "meta.json"):
        path = folder / fname
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
    return {}


def discover_voices(*, refresh: bool = False) -> list[RvcVoice]:
    del refresh  # ileride cache icin
    voices: list[RvcVoice] = []
    if not RVC_ROOT.is_dir():
        return voices
    for folder in sorted(RVC_ROOT.iterdir(), key=lambda p: p.name.lower()):
        if not folder.is_dir():
            continue
        pth_files = sorted(folder.glob("*.pth"), key=lambda p: p.name.lower())
        if not pth_files:
            continue
        meta = _load_meta(folder)
        idx_files = sorted(folder.glob("*.index"), key=lambda p: p.name.lower())
        voices.append(
            RvcVoice(
                id=str(meta.get("id") or _slug(folder.name)),
                label=str(meta.get("label") or _label_from_folder(folder.name)),
                lang=str(meta.get("lang") or "tr").lower(),
                folder=folder,
                pth_path=pth_files[0],
                index_path=idx_files[0] if idx_files else None,
                pitch=int(meta.get("pitch", 0)),
                index_rate=float(meta.get("index_rate", 1.0)),
                edge_voice=str(meta.get("edge_voice") or DEFAULT_EDGE_VOICE),
                gender=str(meta.get("gender") or "Male"),
                default=bool(meta.get("default", False)),
            )
        )
    return voices


def default_voice() -> RvcVoice | None:
    voices = discover_voices()
    if not voices:
        return None
    for v in voices:
        if v.default:
            return v
    return voices[0]


def get_voice(voice_id: str | None) -> RvcVoice | None:
    raw = normalize_voice_id(voice_id)
    if not raw:
        return default_voice()
    for v in discover_voices():
        if v.id.lower() == raw:
            return v
        if v.folder.name.lower() == raw:
            return v
        if _slug(v.folder.name) == raw:
            return v
    return None


def parse_rvc_voice_id(voice_name: str) -> str | None:
    if not (voice_name or "").startswith("rvc:"):
        return None
    rest = voice_name[4:].strip()
    for suffix in ("-Male", "-Female"):
        if rest.endswith(suffix):
            rest = rest[: -len(suffix)]
            break
    resolved = normalize_voice_id(rest)
    return resolved or None


def engine_voice_name(voice: RvcVoice) -> str:
    gender = voice.gender if voice.gender in ("Male", "Female") else "Male"
    return f"rvc:{voice.id}-{gender}"


def resolve_edge_voice_for_rvc(
    voice: RvcVoice | None,
    lang_id: str | None = None,
    user_edge: str | None = None,
) -> str:
    """RVC oncesi Edge telaffuz sesi — kullanici secimi, sonra model cinsiyeti."""
    if (user_edge or "").strip():
        return user_edge.strip()
    from akifactory.languages import EDGE_VOICES

    key = (lang_id or "tr").strip().lower()
    voices = EDGE_VOICES.get(key, EDGE_VOICES["tr"])
    gender = (voice.gender if voice else "").strip().lower()
    if gender == "male":
        for item in voices:
            if "Male" in item["id"]:
                return item["id"]
    if gender == "female":
        for item in voices:
            if "Female" in item["id"]:
                return item["id"]
    if voice and voice.edge_voice:
        return voice.edge_voice
    for item in voices:
        if "Male" in item["id"]:
            return item["id"]
    return DEFAULT_EDGE_VOICE


def list_for_ui(lang_id: str | None = None) -> list[dict[str, object]]:
    key = (lang_id or "tr").strip().lower()
    out: list[dict[str, object]] = []
    for v in discover_voices():
        if v.lang not in (key, "*", "all"):
            continue
        out.append(
            {
                "id": v.id,
                "label": v.label,
                "engine_voice": engine_voice_name(v),
                "pitch": v.pitch,
                "index_rate": v.index_rate,
                "edge_voice": v.edge_voice,
                "gender": v.gender,
                "default": v.default,
            }
        )
    if not out:
        for v in discover_voices():
            out.append(
                {
                    "id": v.id,
                    "label": v.label,
                    "engine_voice": engine_voice_name(v),
                    "pitch": v.pitch,
                    "index_rate": v.index_rate,
                    "edge_voice": v.edge_voice,
                    "gender": v.gender,
                    "default": v.default,
                }
            )
    return out


def model_paths(voice_id: str | None) -> tuple[str, str]:
    voice = get_voice(voice_id)
    if not voice:
        raise FileNotFoundError(
            f"RVC model bulunamadi: {voice_id or '(varsayilan)'}\n"
            f"Cozum: models/rvc/<SesAdi>/ klasorune .pth dosyasi koyun."
        )
    idx = str(voice.index_path) if voice.index_path else ""
    return str(voice.pth_path), idx
