// Recoverable reset of Python dependencies only; never delete models/user data.
module.exports = {
  run: [
    { method: "shell.run", params: {
      path: ".", venv: ".venv", message: ".venv\\Scripts\\python.exe scripts/pinokio_prepare.py --reset"
    } }
  ]
};
