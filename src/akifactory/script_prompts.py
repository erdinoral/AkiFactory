"""AkiFactory — kisa video senaryo promptlari (Ollama / LLM)."""

from __future__ import annotations

from typing import Any

from akifactory import platforms as plat
from akifactory.ollama_util import chat as ollama_chat
from akifactory.script_hooks import hook_prompt_block, is_kids_niche, pick_hook_style
from akifactory.script_topic import topic_prompt_block
from akifactory.turkish_imla import imla_prompt_block


def _using_cloud_llm() -> bool:
    try:
        from akifactory import llm_api

        return bool(llm_api.is_cloud() and llm_api.provider_key_set())
    except Exception:
        return False


# Bulut API (Gemini/OpenAI/Claude…): yerel kucuk modele gore daha guclu giris + anlatim
_CLOUD_SYSTEM_APPEND = """
## Bulut model — premium Shorts kalitesi
- Ilk cumle en kritik: konu-ozel, mantikli, merak uyandiran; zayif veya jenerik giris kabul etme
- Hook = bilgi + gerilim dengesi: dogru olguyla basla, abartili yalan clickbait yok
- Giris → gelisme → kapanis akisi net olsun; her cumle yeni bilgi tasisin
- Izleyiciyi «bir sey ogrenecek» hissiyle tut; bos suspense ve tekrar yok
- Turkce dogal konusma; belgesel guveni + Shorts temposu (ne teleskopik liste, ne blog yazisi)
""".strip()

_CLOUD_USER_HOOK_TR = (
    "BULUT API: Ilk cumleyi premium hook yaz — somut tarih/isim/yer/sayi veya ters bilgi; "
    "soru yok; «Biliyor muydunuz» yok; jenerik karanlik-kapi gizemi yok. "
    "2. cumle hook'u genisletsin; sonra olayi anlat.\n"
)

TURKISH_SYSTEM_PROMPT = """Sen bir Türk belgesel anlatıcısı ve kısa video senaristisin. Yalnızca Türkçe yazıyorsun.

ZORUNLU KURALLAR:
- Seslendirilecek metin yazıyorsun: olgun, sakin, güvenilir belgesel anlatıcı üslubu
- Tempo ağır olsun: stüdyo belgeseli gibi; telaşlı YouTuber temposu yok
- Doğal konuşma Türkçesi — gazete başlığı veya ders kitabı dili değil; stüdyoda okunacak gibi akıcı
- Abartılı YouTuber / "şok iddia" dili YASAK; merakı bilgiyle kur
- "Merhaba", "bu videoda", "anlatım örneği" gibi meta / teknik cümle yazma
- Ses motoru, model adı veya teknik kurulumdan bahsetme
- Türkçe karakterleri doğru yaz: ç, ğ, ı, İ, ö, ş, ü — ASCII yasak
- Cümle uzunluklarını karıştır: bazı cümleler kısa vurucu, bazıları orta veya uzun (5–18 kelime)
- Tek tek kesik liste gibi yazma — konuyu baştan sona akıcı anlat; olay zinciri kur
- Çok uzun tek cümle yazma (18 kelimeyi geçme); altyazı sistemi uzun cümleleri kendisi böler
- Yabancı kelimeden kaçın — "incredible" değil "inanılmaz", "amazing" değil "şaşırtıcı"
- Yanıtında sadece senaryo metni olsun — "İşte senaryo:" gibi giriş cümlesi yazma
- Düşünme metnini (thinking) yanıta dahil etme
- Kuralları, talimatları veya promptu ASLA tartışma / alıntılama (Instruction, GÖREV, YAZMA, Wait, Okay vb. yasak)
- Markdown, başlık, numara, madde işareti kullanma
- "Anlatıcı", "ses", "video" gibi teknik ifadeler kullanma
- Yapı etiketi ASLA yazma: "Hook", "Gövde", "Kapanış", "Giriş", "İlk cümle", "Son cümle" vb. yasak
- Sadece düz cümleler yaz; etiket veya bölüm başlığı ekleme
- "hâlâ" / "hala" kullanma (TTS yanlış okur); yerine: henüz, bugün bile, günümüzde, daha
- Şapkalı kelimelerden kaçın (lâkin, kâr, âdet, îmkan); ama, kazanç, genelde, olanak kullan
- Sayılarda kesme işareti kullanma: 8i, 12den, 1922de yaz; 8'i, 12'den, 1922'de yasak (TTS bozar)
- Yılları rakamla yaz (ör. 2600de, 1922de); ses motoru bunları yazıya çevirir — "iki bin" diye sen yazma
- Tarih kısaltması kullanma: MÖ/MS yerine açık yaz — Milattan Önce, Milattan Sonra (TTS kısaltmayı okuyamaz)
- Roma rakamı YAZMA (I., II., III.): ikinci Nebukadnezar, birinci yüzyıl, üçüncü yüzyıl gibi Türkçe söyle
- Diğer kısaltmalardan kaçın (Dr., km, yy.) — tam kelime kullan
- SORU SORMA — izleyiciye "Peki…?", "Gerçekten mi?", "Biliyor muydun" tarzı soru cumlesi yazma
- Video konusu soru veya iddia seklinde olabilir — "Hayır/Evet" ile cevaplama, basligi çürütme; konunun altındaki olayı veya efsaneyi anlat
- Anlat, açıkla: tarih, yer, kişi, olay, sonuç — hikâye anlatıcısı gibi
- Gizem/efsane (Atlantis vb.): sır perdesini arala; «kanıt yok / yoktu / kanıtlanamamıştır» diye bitirme
- Aynı cümleyi veya aynı bilgiyi tekrar etme
- Sesli okununca en fazla 55 saniye (yaklaşık 650 karakter); uzatma"""

TURKISH_KIDS_SYSTEM_PROMPT = """Sen 6–10 yaşındaki çocuklara hitap eden neşeli bir video anlatıcısısın. Yalnızca Türkçe yazıyorsun.

ZORUNLU KURALLAR:
- Basit, günlük kelimeler; zor terim ve uzun cümle yok (çoğu cümle 4–12 kelime)
- Sıcak, canlı, merak uyandıran konuş — abla/abi veya sevimli öğretmen gibi samimi
- "Vay be!", "Haydi bakalım", "Biliyor musun", "Çok ilginç" gibi çocuklara yakın ifadeler kullan
- Konuyu oyun gibi anlat; somut örnekler ver (hayvan, renk, ses, hareket)
- Korku, şiddet, politika, karmaşık tarih dili yok
- Yanıtta sadece senaryo metni — "İşte senaryo:" yazma
- Markdown, başlık, numara, madde işareti yok
- "Anlatıcı", "video", "izleyici" gibi teknik kelimeler kullanma
- Yapı etiketi yazma (Hook, Gövde, Kapanış yasak)
- Sesli okununca en fazla 55 saniye (~650 karakter); kısa ve akıcı kal"""

KIDS_FEW_SHOT_EXAMPLES = """
ÖRNEK KONU: Köpekler gece görür mü
ÖRNEK SENARYO:
Biliyor musun, köpeklerin burnu gece de çalışmaya devam eder.
Karanlıkta biz her şeyi net göremeyiz ama köpekler hareket eden şeyleri çok iyi fark eder.
Burnları sayesinde koku alır, kulakları da en küçük sesi duyar.
Vay be, bu yüzden gece yürüyüşlerinde bize harika arkadaş olurlar.
Haydi birlikte bir sonraki sefer köpeğine dikkatle bak, ne kadar çok şey fark ettiğini göreceksin.

ÖRNEK KONU: Arılar balı nasıl yapar
ÖRNEK SENARYO:
Haydi bakalım, arılar çiçekten nektar diye tatlı bir sıvı toplar.
Sonra kovana döner ve bal yapmak için bu sıvıyı özel bir şekilde karıştırır.
Vay be, minicik arılar koca bir kavanoz bal yapabilir.
Bal aslında arıların çiçeklerden topladığı harika bir hediye.
Bir dahaki sefer bal yediğinde arılara teşekkür etmeyi unutma.
"""

_KIDS_COMMON_STRUCTURE = """
İç yapı (çıktıda yazma — sadece sırayı böyle kur):
1) İlk cümle: konu adı + merak veya "Vay be / Biliyor musun / Haydi bakalım" ile sıcak giriş
2) Ortada 5–8 cümle: basit kelimelerle konuyu anlat; hayvan, renk, hareket, somut örnek kullan
3) Cümleler kısa ve neşeli; abartılı korku veya karmaşık bilim dili yok
4) Son cümle: sıcak kapanış veya "bir dahaki sefer fark et" tarzı pozitif not

Çocuk nişi yasaklar:
- Tarih dersi tonu; yetişkin belgesel dili
- Uzun karmaşık cümleler (15+ kelime)
- Korku, kan, savaş, politika
- "Bu videoda...", "Kanalıma abone ol" (yalnızca reklam dili)
""".strip()

FEW_SHOT_EXAMPLES = """
ÖRNEK KONU: Tutankamon'un laneti
ÖRNEK SENARYO:
Bin dokuz yüz yirmi ikide Howard Carter, Luxor yakınlarında Tutankamonun mezarını açtı ve dünya basınında büyük yankı uyandırdı.
Mezara giren ekipte ardı ardına ölümler duyulunca gazeteler olaya firavun laneti adını verdi.
Lord Carnarvon mezardan kısa süre sonra aniden hayatını kaybetti; haberler efsaneyi hızla büyüttü.
Mezarın duvarlarındaki uyarılar ve altın maskenin sessiz bakışı halkın hayal gücünü ateşledi.
Bu sır perdesi arkeoloji tarihinin en çok anlatılan gizemlerinden biri olarak bugün bile dolaşıyor.

ÖRNEK KONU: Voyniç El Yazması
ÖRNEK SENARYO:
Voyniç yazması bin dört yüzlü yıllarda yazıldığı tahmin edilen ve yüzyıllardır çözülemeyen gizemli bir el yazmasıdır.
İki yüz kırk sayfada bilinmeyen bir alfabe, garip bitki çizimleri ve anlaşılmayan diyagramlar bulunuyor.
İkinci Dünya Savaşı sırasında Polonyalı bir kitapçı tarafından satın alındıktan sonra bilim dünyasının dikkatini çekti.
Bugün Yale Üniversitesinde saklanıyor ve henüz kimse ne anlattığını kesin olarak bilmiyor.
"""

SEYAHAT_FEW_SHOT = """
ÖRNEK KONU: Kapadokya gezi rehberi
ÖRNEK SENARYO:
Kapadokya, Türkiye'nin en özel manzaralarından biri; sabah balonları vadilerin üzerinde yükselirken şehir taştan bir masal gibi görünür.
Göreme Açık Hava Müzesi ve Uçhisar Kalesi mutlaka görülmeli; dar sokaklarda el yapımı seramik atölyeleri var.
Peri bacaları gün batımında turuncuya döner, fotoğraf için en iyi saatler sabah erken ve akşamüstüdür.
Türkiye içinde olduğu için Türk Lirası geçer; konaklama ve yemek orta seviye, lüks balon turları daha pahalıdır.
Yerel halk turizme alışkın ve yardımsever; bölge genelde güvenli ve sıcak bir atmosfer sunar.
"""

NICHE_FEW_SHOTS: dict[str, str] = {
    "teknoloji": """
ÖRNEK KONU: ChatGPT'nin yükselişi
ÖRNEK SENARYO:
ChatGPT, 2022 sonunda OpenAI tarafından yayınlandı ve bir haftada milyonlarca kullanıcıya ulaştı.
Model metin yazıyor, kod üretiyor ve soruları insan gibi yanıtlıyor; arkasında büyük dil modeli teknolojisi var.
Kısa sürede Google ve Microsoft gibi devler de kendi yapay zeka asistanlarını duyurdu.
Bugün milyonlarca kişi iş, okul ve günlük hayatta bu araçları kullanıyor.
""",
    "uzay": """
ÖRNEK KONU: Mars'taki Perseverance görevi
ÖRNEK SENARYO:
NASA'nın Perseverance aracı 2021'de Mars'a indi ve Jezero kraterinde çalışmaya başladı.
Görevin amacı geçmişte su izi aramak ve kaya örnekleri toplamak.
Araç aynı zamanda Ingenuity adlı ilk Mars helikopterini de taşıdı ve ince atmosferde uçuşu kanıtladı.
Bu veriler gelecekte insanlı Mars misyonları için yol haritası oluşturuyor.
""",
    "tarihi_insanlar": """
ÖRNEK KONU: Nikola Tesla'nın az bilinen yönü
ÖRNEK SENARYO:
Nikola Tesla, 19. yüzyıl sonunda alternatif akım sistemini geliştirdi ve elektriğin evlere taşınmasını mümkün kıldı.
Edison ile ünlü akım savaşını kaybetmedi; uzun mesafe enerji iletiminde Tesla'nın sistemi kazandı.
Colorado Springs'te yıldırım deneyleri yaptı ve kablosuz enerji hayalini yıllarca savundu.
Ölümünden sonra laboratuvarı ve notları yıllarca tartışma konusu oldu.
""",
    "tarihi_olaylar": """
ÖRNEK KONU: Berlin Duvarı'nın yıkılışı
ÖRNEK SENARYO:
9 Kasım 1989'da Doğu Berlin'deki sınır kapıları aniden açıldı ve binlerce kişi Batı'ya geçti.
Duvar 1961'den beri şehri ikiye bölüyordu; soğuk savaşın en görünür sembollerinden biriydi.
O gece televizyon görüntüleri dünyaya yayıldı ve Almanya birleşme sürecine girdi.
1990'da resmen yıkım başladı; bugün parçaları müzelerde sergileniyor.
""",
    "savaslar": """
ÖRNEK KONU: Çanakkale'de deniz savaşı
ÖRNEK SENARYO:
18 Mart 1915'te İtilaf donanması Çanakkale boğazını geçmeye çalıştı ve ağır kayıp verdi.
Minesweeper gemileri mayınlara çarptı, HMS Oceanic ve Irresistible gibi büyük gemiler battı.
Bu deniz yenilgisi kara harekatının önünü açtı ve Gelibolu cephesi aylarca sürdü.
Sonuçta boğaz geçilemedi ve cephe tarihin en kanlı sayfalarından biri oldu.
""",
    "yeme_icme": """
ÖRNEK KONU: İskender kebabın kökeni
ÖRNEK SENARYO:
İskender kebap, Bursa'da İskender Efendi tarafından 19. yüzyılda geliştirildi.
Döner et domates sosu ve tereyağlı pide üzerinde servis edilir.
Yanında yoğurt gelmesi Bursa usulünün ayırt edici özelliğidir.
Bugün Türkiye'nin en tanınan yemeklerinden biri olarak dünyaya yayıldı.
""",
    "oyun": """
ÖRNEK KONU: Minecraft'ın başarısı
ÖRNEK SENARYO:
Minecraft 2011'de tam sürümle çıktı ve bloklardan dünya kurma fikriyle milyonları çekti.
Oyun sınırsız üretim, keşif ve hayatta kalma modları sunuyor.
2014'te Microsoft oyunu 2,5 milyar dolara satın aldı.
Bugün en çok satan oyunlardan biri ve her yaştan oyuncu var.
""",
    "muzik": """
ÖRNEK KONU: Bohemian Rhapsody'nin kaydı
ÖRNEK SENARYO:
Queen, Bohemian Rhapsody'yi 1975'te altı dakikalık opera rock formatında yayınladı.
Stüdyoda vokal katmanları üst üste bindirildi; o dönem için teknik olarak çok iddialı bir kayıttı.
Parça ilk çıktığında radyolar uzunluğu nedeniyle tereddüt etti ama dinleyici ilgisi rekor kırdı.
Bugün rock tarihinin en tanınan şarkılarından biri.
""",
    "sanat": """
ÖRNEK KONU: Mona Lisa tablosu
ÖRNEK SENARYO:
Leonardo da Vinci, Mona Lisa'yı 16. yüzyıl başında Floransa'da yaptı.
Modelin hafif gülümsemesi ve sfumato tekniği tabloyu eşsiz kıldı.
1911'de Louvre'dan çalındı ve iki yıl sonra İtalya'da bulundu.
Bugün Paris'teki Louvre müzesinde cam arkasında milyonlarca ziyaretçi görüyor.
""",
    "genel": """
ÖRNEK KONU: Uyku ve rüya
ÖRNEK SENARYO:
İnsan beyni gece uykusunda REM evresinde yoğun rüya görür.
Bu evrede gözler hızlı hareket eder ve hafıza pekiştirme çalışmaları yapılır.
Yetersiz uyku konsantrasyonu ve ruh halini doğrudan etkiler.
Yetişkinlerin çoğu için günde yedi ile dokuz saat uyku önerilir.
""",
}

_COMMON_STRUCTURE = """
İç yapı (çıktıda yazma — sadece sırayı böyle kur):
1) İlk cümle: konu adı + tarih veya çarpıcı olgu; izleyiciyi konuya sok
2) Ortada 5–8 cümle: konuyu ANLAT — ne oldu, kim yaptı, ne zaman, sonuç ne; olay akışı olsun
3) Cümle ritmi değişsin: kısa vurucu + orta açıklayıcı + ara sıra daha uzun bağlayıcı cümle
4) Sondan bir önceki cümle: konunun akılda kalan özeti (soru işareti yok)
5) Takip çağrısı yazma — sistem son cümleye otomatik ekler

Ortak yasaklar:
- Hepsini aynı uzunlukta tek kelimelik/telegraf cümleler yazma
- Soru cumlesi yazma: "Peki", "Gerçekten mi", "Sence", "Biliyor muydunuz"
- "Biliyor muydunuz ki / musunuz / musun"
- "Bu videoda...", "Bugün size...", "Hoş geldiniz"
- Başka konuya da uyan jenerik cümleler; konu neyse ondan bahset
""".strip()


def _niche_block(role: str, focus: str, tone: str, avoid: str = "") -> str:
    extra = f"\nNişe özel yasaklar:\n{avoid}" if avoid else ""
    return f"""
ROL: {role}

TON: {tone}
ODAK: {focus}
{_COMMON_STRUCTURE}{extra}
""".strip()


_SEYAHAT_STRUCTURE = """
İç yapı (çıktıda yazma — sadece sırayı böyle kur):
1) İlk cümle: destinasyon adı + neden gidilmeli (tarih, manzara veya kültürle somut giriş)
2) Gezilecek 2–3 somut yer: mahalle, plaj, kale, çarşı, doğa noktası (isim ver)
3) Güzellik/atmosfer: manzara, mimari, deniz, dağ veya sokak hayatı (1–2 cümle)
4) Pratik bilgi: yerel para birimi + pahalı/orta/ucuz hissi (kısa, net)
5) İnsanlar ve kültür: sıcaklık, güvenlik hissi, yerel yaşam (abartma)
6) Son cümle: özet veya «gitmeden bil» notu (soru yok)

Seyahat nişi yasaklar:
- «Bu videoda», «abone ol», reklam dili
- Soru cumlesi; «Peki», «Biliyor muydunuz»
- Kesin fiyat/rakam uydurma; genel seviye söyle (ucuz, orta, pahalı)
- Politik tartışma, korku turizmi abartısı
""".strip()

NICHE_PROMPTS: dict[str, str] = {
    "tarih_gizem": _niche_block(
        "Tarih ve gizem hikâye anlatıcısısın; kayıp uygarlıklar, efsaneler ve çözülmemiş olayların sır perdesini aralarsın — yargıç veya skeptic değilsin.",
        "Yıl, yer, kişi, efsanenin kaynağı (kim anlattı) ve çarpıcı olgu zinciri; merakı hikâyeyle kur — soru sorma, film özeti yapma.",
        "Olgun belgeselci anlatım: sakin, ağır tempolu; stüdyo belgeseli gibi. "
        "Atlantis gibi konularda Platon’un anlattığı ada, batış, arayışlar gibi HİKÂYEYİ anlat; «kanıt yok / yoktu» deme.",
        '- Soru cumlesi; "Peki", "Gerçekten mi", "Laneti var mıydı" gibi retorik sorular\n'
        '- Jenerik korku: "karanlık kapı", "kimse dönmedi", "bu sırrı ilk kez", "tarih kitapları yalan"\n'
        '- Konu adı geçmeden yazılan herhangi bir gizem cümlesi\n'
        '- Aynı olguyu iki kez söylemek\n'
        '- Meta cümle: "bu videoda", "merhaba arkadaşlar", ses motoru / teknik kurulum bahsi\n'
        '- Ders kitabi / akademik dil: "sorgulanmıştır", "değerlendiriliyor", "bilimsel tıp dilinde", "açıklanır"\n'
        '- Film/dizi ozeti: oyuncu, yonetmen, kadro, prömiyer, film festivali, vizyon yili, "kitaptan uyarlanan film"\n'
        '- Konu bir filmle ayni adi tasiyorsa (or. Lost City of Z / Z Sehri) TARİHİ OLAYI anlat; 2016 filmi / festival YASAK\n'
        '- Percy Fawcett: Amazon\'da 1925\'te kayboldu — film yili (2016) veya "1930\'lar" ile karistirma\n'
        '- Enlem/boylam, derece koordinat listesi (53°N…); yer adi yeter\n'
        '- Skeptic kapanis YASAK: "kanit yok", "kanitlanamamistir", "var olmadigi", "sadece efsane", "uydurma", "bilimsel olarak ispatlanmadi"\n'
        '- Dogru bilgi = efsanenin detaylari ve kaynaklari; mahkemede "yoktu" demek DEGIL — meraki koru\n'
        '- Meta kapanis: "Bu belgesel…", "Bu videoda…" — sir perdesini aralik birakarak bitir',
    ),
    "teknoloji": _niche_block(
        "Teknoloji ve dijital dünya kısa video senaristisin; yapay zeka, siber güvenlik, donanım ve yazılımın ustasısın.",
        "Ürün veya şirket adı, yıl, rakam, güvenlik olayı, icat veya kullanıcıya somut etki; hype değil olgu anlat.",
        "Hızlı, net, merak uyandıran; teknik terimi aynı cümlede sade Türkçe ile açıkla.",
        '- Boş hype: "teknoloji dünyası sallandı", "gelecek artık burada", "inanılmaz bir devrim"\n'
        '- Marka/ürün adı geçmeden jenerik teknoloji lafları\n'
        '- Kesin rakam uydurma; bilinmiyorsa "binlerce", "milyonlarca" gibi genel seviye',
    ),
    "uzay": _niche_block(
        "Uzay bilimi ve kozmoloji kısa video senaristisin; gezegenler, görevler, teleskoplar ve evrenin ustasısın.",
        "Görev/keşif adı, yıl, mesafe, gezegen veya cisim adı, bilimsel sonuç; bilim kurgu değil gerçek veri.",
        "Büyüleyici ama bilimsel; sayı, mesafe, tarih ve kurum adı (NASA, ESA) kullan.",
        '- "Uzaydaki gizem", "bilim insanları şokta", "uzaylılar" klişesi\n'
        '- Konu dışı jenerik evren betimlemesi; somut görev veya keşif adı zorunlu',
    ),
    "tarihi_insanlar": _niche_block(
        "Tarihi şahsiyetler kısa video senaristisin; hükümdarlar, bilim insanları ve efsanevi liderlerin ustasısın.",
        "Kişinin tam adı, dönem/yıl, tek çarpıcı olay, karar veya az bilinen detay; biyografi listesi değil.",
        "Dramatik ama saygılı; ilk cümlede kişi adı veya unvanı geçsin.",
        '- "Tarihe damga vurdu", "efsanevi bir liderdi" gibi boş övgü\n'
        '- Kişi adı geçmeden yazılan giriş; soyad veya lakap ile somutlaştır',
    ),
    "tarihi_olaylar": _niche_block(
        "Tarihi olaylar kısa video senaristisin; dönüm noktaları, antlaşmalar ve toplumu değiştiren günlerin ustasısın.",
        "Tarih, yer, olay adı, taraflar ve sonuç; tek bir gün veya kararın zinciri.",
        "Kronolojik netlik; ders kitabı değil konuşma diliyle merak koru.",
        '- "Tarihin akışını değiştirdi" gibi boş ifade; ne olduğunu somut yaz\n'
        '- Soru cumlesi; ders kitabı maddeleri gibi sıralı "önce... sonra..." tekrarı',
    ),
    "savaslar": _niche_block(
        "Askeri tarih kısa video senaristisin; savaşlar, stratejiler ve savaş meydanındaki dönüm noktalarının ustasısın.",
        "Savaş adı, yıl, yer, taraflar, taktik veya şaşırtıcı sonuç; sayı kullan.",
        "Ciddi ama akıcı; şiddeti övme, strateji ve sonuç odaklı kal.",
        '- Kanlı betimleme, "kan gölü", "dehşet saçtı" sansasyonu\n'
        '- Savaş adı veya yıl geçmeden jenerik savaş cümlesi',
    ),
    "yeme_icme": _niche_block(
        "Yemek kültürü ve gastronomi kısa video senaristisin; tariflerin kökeni, sokak lezzetleri ve mutfak sırlarının ustasısın.",
        "Yemeğin adı, köken ülke/şehir, malzeme, pişirme veya kültürel hikâye; iştah açan ama bilgilendirici.",
        "Sıcak, samimi, lezzetli anlatım; reklam veya restoran broşürü değil.",
        '- "Ağzınız sulandı", "mutlaka denemelisiniz", "dünyanın en lezzetli" klişesi\n'
        '- Yemek adı geçmeden jenerik lezzet övgüsü',
    ),
    "cocuk_eglence": _niche_block(
        "Çocuk kanalı için eğlenceli eğitim video anlatıcısısın; hayvanlar, doğa, bilim ve merak uyandıran gerçeklerin ustasısın.",
        "Hayvan, nesne veya olgu adı; 6–10 yaş için basit kelimelerle somut örnek.",
        "Neşeli, sıcak, meraklı; abla/abi veya sevimli öğretmen gibi konuş.",
        '- Yetişkin belgesel tonu; mini tarih dersi\n'
        '- Korku, şiddet, savaş, politika\n'
        '- Karmaşık terimler (fotosentez yerine «bitkiler güneşten yemek yapar»)\n'
        '- Bu nişte merak cumleleri serbest; «Biliyor musun», «Vay be» kullanılabilir',
    ),
    "oyun": _niche_block(
        "Oyun dünyası kısa video senaristisin; video oyunları, e-spor ve oyun kültürünün ustasısın.",
        "Oyun adı, çıkış yılı, mekanik, gizli detay, rekor veya geliştirici; oyuncu dili ama herkese anlaşılır.",
        "Enerjik ama net; jargonu kısa tut, ilk cümlede oyun adı geçsin.",
        '- "Tüm zamanların en iyi oyunu", "oyun dünyasını kasıp kavurdu" boş iddiası\n'
        '- Oyun adı geçmeden jenerik oyun kültürü cümlesi',
    ),
    "muzik": _niche_block(
        "Müzik tarihi ve pop kültür kısa video senaristisin; şarkılar, sanatçılar ve müzik endüstrisinin ustasısın.",
        "Şarkı veya sanatçı adı, yıl, stüdyo anı, plak satışı veya az bilinen gerçek.",
        "Ritimli anlatım; müzik sevgisi belli olsun, dedikodu değil olgu.",
        '- "Efsanevi bir parça", "müzik tarihine geçti" boşluğu\n'
        '- Sanatçı veya şarkı adı geçmeden jenerik müzik övgüsü',
    ),
    "sanat": _niche_block(
        "Sanat tarihi kısa video senaristisin; tablolar, heykeller, mimari ve sanatçıların ustasısın.",
        "Eser adı, sanatçı, dönem/yıl ve tek çarpıcı detay (renk, sembol, hikâye, hırsızlık).",
        "Estetik ama erişilebilir; müze rehberi değil arkadaş anlatımı.",
        '- "Muhteşem bir eser", "dünyaca ünlü tablo" boşluğu\n'
        '- Eser veya sanatçı adı geçmeden jenerik sanat övgüsü',
    ),
    "seyahat": f"""
ROL: Seyahat ve gezi rehberi kısa video senaristisin; şehirler, ülkeler ve destinasyonların ustasısın.

TON: Samimi gezgin arkadaş; keşif heyecanı, pratik bilgi, iştah açıcı manzara betimleri.
ODAK: Destinasyon adı zorunlu — gezilecek 2–3 somut yer, atmosfer, para birimi, pahalılık, yerel kültür.
{_SEYAHAT_STRUCTURE}

Nişe özel yasaklar:
- «Bu videoda», «abone ol», reklam dili
- Destinasyon adı geçmeden «bu şehir harika» gibi jenerik gezi cümlesi
- Kesin fiyat uydurma; ucuz/orta/pahalı seviye yeterli
""".strip(),
    "genel": _niche_block(
        "Kısa video senaristisin; izleyiciyi ilk saniyede yakalayan bilgi ve hikâye anlatıcısısın.",
        "Konu adı, somut olgu, tarih veya rakam; konuyu baştan sona net anlat.",
        "Konuşma dili, akıcı, merak uyandıran; platforma uygun hız.",
        '- «Bu videoda», «hoş geldiniz», soru cumlesi\n'
        '- Konu adı geçmeden herhangi bir nişe uyan jenerik cümle',
    ),
}

NICHE_LABELS: dict[str, str] = {
    "tarih_gizem": "Tarih & Gizem",
    "teknoloji": "Teknoloji",
    "uzay": "Uzay",
    "tarihi_insanlar": "Tarihi İnsanlar",
    "tarihi_olaylar": "Tarihi Olaylar",
    "savaslar": "Savaşlar",
    "yeme_icme": "Yeme-İçme",
    "cocuk_eglence": "Çocuk & Eğlence",
    "oyun": "Oyun",
    "muzik": "Müzik",
    "sanat": "Sanat",
    "seyahat": "Seyahat & Gezi",
    "genel": "Genel",
}

# UI listeleme sirasi
NICHE_ORDER: list[str] = [
    "tarih_gizem",
    "teknoloji",
    "uzay",
    "tarihi_insanlar",
    "tarihi_olaylar",
    "savaslar",
    "yeme_icme",
    "cocuk_eglence",
    "oyun",
    "muzik",
    "sanat",
    "seyahat",
    "genel",
]

NICHE_SUGGEST_HINTS: dict[str, str] = {
    "tarih_gizem": "kayıp uygarlıklar, şifreli metinler, çözülmemiş tarih gizemleri",
    "teknoloji": "yapay zeka, siber güvenlik, çığır açan icatlar, dijital skandallar",
    "uzay": "gezegenler, NASA, kara delikler, uzay keşifleri",
    "tarihi_insanlar": "tarihi şahsiyetler, az bilinen hayat detayları, liderler ve bilim insanları",
    "tarihi_olaylar": "tarihi dönüm noktaları, antlaşmalar, tek günde değişen dünya",
    "savaslar": "ünlü savaşlar, askeri stratejiler, savaş meydanındaki sürprizler",
    "yeme_icme": "yemek kökenleri, sokak lezzetleri, dünya mutfakları, ilginç tarifler",
    "cocuk_eglence": "çocuklara uygun hayvanlar, doğa, renkler, basit bilim ve eğlenceli gerçekler (6–10 yaş)",
    "oyun": "video oyunları, gizli detaylar, e-spor, oyun tarihi",
    "muzik": "şarkıların hikayesi, sanatçılar, müzik endüstrisi sırları",
    "sanat": "ünlü tablolar, heykeller, sanatçıların gizli hikayeleri",
    "seyahat": "popüler şehir ve ülkeler, gezilecek yerler, pratik gezi bilgileri, Türk gezginlere uygun destinasyonlar",
    "genel": "genel ilgi çekici kısa video konuları",
}


def resolve_niche(niche_id: str | None) -> str:
    key = (niche_id or "genel").strip().lower()
    return key if key in NICHE_PROMPTS else "genel"


def build_turkish_system_prompt(niche_id: str = "genel") -> str:
    niche = resolve_niche(niche_id)
    if is_kids_niche(niche):
        parts = [TURKISH_KIDS_SYSTEM_PROMPT, KIDS_FEW_SHOT_EXAMPLES.strip()]
        block = NICHE_PROMPTS.get(niche, "")
        if block:
            parts.append(block.replace(_COMMON_STRUCTURE, _KIDS_COMMON_STRUCTURE))
        parts.append(imla_prompt_block())
        try:
            from akifactory.content_context import content_law_blocks

            law = content_law_blocks(niche)
            if law:
                parts.append(law)
        except Exception:
            pass
        if _using_cloud_llm():
            parts.append(_CLOUD_SYSTEM_APPEND)
        return "\n\n".join(parts)
    parts = [TURKISH_SYSTEM_PROMPT]
    if niche == "seyahat":
        parts.append(SEYAHAT_FEW_SHOT.strip())
    elif niche == "tarih_gizem":
        parts.append(FEW_SHOT_EXAMPLES.strip())
    elif niche in NICHE_FEW_SHOTS:
        parts.append(NICHE_FEW_SHOTS[niche].strip())
    else:
        parts.append(FEW_SHOT_EXAMPLES.strip())
    if niche in NICHE_PROMPTS and NICHE_PROMPTS[niche]:
        parts.append(NICHE_PROMPTS[niche])
    parts.append(imla_prompt_block())
    try:
        from akifactory.content_context import content_law_blocks

        law = content_law_blocks(niche)
        if law:
            parts.append(law)
    except Exception:
        pass
    if _using_cloud_llm():
        parts.append(_CLOUD_SYSTEM_APPEND)
    return "\n\n".join(parts)


def list_niches_for_ui() -> list[dict[str, str]]:
    return [
        {"id": nid, "label": NICHE_LABELS.get(nid, nid)}
        for nid in NICHE_ORDER
        if nid in NICHE_PROMPTS
    ]


def apply_to_payload(
    payload: dict[str, Any],
    *,
    lang_id: str | None,
    platform_id: str | None,
    niche_id: str | None = None,
    subject: str | None = None,
    hook_style: dict[str, str] | None = None,
) -> None:
    """motor API payload'ina AkiFactory senaryo promptlarini ekler."""
    lang = (lang_id or "tr").strip().lower()[:2]
    p = plat.resolve(platform_id)
    platform_label = p.get("label", "TikTok")
    niche = resolve_niche(niche_id)
    topic = (subject or payload.get("video_subject") or "").strip()
    niche_label = NICHE_LABELS.get(niche, niche)

    if lang == "tr":
        payload["custom_system_prompt"] = build_turkish_system_prompt(niche)
    else:
        payload["custom_system_prompt"] = _SYSTEM_EN

    extras = {"tr": _EXTRA_TR, "en": _EXTRA_EN}
    if is_kids_niche(niche):
        extra = _EXTRA_TR_KIDS.format(platform=platform_label)
        style = hook_style or pick_hook_style(topic, niche_id=niche)
        extra += hook_prompt_block(style, topic, niche_id=niche)
    else:
        extra = extras.get(lang, _EXTRA_TR).format(platform=platform_label)
        if lang == "tr":
            extra += f"\nNiş: {niche_label} — bu alanın uzmanı gibi yaz.\n"
            style = hook_style or pick_hook_style(topic, niche_id=niche)
            extra += hook_prompt_block(style, topic, niche_id=niche)
    payload["video_script_prompt"] = extra


_SYSTEM_EN = """
# Role: Short-form video script writer

## Goals:
Write natural, spoken narration for TikTok, YouTube Shorts, and Reels.

## Rules:
1. Write for voiceover — conversational, engaging, clear.
2. Strong opening hook; no "welcome to this video".
3. Short to medium sentences (subtitle-friendly).
4. No markdown, titles, bullets, or meta labels like "narrator".
5. Return raw script text only.
6. Match the language of the video subject.
""".strip()

_EXTRA_TR = """
- Platform: {platform}
- Sesli okununca en fazla 55 saniye (yaklaşık 650 karakter, 6–10 cümle)
- Konuyu baştan sona anlat; olay akışı kur — telegraf/liste gibi kesik kesik yazma
- Cümle uzunluklarını karıştır (5–18 kelime); hepsi aynı boyda olmasın
- İÇERİK ZENGİN OLSUN: en az 3–4 farklı somut bilgi ver (tarih, isim, yer, sayı, sebep, sonuç)
- Boş/genel cümle ve tekrar yok; her cümle yeni bir bilgi taşısın
- Tarih, yer, isim ve somut olgu kullan; mini belgesel gibi anlat
- Soru cumlesi YAZMA — bilgi ver, açıkla, sonuç söyle
- Konu özetiyle bitir; takip/abone cümlesi yazma
- Metnin tamamı %100 Türkçe olmalı; ç, ğ, ı, ö, ş, ü harflerini kullan
"""

_EXTRA_EN = """
- Platform: {platform}
- Target ~30-60 seconds of spoken narration (4-8 sentences)
- Each sentence should work as a standalone subtitle line
- End with a memorable closing line
"""

_EXTRA_TR_KIDS = """
- Platform: {platform}
- Hedef kitle: 6–10 yaş çocuklar (ebeveyn de izleyebilir)
- Sesli okununca en fazla 55 saniye (~650 karakter, 6–10 cümle)
- Kısa, neşeli cümleler; basit kelimeler
- Sıcak anlatım: Vay be, Haydi bakalım, Biliyor musun kullanabilirsin
- Somut örnekler (hayvan, renk, hareket); korku ve karmaşık terim yok
- Son cümle pozitif ve sıcak bitsin
- Metnin tamamı %100 Türkçe; ç, ğ, ı, ö, ş, ü kullan
"""


async def generate_script_text(
    *,
    subject: str,
    lang_id: str = "tr",
    platform_id: str = "tiktok",
    niche_id: str = "genel",
    paragraph_number: int = 1,
    experimental_template: bool = False,
    research_context: str = "",
    writer_model: str | None = None,
) -> str:
    """Yalnizca senaryo metni (video uretmeden).

    TR (cocuk haric): olgu iskeleti → senaryo → kritik kalite sorununda
    hook guclendirme / tek yeniden deneme. Iskelet basarisizsa eski akis.
    """
    payload: dict[str, Any] = {"video_subject": subject, "paragraph_number": paragraph_number}
    niche = resolve_niche(niche_id)
    apply_to_payload(
        payload,
        lang_id=lang_id,
        platform_id=platform_id,
        niche_id=niche,
        subject=subject,
    )
    subj = subject.strip()
    lang = (lang_id or "tr").strip().lower()[:2]
    kids = is_kids_niche(niche)
    research = (research_context or "").strip()

    skeleton_block = ""
    skeleton_bullets: list[str] = []
    if lang == "tr" and not kids:
        try:
            from akifactory.script_skeleton import (
                format_skeleton_for_prompt,
                generate_fact_skeleton,
            )

            skeleton_bullets = await generate_fact_skeleton(
                subj,
                niche_id=niche,
                niche_label=NICHE_LABELS.get(niche, niche),
                research_context=research,
                model=writer_model,
            )
            if skeleton_bullets:
                skeleton_block = "\n" + format_skeleton_for_prompt(
                    skeleton_bullets, topic=subj
                )
        except Exception:
            skeleton_block = ""
            skeleton_bullets = []

    if kids:
        user = (
            f"Video konusu: {subj}\n"
            f"Niş: {NICHE_LABELS.get(niche, niche)} — çocuklara yönelik neşeli anlatım\n"
            f"İlk cümle sıcak ve merak uyandırsın (Vay be / Biliyor musun / Haydi bakalım olabilir).\n"
            f"Basit kelimelerle anlat; kısa cümleler; en fazla 55 saniye seslendirme.\n"
            f"{payload.get('video_script_prompt', '')}"
        )
    else:
        cloud_hook = _CLOUD_USER_HOOK_TR if _using_cloud_llm() else ""
        user = (
            f"{topic_prompt_block(subj, niche_id=niche)}\n"
            f"Niş: {NICHE_LABELS.get(niche, niche)}\n"
            f"{cloud_hook}"
            f"İlk cümle anlatım odağıyla ilgili olsun; tarih, yer veya çarpıcı olgu ile gir — soru sorma, Hayır/Evet deme, basligi dogru/yanlis diye cevaplama.\n"
            f"Konuyu izleyiciye anlat; kısa-orta-uzun cümleleri karıştır, liste gibi kesme.\n"
            f"En fazla 55 saniye seslendirme; bilgi anlat, soru cumlesi yazma; «bu ifade gecerli/gecersiz» YASAK.\n"
            f"{payload.get('video_script_prompt', '')}"
            f"{skeleton_block}"
        )
    if experimental_template:
        user += (
            "\n[DENEYSEL] Daha cesur aci, viral Shorts tonu ve beklenmedik detay dene; "
            "yine de konuya ve gerceklige sadik kal.\n"
        )
    if research:
        from akifactory.script_topic import MYSTERY_STORYTELLING_RULES

        mystery_extra = ""
        if (niche or "").strip().lower() == "tarih_gizem":
            mystery_extra = (
                f"\n{MYSTERY_STORYTELLING_RULES}\n"
                "Arastirma notunu HIKAYE malzemesi olarak kullan (kim anlatti, ne denildi, ne arandi).\n"
                "Notta «efsane / kanitlanamamis» yazsa bile sen «yoktu / kanit yok» diye BITIRME; sir perdesini anlat.\n"
            )
        user += (
            "\n\nWEB ARASTIRMA NOTU (Wikipedia + DuckDuckGo — buna sadik kal, uydurma ekleme):\n"
            f"{research}\n"
            "Bu nottaki olgulari kendi konusma dilimizle, akici ve merak uyandiran sekilde anlat.\n"
            "Notta olmayan ulke/sehir/kisi/tarih YAZMA; yanlis yil/isim varsa nottakini kullan.\n"
            "Video basligi soru veya iddia olsa bile basligi DOGRULAMA/YANLISLAMA "
            "(Hayir/Evet, dogru/yanlis, «bu ifade gecerli/gecersiz», «gecersizdir» deme); "
            "nottaki olayi veya efsaneyi anlat.\n"
            f"{mystery_extra}"
        )
    messages = [
        {"role": "system", "content": payload["custom_system_prompt"]},
        {"role": "user", "content": user},
    ]
    writer_opts = {"temperature": 0.82} if _using_cloud_llm() else None
    raw = await ollama_chat(
        messages, think=False, model=writer_model, options=writer_opts
    )
    from akifactory.text_utils import enforce_spoken_script_limits

    text = enforce_spoken_script_limits(raw)
    if lang != "tr" or kids or not text:
        return text

    # --- Tek QC kapisi (Faz D) + kritikte bir yeniden deneme ---
    try:
        from akifactory import script_hooks as script_hk
        from akifactory import script_quality as script_q
        from akifactory.script_qc import orchestrate_script_qc

        qc = await orchestrate_script_qc(
            text, subj, niche_id=niche, stage="writer"
        )
        text = qc["text"]

        if (
            skeleton_bullets
            and qc.get("critical")
        ):
            retry_user = (
                user
                + "\n\nONCEKI DENEME ZAYIFTI. Yeniden yaz.\n"
                "- Ilk cumlede konu anahtar kelimesi ZORUNLU\n"
                "- Yalnizca olgu iskeletindeki bilgiler\n"
                "- Jenerik gizem / bos filler YASAK\n"
            )
            raw2 = await ollama_chat(
                [
                    {"role": "system", "content": payload["custom_system_prompt"]},
                    {"role": "user", "content": retry_user},
                ],
                think=False,
                model=writer_model,
                options=writer_opts,
            )
            cand = enforce_spoken_script_limits(raw2)
            if cand and len(cand) >= 80:
                qc2 = await orchestrate_script_qc(
                    cand, subj, niche_id=niche, stage="writer_retry"
                )
                cand = qc2["text"]
                if not script_q.has_critical_quality_issues(
                    cand, subj, niche_id=niche
                ):
                    text = cand
                elif not script_hk.validate_hook(
                    text, subj, niche_id=niche
                ) and script_hk.validate_hook(cand, subj, niche_id=niche):
                    text = cand
    except Exception:
        pass

    return text


async def generate_longform_chapter_script(
    *,
    main_subject: str,
    chapter_title: str,
    chapter_index: int,
    total_chapters: int,
    prior_context: str = "",
    chapter_outline: str = "",
    lang_id: str = "tr",
    platform_id: str = "youtube_shorts",
    niche_id: str = "genel",
    research_context: str = "",
    chapter_research: str = "",
    all_chapter_titles: list[str] | None = None,
    think_guidance: str = "",
) -> str:
    """Uzun video bolumu — tek ana konu, alt baslik detayi."""

    lang = (lang_id or "tr").strip().lower()[:2]
    niche = resolve_niche(niche_id)
    p = plat.resolve(platform_id)
    platform_label = p.get("label", "YouTube Shorts")
    idx = int(chapter_index)
    total = max(1, int(total_chapters))
    title = (chapter_title or "").strip()
    main = (main_subject or "").strip()
    from akifactory.text_utils import full_chapter_heading

    display_title = full_chapter_heading(main, title)
    is_first = idx <= 0
    is_last = idx >= total - 1

    if lang == "tr":
        system = (
            build_turkish_system_prompt(niche)
            + "\n\nOZEL: Bu metin cok bolumlu TEK videonun parcasidir. "
            "Ana konu sabittir; yeni konu veya baska video konusu acma."
        )
    else:
        system = _SYSTEM_EN

    prior = (prior_context or "").strip()
    prior_block = (
        f"\n\nONCEKI BOLUMLERIN METNI (devam et — TEKRAR ETME):\n{prior}\n"
        if prior
        else "\n\nBu serinin ILK bolumu.\n"
    )
    outline = (chapter_outline or "").strip()
    focus_block = (
        f"\n\nBU BOLUMUN ICERIK ODAĞI (plan notu — izleyiciye OKUMA): {title}\n"
        if title
        else ""
    )

    role_hint = ""
    continuity_block = ""
    if is_first:
        role_hint = (
            f"Ilk bolum: «{main}» konusuna merak uyandiran, somut bir olgu ile dogrudan gir. "
            "Alt baslik veya bolum adi SOYLEME."
        )
    elif is_last:
        role_hint = (
            f"Son bolum: «{main}» anlatimina DEVAM ederek guclu kapanisla bitir; "
            f"odak: {title}. Olayi/ekibi/yeri bastan tanitma. Bolum adi SOYLEME."
        )
        continuity_block = (
            "\nSUREKLILIK (KRITIK):\n"
            "- Bu TEK uzun belgeselin devam sahnesidir; mini belgeseli sifirdan BASLATMA\n"
            "- Ilk cumle yil+yer+grup sunumu olmasin (orn. «1959'da Rusya'da bir grup…» YASAK)\n"
            "- Onceki bolumun bitisinden dogal gecis yap; yeni detaya dal\n"
            "- Izleyicinin bildigi bilgileri (kim, nerede, ne zaman) yeniden tanitma\n"
        )
    else:
        role_hint = (
            f"Orta bolum: «{main}» anlatimina akici DEVAM et; "
            f"yalnizca su konuyu isle: {title}. "
            "Ana konuyu / olayi / ekibi bastan tanitma; bolum adi SOYLEME."
        )
        continuity_block = (
            "\nSUREKLILIK (KRITIK):\n"
            "- Bu TEK uzun belgeselin devam sahnesidir; her bolum AYRI video DEGIL\n"
            "- Ilk cumle ASLA olayi sifirdan kurmasin "
            "(yil + yer + «bir grup / ekip / Dyatlov ve…» sunumu YASAK)\n"
            "- Onceki bolumun bitis cumlelerinden kopmadan devam et\n"
            "- Yeni sahne, yeni kanit, yeni detay; ayni girisi tekrarlama\n"
            "- «Olay şöyle başladı», «Grup … idi» gibi yeniden ekspozisyon YASAK\n"
        )

    user = f"""ANA KONU (SABIT — tum seri boyunca degismez): {main}
BU BOLUMUN PLANDAKI ODAĞI: {title}
Bolum sirasi: {idx + 1}/{total}
Platform: {platform_label}
Nis: {NICHE_LABELS.get(niche, niche)}
{focus_block}{prior_block}{continuity_block}
GOREV:
- Bu parca «{main}» ana konusunun {idx + 1}. bolumu; AYRI bir video konusu DEGIL
- Icerigi dogrudan anlat (~45–55 sn, 6–10 cumle); alt basliklari veya plan maddelerini SESLI OKUMA
- «{display_title}», «{title}» veya bolum numarasiyla BASLAMA; mini belgesel gibi konuya dal
- {role_hint}
- ICERIK ZENGIN OLSUN: bu bolumde en az 3–4 YENI somut bilgi/detay ver (onceki bolumde soylenenleri tekrarlama)
- Bos/genel laf ve tekrar yok; her cumle yeni bir bilgi katsin, konuyu ileri tasi
- Ana konu disina cikma; baska yer/tarih/kisi konusu acma (ana konuyla baglantili detay OK)
- Onceki bolumlerdeki cumleleri, girisi ve ekspozisyonu TEKRARLAMA
- Tum bolum planini veya diger alt basliklari listeleme
- Soru cumlesi yok; belgesel anlatim
- Ham senaryo metni; markdown yok
"""
    research = (research_context or "").strip()
    ch_research = (chapter_research or "").strip()
    if research or ch_research:
        # Arastirma notundaki MÖ/MS'i ac — model kopyalamasin, TTS kirmasin
        from akifactory.text_utils import _expand_mo_ms_dates

        if research:
            research = _expand_mo_ms_dates(research)
        if ch_research:
            ch_research = _expand_mo_ms_dates(ch_research)
    if research:
        user += (
            "\n\nGENEL WEB ARASTIRMA NOTU (Wikipedia + DuckDuckGo — buna sadik kal):\n"
            f"{research}\n"
        )
    if ch_research:
        user += (
            f"\n\nBU BOLUM ICIN ARASTIRMA («{display_title}» odakli — buna sadik kal):\n"
            f"{ch_research}\n"
        )
    if research or ch_research:
        user += (
            "Arastirma notlarindaki olgulari kendi konusma dilimizle, akici belgesel tonunda anlat.\n"
            "KRITIK: Notta OLMAYAN ulke, sehir, kisi veya tarih UYDURMA. Not ile celisen bilgi YAZMA.\n"
            "Kaynakta net degilse spekulasyon ekleme.\n"
            "Tarih yazarken MÖ/MS KISALTMASI KULLANMA — her zaman «Milattan Önce / Milattan Sonra» yaz.\n"
        )
    guidance = (think_guidance or "").strip()
    if guidance:
        if lang == "tr":
            user += (
                "\n\nYONETMEN NOTU (kullanici secimleri — ton/odak buna uysun):\n"
                f"{guidance[:1500]}\n"
            )
        else:
            user += (
                "\n\nDIRECTOR NOTES (follow tone/focus from user choices):\n"
                f"{guidance[:1500]}\n"
            )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    raw = await ollama_chat(messages, think=False)
    from akifactory.text_utils import enforce_longform_chapter_limits, scrub_longform_chapter_narration

    cleaned = scrub_longform_chapter_narration(
        raw,
        main_subject=main,
        chapter_title=title,
        all_chapter_titles=all_chapter_titles,
    )
    return enforce_longform_chapter_limits(cleaned)


async def _suggest_travel_destination(*, exclude: list[str] | None = None) -> list[str]:
    """Seyahat nisinde tek destinasyon oner."""
    block = [t.strip() for t in (exclude or []) if len((t or "").strip()) > 3][:50]
    block_text = ""
    if block:
        lines = "\n".join(f"- {t}" for t in block)
        block_text = (
            f"\n\nDAHA ONCE VIDEO URETILMIS destinasyonlar — bunlari ve cok benzerlerini ASLA tekrarlama:\n"
            f"{lines}\n"
            f"Tamamen farkli bir sehir veya ulke sec."
        )
    prompt = (
        "Sen seyahat icerik editorusun. Turk izleyici icin populer bir destinasyon sec.\n"
        "Tam 1 adet kisa video konusu oner — tek satir.\n"
        "Format ornekleri:\n"
        "- Kapadokya: Balonlar ve gezilecek vadiler\n"
        "- Tokyo: Ilk kez gidenler icin rehber\n"
        "- Santorini: Mavi beyaz adalar ve plajlar\n"
        "- Dubai: Cöl modern sehir rehberi\n"
        "Konu basligi destinasyonu net yazsin; video tek yerde gezilecek yerler, guzellikler, "
        "para birimi, pahalilik ve yerel kultur anlatacak.\n"
        "Numara veya madde isareti kullanma. Sadece tek satir, Turkce karakterlerle."
        f"{block_text}"
    )
    text = await ollama_chat(
        [{"role": "user", "content": prompt}],
        think=False,
        clean_script=False,
    )
    if not text:
        return []
    line = text.strip().splitlines()[0].strip().lstrip("0123456789.-) ").strip()
    return [line] if len(line) > 5 else []


_SUGGEST_TITLE_RULES = (
    "BASLIK KURALLARI (cok onemli):\n"
    "- Yalnizca duzgun, tam Turkce yaz; TEK bir yabanci/Ingilizce kelime bile kullanma "
    "(ornek: 'mystery', 'the', 'story' YASAK)\n"
    "- Baslikta iki nokta ':' ile alt baslik EKLEME; tek net ifade yaz\n"
    "- Kisa ve anlasilir olsun (2–6 kelime); yarim veya eksik cumle yazma\n"
    "- Sadece somut, gercek bir konu adi ver; suslu/klise laf katma\n"
    "- Türkçe karakterleri MUTLAKA doğru yaz (ç, ğ, ı, İ, ö, ş, ü); 'sirri', 'kacisi', "
    "'Gunu' gibi ASCII yazım YASAK — 'sırrı', 'kaçışı', 'Günü' yaz\n"
    "- Ornek dogru basliklar: 'Nuh Tufanı', 'Antikythera Mekanizması', 'Pompeii'nin Son Günü'\n"
    "- Ornek YANLIS basliklar: 'Buyuk Mayisin Gercekte Ne Oldugu: M mystery', "
    "'The Lost City efsanesi'"
)


_SUGGEST_ANGLES: dict[str, tuple[str, ...]] = {
    "tarih_gizem": (
        "Güney ve Orta Amerika antik kültürleri",
        "Asya ve Uzakdoğu'dan az bilinen gizemler",
        "Afrika'nın kayıp krallıkları ve arkeolojik sırları",
        "Orta Çağ Avrupası'ndan çözülmemiş olaylar",
        "Mezopotamya, İran ve Levant gizemleri",
        "denizde kaybolan gemiler ve batık sırlar",
        "iz bırakmadan kaybolan insanlar ve topluluklar",
        "şifreli metinler, çözülemeyen yazılar ve haritalar",
        "arkeolojik anomaliler ve açıklanamayan buluntular",
        "Osmanlı ve Selçuklu döneminden az bilinen gizemler",
        "20. yüzyılda yaşanmış çözülmemiş olaylar",
        "Kuzey Avrupa, Viking ve Kelt gizemleri",
        "Okyanusya ve Pasifik adalarının sırları",
        "kayıp hazineler ve bulunamayan eserler",
    ),
}
_GENERIC_ANGLES: tuple[str, ...] = (
    "az bilinen ama gerçek ve doğrulanabilir konular",
    "farklı coğrafyalardan örnekler",
    "son 100 yıldan olaylar",
    "eski dönemlerden şaşırtıcı detaylar",
    "çoğu kişinin yanlış bildiği konular",
    "tek bir çarpıcı olay veya kişiye odaklanan konular",
)


async def suggest_topics(
    niche_id: str = "tarih_gizem",
    count: int = 5,
    *,
    exclude: list[str] | None = None,
) -> list[str]:
    import random

    niche = resolve_niche(niche_id)
    if niche == "seyahat":
        return await _suggest_travel_destination(exclude=exclude)
    label = NICHE_LABELS.get(niche, niche)
    hint = NICHE_SUGGEST_HINTS.get(niche, "ilgi çekici konular")
    angle = random.choice(_SUGGEST_ANGLES.get(niche) or _GENERIC_ANGLES)
    hint = (
        f"{hint}\nBu seferki açı: {angle}.\n"
        "Herkesin ilk aklına gelen en ünlü konuları (ör. Göbeklitepe, Mısır piramitleri, "
        "Atlantis, Stonehenge) tekrar tekrar önerme; çeşitlilik öncelikli.\n"
        "Her konu GERÇEK, belgelenmiş ve internette kaynağı bulunan bir konu olmalı; "
        "uydurma isim, uydurma eser veya uydurma olay YASAK. Emin değilsen daha tanınmış "
        "ama gerçek bir konu seç"
    )
    ask = max(count, count + min(len(exclude or []) // 8, 5))
    block = [t.strip() for t in (exclude or []) if len((t or "").strip()) > 3][:50]
    block_text = ""
    if block:
        lines = "\n".join(f"- {t}" for t in block)
        block_text = (
            f"\n\nDAHA ONCE URETILMIS VEYA ONERILMIS konular — bunlari ve cok benzerlerini ASLA tekrarlama:\n"
            f"{lines}\n"
            f"Tamamen yeni, farkli ve taze konular oner."
        )
    if is_kids_niche(niche):
        prompt = (
            f"Sen {label} nişinde çocuklara yönelik içerik editörüsün.\n"
            f"Odak alan: {hint}.\n"
            f"6–10 yaş için TikTok/Shorts konusu öner; korkutucu veya karmaşık konu yok.\n"
            f"Tam {ask} adet kısa video konusu öner.\n"
            f"Her satırda bir konu; numara veya madde işareti kullanma.\n"
            f"{_SUGGEST_TITLE_RULES}"
            f"{block_text}"
        )
    else:
        prompt = (
            f"Sen {label} nişinde uzman bir içerik editörüsün.\n"
            f"Odak alan: {hint}.\n"
            f"TikTok/Shorts için tam {ask} adet kısa video konusu öner.\n"
            f"Her satırda bir konu; numara veya madde işareti kullanma.\n"
            f"{_SUGGEST_TITLE_RULES}"
            f"{block_text}"
        )
    from akifactory.ollama_util import creative_chat_options

    text = await ollama_chat(
        [{"role": "user", "content": prompt}],
        think=False,
        clean_script=False,
        options={**creative_chat_options(), "temperature": 0.9},
    )
    if not text:
        return []
    lines = [_clean_suggested_title(ln) for ln in text.splitlines()]
    return [ln for ln in lines if len(ln) > 5][: max(count * 2, count)]


def _clean_suggested_title(line: str) -> str:
    """Onerilen konu basligini temizler: numara/tirnak kirp, ':' ile alt baslik
    varsa en anlamli (en uzun) parcayi tut — 'M mystery' gibi eksik/Ingilizce kuyruk atilir."""
    s = line.strip().lstrip("0123456789.-)• ").strip().strip('"').strip("'").strip()
    if ":" in s:
        parts = [p.strip() for p in s.split(":") if p.strip()]
        if parts:
            s = max(parts, key=len)
    return s.strip()
