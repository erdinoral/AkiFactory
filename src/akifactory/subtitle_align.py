"""Altyazi-ses hizalama: Whisper kelime zamanlari + senaryo metni.

Karakter-oranli (script-only) ve Whisper-dilim-icine metin-kova
yontemleri sonlara kayar. Bu modul Whisper word_timestamps ile
senaryo kelimelerini eslestirir; her altyazi satiri akustik aralik alir.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from akifactory.text_utils import split_script_lines

_PUNCT_STRIP = re.compile(r"^[^\wçğıöşüÇĞİÖŞÜ]+|[^\wçğıöşüÇĞİÖŞÜ]+$", re.UNICODE)
_NON_WORD = re.compile(r"[^\wçğıöşü]", re.UNICODE | re.IGNORECASE)


def normalize_align_token(word: str) -> str:
    """Karsilastirma icin sadelestirilmis token (TR uyumlu)."""
    raw = unicodedata.normalize("NFC", (word or "").strip())
    raw = _PUNCT_STRIP.sub("", raw)
    if not raw:
        return ""
    # casefold TR: I/İ
    low = raw.replace("İ", "i").replace("I", "ı").casefold()
    low = low.replace("i̇", "i")
    low = _NON_WORD.sub("", low)
    return low


def _fold_tr_confusions(tok: str) -> str:
    """Whisper/TTS sik karistirdigi TR isaretlerini esitle (yalnizca hizalama)."""
    t = tok
    for a, b in (
        ("ş", "s"),
        ("ç", "c"),
        ("ğ", "g"),
        ("ö", "o"),
        ("ü", "u"),
        ("ı", "i"),
    ):
        t = t.replace(a, b)
    return t


def tokens_align_equal(a: str, b: str) -> bool:
    na, nb = normalize_align_token(a), normalize_align_token(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    fa, fb = _fold_tr_confusions(na), _fold_tr_confusions(nb)
    if fa == fb:
        return True
    # Kisa ek farki (bahce/bahceler)
    if len(fa) >= 4 and len(fb) >= 4:
        if fa.startswith(fb) or fb.startswith(fa):
            return abs(len(fa) - len(fb)) <= 3
    return False


def script_display_lines(script: str) -> list[str]:
    lines = [
        ln.strip()
        for ln in split_script_lines(script or "")
        if (ln or "").strip()
    ]
    if lines:
        return lines
    flat = " ".join((script or "").split())
    return [flat] if flat else []


def tokenize_keep(text: str) -> list[str]:
    """Boslukla kelime; noktalama kelimeye yapisik kalabilir (sonra norm)."""
    return [t for t in (text or "").split() if t.strip()]


def extract_whisper_words(
    audio_file: str, language: str = "tr"
) -> list[tuple[str, float, float]]:
    """faster-whisper word_timestamps → [(word, start, end), ...]."""
    if not audio_file:
        return []
    try:
        from akifactory.engine.services import subtitle as sub_svc
    except ImportError:
        return []

    if getattr(sub_svc, "WhisperModel", None) is None:
        return []

    # Model singleton (motor subtitle.create ile ayni)
    model = getattr(sub_svc, "model", None)
    if model is None:
        # create() model yukler; gecici SRT yazmadan sadece model kur
        try:
            import os

            from akifactory.engine.config import config
            from akifactory.engine.utils import utils

            model_size = config.whisper.get("model_size", "large-v3")
            device = config.whisper.get("device", "cpu")
            compute_type = config.whisper.get("compute_type", "int8")
            model_path = f"{utils.root_dir()}/models/whisper-{model_size}"
            model_bin = f"{model_path}/model.bin"
            if not os.path.isdir(model_path) or not os.path.isfile(model_bin):
                model_path = model_size
            model = sub_svc.WhisperModel(
                model_size_or_path=model_path,
                device=device,
                compute_type=compute_type,
            )
            sub_svc.model = model
        except Exception:
            return []

    lang = (language or "tr").strip().lower()
    if "-" in lang:
        lang = lang.split("-")[0]

    kwargs: dict[str, Any] = dict(
        beam_size=5,
        word_timestamps=True,
        # Agresif VAD kelime kesip ara bosluk/kayma yaratir; daha yumusak tut
        vad_filter=True,
        vad_parameters=dict(
            min_silence_duration_ms=500,
            speech_pad_ms=120,
        ),
        condition_on_previous_text=False,
    )
    if lang:
        kwargs["language"] = lang

    try:
        segments, _info = model.transcribe(audio_file, **kwargs)
    except Exception:
        return []

    words: list[tuple[str, float, float]] = []
    for segment in segments:
        seg_words = getattr(segment, "words", None) or []
        for w in seg_words:
            text = (getattr(w, "word", None) or "").strip()
            if not text:
                continue
            start = float(getattr(w, "start", 0.0) or 0.0)
            end = float(getattr(w, "end", 0.0) or 0.0)
            if end <= start:
                end = start + 0.08
            words.append((text, start, end))
    return words


def _align_script_to_whisper(
    script_tokens: list[str],
    whisper_words: list[tuple[str, float, float]],
) -> list[tuple[float, float] | None]:
    """Her senaryo kelimesi icin (start, end) veya None.

    SequenceMatcher ile ASR↔senaryo eslestirmesi; TTS metni ile Whisper
    metni birebir olmasa da zamanlari orantili tasir.
    """
    if not script_tokens or not whisper_words:
        return [None] * len(script_tokens)

    a = [normalize_align_token(t) for t in script_tokens]
    b = [normalize_align_token(t[0]) for t in whisper_words]
    # Sirayi koruyarak TR-yumusak eslesmeleri ayni sentinel yap
    sentinel_a = list(a)
    sentinel_b = list(b)
    j = 0
    for i, sa in enumerate(script_tokens):
        hit = None
        for k in range(j, min(len(whisper_words), j + 10)):
            if tokens_align_equal(sa, whisper_words[k][0]):
                hit = k
                break
        if hit is not None:
            key = f"§{i}"
            sentinel_a[i] = key
            sentinel_b[hit] = key
            j = hit + 1

    sm = SequenceMatcher(a=sentinel_a, b=sentinel_b, autojunk=False)
    mapping: list[tuple[float, float] | None] = [None] * len(script_tokens)

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for di, dj in zip(range(i1, i2), range(j1, j2)):
                _w, s, e = whisper_words[dj]
                mapping[di] = (s, e)
        elif tag == "replace":
            # Bloklari sure oranina gore dagit
            a_n = i2 - i1
            b_n = j2 - j1
            if a_n <= 0:
                continue
            if b_n <= 0:
                continue
            block = whisper_words[j1:j2]
            b_start = block[0][1]
            b_end = block[-1][2]
            span = max(b_end - b_start, 0.05)
            for k, di in enumerate(range(i1, i2)):
                # Her script kelimesine esit dilim
                t0 = b_start + span * (k / a_n)
                t1 = b_start + span * ((k + 1) / a_n)
                mapping[di] = (t0, max(t1, t0 + 0.05))
        elif tag == "delete":
            # Whisper'da karsiligi yok — sonra komsulardan doldur
            continue
        elif tag == "insert":
            # Fazla ASR kelimesi — atla
            continue

    # Bosluklari komsu zamanlardan doldur
    n = len(mapping)
    for i in range(n):
        if mapping[i] is not None:
            continue
        prev = next((mapping[j] for j in range(i - 1, -1, -1) if mapping[j]), None)
        nxt = next((mapping[j] for j in range(i + 1, n) if mapping[j]), None)
        if prev and nxt:
            mapping[i] = (prev[1], max(nxt[0], prev[1] + 0.05))
        elif prev:
            mapping[i] = (prev[1], prev[1] + 0.12)
        elif nxt:
            mapping[i] = (max(0.0, nxt[0] - 0.12), nxt[0])
        else:
            mapping[i] = None
    return mapping


def _spoken_tokens_for_align(line: str) -> list[str]:
    """TTS'in okudugu kelimeler — rakamlar yazıya dokulmus (altyazi metni degil)."""
    try:
        from akifactory.chatterbox_util import normalize_turkish_tts_text

        spoken = normalize_turkish_tts_text(line)
    except Exception:
        try:
            from akifactory.tts_numbers import expand_numbers_for_turkish_tts

            spoken = expand_numbers_for_turkish_tts(line)
        except Exception:
            spoken = line
    return tokenize_keep(spoken or line)


def build_aligned_srt_items(
    script: str,
    whisper_words: list[tuple[str, float, float]],
    *,
    audio_duration: float,
) -> list[tuple[float, float, str]]:
    """Senaryo satirlari + Whisper kelime zamanlari → (start, end, text).

    Ekranda orijinal metin (2600 rakam); hizalama TTS konusma metniyle yapilir
    (iki bin alti yuz) — boylece sayi/kayma kaynakli cift okuma hissi azalir.
    """
    lines = script_display_lines(script)
    if not lines:
        return []

    # Hizalama: TTS metni | Gorunum: orijinal satir
    line_toks: list[list[str]] = [_spoken_tokens_for_align(ln) for ln in lines]
    flat_tokens: list[str] = [t for toks in line_toks for t in toks]
    if not flat_tokens:
        return []

    if not whisper_words:
        return []

    word_times = _align_script_to_whisper(flat_tokens, whisper_words)
    matched = sum(1 for t in word_times if t is not None)
    # %25 altinda akustik eslesme guvenilmez → ust katman Whisper/Edge dener
    if matched < max(1, int(len(flat_tokens) * 0.25)):
        return []

    dur = max(float(audio_duration or 0), 0.0)
    w1 = whisper_words[-1][2]
    if dur <= 0.1:
        dur = w1

    items: list[tuple[float, float, str]] = []
    cursor = 0
    for line, toks in zip(lines, line_toks):
        if not toks:
            # TTS bosaldiysa yine de satiri goster — komsu zamandan pay
            items.append((-1.0, -1.0, line))
            continue
        span_times = word_times[cursor : cursor + len(toks)]
        cursor += len(toks)
        valid = [t for t in span_times if t is not None]
        if not valid:
            items.append((-1.0, -1.0, line))
            continue
        start = valid[0][0]
        end = valid[-1][1]
        if end <= start + 0.05:
            end = start + max(0.12, len(toks) * 0.08)
        items.append((start, end, line))

    # Placeholder (-1) satirlari komsulardan doldur
    for i, (start, end, text) in enumerate(items):
        if start >= 0:
            continue
        prev = next(((items[j][0], items[j][1]) for j in range(i - 1, -1, -1) if items[j][0] >= 0), None)
        nxt = next(((items[j][0], items[j][1]) for j in range(i + 1, len(items)) if items[j][0] >= 0), None)
        if prev and nxt:
            items[i] = (prev[1], max(nxt[0], prev[1] + 0.08), text)
        elif prev:
            items[i] = (prev[1], prev[1] + 0.2, text)
        elif nxt:
            items[i] = (max(0.0, nxt[0] - 0.2), nxt[0], text)
        else:
            items[i] = (0.0, max(0.2, dur * 0.1), text)

    if not items:
        return []

    # Monoton, surekli altyazi (TikTok): ara bosluklarda onceki satir kalsin
    fixed = _tighten_subtitle_cues(items, audio_duration=dur, whisper_end=w1)
    return fixed


_MIN_CUE_SEC = 0.70
_MAX_GAP_FILL_SEC = 2.0
_MERGE_SHORT_SEC = 0.65


def _tighten_subtitle_cues(
    items: list[tuple[float, float, str]],
    *,
    audio_duration: float,
    whisper_end: float,
) -> list[tuple[float, float, str]]:
    """Bosluklari kapat, cok kisa cue'leri birlestir — kayma hissini azalt."""
    dur = max(float(audio_duration or 0), 0.0)
    w1 = max(float(whisper_end or 0), 0.0)

    # 1) Cok kisa kuyruklari onceki satira yapistir ("doğruladı." gibi)
    merged: list[tuple[float, float, str]] = []
    for start, end, text in items:
        start = max(0.0, float(start))
        end = max(end, start + 0.08)
        text = (text or "").strip()
        if not text:
            continue
        if merged:
            prev_s, prev_e, prev_t = merged[-1]
            cue_dur = end - start
            word_n = len(text.split())
            if cue_dur < _MERGE_SHORT_SEC and word_n <= 3:
                joined = f"{prev_t} {text}".strip()
                merged[-1] = (prev_s, max(prev_e, end), joined)
                continue
        merged.append((start, end, text))

    if not merged:
        return []

    # 2) Bosluk doldur + minimum sure + monotonluk
    fixed: list[tuple[float, float, str]] = []
    for start, end, text in merged:
        if dur > 0.2:
            end = min(end, dur)
            start = min(start, max(0.0, dur - 0.08))
        end = max(end, start + 0.08)
        if fixed:
            prev_s, prev_e, prev_t = fixed[-1]
            if start < prev_e - 0.02:
                start = prev_e
            gap = start - prev_e
            if 0.02 < gap <= _MAX_GAP_FILL_SEC:
                # Sessizlikte bile onceki altyazi kalsin — kayma hissi azalir
                fixed[-1] = (prev_s, start, prev_t)
            elif gap > _MAX_GAP_FILL_SEC:
                # Uzun ara: bir miktar uzat, sonra yeni satir
                fixed[-1] = (prev_s, prev_e + 0.45, prev_t)
                start = max(start, prev_e + 0.45)
        if end < start + _MIN_CUE_SEC:
            end = start + _MIN_CUE_SEC
        if dur > 0.2:
            end = min(end, dur)
        if end <= start + 0.05:
            end = start + 0.1
        fixed.append((start, end, text))

    # 3) Cakisan bitisleri sonraki baslangica kirp
    for i in range(len(fixed) - 1):
        s, e, t = fixed[i]
        ns, ne, nt = fixed[i + 1]
        if e > ns + 0.01:
            cut = ns
            if cut - s < 0.35:
                # Cok sikisiksa sonraki basini biraz kaydir
                cut = s + 0.45
                fixed[i + 1] = (cut, max(ne, cut + 0.12), nt)
            fixed[i] = (s, cut, t)

    if fixed and dur > 0.2:
        ls, le, lt = fixed[-1]
        target_end = min(dur, max(le, min(dur, w1 + 0.25)))
        if target_end > ls + 0.08:
            fixed[-1] = (ls, target_end, lt)

    if fixed and fixed[0][0] > 0.85:
        # Gec baslayan ilk altyaziyi one cek (Whisper sessizligi)
        shift = fixed[0][0] - 0.08
        fixed = [(max(0.0, s - shift), max(0.08, e - shift), t) for s, e, t in fixed]
        if dur > 0.2:
            fixed = [(s, min(e, dur), t) for s, e, t in fixed]

    return fixed


def alignment_coverage_ratio(
    script: str, whisper_words: list[tuple[str, float, float]]
) -> float:
    """0–1: senaryo kelimelerinin kacinin ASR ile eslestigi (test/log)."""
    toks = tokenize_keep(" ".join(script_display_lines(script)))
    if not toks or not whisper_words:
        return 0.0
    times = _align_script_to_whisper(toks, whisper_words)
    return sum(1 for t in times if t is not None) / len(toks)


def _parse_srt_timestamp(ts: str) -> float:
    ts = (ts or "").strip().replace(".", ",")
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _fmt_srt_timestamp(sec: float) -> str:
    if sec < 0:
        sec = 0.0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms >= 1000:
        s += 1
        ms = 0
    if s >= 60:
        m += 1
        s = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def tighten_srt_file(subtitle_path: str, audio_duration: float = 0.0) -> int:
    """Mevcut SRT dosyasindaki bosluk/kisa cue kaymasini duzelt; cue sayisi doner."""
    import os
    from pathlib import Path

    path = Path(subtitle_path or "")
    if not path.is_file():
        return 0
    raw = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\s*\n", raw.strip())
    items: list[tuple[float, float, str]] = []
    for block in blocks:
        lines = [ln for ln in block.strip().splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        # index satiri opsiyonel
        time_ln = lines[0]
        text_start = 1
        if "-->" not in time_ln and len(lines) >= 3:
            time_ln = lines[1]
            text_start = 2
        if "-->" not in time_ln:
            continue
        try:
            a, b = [t.strip() for t in time_ln.split("-->")]
            start = _parse_srt_timestamp(a)
            end = _parse_srt_timestamp(b)
        except Exception:
            continue
        text = " ".join(lines[text_start:]).strip()
        if text and end > start:
            items.append((start, end, text))
    if not items:
        return 0

    whisper_end = items[-1][1]
    dur = float(audio_duration or 0.0)
    if dur <= 0.2:
        dur = whisper_end
    fixed = _tighten_subtitle_cues(items, audio_duration=dur, whisper_end=whisper_end)
    if not fixed:
        return 0

    out_chunks: list[str] = []
    for i, (s, e, text) in enumerate(fixed, start=1):
        out_chunks.append(
            f"{i}\n{_fmt_srt_timestamp(s)} --> {_fmt_srt_timestamp(e)}\n{text.strip()}\n"
        )
    path.write_text("\n".join(out_chunks) + "\n", encoding="utf-8")
    try:
        os.utime(path, None)
    except OSError:
        pass
    return len(fixed)
