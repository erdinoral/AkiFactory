"""Galeri videosu + YouTube istatistikleri — vision LLM ile performans analizi."""

from __future__ import annotations

import base64
import json
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from akifactory import script_prompts as script_pr
from akifactory.caption import PLATFORM_LABELS
from akifactory.gpu import resolve_ffmpeg_exe
from akifactory.llm_profiles import resolve_vision_model
from akifactory.ollama_util import chat_vision
from akifactory.paths import analysis_dir
from akifactory.text_utils import clean_turkish_script

INDEX_NAME = "index.json"
VISION_OPTIONS: dict[str, float] = {
    "temperature": 0.35,
    "top_p": 0.85,
    "repeat_penalty": 1.1,
}

FRAME_POSITIONS = (0.05, 0.22, 0.50, 0.82)
FRAME_LABELS = ("Acilis (hook)", "Erken bolum", "Orta bolum", "Kapanis")


def _index_path() -> Path:
    return analysis_dir() / INDEX_NAME


def _load_index() -> list[dict[str, Any]]:
    p = _index_path()
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_index(items: list[dict[str, Any]]) -> None:
    _index_path().write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_history(*, gallery_id: str | None = None, source_type: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
    items = _load_index()
    if gallery_id:
        items = [e for e in items if e.get("gallery_id") == gallery_id]
    if source_type:
        items = [e for e in items if e.get("source_type") == source_type]
    return items[:limit]


MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_IMAGES = 3
ALLOWED_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"})


def _image_label_from_name(name: str, index: int, total: int) -> str:
    base = Path(name or "gorsel").stem.strip() or f"Gorsel {index + 1}"
    if total <= 1:
        return base
    return f"{base} ({index + 1}/{total})"


def prepare_uploaded_images(files: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    """Dosya adi + ham icerik -> vision model icin (etiket, bytes)."""
    if not files:
        raise ValueError("En az bir gorsel secin")
    if len(files) > MAX_UPLOAD_IMAGES:
        raise ValueError(f"En fazla {MAX_UPLOAD_IMAGES} gorsel yukleyebilirsiniz")
    out: list[tuple[str, bytes]] = []
    for i, (name, data) in enumerate(files):
        if not data:
            raise ValueError(f"Gorsel bos: {name or i + 1}")
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError(f"Gorsel cok buyuk (max {MAX_IMAGE_BYTES // (1024 * 1024)} MB): {name}")
        suffix = Path(name or "").suffix.lower()
        if suffix and suffix not in ALLOWED_IMAGE_SUFFIXES:
            raise ValueError(f"Desteklenmeyen format: {suffix or name}")
        out.append((_image_label_from_name(name, i, len(files)), data))
    return out


def _video_duration_sec(video_path: Path) -> float:
    ffmpeg = resolve_ffmpeg_exe()
    if not ffmpeg:
        return 30.0
    try:
        r = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-i",
                str(video_path),
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr or "")
        if m:
            h, mi, s = m.groups()
            return int(h) * 3600 + int(mi) * 60 + float(s)
    except Exception:
        pass
    return 30.0


def _extract_frame(video_path: Path, time_sec: float, out_path: Path) -> bool:
    ffmpeg = resolve_ffmpeg_exe()
    if not ffmpeg:
        return False
    try:
        r = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{max(0.0, time_sec):.3f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                "-y",
                str(out_path),
            ],
            capture_output=True,
            timeout=45,
        )
        return r.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 0
    except Exception:
        return False


def extract_key_frames(video_path: Path) -> list[tuple[str, bytes]]:
    """Videodan 4 ana kare cikar; (etiket, jpeg_bytes) listesi."""
    duration = _video_duration_sec(video_path)
    out: list[tuple[str, bytes]] = []
    with tempfile.TemporaryDirectory(prefix="aki-analyze-") as tmp:
        tmp_path = Path(tmp)
        for label, ratio in zip(FRAME_LABELS, FRAME_POSITIONS):
            t = max(0.1, min(duration - 0.1, duration * ratio))
            frame_file = tmp_path / f"frame_{len(out)}.jpg"
            if not _extract_frame(video_path, t, frame_file):
                continue
            out.append((label, frame_file.read_bytes()))
    return out


def _encode_images(frames: list[tuple[str, bytes]]) -> list[str]:
    return [base64.b64encode(data).decode("ascii") for _, data in frames]


def _parse_sections(content: str) -> dict[str, Any]:
    text = clean_turkish_script(content or "")
    sections: dict[str, list[str]] = {
        "strengths": [],
        "weaknesses": [],
        "stats_insights": [],
        "recommendations": [],
        "next_video": [],
    }
    key_map = {
        "GUCLU": "strengths",
        "ZAYIF": "weaknesses",
        "ISTATISTIK": "stats_insights",
        "ONERI": "recommendations",
        "SONRAKI": "next_video",
    }
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        matched = False
        for prefix, key in key_map.items():
            if upper.startswith(prefix + ":"):
                current = key
                rest = stripped.split(":", 1)[-1].strip().lstrip("-•* ").strip()
                if rest:
                    sections[key].append(rest)
                matched = True
                break
            if upper.startswith(prefix + "_") and ":" in stripped:
                current = key
                rest = stripped.split(":", 1)[-1].strip().lstrip("-•* ").strip()
                if rest:
                    sections[key].append(rest)
                matched = True
                break
        if not matched and current and stripped.startswith(("-", "•", "*")):
            sections[current].append(stripped.lstrip("-•* ").strip())
        elif not matched and current and re.match(r"^\d+[\.\)]\s+", stripped):
            sections[current].append(re.sub(r"^\d+[\.\)]\s+", "", stripped).strip())

    ozet = ""
    m = re.search(r"OZET:\s*(.+)", text, re.IGNORECASE | re.DOTALL)
    if m:
        ozet = m.group(1).strip().split("\n")[0][:400]

    return {
        **sections,
        "summary": ozet,
        "raw": text,
    }


def _build_youtube_studio_prompt(
    *,
    topic: str,
    platform: str,
    niche_id: str,
    frame_labels: list[str],
    note: str,
    extra_stats: str,
) -> str:
    plat = PLATFORM_LABELS.get(platform, platform)
    niche = script_pr.NICHE_LABELS.get(niche_id, niche_id or "genel")
    frames_desc = ", ".join(f"Gorsel {i + 1}: {lbl}" for i, lbl in enumerate(frame_labels))
    extra = (extra_stats or "").strip()
    extra_block = (
        f"\nEK KULLANICI NOTU (gorselde olmayan bilgi):\n{extra[:2000]}\n"
        if extra
        else ""
    )
    user_note = (note or "").strip()
    note_block = f"\nKULLANICI NOTU:\n{user_note[:600]}\n" if user_note else ""

    return f"""Sen Turkiye odakli YouTube Shorts performans analistisin ve ekran goruntulerindeki metinleri okuyabilirsin.

Kullanici YouTube Studio "Video analizi" (veya benzeri) ekraninin ekran goruntusunu yukledi.
{len(frame_labels)} gorsel var: {frames_desc}.

ONCE GORSELDEN OKU (gorunen her seyi tespit et, tahmin etme):
- Goruntulenme / izlenme sayisi
- Abone kazanimi (+X abone)
- Grafik egilimi (ilk saat patlamasi, plato, dusus vb.)
- Trafik kaynaklari yuzdeleri (Shorts ozet akisi, arama, kanal sayfasi, goz atma vb.)
- Gercek zamanli / son 48 saat verileri
- Kitleyi elde tutma (retention) verisi var mi, yok mu — mesaj ne diyor
- CTR, ortalama izlenme suresi, begeni, yorum (gorselde varsa)
- Hangi sekme acik: Genel bakis, Erisim, Etkilesim, Kitle

ICERIK BAGLAMI (AkiFactory galerisindeki video — gorsel bu videoya ait istatistik):
- Video konusu: {topic or "Belirtilmedi"}
- Platform: {plat}
- Nis: {niche}
{note_block}{extra_block}
GOREV:
1) Gorseldeki rakamlari yorumla — bu Shorts iyi mi, orta mi, zayif mi?
2) Trafik kaynagi dagilimini analiz et (ornegin %97 Shorts akisi = normal ama arama dusuk)
3) Abone donusumu, izlenme hizi, plato/duraklama gibi sinyalleri acikla
4) Retention verisi yoksa bunun ne anlama geldigini ve ne zaman tekrar bakilacagini soyle
5) AkiFactory ile bir sonraki videoda ne degistirmeli — somut oneriler

CIKTI FORMATI (baska hicbir sey yok, Turkce karakter kullan):

OZET: (1-2 cumle — gorseldeki ana performans ozeti)

GUCLU_1: (gorseldeki veriye dayali guclu yan)
GUCLU_2: ...
GUCLU_3: ...

ZAYIF_1: (gorseldeki veriye dayali zayif yan veya risk)
ZAYIF_2: ...
ZAYIF_3: ...

ISTATISTIK_1: (okudugun spesifik rakam + yorumu)
ISTATISTIK_2: ...
ISTATISTIK_3: ...
ISTATISTIK_4: ...

ONERI_1: (AkiFactory uretiminde degistirilebilir — hook, kapak, tempo, altyazi, BGM)
ONERI_2: ...
ONERI_3: ...
ONERI_4: ...

SONRAKI_1: (bir sonraki videoda veya 48 saat sonra kontrol et)
SONRAKI_2: ...
SONRAKI_3: ...

KURALLAR:
- Gorselde gorunmeyen rakami UYDURMA; "gorselde yok" de
- Her madde tek satir, en az 8 kelime
- Rakip icerik kopyalama onerme; teknik ve strateji oner"""


def _build_prompt(
    *,
    topic: str,
    platform: str,
    niche_id: str,
    aspect: str,
    script_excerpt: str,
    youtube_stats: str,
    frame_labels: list[str],
    source_kind: str = "video",
    image_mode: str = "",
) -> str:
    if source_kind == "image" and image_mode == "youtube_studio":
        return _build_youtube_studio_prompt(
            topic=topic,
            platform=platform,
            niche_id=niche_id,
            frame_labels=frame_labels,
            note=script_excerpt,
            extra_stats=youtube_stats,
        )

    plat = PLATFORM_LABELS.get(platform, platform)
    niche = script_pr.NICHE_LABELS.get(niche_id, niche_id or "genel")
    frames_desc = ", ".join(f"Gorsel {i + 1}: {lbl}" for i, lbl in enumerate(frame_labels))
    stats_block = (youtube_stats or "").strip() or "(Kullanici istatistik yapistirmadi — yalnizca gorsel analiz yap)"

    mode_hints = {
        "youtube_studio": "Bu gorsel YouTube Studio Video analizi ekran goruntusudur.",
        "reference": "Bu gorsel rakip / referans bir Shorts ekran goruntusu veya trend ornegi olabilir.",
        "own": "Bu gorsel kullanicinin kendi videosundan kare, kapak veya thumbnail olabilir.",
        "general": "Bu gorsel genel bir video/storyboard referansi olabilir.",
    }
    mode_line = mode_hints.get(image_mode, mode_hints["general"])

    if source_kind == "image":
        source_intro = (
            f"Sana kullanicinin yukledigi {len(frame_labels)} gorsel gonderiliyor ({frames_desc}).\n"
            f"{mode_line}"
        )
        aspect_line = f"- Oran (tahmini): {aspect}" if aspect else ""
        script_block = ""
        if (script_excerpt or "").strip():
            script_block = f"\nKULLANICI NOTU:\n{(script_excerpt or topic)[:600]}\n"
    else:
        source_intro = (
            f"Sana bu videodan alinmis {len(frame_labels)} kare gonderiliyor ({frames_desc}).\n"
            "Videoyu ve asagidaki YouTube Studio verilerini birlikte degerlendir."
        )
        aspect_line = f"- Oran: {aspect}"
        script_block = f"\nSENARYO OZETI (ilk ~600 karakter):\n{(script_excerpt or topic)[:600]}\n"

    return f"""Sen Turkiye odakli kisa video editoru ve YouTube Shorts performans analistisin.
{source_intro}

VIDEO / ICERIK BILGISI:
- Konu: {topic or "Belirtilmedi"}
- Platform: {plat}
- Nis: {niche}
{aspect_line}
{script_block}
YOUTUBE / PLATFORM ISTATISTIKLERI (kullanicinin yapistirdigi ham veri):
{stats_block[:4000]}

GOREV:
1) Gorsellerde hook, altyazi okunabilirligi, kadraj, renk, tempo hissi, gorsel ilgi degerlendir
2) Istatistikleri (izlenme, CTR, ort. izlenme suresi, begeni, yorum vb.) gorsellerle iliskilendir
3) Somut, uygulanabilir Turkce oneriler ver — genel klise yok

CIKTI FORMATI (baska hicbir sey yok, Turkce karakter kullan):

OZET: (1-2 cumle genel degerlendirme)

GUCLU_1: (somut guclu yan)
GUCLU_2: ...
GUCLU_3: ...

ZAYIF_1: (somut zayif yan veya risk)
ZAYIF_2: ...
ZAYIF_3: ...

ISTATISTIK_1: (veriye dayali yorum — ornek: "CTR dusukse kapak/ilk kare zayif olabilir")
ISTATISTIK_2: ...
ISTATISTIK_3: ...

ONERI_1: (AkiFactory uretiminde degistirilebilir sey — altyazi stili, hook, tempo, BGM vb.)
ONERI_2: ...
ONERI_3: ...
ONERI_4: ...

SONRAKI_1: (bir sonraki videoda dene)
SONRAKI_2: ...
SONRAKI_3: ...

KURALLAR:
- Her madde tek satir, en az 8 kelime
- Istatistik verilmediyse tahmin etme; gorsel odakli yorum yap
- Rakip icerik kopyalama onerme; ilham ve teknik iyilestirme oner"""


async def _run_vision_analysis(
    frames: list[tuple[str, bytes]],
    *,
    topic: str,
    platform: str,
    niche_id: str,
    aspect: str,
    script_excerpt: str,
    youtube_stats: str,
    vision_model: str,
    source_kind: str = "video",
    image_mode: str = "",
) -> dict[str, Any]:
    if not frames:
        raise ValueError("Analiz icin gorsel bulunamadi")

    labels = [lbl for lbl, _ in frames]
    images_b64 = _encode_images(frames)
    prompt = _build_prompt(
        topic=topic,
        platform=platform,
        niche_id=niche_id,
        aspect=aspect,
        script_excerpt=script_excerpt,
        youtube_stats=youtube_stats,
        frame_labels=labels,
        source_kind=source_kind,
        image_mode=image_mode,
    )

    content = await chat_vision(
        prompt,
        images_b64=images_b64,
        model=vision_model,
        options=VISION_OPTIONS,
        timeout=240.0,
    )
    if not content:
        raise ValueError("Vision model bos yanit dondurdu")

    parsed = _parse_sections(content)
    return {
        "vision_model": vision_model,
        "source_kind": source_kind,
        "image_mode": image_mode,
        "frame_count": len(frames),
        "frame_labels": labels,
        **parsed,
    }


async def analyze_gallery_stats(
    gallery_entry: dict[str, Any],
    files: list[tuple[str, bytes]],
    *,
    note: str = "",
    extra_stats: str = "",
    vision_model: str,
) -> dict[str, Any]:
    """Galeri videosuna bagli YouTube Studio istatistik goruntusu — video karesi yok."""
    frames = prepare_uploaded_images(files)
    topic = (gallery_entry.get("subject") or gallery_entry.get("title") or "Video").strip()
    script = (gallery_entry.get("script") or "").strip()
    context_note = note.strip()
    if script and not context_note:
        context_note = f"Video senaryosu ozeti: {script[:400]}"
    elif script and context_note:
        context_note = f"{context_note}\n\nSenaryo ozeti: {script[:300]}"

    return await _run_vision_analysis(
        frames,
        topic=topic,
        platform=gallery_entry.get("platform") or "youtube_shorts",
        niche_id=gallery_entry.get("niche") or "tarih_gizem",
        aspect=gallery_entry.get("aspect") or "9:16",
        script_excerpt=context_note,
        youtube_stats=extra_stats,
        vision_model=vision_model,
        source_kind="image",
        image_mode="youtube_studio",
    )


def parse_youtube_studio_csv(raw: str | bytes, *, max_rows: int = 40) -> dict[str, Any]:
    """YouTube Studio CSV — metin ozeti uretir (vision gerekmez)."""
    import csv
    import io

    if isinstance(raw, bytes):
        text = raw.decode("utf-8-sig", errors="replace")
    else:
        text = (raw or "").lstrip("\ufeff")
    if not text.strip():
        raise ValueError("CSV bos")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV baslik satiri yok")
    rows: list[dict[str, str]] = []
    for i, row in enumerate(reader):
        if i >= max_rows:
            break
        clean = {str(k).strip(): str(v or "").strip() for k, v in row.items() if k}
        if any(clean.values()):
            rows.append(clean)
    if not rows:
        raise ValueError("CSV'de veri satiri yok")
    # Ozet metin — LLM'e gidecek
    headers = [h for h in (reader.fieldnames or []) if h]
    lines = ["YouTube Studio CSV ozeti:", "Sutunlar: " + ", ".join(headers[:12])]
    for i, row in enumerate(rows[:15], start=1):
        parts = [f"{k}={v}" for k, v in row.items() if v][:8]
        lines.append(f"{i}. " + " | ".join(parts))
    summary = "\n".join(lines)
    return {
        "row_count": len(rows),
        "headers": headers,
        "rows_preview": rows[:10],
        "stats_text": summary,
    }


async def analyze_youtube_csv(
    *,
    csv_text: str,
    topic: str,
    platform: str,
    niche_id: str,
    note: str = "",
    vision_model: str | None = None,
    gallery_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """CSV istatistiklerini LLM ile yorumla (metin chat — vision zorunlu degil)."""
    from akifactory.ollama_util import chat as ollama_chat
    from akifactory import llm_profiles as llm_prof

    parsed = parse_youtube_studio_csv(csv_text)
    stats = parsed["stats_text"]
    if note.strip():
        stats = f"{note.strip()}\n\n{stats}"
    subject = topic
    if gallery_entry:
        subject = (
            gallery_entry.get("subject")
            or gallery_entry.get("title")
            or topic
            or "Video"
        ).strip()
    prompt = f"""Sen bir YouTube buyume danismaniisin. Asagidaki YouTube Studio CSV ozetini analiz et.

VIDEO / KONU: {subject}
PLATFORM: {platform}
NIS: {niche_id}

ISTATISTIKLER:
{stats}

JSON olarak yanit ver (sadece JSON):
{{
  "summary": "2-3 cumle ozet",
  "strengths": ["..."],
  "weaknesses": ["..."],
  "stats_insights": ["..."],
  "recommendations": ["..."],
  "next_video": ["..."]
}}"""
    installed = []
    try:
        from akifactory import ollama_util

        st = await ollama_util.fetch_status(probe=False)
        installed = st.get("models") or []
    except Exception:
        pass
    model = vision_model or llm_prof.resolve_editor_model(installed)
    raw = await ollama_chat(
        [{"role": "user", "content": prompt}],
        model=model,
        think=False,
        clean_script=False,
        options={"temperature": 0.35},
        timeout=120.0,
    )
    parsed_json: dict[str, Any] = {}
    try:
        m = re.search(r"\{[\s\S]*\}", raw or "")
        if m:
            parsed_json = json.loads(m.group(0))
    except Exception:
        parsed_json = {}
    return {
        "summary": parsed_json.get("summary") or (raw or "")[:500],
        "strengths": parsed_json.get("strengths") or [],
        "weaknesses": parsed_json.get("weaknesses") or [],
        "stats_insights": parsed_json.get("stats_insights") or [],
        "recommendations": parsed_json.get("recommendations") or [],
        "next_video": parsed_json.get("next_video") or [],
        "raw": raw or "",
        "vision_model": model,
        "source_kind": "csv",
        "image_mode": "youtube_studio_csv",
        "csv_meta": {
            "row_count": parsed["row_count"],
            "headers": parsed["headers"],
        },
    }


async def analyze_uploaded_images(
    files: list[tuple[str, bytes]],
    *,
    topic: str,
    platform: str,
    niche_id: str,
    aspect: str,
    note: str,
    youtube_stats: str,
    vision_model: str,
    image_mode: str = "youtube_studio",
) -> dict[str, Any]:
    frames = prepare_uploaded_images(files)
    return await _run_vision_analysis(
        frames,
        topic=topic or "Gorsel analizi",
        platform=platform or "youtube_shorts",
        niche_id=niche_id or "tarih_gizem",
        aspect=aspect or "9:16",
        script_excerpt=note,
        youtube_stats=youtube_stats,
        vision_model=vision_model,
        source_kind="image",
        image_mode=image_mode,
    )


async def analyze_gallery_video(
    *,
    video_path: Path,
    gallery_entry: dict[str, Any],
    youtube_stats: str,
    vision_model: str,
) -> dict[str, Any]:
    frames = extract_key_frames(video_path)
    if not frames:
        raise ValueError("Videodan kare cikarilamadi — ffmpeg gerekli")

    return await _run_vision_analysis(
        frames,
        topic=(gallery_entry.get("subject") or gallery_entry.get("title") or "Video").strip(),
        platform=gallery_entry.get("platform") or "youtube_shorts",
        niche_id=gallery_entry.get("niche") or "tarih_gizem",
        aspect=gallery_entry.get("aspect") or "9:16",
        script_excerpt=(gallery_entry.get("script") or "").strip(),
        youtube_stats=youtube_stats,
        vision_model=vision_model,
        source_kind="video",
    )


def save_analysis(
    *,
    gallery_id: str = "",
    gallery_subject: str,
    youtube_stats: str,
    report: dict[str, Any],
    source_type: str = "gallery",
    image_mode: str = "",
) -> dict[str, Any]:
    entry_id = uuid.uuid4().hex[:12]
    record = {
        "id": entry_id,
        "source_type": source_type,
        "image_mode": image_mode or "youtube_studio",
        "gallery_id": gallery_id,
        "subject": gallery_subject[:500],
        "youtube_stats": (youtube_stats or "")[:8000],
        "vision_model": report.get("vision_model", ""),
        "summary": report.get("summary", ""),
        "strengths": report.get("strengths", []),
        "weaknesses": report.get("weaknesses", []),
        "stats_insights": report.get("stats_insights", []),
        "recommendations": report.get("recommendations", []),
        "next_video": report.get("next_video", []),
        "raw": report.get("raw", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    items = _load_index()
    items.insert(0, record)
    _save_index(items[:200])
    return record
