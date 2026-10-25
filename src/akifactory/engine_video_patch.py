"""Yerel klip yolu, AI gorsel onceligi + eksik sureyi stokla doldurma.

motor local kaynakta video_terms uretmiyor; AI stok doldurma bu yuzden bos kaliyordu
ve combine_videos ayni klip baslarini donguye aliyordu.
"""

from __future__ import annotations


def apply_video_runtime_patch() -> None:
    try:
        from akifactory.engine.services import task
        from akifactory.engine.services import video as video_svc
    except ImportError:
        return
    if getattr(task, "_aki_video_patched", False):
        return

    from loguru import logger

    from akifactory.engine.models import const
    from akifactory.engine.models.schema import VideoConcatMode
    from akifactory.engine.services import state as sm

    _orig_get = task.get_video_materials
    _orig_start = task.start
    _orig_combine = video_svc.combine_videos

    def _resolve_local_material_paths(urls: list[str]) -> list[str]:
        from akifactory.engine.utils import file_security, utils

        local_videos_dir = utils.storage_dir("local_videos", create=True)
        resolved: list[str] = []
        for url in urls:
            if not url:
                continue
            try:
                resolved.append(
                    str(
                        file_security.resolve_path_within_directory(
                            local_videos_dir, url
                        )
                    )
                )
            except ValueError:
                resolved.append(url)
        return resolved

    def _path_is_ai(path: str) -> bool:
        return "_ai_" in str(path or "").replace("\\", "/")

    def _is_ai_staged(params, urls: list[str]) -> bool:
        if any(_path_is_ai(u) for u in urls):
            return True
        mats = getattr(params, "video_materials", None) or []
        for m in mats:
            url = getattr(m, "url", None)
            if url is None and isinstance(m, dict):
                url = m.get("url")
            if _path_is_ai(str(url or "")):
                return True
        return False

    def _file_duration(path: str) -> float:
        try:
            clip = video_svc._open_video_clip_quietly(path)
            try:
                return float(clip.duration or 0)
            finally:
                video_svc.close_clip(clip)
        except Exception:
            return 0.0

    def _usable_duration(path: str, max_clip: int) -> float:
        """AI montajda dosyanin tamamini kullaniriz."""
        dur = _file_duration(path)
        if dur <= 0:
            return float(max_clip)
        return dur

    def _fill_source() -> str:
        import os

        env = (os.environ.get("AKI_AI_STOCK_FILL") or "").strip().lower()
        if env in ("pexels", "pixabay", "pexels+pixabay"):
            return env
        try:
            from akifactory.engine.config import config

            src = str(config.app.get("video_source") or "pexels").strip().lower()
            if src and src != "local":
                return src
        except Exception:
            pass
        return "pexels"

    def _ensure_search_terms(params, video_terms) -> list[str]:
        if isinstance(video_terms, list) and video_terms:
            return [str(t).strip() for t in video_terms if str(t).strip()]
        if isinstance(video_terms, str) and video_terms.strip():
            return [
                t.strip()
                for t in video_terms.replace("，", ",").split(",")
                if t.strip()
            ]

        subject = (getattr(params, "video_subject", None) or "").strip()
        script = (getattr(params, "video_script", None) or "").strip()
        try:
            from akifactory.video_search_terms import (
                fallback_search_terms,
                generate_search_terms,
            )

            gen = None
            try:
                from akifactory.engine.services import llm as engine_llm

                gen = getattr(engine_llm, "_generate_response", None)
            except Exception:
                gen = None

            if callable(gen):
                terms = generate_search_terms(
                    subject,
                    script,
                    amount=7,
                    generate_response=gen,
                )
            else:
                terms = fallback_search_terms(subject, script, amount=7)
            if terms:
                logger.info(f"AI stok arama terimleri: {terms}")
                return terms
            terms = fallback_search_terms(subject, script, amount=7)
            if terms:
                logger.info(f"AI stok arama terimleri (domain yedek): {terms}")
                return terms
        except Exception as exc:
            logger.warning(f"AI stok terim uretimi basarisiz: {exc}")

        terms = [
            "ancient archaeological ruins",
            "museum historical artifact",
            "mysterious ancient chamber",
        ]
        logger.info(f"AI stok arama terimleri (son yedek): {terms}")
        return terms

    def get_video_materials(task_id, params, video_terms, audio_duration):
        result = _orig_get(task_id, params, video_terms, audio_duration)
        if not result or getattr(params, "video_source", "") != "local":
            return result

        local_urls = _resolve_local_material_paths(list(result))
        max_clip = int(getattr(params, "video_clip_duration", 5) or 5)
        audio_dur = float(audio_duration or 0)

        if not _is_ai_staged(params, local_urls) or audio_dur <= 0:
            return local_urls

        covered = sum(_usable_duration(p, max_clip) for p in local_urls)
        if covered >= audio_dur * 0.98:
            logger.info(
                f"AI local yeterli: {covered:.1f}s >= ses {audio_dur:.1f}s — stok yok"
            )
            return local_urls

        need = max(float(max_clip) * 2, audio_dur - covered + float(max_clip))
        fill_src = _fill_source()
        terms = _ensure_search_terms(params, video_terms)
        logger.info(
            f"AI local once ({covered:.1f}s / {len(local_urls)} dosya), "
            f"eksik ~{need:.1f}s stok ({fill_src})"
        )
        try:
            from akifactory.engine.services import material

            fill_paths = (
                material.download_videos(
                    task_id=task_id,
                    search_terms=terms,
                    source=fill_src,
                    video_aspect=params.video_aspect,
                    video_contact_mode=getattr(params, "video_concat_mode", None),
                    audio_duration=need,
                    max_clip_duration=max_clip,
                )
                or []
            )
        except Exception as exc:
            logger.warning(f"AI stok doldurma basarisiz: {exc}")
            fill_paths = []

        if fill_paths:
            logger.info(f"AI stok eklendi: {len(fill_paths)} klip (kullanici once)")
            return local_urls + list(fill_paths)

        logger.warning("AI stok bos — dosyanin tamami sirayla kullanilacak")
        return local_urls

    def _combine_ai_full_sequential(
        *,
        combined_video_path,
        video_paths,
        audio_file,
        video_aspect,
        video_transition_mode,
        max_clip_duration,
        threads,
        orig_combine,
    ):
        """Kullanici AI klipleri tek parca (or. 1x20sn); stok 5sn dilim.

        Sonra motor sequential + yuksek max_clip ile her dosya bir kez, bas dongusu yok.
        """
        import os

        from moviepy import AudioFileClip

        stock_clip = int(max_clip_duration or 5)
        try:
            audio_clip = AudioFileClip(audio_file)
            try:
                audio_duration = float(audio_clip.duration or 0)
            finally:
                video_svc.close_clip(audio_clip)
        except Exception:
            audio_duration = 0.0

        out_dir = os.path.dirname(combined_video_path) or "."
        expanded: list[str] = []
        total = 0.0
        longest = float(stock_clip)
        ai_speed = 1.06
        # Motor eksik kalan sureyi bastaki klibi tekrar ederek doldurur — hedefi biraz as.
        target = audio_duration + 0.25 if audio_duration > 0 else 0.0
        ai_indexes = [i for i, p in enumerate(video_paths) if _path_is_ai(p)]
        last_ai = ai_indexes[-1] if ai_indexes else -1
        # Sahneler senaryo sirasiyla yazildi: AI toplami sesten uzunsa hepsini ayni oranda
        # kisalt, yoksa sondaki sahneler (kapanis) 1 sn'ye duser.
        ai_fit = 1.0
        if audio_duration > 0 and ai_indexes:
            ai_total = sum(_file_duration(video_paths[i]) for i in ai_indexes) / ai_speed
            if ai_total > audio_duration:
                ai_fit = audio_duration / ai_total
                logger.info(
                    f"AI klipler {ai_total:.1f}s > ses {audio_duration:.1f}s — "
                    f"her sahne %{ai_fit * 100:.0f} kullanilacak"
                )

        for vi, path in enumerate(video_paths):
            if target > 0 and total >= target:
                break
            try:
                clip = video_svc._open_video_clip_quietly(path)
            except Exception as exc:
                logger.warning(f"AI montaj klip acilamadi: {path} ({exc})")
                continue
            try:
                dur = float(clip.duration or 0)
                if dur <= 0:
                    continue
                is_user_ai = _path_is_ai(path)

                if is_user_ai:
                    # 1x20sn gibi: tek parca, cok ufak hizlandir (tempo)
                    user_speed = ai_speed
                    # Son AI klibi kalan sureyi kapatir (kare yuvarlamasi dahil)
                    slice_len = dur if vi == last_ai else dur * ai_fit
                else:
                    # Stok: klasik 5sn dilimler
                    slice_len = stock_clip
                    user_speed = 1.0
                start = 0.0

                part = 0
                while start < dur - 0.05 and (target <= 0 or total < target):
                    rem = max(0.1, target - total) if target > 0 else dur
                    end = min(start + slice_len, dur, start + rem * user_speed)
                    if end <= start + 0.05:
                        break
                    seg = clip.subclipped(start, end)
                    if user_speed != 1.0:
                        try:
                            from moviepy import vfx

                            seg = seg.with_effects([vfx.MultiplySpeed(user_speed)])
                        except Exception:
                            try:
                                seg = seg.speedx(user_speed)
                            except Exception:
                                pass
                    seg_path = os.path.join(
                        out_dir,
                        f"aki-ai-seg-{vi:02d}-{part:02d}.mp4",
                    )
                    try:
                        video_svc._write_clip_video(seg, seg_path)
                        expanded.append(seg_path)
                        seg_dur = float(seg.duration or ((end - start) / user_speed))
                        total += seg_dur
                        longest = max(longest, seg_dur)
                    except Exception as exc:
                        logger.warning(f"AI dilim yazilamadi: {exc}")
                    finally:
                        video_svc.close_clip(seg)
                    if is_user_ai:
                        break  # kullanici dosyasi tek parca
                    start = end
                    part += 1
            finally:
                video_svc.close_clip(clip)

        if not expanded:
            logger.warning("AI dilim yok — orijinal combine")
            return orig_combine(
                combined_video_path,
                video_paths,
                audio_file,
                video_aspect=video_aspect,
                video_concat_mode=VideoConcatMode.sequential,
                video_transition_mode=video_transition_mode,
                max_clip_duration=max_clip_duration,
                threads=threads,
            )

        # Her genisletilmis dosya bir kez tam kullanilsin (motor 5sn'e tekrar kesmesin)
        bump = min(120, max(stock_clip, int(longest) + 1))
        logger.info(
            f"AI montaj: {len(expanded)} parca, ~{total:.1f}s / ses {audio_duration:.1f}s "
            f"(kullanici tek parca + stok dilim, max_clip={bump})"
        )
        return orig_combine(
            combined_video_path,
            expanded,
            audio_file,
            video_aspect=video_aspect,
            video_concat_mode=VideoConcatMode.sequential,
            video_transition_mode=video_transition_mode,
            max_clip_duration=bump,
            threads=threads,
        )

    def combine_videos(
        combined_video_path,
        video_paths,
        audio_file,
        video_aspect=None,
        video_concat_mode=None,
        video_transition_mode=None,
        max_clip_duration: int = 5,
        threads: int = 2,
    ):
        paths = list(video_paths or [])
        if not any(_path_is_ai(p) for p in paths):
            return _orig_combine(
                combined_video_path,
                video_paths,
                audio_file,
                video_aspect=video_aspect,
                video_concat_mode=video_concat_mode,
                video_transition_mode=video_transition_mode,
                max_clip_duration=max_clip_duration,
                threads=threads,
            )

        mode_val = getattr(video_concat_mode, "value", video_concat_mode)
        if mode_val == VideoConcatMode.sequential.value or str(mode_val) == "sequential":
            logger.info(
                "AI montaj: tam dosya dilimleri (sequential break kapali)"
            )
            return _combine_ai_full_sequential(
                combined_video_path=combined_video_path,
                video_paths=paths,
                audio_file=audio_file,
                video_aspect=video_aspect,
                video_transition_mode=video_transition_mode,
                max_clip_duration=max_clip_duration,
                threads=threads,
                orig_combine=_orig_combine,
            )

        return _orig_combine(
            combined_video_path,
            video_paths,
            audio_file,
            video_aspect=video_aspect,
            video_concat_mode=video_concat_mode,
            video_transition_mode=video_transition_mode,
            max_clip_duration=max_clip_duration,
            threads=threads,
        )

    def start(task_id, params, stop_at: str = "video"):
        try:
            return _orig_start(task_id, params, stop_at=stop_at)
        except Exception as exc:
            logger.exception(f"task {task_id} failed: {exc}")
            sm.state.update_task(
                task_id,
                state=const.TASK_STATE_FAILED,
                error=str(exc) or "Video montaji basarisiz",
            )
            return None

    task.get_video_materials = get_video_materials
    task.start = start
    video_svc.combine_videos = combine_videos
    task._aki_video_patched = True
