# AkiFactory · Pinokio

Windows 10/11 x64 için Türkçe Shorts/Reels video stüdyosu. Stok görüntü,
seslendirme, altyazı, montaj ve isteğe bağlı Qwen AI kapak üretir.

## Kurulum

GitHub'da bu klasörü **tek depo** olarak yayınlayın: Pinokio dosyaları ve uygulama
kodu aynı depoda bulunur. Kullanıcı Pinokio'nun GitHub bağlantısından indirme
seçeneğine depo adresini girer, ardından **Kur / Onar** ve **Başlat** seçer.
`install.js` ayrıca ikinci bir uygulama kopyası klonlamaz.

Geliştirme bilgisayarında mevcut klasörde çalışmaya devam edilebilir. Pinokio
dosyaları bu klasördedir; uygulamayı Pinokio `api` klasörüne kopyalamak gerekmez.
Başlatıcı göreli yollar kullanır. Pinokio'nun yerel terminalinde bu klasörün
`start.js` dosyası çalıştırılabilir.

Temel kurulum Python 3.12 ortamını ve uygulama bağımlılıklarını hazırlar. Mevcut
`.venv` kullanılır; modeller otomatik yeniden indirilmez. **Kur / Onar**, Python
paketlerini requirements.txt sürümlerine getirir; özel geliştirme paketleri varsa
önce sürümlerini kaydedin. Electron kurulması gerekmez; arayüz Pinokio içinde açılır.

İlk açılışta Ayarlar'dan Pexels/Pixabay anahtarlarını ve LLM seçimini yapın.
Ücretsiz yerel senaryo için Ollama ve bir yazar modeli gerekir; Ollama henüz
kurulu değilse kendi resmi kurulumunu tamamlayın. Alternatif olarak desteklenen
bir LLM API bağlantısı yapılandırılabilir. Edge TTS internet gerektirir.
RVC ses modelleri uygulamayla birlikte dağıtılmaz; kendi modellerinizi ekleyin.

## İsteğe bağlı AI kapak

**AI kapak motorunu kur** ComfyUI + Qwen-Image-2512 bileşenini indirir. Yaklaşık
30 GB model, Python/CUDA bağımlılıkları ve en az 50 GB boş alan planlayın.
NVIDIA CUDA gerekir; örnek kapak RTX 5060 Ti 16 GB ile üretildi. Bu özellik
kapalıyken Qwen modelleri indirilmez ve kapak üretimi yapılmaz.

Üretim ekranından **Video bitince AI kapak oluştur** seçilebilir. Görsel yazısız
üretilir; başlık gerçek fontla eklenir ve video detayındaki Kapaklar'da görünür.
Model dosyaları GitHub'a yüklenmez; kurulum resmi model kaynağından indirir.

## Güncelleme ve sıfırlama

Önce üretimleri bitirip uygulamayı durdurun. **Güncelle**, tek depoda
`git pull --ff-only` çalıştırır ve bağımlılıkları yeniler. Yerel kod değişiklikleriyle
çakışma olursa durur; zorla üzerine yazmaz. ZIP'ten indirilmiş veya henüz Git
deposu olmayan bir geliştirme klasöründe Git güncellemesi kullanılamaz.

**Python ortamını sıfırla**, `.venv` klasörünü tarihli bir yedeğe taşır. Bu işlem
ek disk alanı kullanabilir; otomatik çalışmaz. Videoları, anahtarları veya modelleri
silmez. Yeniden kurulum için **Kur / Onar** kullanılır.

Üretilenler ve API anahtarları `data/`, modeller `models/`, ses dosyaları
`resource/songs/` altında yereldir. Bunları yayınlamayın. `.gitignore` kişisel
verileri, ortamı, modelleri ve günlükleri dışarıda tutar. Depo paylaşmadan önce
yalnızca kod ve gerekli varsayılan kaynakların seçildiğini doğrulayın.

## API örnekleri

Arayüzün açıldığı gerçek portu kullanın (varsayılan 7860, doluysa sonraki port).

JavaScript:
```js
const result = await fetch('http://127.0.0.1:7860/api/health');
console.log(await result.json());
```

Python:
```python
import requests
print(requests.get('http://127.0.0.1:7860/api/health', timeout=10).json())
```

Curl:
```sh
curl http://127.0.0.1:7860/api/health
curl http://127.0.0.1:7860/api/settings/ai-cover
```

Pinokio kullanımı yerel makinede test edilmelidir. Yerel başlatma testi, temiz
Windows kurulumundaki tüm paket/model indirmelerinin tamamlandığını kanıtlamaz.
