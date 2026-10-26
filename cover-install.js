module.exports = {
  requires: { bundle: "ai" },
  run: [{ method: "shell.run", params: {
    path: ".", venv: ".venv", env: { PYTHONUTF8: "1" },
    message: ".venv\\Scripts\\python.exe scripts/setup_ai_cover.py"
  } }]
};
