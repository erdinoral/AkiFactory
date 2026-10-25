"""Senaryo hook — konuya ozel, jenerik gizem engeli."""

from __future__ import annotations

import random
import re

from akifactory.ollama_util import chat as ollama_chat
from akifactory.text_utils import clean_turkish_script

CLICHE_HOOKS = (
    "biliyor muydunuz",
    "biliyor musunuz",
    "biliyor musun ki",
    "biliyor musun",
    "biliyor muydun",
    "bu videoda",
    "bugün size",
    "bugun size",
    "hoş geldiniz",
    "hos geldiniz",
    "merhaba arkadaşlar",
    "merhaba arkadaslar",
    "izleyiciler",
    "kanalıma",
    "kanalima",
)

# Her konuya uyan bos gizem kalıplari — Voynich icin "karanlik kapi" gibi
GENERIC_HOOK_PATTERNS = (
    r"karanlık\s+(bir\s+)?(kapı|kapi|koridor|oda)",
    r"karanlik\s+(bir\s+)?(kapi|koridor|oda)",
    r"kimse\s+geri\s+dön",
    r"kimse\s+geri\s+don",
    r"kimse\s+gelmedi",
    r"kapı\s+açıld",
    r"kapi\s+acild",
    r"eski\s+bildiklerinin\s+çoğu",
    r"bu\s+detayı\s+duyunca",
    r"bu\s+sırrı\s+ilk\s+kez",
    r"tarih\s+kitapları\s+yalan",
    r"herkes\s+bunu\s+biliyor\s+san",
)

_TOPIC_STOPWORDS = frozenset(
    {
        "ve", "bir", "ile", "için", "icin", "the", "of", "el", "de", "da",
        "mi", "mı", "mu", "mü", "ne", "bu", "şu", "su", "o", "en", "çok",
        "cok", "hakkında", "hakkinda", "üzerine", "uzerine", "olan", "gibi",
    }
)

HOOK_STYLES: list[dict[str, str]] = [
    {
        "id": "sok_iddia",
        "label": "Sok iddia",
        "instruction": "Konunun kendisiyle ilgili cesur bir bilgi iddiasi; konu adi veya bilinen detay gecsin. Soru sorma.",
        "ornek": "Voyniç El Yazması 600 yıldır kimse tarafından okunamıyor.",
    },
    {
        "id": "sayi_veri",
        "label": "Sayi / tarih",
        "instruction": "Bu konuya ait tarih, sayi veya olgu ile giris yap. Soru isareti kullanma.",
        "ornek": "1912'de bulunan el yazması henüz çözülemedi.",
    },
    {
        "id": "ters_bilgi",
        "label": "Yanlis bilinen",
        "instruction": "Bu konu hakkinda yanlis bilinen bir seyi duzelt; konu adi gecsin. Soru sorma.",
        "ornek": "Voyniç yazması sadece sifreli metin degil; baska bir sey.",
    },
    {
        "id": "somut_detay",
        "label": "Somut detay",
        "instruction": "Konunun gorsel veya somut bir ozelligiyle ac; jenerik korku sahnesi yazma.",
        "ornek": "Yazmanın sayfalarında insan disi bitkiler cizili.",
    },
    {
        "id": "tek_kelime_vur",
        "label": "Kisa vurus",
        "instruction": "Konu adi veya anahtar kelime iceren kisa bilgi cumlesi; soru yok.",
        "ornek": "Voyniç yazması henüz okunamıyor.",
    },
]

NICHE_STYLE_ORNEK: dict[str, dict[str, str]] = {
    "teknoloji": {
        "sok_iddia": "ChatGPT bir haftada milyonlarca kullaniciya ulasti.",
        "sayi_veri": "2017'de WannaCry 150 ulkede bilgisayarlari ayni gunde kilitlemisti.",
        "ters_bilgi": "iPhone ciktiginda cogu marka dokunmatik ekrani gereksiz saniyordu.",
        "somut_detay": "Tesla'nin otopilotu saniyede milyonlarca kamera karesi isliyor.",
        "tek_kelime_vur": "ChatGPT yapay zeka tarihini degistirdi.",
    },
    "uzay": {
        "sok_iddia": "Ingenuity ince Mars atmosferinde ucabilen ilk helikopter oldu.",
        "sayi_veri": "Perseverance 2021'de Mars'a indi ve Jezero kraterinde calisiyor.",
        "ters_bilgi": "Pluto gezegen sayilmaktan cikarildi ama bilimsel onemi azalmadi.",
        "somut_detay": "Hubble teleskobu evrenin en uzak galaksilerini goruntuluyor.",
        "tek_kelime_vur": "Mars'ta su izi araniyor.",
    },
    "tarihi_insanlar": {
        "sok_iddia": "Nikola Tesla Edison'dan once alternatif akimi evlere tasidi.",
        "sayi_veri": "Ataturk 1923'te Turkiye Cumhuriyeti'ni kurdu.",
        "ters_bilgi": "Cleopatra Misir kralicesi degil, Helenistik donem hukumdaridir.",
        "somut_detay": "Einstein 1905'te dort devrimci makale yayinladi.",
        "tek_kelime_vur": "Tesla kablosuz enerji hayalini savundu.",
    },
    "tarihi_olaylar": {
        "sok_iddia": "9 Kasim 1989'da Berlin Duvari'nin kapilari aniden acildi.",
        "sayi_veri": "1929 Borsa cokusu Buyuk Buhran'in baslangic gunu oldu.",
        "ters_bilgi": "Bastille'in dusmesi devrimin baslangici sanilir ama olay daha karmasikti.",
        "somut_detay": "Normandiya cikarmasi 1944'te binlerce gemi ve ucakla basladi.",
        "tek_kelime_vur": "Berlin Duvari 1961'de sehri ikiye boldu.",
    },
    "savaslar": {
        "sok_iddia": "18 Mart 1915'te Canakkale'de Ittifak donanmasi geri cekildi.",
        "sayi_veri": "Waterloo Savasi 1815'te Napolyon'un son buyuk yenilgisini getirdi.",
        "ters_bilgi": "Normandiya cikarmasi sadece denizden degil, hava ve kara ile de planlandi.",
        "somut_detay": "Gelibolu cephesi aylarca surdu ve bogaz gecilemedi.",
        "tek_kelime_vur": "Canakkale deniz savasi tarihin donum noktasiydi.",
    },
    "yeme_icme": {
        "sok_iddia": "Iskender kebap 19. yuzyilda Bursa'da gelistirildi.",
        "sayi_veri": "Espresso Italya'da 20. yuzyil basinda hizli kahve kulturunu baslatti.",
        "ters_bilgi": "Sushi aslinda balik koruma yontemi olarak basladi.",
        "somut_detay": "Iskender kebapta et domates sosu ve tereyagli pide uzerinde servis edilir.",
        "tek_kelime_vur": "Bursa iskender kebabin anavatanidir.",
    },
    "oyun": {
        "sok_iddia": "Minecraft bloklardan dunya kurma fikriyle milyonlari cekti.",
        "sayi_veri": "Tetris 1984'te yazildi ve en cok oynanan oyunlardan biri oldu.",
        "ters_bilgi": "Fortnite baslangicta sadece insa oyunuydu, battle royale sonra eklendi.",
        "somut_detay": "Minecraft'ta sinirsiz uretim ve kesif modlari var.",
        "tek_kelime_vur": "Minecraft 2011'de tam surumle cikti.",
    },
    "muzik": {
        "sok_iddia": "Bohemian Rhapsody alti dakikalik opera rock formatinda yayinlandi.",
        "sayi_veri": "Thriller dunyanin en cok satan muzik albumlerinden biri.",
        "ters_bilgi": "The Beatles Amerika'da once radyoda degil canli yayinda patladi.",
        "somut_detay": "Queen stüdyoda vokal katmanlarini ust uste bindirdi.",
        "tek_kelime_vur": "Bohemian Rhapsody 1975'te cikti.",
    },
    "sanat": {
        "sok_iddia": "Mona Lisa 1911'de Louvre'dan calindi ve iki yil sonra bulundu.",
        "sayi_veri": "Michelangelo Davut heykelini 1504'te tamamladi.",
        "ters_bilgi": "Van Gogh yasarken cok az tablo satabildi.",
        "somut_detay": "Mona Lisa'nin hafif gulumsemesi sfumato tekniğiyle yapildi.",
        "tek_kelime_vur": "Mona Lisa Louvre'da sergileniyor.",
    },
    "seyahat": {
        "sok_iddia": "Kapadokya'da sabah balonlari vadilerin uzerinde yukseliyor.",
        "sayi_veri": "Tokyo Shibuya Kavsaği her gun milyonlarca insanin gectigi bir nokta.",
        "ters_bilgi": "Santorini sadece plajlariyla degil, volkanik kayalariyla da unlu.",
        "somut_detay": "Kapadokya'da peri bacalari gun batiminda turuncuya donuyor.",
        "tek_kelime_vur": "Kapadokya Turkiye'nin en ozel manzaralarindan biri.",
    },
    "genel": {
        "sok_iddia": "Insan beyni gece uykusunda REM evresinde yogun ruya gorur.",
        "sayi_veri": "Dunya yuzeyinin yuzde yetmisinden fazlasi okyanuslarla kapli.",
        "ters_bilgi": "Bal arilari tek basina degil, kovan halinde calisir.",
        "somut_detay": "REM evresinde gozler hizli hareket eder.",
        "tek_kelime_vur": "Yetersiz uyku konsantrasyonu etkiler.",
    },
    "tarih_gizem": {
        "sok_iddia": "Voynic el yazmasi 600 yildir kimse tarafindan okunamiyor.",
        "sayi_veri": "1912'de Titanik battiktan sonra batarya kutulari sinyal gonderiyordu.",
        "ters_bilgi": "Tutankamon laneti aslinda mezardaki bakteri ve kuf sporlariyla baglantili olabilir.",
        "somut_detay": "Voynic yazmasinin sayfalarinda insan disi bitkiler cizili.",
        "tek_kelime_vur": "Gobeklitepe yazidan 7 bin yil once insa edildi.",
    },
}

KIDS_HOOK_STYLES: list[dict[str, str]] = [
    {
        "id": "merak",
        "label": "Merak",
        "instruction": "Biliyor musun veya Haydi bakalim ile basla; konu adi gecsin; sicak ve neşeli.",
        "ornek": "Biliyor musun, köpeklerin burnu gece de calismaya devam eder.",
    },
    {
        "id": "vay_be",
        "label": "Vay be",
        "instruction": "Vay be ile sasirtici ama cocuklara uygun bir gercekle ac; korku yok.",
        "ornek": "Vay be, arilar gun boyu calisip bal yapar.",
    },
    {
        "id": "haydi",
        "label": "Haydi bakalim",
        "instruction": "Haydi bakalim ile davet et; konuyu oyun gibi anlatmaya basla.",
        "ornek": "Haydi bakalim, gokkusagi nasil olusur birlikte ogrenelim.",
    },
    {
        "id": "ilginç",
        "label": "Cok ilginç",
        "instruction": "Konu adi + cok ilginc / harika gibi sicak bir ifade; basit kelimeler.",
        "ornek": "Kaplumbagalar cok ilginc hayvanlardir.",
    },
]

KIDS_CLICHE_HOOKS = (
    "bu videoda",
    "bugün size",
    "bugun size",
    "hoş geldiniz",
    "hos geldiniz",
    "kanalıma",
    "kanalima",
    "abone ol",
)


def is_kids_niche(niche_id: str | None) -> bool:
    return (niche_id or "").strip().lower() == "cocuk_eglence"


def pick_hook_style(topic: str = "", *, niche_id: str | None = None) -> dict[str, str]:
    styles = KIDS_HOOK_STYLES if is_kids_niche(niche_id) else HOOK_STYLES
    if topic.strip():
        rng = random.Random(hash(topic.strip()) ^ random.randrange(1_000_000))
        style = rng.choice(styles)
    else:
        style = random.choice(styles)
    niche = (niche_id or "").strip().lower()
    niche_ornek = (NICHE_STYLE_ORNEK.get(niche) or {}).get(style.get("id", ""))
    if niche_ornek:
        return {**style, "ornek": niche_ornek}
    return style


def _topic_keywords(topic: str) -> list[str]:
    words = re.findall(r"[\wçğıöşüÇĞİÖŞÜ]+", (topic or "").lower())
    out: list[str] = []
    for w in words:
        if len(w) < 3 or w in _TOPIC_STOPWORDS:
            continue
        out.append(w)
        if len(w) > 5:
            out.append(w[:5])
    return out


def hook_relates_to_topic(hook: str, topic: str) -> bool:
    if not (topic or "").strip():
        return True
    hook_low = (hook or "").lower()
    keywords = _topic_keywords(topic)
    if not keywords:
        return len(hook_low.replace(" ", "")) >= 12
    return any(kw in hook_low for kw in keywords)


def is_generic_hook(script: str) -> bool:
    first = _first_sentence_lower(script)
    if not first:
        return False
    return any(re.search(pat, first, re.IGNORECASE) for pat in GENERIC_HOOK_PATTERNS)


def is_cliche_hook(script: str, *, niche_id: str | None = None) -> bool:
    first = _first_sentence_lower(script)
    cliches = KIDS_CLICHE_HOOKS if is_kids_niche(niche_id) else CLICHE_HOOKS
    return any(c in first for c in cliches)


def kids_hook_prompt_block(topic: str = "") -> str:
    s = pick_hook_style(topic, niche_id="cocuk_eglence")
    topic_block = ""
    if topic.strip():
        topic_block = (
            f"\nKONU: {topic.strip()}\n"
            f"- Ilk cumle bu konuyla ilgili ve cocuklara sicak olmali\n"
        )
    return (
        f"\nCocuk kanali acilisi (etiket yazma):{topic_block}"
        f"- Stil: {s['label']}\n"
        f"- Talimat: {s['instruction']}\n"
        f"- Ornek ton: «{s['ornek']}»\n"
        f"- Vay be, Haydi bakalim, Biliyor musun kullanabilirsin\n"
        f"- Basit kelimeler; neşeli ve merak uyandiran\n"
        f"- YASAK: Bu videoda, Hos geldiniz, kanalima abone ol\n"
    )


def _is_cloud_llm() -> bool:
    try:
        from akifactory import llm_api

        return bool(llm_api.is_cloud() and llm_api.provider_key_set())
    except Exception:
        return False


def cloud_hook_craft_block(topic: str = "", *, niche_id: str | None = None) -> str:
    """Bulut API (Gemini/OpenAI vb.) icin daha guclu acilis / hook talimati.

    Yerel kucuk modellere gore daha keskin, mantikli ve konu-ozel giris ister.
    """
    if is_kids_niche(niche_id):
        return (
            "\n[BULUT API — COCUK ACILISI]\n"
            "- Ilk cumle sicak, net ve konuya ozel olsun (Vay be / Haydi bakalim uyumlu)\n"
            "- Jenerik «Bu videoda…» yok; hemen merak uyandir\n"
        )
    topic_line = f"Konu: {topic.strip()}\n" if topic.strip() else ""
    return (
        "\n[BULUT API — PREMIUM HOOK]\n"
        f"{topic_line}"
        "- Ilk cumle: izleyiciyi 1 saniyede yakala; somut olgu, tarih, isim veya ters bilgi\n"
        "- Mantik: «neden bu video?» sorusuna ilk cumlede cevap ver (soru cumlesi yazmadan)\n"
        "- Konuya ozel ol; baska konuya da uyan bos gizem kalibi YASAK\n"
        "- Clickbait abartma yok ama zayif/jenerik giris de YASAK — guclu ve dogru ol\n"
        "- 2. cumle: hook'u genislet (neden onemli / ne oldu); 3+ cumle: hikaye akisi\n"
        "- Ciktiya Hook/Giris etiketi yazma; sadece metin\n"
    )


def hook_prompt_block(
    style: dict[str, str] | None = None,
    topic: str = "",
    *,
    niche_id: str | None = None,
) -> str:
    if is_kids_niche(niche_id):
        base = kids_hook_prompt_block(topic)
    else:
        s = style or pick_hook_style(topic, niche_id=niche_id)
        topic_block = ""
        if topic.strip():
            from akifactory.script_topic import normalize_narrative_topic, is_question_form_topic

            narrative = normalize_narrative_topic(topic) if is_question_form_topic(topic) else topic.strip()
            topic_block = (
                f"\nKONU (ZORUNLU): {topic.strip()}\n"
                f"- Anlatim odagi: {narrative}\n"
                f"- Ilk cumle anlatim odagina ait olmali; basligi Evet/Hayir ile cevaplama\n"
                f"- Baska konuya da uyan jenerik cumle YASAK "
                f"(ornek: karanlik kapi, kimse donmedi, bu sirri ilk kez)\n"
                f"- Ornek cumleler sadece ton icin; birebir kopyalama\n"
            )
        base = (
            f"\nAcilis stili (sadece talimat — ciktida etiket yazma):{topic_block}"
            f"- Stil: {s['label']}\n"
            f"- Talimat: {s['instruction']}\n"
            f"- Ornek ton (kopyalama, konuya uyarla): «{s['ornek']}»\n"
            f"- Ilk cumle SORU olmasin; bilgi, tarih veya olgu ile gir\n"
            f"- Tum metinde soru cumlesi yazma\n"
            f"- YASAK: «Biliyor muydunuz», «Peki», «Gerçekten mi», jenerik gizem kalıplari\n"
        )
    if _is_cloud_llm():
        base += cloud_hook_craft_block(topic, niche_id=niche_id)
    try:
        from akifactory import hook_examples as hook_ex_mod
        from akifactory import hook_memory as hook_mem_mod

        base += hook_ex_mod.prompt_block(niche_id)
        base += hook_mem_mod.prompt_block(niche_id)
    except Exception:
        pass
    return base


def _first_sentence_lower(script: str) -> str:
    s = (script or "").strip()
    if not s:
        return ""
    return s.split(".")[0].split("!")[0].split("?")[0].strip().lower()


def validate_hook(script: str, topic: str = "", *, niche_id: str | None = None) -> bool:
    if not (script or "").strip():
        return False
    from akifactory.script_topic import is_debunk_opening, normalize_narrative_topic

    if is_debunk_opening(script):
        return False
    if is_cliche_hook(script, niche_id=niche_id):
        return False
    if is_generic_hook(script) and not is_kids_niche(niche_id):
        return False
    first = first_sentence(script)
    min_len = 8 if is_kids_niche(niche_id) else 12
    if len(first.replace(" ", "")) < min_len:
        return False
    narrative = normalize_narrative_topic(topic) if topic.strip() else topic
    check_topic = narrative or topic
    if check_topic.strip() and not hook_relates_to_topic(first, check_topic):
        return False
    if is_kids_niche(niche_id):
        return hook_relates_to_topic(first, check_topic)
    low = first.lower()
    if "?" in first:
        return False
    strong = (
        "asla", "kimse", "gercek", "gerçek", "sır", "sir", "gizem",
        "yil", "yıl", "yüzyıl", "yuzyil", "tarih", "olay", "sonra",
        "belki", "aslinda", "aslında",
    )
    return any(w in low for w in strong) or hook_relates_to_topic(first, check_topic)


def first_sentence(script: str) -> str:
    s = (script or "").strip()
    if not s:
        return ""
    for sep in (".", "!", "?"):
        if sep in s:
            return s.split(sep)[0] + sep
    return s


async def strengthen_hook(script: str, topic: str = "", *, niche_id: str | None = None) -> str:
    first = first_sentence(script)
    style = pick_hook_style(topic, niche_id=niche_id)
    extra = ""
    try:
        from akifactory import hook_examples as hook_ex_mod
        from akifactory import hook_memory as hook_mem_mod

        extra = hook_ex_mod.prompt_block(niche_id) + hook_mem_mod.prompt_block(niche_id)
    except Exception:
        pass
    if is_kids_niche(niche_id):
        prompt = (
            f"Gorev: Cocuk kanali videosunun YALNIZCA ilk cumlesini yeniden yaz.\n\n"
            f"KONU: {topic}\n"
            f"STIL: {style['label']} — {style['instruction']}\n"
            f"ORNEK: «{style['ornek']}»\n"
            f"{extra}\n"
            f"KURALLAR:\n"
            f"- 6-10 yas icin basit kelimeler\n"
            f"- Vay be, Haydi bakalim, Biliyor musun kullanabilirsin\n"
            f"- Sicak ve neseli; korku yok\n"
            f"- Sadece yeni ilk cumleyi yaz\n\n"
            f"MEVCUT: {first}\n"
            f"METIN: {script[:500]}"
        )
    else:
        cloud_rules = ""
        if _is_cloud_llm():
            cloud_rules = (
                "- BULUT API: ilk cumle premium Shorts hook olsun — somut, dogru, merak uyandiran\n"
                "- Izleyici «bunu bilmiyordum» desin; bos suspense / jenerik korku yok\n"
                "- Tarih, yer, isim veya sayi mumkunse ilk cumlede\n"
            )
        prompt = (
            f"Gorev: Asagidaki kisa video senaryosunun YALNIZCA ilk cumlesini yeniden yaz.\n\n"
            f"KONU (ZORUNLU — ilk cumle bununla ilgili olmali): {topic}\n"
            f"HOOK STILI: {style['label']} — {style['instruction']}\n"
            f"ORNEK TON (kopyalama, KONUYA uyarla): «{style['ornek']}»\n"
            f"{extra}\n"
            f"KURALLAR:\n"
            f"- Ilk cumlede konunun adi veya bilinen bir detayi gecmeli\n"
            f"- Ilk cumle SORU olmasin; soru isareti kullanma\n"
            f"- Jenerik gizem cumlesi YASAK: karanlik kapi, kimse donmedi, bu sirri ilk kez\n"
            f"- Tek cumle, dogal Turkce (ç, ğ, ı, ö, ş, ü)\n"
            f"- «Biliyor muydunuz», «Bu videoda» YASAK\n"
            f"{cloud_rules}"
            f"- Sadece yeni ilk cumleyi yaz\n\n"
            f"MEVCUT ILK CUMLE (kotu ornek olabilir): {first}\n"
            f"TAM METIN: {script[:500]}"
        )
    opts = {"temperature": 0.85} if _is_cloud_llm() else None
    content = await ollama_chat(
        [{"role": "user", "content": prompt}],
        think=False,
        timeout=60.0,
        options=opts,
    )
    if not content or len(content) < 8:
        return script
    hook = clean_turkish_script(
        re.sub(r'^["\'«»]+|["\'«»]+$', "", content.splitlines()[0].strip())
    )
    if not hook or is_cliche_hook(hook, niche_id=niche_id) or (
        is_generic_hook(hook) and not is_kids_niche(niche_id)
    ):
        return script
    if "?" in hook and not is_kids_niche(niche_id):
        return script
    if topic.strip() and not hook_relates_to_topic(hook, topic):
        return script
    try:
        from akifactory import hook_memory as hook_mem_mod

        if first and first.strip() != hook.strip():
            hook_mem_mod.remember_auto(niche_id or "genel", first, topic, good=False)
        hook_mem_mod.remember_auto(niche_id or "genel", hook, topic, good=True)
    except Exception:
        pass
    rest = script.strip()
    if first and first in rest:
        return rest.replace(first, hook, 1)
    return hook + " " + rest


def estimate_duration_sec(script: str) -> int:
    return max(5, min(59, round(len((script or "").strip()) / 12)))
