# scripts/

Kurulum ve yardımcı araçlar. Normal kullanıcı yalnızca kökteki `AkiFactory.bat` çalıştırır.

| Script | Ne yapar |
|--------|----------|
| `launch_preflight.py` | Python, pip, ffmpeg, Ollama kontrolü |
| `apply_config.py` | `data/engine.toml` oluşturur |
| `setup_local.py` | Whisper + yerel modeller |
| `sync_gpu.py` | GPU profili |
| `run_backend.py` | Electron arka plan (arayuz FastAPI + video motoru) |
| `prelaunch_cleanup.py` | Eski motor süreçlerini temizler |
| `bootstrap.py` | Kurulum alt komutları (`--kur`, `--chatterbox`, `--rvc`…) |
| `setup_chatterbox.py` | Chatterbox Multilingual (TR) |
| `setup_rvc.py` | RVC paketi |
| `install_vision.py` | Vision model (analiz sekmesi) |
