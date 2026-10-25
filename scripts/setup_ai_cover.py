"""Install the optional Qwen cover component into AkiFactory user data."""
import argparse
import json
import shutil
import subprocess
import sys
import urllib.request
import venv
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from akifactory.ai_cover import component_root

MODELS = {
    "diffusion_models/qwen_image_2512_fp8_e4m3fn.safetensors": 20430679144,
    "text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors": None,
    "vae/qwen_image_vae.safetensors": None,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-from", type=Path, help="Optional existing Comfy models folder to import")
    args = parser.parse_args()
    root = component_root()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / "install_status.json"
    def status(state, detail):
        marker.write_text(json.dumps({"state": state, "detail": detail}, ensure_ascii=False), encoding="utf-8")
        print(detail, flush=True)
    try:
        status("running", "Kapak motoru indiriliyor")
        comfy = root / "ComfyUI"
        if not (comfy / "main.py").exists():
            archive = root / "comfy.zip"
            urllib.request.urlretrieve("https://github.com/Comfy-Org/ComfyUI/archive/refs/heads/master.zip", archive)
            with zipfile.ZipFile(archive) as package:
                for name in package.namelist():
                    dest = (root / name).resolve()
                    if not dest.is_relative_to(root.resolve()):
                        raise ValueError("Gecersiz arsiv yolu")
                package.extractall(root)
            (root / "ComfyUI-master").rename(comfy)
        status("running", "Python ve CUDA bilesenleri kuruluyor")
        env = root / ".venv"
        if not (env / "Scripts" / "python.exe").is_file():
            venv.EnvBuilder(with_pip=True).create(env)
        python = str(env / "Scripts" / "python.exe")
        subprocess.run([python, "-m", "pip", "install", "torch", "torchvision", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cu128"], check=True)
        subprocess.run([python, "-m", "pip", "install", "-r", str(comfy / "requirements.txt")], check=True)
        for relative, known_size in MODELS.items():
            target = comfy / "models" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            metadata_url = "https://huggingface.co/api/models/Comfy-Org/Qwen-Image/tree/main/split_files/" + relative.split("/")[0]
            with urllib.request.urlopen(metadata_url) as response:
                entries = json.load(response)
            expected = next(int(e["size"]) for e in entries if e["path"] == "split_files/" + relative)
            if known_size and expected != known_size:
                raise RuntimeError("Model boyutu degisti; kurulum manifesti kontrol edilmeli")
            if target.is_file() and target.stat().st_size == expected:
                continue
            status("running", "Model hazirlaniyor: " + target.name)
            part = target.with_suffix(".part")
            source = args.models_from / relative if args.models_from else None
            if source and source.is_file() and source.stat().st_size == expected:
                shutil.copy2(source, part)
            else:
                url = "https://huggingface.co/Comfy-Org/Qwen-Image/resolve/main/split_files/" + relative
                urllib.request.urlretrieve(url, part)
            if part.stat().st_size != expected:
                raise RuntimeError("Model indirmesi eksik: " + target.name)
            part.replace(target)
        subprocess.run([python, "-c", "import torch; assert torch.cuda.is_available(), 'NVIDIA CUDA gerekli'"], check=True)
        status("done", "AI kapak motoru hazir")
    except Exception as exc:
        status("error", str(exc))
        raise


if __name__ == "__main__":
    main()
