# AkiFactory

**Windows public preview · Pinokio launcher included**

Turn a topic into a vertical short video with stock footage, narration, subtitles
and a finished edit. Turkish-first, with multilingual production options.
Choose automatic stock production or prepare separate assets for manual editing.
Optional local Qwen-Image covers are generated without text; the video title is
then typeset with a real font to preserve Turkish characters.

## Install with Pinokio

Download this repository in Pinokio:
**https://github.com/erdinoral/AkiFactory**

1. Select **Kur / Onar** (Install / Repair).
2. Select **Başlat** (Start).
3. In Settings, configure your stock API keys and an LLM connection. Use Ollama
   for local text generation or configure one of the supported API providers.
4. Optionally install the AI cover engine and enable automatic covers.

Windows 10/11 x64 is supported by this launcher. Stock search and Edge TTS need
internet. AI covers require NVIDIA CUDA and a separate model download of about
30 GB; allow at least 50 GB of free space. RVC voices and your personal music
library are not included. The preview has been tested on the development machine;
fresh-machine installation may still need fixes. Report issues with platform,
GPU and error details, without including API keys.

See [Pinokio setup and API examples](README-PINOKIO.md).

Türkçe odaklı kısa dikey video stüdyosu (YouTube Shorts, TikTok, Instagram Reels).

**Tek giriş:** `AkiFactory.bat` → Electron penceresi + arka planda Python motoru.

Pinokio başlatıcısı ve kurulum: [README-PINOKIO.md](README-PINOKIO.md).

## Gereksinimler

- Windows 10/11
- Python 3.11 veya 3.12 (ilk açılışta `.venv` otomatik)
- [Node.js](https://nodejs.org/) (Electron)
- [Ollama](https://ollama.com) — `ollama serve` + model (`ollama pull qwen3.5:9b`) veya Ayarlar'dan bulut LLM anahtarı
- İnternet (Edge TTS, Pexels / Pixabay)
- İsteğe bağlı: NVIDIA GPU (Whisper CUDA, NVENC, yerel TTS)

## Başlatma

```bat
AkiFactory.bat
```

İlk açılış 2–5 dk sürebilir (pip, Whisper, Electron npm). Sonraki açılışlar daha hızlıdır.

## Proje yapısı

```
AkiFactory/
├── AkiFactory.bat          ← tek başlatıcı
├── electron/               ← masaüstü kabuk (Electron)
├── web/                    ← arayüz (HTML, CSS, JS)
├── src/akifactory/         ← FastAPI arayüz + üretim mantığı
│   └── engine/             ← video motoru
├── scripts/                ← kurulum ve yardımcı scriptler
├── models/                 ← whisper, chatterbox, rvc modelleri
├── resource/               ← fontlar, BGM
├── data/                   ← galeri, geçmiş, ayarlar, motor çıktıları (git'e girmez)
└── assets/                 ← logo, ikon
```

## Portlar

| Servis | Adres |
|--------|--------|
| Arayüz (FastAPI) | `http://127.0.0.1:7860+` |
| Video motoru | `http://127.0.0.1:8080+` |
| Ollama | `http://127.0.0.1:11434` |

## API anahtarları

Pexels, Pixabay ve LLM anahtarları uygulama içinden (Ayarlar) girilir ve yalnızca bu bilgisayarda
`data/api_keys.json` / `data/llm_settings.json` dosyalarında saklanır. Bu dosyalar git'e girmez.

## Geliştirici komutları (opsiyonel)

| Komut | Açıklama |
|-------|----------|
| `python scripts/bootstrap.py --kur` | Tam kurulum tekrar |
| `python scripts/bootstrap.py --guncelle` | AkiFactory `git pull` + bağımlılıklar |
| `python scripts/bootstrap.py --chatterbox` | Chatterbox (yerel TR taban) |
| `python scripts/bootstrap.py --rvc` | RVC paketi |
| `cd electron && npm start` | Electron (AkiFactory.bat ile aynı) |

## Lisans

AkiFactory kodu proje sahibine aittir. Video motoru başlangıçta
[MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) (MIT) kodundan türetilmiştir;
MIT lisansının gerektirdiği telif bildirimi `LICENSE-engine-upstream.txt` dosyasındadır.
