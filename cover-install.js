module.exports = {
  requires: { bundle: "ai" },
  run: [{ method: "shell.run", params: {
    path: ".", venv: ".venv", env: { PYTHONUTF8: "1" },
    message: "python scripts/setup_ai_cover.py"
  } }]
};
