# Optional AI cover component

Ship `src/akifactory/ai_cover.py`, `cover_text.py`, and
`scripts/setup_ai_cover.py` with AkiFactory. The production UI's install button
starts the installer with the app Python runtime. The base runtime must include
Python's venv and ensurepip modules. No Desktop path is used at runtime.

The installer downloads upstream ComfyUI and the three official Comfy-Org
Qwen-Image model files into the writable AkiFactory data directory under
`components/qwen-cover/`. It creates a separate Python environment, installs
CUDA PyTorch and ComfyUI requirements, checks model sizes and CUDA availability.
Upstream source/license files are retained. Do not include user API keys,
galleries, settings, or unrelated image-studio data in a release package.

The model download is about 30 GB plus Python/CUDA dependencies; allow 50 GB
free disk space and a supported NVIDIA GPU (tested generation: RTX 5060 Ti
16 GB). Installation is opt-in. The default cover preference for new users is off.

For development, existing model files can be copied without downloading again:
`python scripts/setup_ai_cover.py --models-from <ComfyUI-models-directory>`.
This imports file contents, not links to the source directory.

The built-in cover client speaks directly to local ComfyUI on port 8189. An
already running compatible ComfyUI can be reused; Image Studio's server on 8790
is no longer needed. Otherwise the installed component is started automatically.

Each completed short-video task is archived before cover work begins. Cover
generation is awaited before starting the next video, keeping GPU jobs serial.
The active text model is unloaded before Qwen inference; Qwen is unloaded after.
Cover errors are stored on the gallery entry and do not fail the video.

Clean-machine installation and packaged-EXE distribution require a release test
on supported Windows/NVIDIA hardware; unit tests do not validate downloads,
driver compatibility, or an embedded Python distribution.
