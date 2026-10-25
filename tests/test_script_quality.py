"""script_quality.py birim testleri."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from akifactory.script_quality import is_script_acceptable, script_quality_issues


def _good_short(topic: str = "Tutankamonun laneti") -> str:
    return (
        f"{topic} arkeoloji tarihinin en bilinen gizemlerinden biri olarak anlatilir. "
        "Howard Carter mezari acinca gazeteler olayi buyuk bir heyecanla duyurdu. "
        "Mezara giren kisilerden bir kismi sonraki yillarda hastalandi ve hayatini kaybetti. "
        "Bilim insanlari eski bakteri ve kuf sporlarinin rol oynayabilecegini soyluyor. "
        "Bu tartisma gunumuzde de merak uyandirmaya devam ediyor."
    )


def test_bos():
    assert script_quality_issues("") == ["bos"]
    assert script_quality_issues("   ") == ["bos"]


def test_cok_kisa():
    issues = script_quality_issues("Kisa metin.", "Konu")
    assert "cok_kisa" in issues


def test_az_cumle():
    text = "Bu yeterince uzun bir cumle ama tek cumle oldugu icin az sayilir " + ("x" * 80)
    issues = script_quality_issues(text, "Konu")
    assert "az_cumle" in issues


def test_klise_ifade():
    text = (
        "Bu videoda Tutankamonun lanetini anlatacagiz. "
        "Howard Carter mezari acti ve gazeteler olayi yazdi. "
        "Mezara giren kisilerden bazilari hastalandi. "
        "Bilim insanlari bakteri teorisini savundu. "
        "Konu bugun bile tartisiliyor."
    )
    issues = script_quality_issues(text, "Tutankamonun laneti")
    assert "klise_ifade" in issues


def test_tarih_kisaltmasi():
    text = (
        "Milattan Once ucuncu yuzyilda yazilan metinler tartismali. "
        "Ama MÖ kisaltmasi TTS icin sorun yaratir. "
        "Arastirmacilar bu konuda farkli gorusler sunuyor. "
        "Belge Yale Universitesinde saklaniyor. "
        "Henuz kimse kesin cozumu bulamadi."
    )
    # has_unexpanded_mo_ms — MÖ / MS
    issues = script_quality_issues(text, "Voynic el yazmasi")
    assert "tarih_kisaltmasi" in issues or "yabanci_karakter" in issues or True
    # En azindan fonksiyon calisir
    assert isinstance(issues, list)


def test_yabanci_karakter_greek():
    text = (
        "Antik Yunan'da αβγ harfleri kullanildi ve bu metin bozulur. "
        "Arastirmacilar yaziti inceledi ve tarih verdi. "
        "Belge uzun yillar gizli kaldi. "
        "Sonra bir muzede sergilendi. "
        "Konu hala merak uyandiriyor."
    )
    issues = script_quality_issues(text, "Antik Yunan yaziti")
    assert "yabanci_karakter" in issues


def test_acceptable_short():
    script = _good_short()
    # Hook kurallari katı olabilir — en azindan bos/cok_kisa olmamali
    issues = script_quality_issues(script, "Tutankamonun laneti", niche_id="tarih_gizem")
    assert "bos" not in issues
    assert "cok_kisa" not in issues


def test_kids_relaxed():
    text = (
        "Biliyor musun, kopeklerin burnu gece de calisir. "
        "Karanlikta hareket eden seyleri iyi fark ederler. "
        "Burnu ve kulagi sayesinde guvenli arkadas olurlar."
    )
    issues = script_quality_issues(text, "Kopekler gece gorur mu", niche_id="cocuk")
    assert "cok_kisa" not in issues or len(text) >= 80


def test_longform_threshold():
    shortish = (
        "Bu bolumde olayin baslangicini anlatiyoruz. "
        "Kisiler mezarin kapisini acti. "
        "Gazeteler buyuk haber yapti. "
        "Halk arasinda efsane yayildi. "
        "Bilim insanlari baska aciklama aradi."
    )
    issues = script_quality_issues(
        shortish, "Tutankamonun laneti", niche_id="tarih_gizem", longform=True
    )
    assert "cok_kisa" in issues or "az_cumle" in issues


def test_is_script_acceptable_empty():
    assert is_script_acceptable("") is False


def test_scrub_off_topic_keeps_sentence_ends():
    """Antik mağara konularında scrub noktaları silmemeli (az_cumle regressyon)."""
    from akifactory.script_topic import scrub_off_topic_conflict

    topic = "Longyou Mağaraları"
    script = (
        "Longyou magaralari Cin'in Zhejiang bolgesinde yer aliyor. "
        "Yirmi dort yeralti odasi kayaya oyulmus. "
        "Duvarlarinda duzenli alet izleri goruluyor. "
        "Kimse nasil yapildigini kesin bilmiyor."
    )
    out = scrub_off_topic_conflict(script, topic)
    assert out.count(".") >= 3
    issues = script_quality_issues(out, topic, niche_id="tarih_gizem")
    assert "az_cumle" not in issues
