# AkiFactory

**Windows public preview · One-click setup with Pinokio**

Turn a topic into a vertical short video with stock footage, narration, subtitles and a finished edit. Create content for YouTube Shorts, TikTok and Instagram Reels with multilingual production options.

- **Automatic production:** use Pexels, Pixabay or both.
- **Manual editing:** prepare separate narration, subtitles, music and source clips.
- **Optional AI covers:** Qwen-Image creates text-free artwork; real fonts add your title.
- **Gallery:** keep finished videos, covers and publishing text together.
- **Interface:** English by default. Switch to Turkish anytime; your choice is remembered.

## Install with Pinokio

Download **https://github.com/erdinoral/AkiFactory** in Pinokio.

1. Select **Install / Repair**.
2. Select **Start**, then **Open AkiFactory**.
3. In **Settings**, configure your stock API keys and an LLM connection. Use Ollama for local text generation or a supported API provider.
4. Optionally select **Install AI cover engine (optional)** and enable automatic covers.

See [Pinokio setup and API examples](README-PINOKIO.md).

## Requirements

- Windows 10/11 x64.
- Internet for stock search, downloads and Edge TTS.
- Ollama with a text model, or a supported LLM API connection.
- Optional AI covers: NVIDIA CUDA, about 30 GB of model downloads and at least 50 GB of free space.
- Optional RVC: supply your own voice models. Personal voices and music libraries are not included.

The preview has been tested on the development machine. Fresh-machine installation may still need fixes. Report your Windows version, GPU and error details without API keys or private files.

## Standalone desktop launch

Install Python 3.11 or 3.12 and [Node.js](https://nodejs.org/), then run:

```bat
AkiFactory.bat
```

The first launch prepares the Python environment and desktop dependencies. Pinokio opens the web interface directly and does not require Electron.

For local text generation, install [Ollama](https://ollama.com) and a model:

```sh
ollama serve
ollama pull qwen3.5:9b
```

## Project layout

```text
AkiFactory/
├── AkiFactory.bat       # Standalone desktop launcher
├── pinokio.js          # Pinokio menu
├── install.js          # Installation and repair
├── start.js            # Pinokio launch
├── electron/           # Desktop shell
├── web/                # Web interface
├── src/akifactory/     # API and video engine
├── scripts/            # Setup and utilities
├── models/             # Local model files
├── resource/           # Fonts and music
├── data/               # Local gallery, settings and outputs
└── assets/             # Application branding
```

## Local services

The interface starts at `http://127.0.0.1:7860` and the engine at `http://127.0.0.1:8080`. Occupied ports are skipped automatically. Ollama normally uses `http://127.0.0.1:11434`.

## API keys and privacy

Enter credentials in **Settings**. Personal configuration is stored locally in `data/api_keys.json` and `data/llm_settings.json`. These files, generated videos, model weights and logs are excluded from Git. Never attach private configuration to issue reports.

## Updates and recovery

Finish all generations before using **Update**. **Reset Python environment** backs up the environment and preserves videos, models and API keys; select **Install / Repair** afterward.

Third-party license notices are included in the repository.
