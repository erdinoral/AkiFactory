// Reference: Pinokio examples/ai-video-composer/install.js (shell + venv).
module.exports = {
  requires: { bundle: "ai" },
  run: [
    { when: "{{!exists('.venv/Scripts/python.exe')}}", method: "shell.run", params: {
      path: ".", message: "uv venv --python 3.12 --seed .venv"
    } },
    { method: "shell.run", params: {
      path: ".", venv: ".venv", env: { PYTHONUTF8: "1" },
      message: [
        "uv pip install --python .venv/Scripts/python.exe -r requirements.txt",
        "uv pip install --python .venv/Scripts/python.exe --no-deps -e .",
        "uv pip install --python .venv/Scripts/python.exe git+https://github.com/emres/turkish-deasciifier.git",
        ".venv\\Scripts\\python.exe scripts/pinokio_prepare.py"
      ]
    } }
  ]
};
