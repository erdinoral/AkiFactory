"""Tek QC kapisi — writer/finalize icin (Faz D).

Mevcut script_quality + script_hooks kurallarini bir yerden cagirir.
Geri al: bu dosya; eski daginik cagrilara donulebilir.
"""

from __future__ import annotations

from typing import Any

from akifactory import script_hooks as script_hk
from akifactory import script_quality as script_q
from akifactory.text_utils import enforce_spoken_script_limits, repair_script_narration


async def orchestrate_script_qc(
    text: str,
    topic: str,
    *,
    niche_id: str = "genel",
    strengthen_hook: bool = True,
    scrub_filler: bool = True,
    stage: str = "writer",
) -> dict[str, Any]:
    """Tek gecis: filler scrub + kritik sorunlarda bir kez hook guclendirme.

    Returns: {text, strengthened: bool, critical: bool, stage}
    """
    out = (text or "").strip()
    if not out:
        return {
            "text": "",
            "strengthened": False,
            "critical": False,
            "stage": stage,
        }

    strengthened = False
    out = repair_script_narration(out)
    if scrub_filler and not script_hk.is_kids_niche(niche_id):
        out = script_q.scrub_filler_sentences(out, topic)
        out = enforce_spoken_script_limits(out)

    critical = script_q.has_critical_quality_issues(out, topic, niche_id=niche_id)
    if strengthen_hook and critical:
        out = (await script_hk.strengthen_hook(out, topic, niche_id=niche_id)).strip()
        out = repair_script_narration(out)
        out = enforce_spoken_script_limits(out)
        strengthened = True
        critical = script_q.has_critical_quality_issues(out, topic, niche_id=niche_id)

    return {
        "text": out,
        "strengthened": strengthened,
        "critical": critical,
        "stage": stage,
        "acceptable": script_q.is_script_acceptable(out, topic, niche_id=niche_id),
    }


def caption_quality_issues(
    caption: str,
    topic: str,
    *,
    max_len: int = 420,
) -> list[str]:
    """Caption QC — bos/konu disi/uzun/baslik-taklidi."""
    import re

    issues: list[str] = []
    cap = (caption or "").strip()
    if len(cap) < 40:
        issues.append("cok_kisa")
    if len(cap) > max_len + 40:
        issues.append("cok_uzun")
    low = cap.lower()
    banned = ("tikla", "abone ol", "like at", "link bio", "linkte")
    if any(b in low for b in banned):
        issues.append("yasak_cta")

    # "Derinkuyu Yeralti Sehri 1 🕵️" gibi baslik+numara — gercek aciklama degil
    bare = re.sub(r"[\W_]+", " ", cap, flags=re.UNICODE).strip()
    words = [w for w in bare.split() if w]
    if len(words) <= 6 and re.search(r"\b\d{1,2}\b", bare):
        issues.append("baslik_taklidi")
    if len(words) <= 5 and len(cap) < 80:
        issues.append("baslik_taklidi")
    # Tek cumle + emoji, nokta yok, cok kisa anlatim
    if cap.count(".") + cap.count("!") + cap.count("?") == 0 and len(cap) < 90:
        issues.append("az_cumle_aciklama")

    # Konu ortusmesi (kaba)
    from akifactory.script_topic import normalize_text_for_match, topic_anchor_phrases

    anchors = topic_anchor_phrases(topic) or []
    if anchors:
        hit = sum(1 for a in anchors[:6] if normalize_text_for_match(a) in normalize_text_for_match(cap))
        if hit == 0 and len(normalize_text_for_match(topic)) >= 4:
            t = normalize_text_for_match(topic)
            if t and t[:8] not in normalize_text_for_match(cap) and len(cap) > 20:
                issues.append("konu_ortusmesi_zayif")
    return issues
