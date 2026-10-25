"""motor senaryo / altyazi / Turkce metin runtime patch."""

from __future__ import annotations

from akifactory.text_utils import prepare_script_for_engine, split_script_lines


def apply_script_runtime_patch() -> None:
    _patch_split_string()
    _patch_turkish_orthography()
    _patch_generate_script()
    _patch_generate_terms()
    _patch_turkish_subtitle_timing()


def _patch_turkish_subtitle_timing() -> None:
    """Altyazi senkronu — Edge cue / Whisper kelime hizalama / script-only.

    motor orijinal (task.generate_subtitle):
      - Turkce → create_subtitle_script_only(senaryo, sure)
      - Diger → Edge cue veya Whisper + correct()

    Hatalar:
      1) motor sureyi once Edge cue'dan aliyor; RVC sesi farkli olunca kayar.
      2) subtitle.correct() fazla satira 00:00:00 yaziyor.
      3) Whisper dilimine karakter-oranli metin koyma sonlara kayar.
      4) Saf script-only degisken konusma hizinda kayar.

    Bu patch:
      - Turkce: once Whisper word-align (Edge/Chatterbox/RVC fark etmez)
      - Sonra Whisper segment + senaryo overlay
      - Edge cue yalnizca Whisper yokken ve cue~audio uyumluysa
      - Script-only son care (kayma riski; yine de bosluk sikilastirilir)
      - Tum yollarda tighten_srt_file (ara bosluk / kisa cue kaymasi)
      - 00:00:00 satiri uretme
    """
    try:
        from akifactory.engine.services import task, voice
        from akifactory.engine.utils import utils
    except ImportError:
        return
    if getattr(task, "_aki_turkish_subtitle_patched", False):
        return

    _orig = task.generate_subtitle

    def _audio_file_duration(audio_file: str) -> float:
        if not audio_file:
            return 0.0
        try:
            return float(voice.get_audio_duration(audio_file) or 0.0)
        except Exception:
            return 0.0

    def _submaker_duration(sub_maker) -> float:
        if sub_maker is None:
            return 0.0
        try:
            return float(voice.get_audio_duration(sub_maker) or 0.0)
        except Exception:
            return 0.0

    def _parse_srt_ts(ts: str) -> float:
        ts = (ts or "").strip().replace(".", ",")
        try:
            hms, ms = ts.split(",")
            h, m, s = hms.split(":")
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0
        except Exception:
            return 0.0

    def _fmt_srt_ts(sec: float) -> str:
        if sec < 0:
            sec = 0.0
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int(round((sec - int(sec)) * 1000.0))
        if ms >= 1000:
            s += 1
            ms = 0
        if s >= 60:
            m += 1
            s = 0
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def _write_srt(path: str, items: list[tuple[str, str]]) -> None:
        with open(path, "w", encoding="utf-8") as fd:
            for i, (times, text) in enumerate(items, start=1):
                fd.write(f"{i}\n{times}\n{text.strip()}\n\n")

    def _final_audio_duration(sub_maker, audio_file: str) -> float:
        """RVC/Chatterbox: dosya suresi. Saf Edge: cue ile dosya uyumluysa ikisi de OK."""
        file_dur = _audio_file_duration(audio_file)
        cue_dur = _submaker_duration(sub_maker)
        if file_dur > 0.15:
            return file_dur
        return max(float(cue_dur or 0), 0.1)

    def _finalize_srt_timing(subtitle_path: str, audio_duration: float) -> int:
        """Tum yollarda bosluk/kisa-cue kaymasini kapat."""
        try:
            from akifactory.subtitle_align import tighten_srt_file

            return int(tighten_srt_file(subtitle_path, audio_duration) or 0)
        except Exception:
            return 0

    def _scrub_and_keep_whisper(
        subtitle_path: str, audio_duration: float
    ) -> int:
        """Gecersiz satirlari at, sonra timing sikilastir."""
        from akifactory.engine.services import subtitle as sub_svc

        entries = sub_svc.file_to_subtitles(subtitle_path)
        items: list[tuple[str, str]] = []
        for _idx, times, text in entries:
            try:
                a, b = [t.strip() for t in times.split("-->")]
            except ValueError:
                continue
            start = _parse_srt_ts(a)
            end = _parse_srt_ts(b)
            if end <= start + 0.05:
                continue
            if audio_duration > 0.5:
                if start >= audio_duration:
                    continue
                end = min(end, audio_duration + 0.05)
                if end <= start + 0.05:
                    continue
            items.append(
                (f"{_fmt_srt_ts(start)} --> {_fmt_srt_ts(end)}", (text or "").strip())
            )
        if not items:
            return 0
        _write_srt(subtitle_path, items)
        n = _finalize_srt_timing(subtitle_path, audio_duration)
        return n if n > 0 else len(items)

    def _whisper_subtitles(
        *,
        audio_file: str,
        subtitle_path: str,
        video_language: str,
        duration: float,
    ) -> int:
        from akifactory.engine.services import subtitle as sub_svc

        lang = (video_language or "tr").strip().lower()
        if "-" in lang:
            lang = lang.split("-")[0]
        if hasattr(task, "_whisper_language"):
            lang = task._whisper_language(video_language) or lang
        sub_svc.create(
            audio_file=audio_file,
            subtitle_file=subtitle_path,
            language=lang,
        )
        return _scrub_and_keep_whisper(subtitle_path, duration)

    def _aligned_script_subtitles(
        *,
        audio_file: str,
        subtitle_path: str,
        video_script: str,
        video_language: str,
        duration: float,
    ) -> int:
        """Whisper kelime zamanlari + senaryo satirlari — orantili, kaymasiz."""
        from akifactory.subtitle_align import (
            build_aligned_srt_items,
            extract_whisper_words,
        )

        lang = (video_language or "tr").strip().lower()
        if "-" in lang:
            lang = lang.split("-")[0]
        if hasattr(task, "_whisper_language"):
            lang = task._whisper_language(video_language) or lang

        words = extract_whisper_words(audio_file, lang)
        if len(words) < 3:
            return 0
        items_raw = build_aligned_srt_items(
            video_script, words, audio_duration=duration
        )
        if not items_raw:
            return 0
        items = [
            (f"{_fmt_srt_ts(s)} --> {_fmt_srt_ts(e)}", text)
            for s, e, text in items_raw
            if (text or "").strip() and e > s + 0.05
        ]
        if not items:
            return 0
        _write_srt(subtitle_path, items)
        return len(items)

    def _overlay_script_on_whisper_timings(
        subtitle_path: str, video_script: str
    ) -> None:
        """[Eski yedek] Whisper dilimlerine sure-oranli metin — kayma riski var.

        Yeni yol: _aligned_script_subtitles (kelime hizalama).
        """
        from akifactory.engine.services import subtitle as sub_svc

        script = " ".join(
            ln.strip()
            for ln in split_script_lines(video_script or "")
            if (ln or "").strip()
        ).strip()
        if not script:
            return
        entries = sub_svc.file_to_subtitles(subtitle_path)
        if not entries:
            return

        spans: list[tuple[float, float, str]] = []
        for _idx, times, _text in entries:
            try:
                a, b = [t.strip() for t in times.split("-->")]
            except ValueError:
                continue
            start, end = _parse_srt_ts(a), _parse_srt_ts(b)
            if end <= start + 0.05:
                continue
            spans.append((start, end, times))
        if not spans:
            return

        total = sum(e - s for s, e, _ in spans)
        if total <= 0.1:
            return

        def _cut_at_boundary(text: str, target: int) -> int:
            if target >= len(text):
                return len(text)
            if target <= 0:
                return 0
            window = text[max(0, target - 24) : min(len(text), target + 24)]
            base = max(0, target - 24)
            best = None
            for sep in (". ", "! ", "? ", "; ", ", ", " "):
                pos = window.rfind(sep)
                if pos >= 0:
                    cand = base + pos + len(sep)
                    if best is None or abs(cand - target) < abs(best - target):
                        best = cand
            return best if best is not None else target

        items: list[tuple[str, str]] = []
        cursor = 0
        n_chars = len(script)
        for i, (start, end, times) in enumerate(spans):
            if i == len(spans) - 1:
                chunk = script[cursor:].strip()
            else:
                share = (end - start) / total
                target = cursor + max(1, int(round(n_chars * share)))
                cut = _cut_at_boundary(script, target)
                if cut <= cursor:
                    cut = min(n_chars, cursor + max(8, target - cursor))
                chunk = script[cursor:cut].strip()
                cursor = cut
            if chunk:
                items.append((times, chunk))
        if items:
            _write_srt(subtitle_path, items)

    def _generate_subtitle(task_id, params, video_script, sub_maker, audio_file):
        if not params.subtitle_enabled or sub_maker is None:
            return ""
        if not (video_script or "").strip():
            return _orig(task_id, params, video_script, sub_maker, audio_file)

        import os

        from akifactory.engine.config import config
        from akifactory.engine.services import turkish_text
        from loguru import logger

        video_language = getattr(params, "video_language", "") or ""
        turkish = (video_language or "").strip().lower().startswith("tr")
        subtitle_path = os.path.join(utils.task_dir(task_id), "subtitle.srt")
        voice_name = str(getattr(params, "voice_name", "") or "").lower()
        is_converted = voice_name.startswith("rvc:") or "chatterbox" in voice_name
        provider = (
            (config.app.get("subtitle_provider") or "edge").strip().lower()
        )

        if turkish:
            video_script = turkish_text.apply_turkish_orthography(
                video_script, video_language
            )

        file_dur = _audio_file_duration(audio_file)
        cue_dur = _submaker_duration(sub_maker)
        duration = _final_audio_duration(sub_maker, audio_file)
        cues_match_audio = (
            file_dur > 0.2
            and cue_dur > 0.2
            and abs(cue_dur - file_dur) <= 0.45
            and not is_converted
        )

        # --- Turkce ---
        # Oncelik: Whisper kelime hizalama (Chatterbox/RVC/Edge hepsi).
        # Script-only karakter-oranli oldugu icin kayma yapar — son care.
        if turkish:
            if audio_file and os.path.isfile(audio_file):
                try:
                    n = _aligned_script_subtitles(
                        audio_file=audio_file,
                        subtitle_path=subtitle_path,
                        video_script=video_script,
                        video_language=video_language or "tr",
                        duration=duration,
                    )
                    if n > 0:
                        _finalize_srt_timing(subtitle_path, duration)
                        logger.info(
                            f"Turkish subtitles via Whisper word-align "
                            f"({n} cues, audio={duration:.2f}s "
                            f"converted={is_converted})"
                        )
                        return subtitle_path
                except Exception as exc:
                    logger.warning(
                        f"word-align subtitle failed, trying segment whisper: {exc}"
                    )
                try:
                    n = _whisper_subtitles(
                        audio_file=audio_file,
                        subtitle_path=subtitle_path,
                        video_language=video_language or "tr",
                        duration=duration,
                    )
                    if n > 0:
                        try:
                            _overlay_script_on_whisper_timings(
                                subtitle_path, video_script
                            )
                        except Exception as exc:
                            logger.warning(
                                f"script overlay on whisper timings skipped: {exc}"
                            )
                        _finalize_srt_timing(subtitle_path, duration)
                        logger.info(
                            f"Turkish subtitles via Whisper segments "
                            f"(fallback, {n} cues, audio={duration:.2f}s)"
                        )
                        return subtitle_path
                except Exception as exc:
                    logger.warning(
                        f"Turkish whisper subtitle failed: {exc}"
                    )

            # Saf Edge + cue uyumluysa (Whisper yok/basarisiz)
            if (
                not is_converted
                and cues_match_audio
                and hasattr(sub_maker, "cues")
                and sub_maker.cues
            ):
                voice.create_subtitle(
                    sub_maker, video_script, subtitle_path, script_only=False
                )
                if os.path.isfile(subtitle_path):
                    n = _scrub_and_keep_whisper(subtitle_path, duration)
                    if n > 0:
                        logger.info(
                            f"Turkish subtitles via Edge cues "
                            f"(cue={cue_dur:.2f}s audio={file_dur:.2f}s)"
                        )
                        return subtitle_path

            # Son care: karakter-oranli (donusturulmus seste tercihen kullanma)
            if voice.create_subtitle_script_only(
                video_script, subtitle_path, duration
            ):
                _finalize_srt_timing(subtitle_path, duration)
                logger.warning(
                    f"Turkish script-only subtitles (kayma riski) "
                    f"(audio={duration:.2f}s cue={cue_dur:.2f}s "
                    f"converted={is_converted})"
                )
                return subtitle_path

            sm = voice.populate_legacy_submaker_with_full_text(
                voice.ensure_legacy_submaker_fields(sub_maker),
                video_script,
                duration,
            )
            voice.create_subtitle(sm, video_script, subtitle_path, script_only=True)
            if os.path.isfile(subtitle_path):
                _finalize_srt_timing(subtitle_path, duration)
                return subtitle_path
            return ""

        # --- EN / diger: kelime hizalama (donusturulmus) veya Whisper ---
        use_whisper = (
            provider == "whisper"
            or is_converted
            or not cues_match_audio
        )
        if use_whisper and audio_file and os.path.isfile(audio_file):
            if is_converted:
                try:
                    n = _aligned_script_subtitles(
                        audio_file=audio_file,
                        subtitle_path=subtitle_path,
                        video_script=video_script,
                        video_language=video_language or "en",
                        duration=duration,
                    )
                    if n > 0:
                        logger.info(
                            f"Non-TR subtitles via Whisper word-align "
                            f"({n} cues, audio={duration:.2f}s)"
                        )
                        return subtitle_path
                except Exception as exc:
                    logger.warning(f"non-TR word-align failed: {exc}")
            try:
                n = _whisper_subtitles(
                    audio_file=audio_file,
                    subtitle_path=subtitle_path,
                    video_language=video_language or "en",
                    duration=duration,
                )
                if n > 0:
                    logger.info(
                        f"Non-TR subtitles via whisper (kept, "
                        f"{n} cues, audio={duration:.2f}s)"
                    )
                    return subtitle_path
            except Exception as exc:
                logger.warning(f"whisper subtitle failed: {exc}")

        if cues_match_audio and hasattr(sub_maker, "cues") and sub_maker.cues:
            voice.create_subtitle(
                sub_maker, video_script, subtitle_path, script_only=False
            )
            if os.path.isfile(subtitle_path):
                return subtitle_path

        if voice.create_subtitle_script_only(
            video_script, subtitle_path, duration
        ):
            return subtitle_path
        return _orig(task_id, params, video_script, sub_maker, audio_file)

    def _subtitle_audio_duration(sub_maker, audio_file: str) -> float:
        return _final_audio_duration(sub_maker, audio_file)

    # motor correct() 00:00:00 yazmasin — baska yollardan cagrilsa bile
    try:
        from akifactory.engine.services import subtitle as sub_mod

        if not getattr(sub_mod, "_aki_correct_patched", False):
            _orig_correct = sub_mod.correct

            def _correct_no_zeros(subtitle_file, video_script):
                _orig_correct(subtitle_file, video_script)
                # Sifir zamanli satirlari temizle / yay
                try:
                    dur = 0.0
                    # audio yaninda degil; SRT'deki son gecerli end'e gore yay
                    entries = sub_mod.file_to_subtitles(subtitle_file)
                    good: list[tuple[float, float, str]] = []
                    bad_texts: list[str] = []
                    for _i, times, text in entries:
                        try:
                            a, b = [t.strip() for t in times.split("-->")]
                        except ValueError:
                            continue
                        start, end = _parse_srt_ts(a), _parse_srt_ts(b)
                        if end <= start + 0.05:
                            if (text or "").strip():
                                bad_texts.append(text.strip())
                            continue
                        good.append((start, end, (text or "").strip()))
                    if not bad_texts:
                        if good:
                            items = [
                                (f"{_fmt_srt_ts(s)} --> {_fmt_srt_ts(e)}", t)
                                for s, e, t in good
                            ]
                            _write_srt(subtitle_file, items)
                        return
                    last_end = good[-1][1] if good else 0.0
                    # Kalan metinleri esit aralikla 2sn'lik dilimlere koy
                    # (audio suresi bilinmiyor; en azindan 00:00:00 yok)
                    cursor = last_end
                    for text in bad_texts:
                        span = max(0.8, min(2.5, 0.05 * max(len(text), 8)))
                        good.append((cursor, cursor + span, text))
                        cursor += span
                    items = [
                        (f"{_fmt_srt_ts(s)} --> {_fmt_srt_ts(e)}", t)
                        for s, e, t in good
                    ]
                    _write_srt(subtitle_file, items)
                except Exception:
                    pass

            sub_mod.correct = _correct_no_zeros
            sub_mod._aki_correct_patched = True
    except Exception:
        pass

    task.generate_subtitle = _generate_subtitle
    task._subtitle_audio_duration = _subtitle_audio_duration
    task._aki_turkish_subtitle_patched = True


def _patch_split_string() -> None:
    try:
        from akifactory.engine.utils import utils
    except ImportError:
        return
    if getattr(utils, "_aki_script_split_patched", False):
        return

    def _split(s: str) -> list[str]:
        if not (s or "").strip():
            return []
        return split_script_lines(s)

    utils.split_string_by_punctuations = _split
    utils._aki_script_split_patched = True


def _patch_turkish_orthography() -> None:
    try:
        from akifactory.engine.services import turkish_text
    except ImportError:
        return
    if getattr(turkish_text, "_aki_orthography_patched", False):
        return

    def _safe(text: str, video_language: str = "") -> str:
        if not text:
            return text
        lang = (video_language or "").lower().split("-")[0] or "tr"
        raw = text.strip()
        return prepare_script_for_engine(raw, lang) or raw

    turkish_text.apply_turkish_orthography = _safe
    turkish_text._aki_orthography_patched = True


def _patch_generate_terms() -> None:
    """SubtitleRequest'te video_terms / video_subject yok; motor patlamasin."""
    try:
        from akifactory.engine.services import task
    except ImportError:
        return
    if getattr(task, "_aki_generate_terms_patched", False):
        return

    import re

    from loguru import logger

    _orig = task.generate_terms

    def _generate_terms(task_id, params, video_script):
        video_terms = getattr(params, "video_terms", None)
        if not video_terms:
            from akifactory.engine.services import llm

            subject = (getattr(params, "video_subject", None) or "").strip()
            video_terms = llm.generate_terms(
                video_subject=subject, video_script=video_script, amount=7
            )
        else:
            if isinstance(video_terms, str):
                video_terms = [term.strip() for term in re.split(r"[,，]", video_terms)]
            elif isinstance(video_terms, list):
                video_terms = [term.strip() for term in video_terms]
            else:
                raise ValueError("video_terms must be a string or a list of strings.")
            logger.debug(f"video terms: {video_terms}")

        if not video_terms:
            from akifactory.engine.models import const
            from akifactory.engine.services import state as sm

            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error("failed to generate video terms.")
            return None
        return video_terms

    task.generate_terms = _generate_terms
    task._aki_generate_terms_patched = True


def _patch_generate_script() -> None:
    try:
        from akifactory.engine.services import task
        from loguru import logger
    except ImportError:
        return
    if getattr(task, "_aki_generate_script_patched", False):
        return

    _orig = task.generate_script

    def _generate(task_id, params):
        script = (getattr(params, "video_script", None) or "").strip()
        if not script:
            return _orig(task_id, params)

        lang = (getattr(params, "video_language", "") or "tr").lower()
        lang_id = lang.split("-")[0] if lang else "tr"
        cleaned = prepare_script_for_engine(script, lang_id) or script
        if not cleaned.strip():
            cleaned = script
        params.video_script = cleaned
        logger.info(
            f"using provided video script ({len(cleaned)} chars), skip motor LLM script step"
        )
        return cleaned

    task.generate_script = _generate
    task._aki_generate_script_patched = True
