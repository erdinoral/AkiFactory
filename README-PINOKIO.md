# AkiFactory · Pinokio

A multilingual Shorts/Reels video studio for Windows 10/11 x64. Create stock-based videos with narration, subtitles, music and optional local Qwen AI covers.

## Setup

Download `https://github.com/erdinoral/AkiFactory` in Pinokio. Select **Install / Repair**, **Start**, then **Open AkiFactory**.

The installer prepares Python 3.12 and application dependencies. It reuses an existing `.venv` without cloning another application copy. Electron is not required.

In **Settings**, enter Pexels/Pixabay API keys and choose an LLM connection. For local text generation, install Ollama from its official website and download a model. Supported LLM API providers are also available. Edge TTS needs internet. Supply your own optional RVC voice models.

English is the default interface language. The TR/EN switch remembers your choice. Generation language is selected separately.

## Optional AI covers

Select **Install AI cover engine (optional)** to download ComfyUI and Qwen-Image-2512. Allow about 30 GB for models plus Python/CUDA dependencies and at least 50 GB of free space. An NVIDIA CUDA GPU is required; the sample cover used an RTX 5060 Ti with 16 GB VRAM.

Enable automatic covers on the generation screen. Artwork is generated without text; real fonts add the title. Find the result in the video's cover section. Cover generation can be disabled. Models are downloaded separately and are not published on GitHub.

## Updates and recovery

Finish all generations and stop the app before selecting **Update**. The updater uses `git pull --ff-only` and refreshes dependencies. It does not force overwrite conflicting local changes. Git-based updates require a Git checkout.

**Reset Python environment** renames `.venv` to a dated backup, preserving videos, API keys and models. Select **Install / Repair** afterward. Backups use additional disk space. Repair aligns packages with `requirements.txt`; record custom development dependencies first.

## Local data

Videos and settings live in `data/`, models in `models/`, and local music in `resource/songs/`. Personal files are excluded from Git. Do not publish them or include API keys in support requests.

Developers can continue using an existing working folder. Relative launcher paths avoid requiring a second copy of large model files.

## API examples

Use the actual interface port shown by the launcher (default 7860).

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

Local launch has been tested on the development machine. This does not yet verify every dependency and model download on a fresh Windows installation.
