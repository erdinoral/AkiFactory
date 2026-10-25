// Recoverable reset of Python dependencies only; never delete models/user data.
module.exports = {
  run: [
    { method: "shell.run", params: {
      path: ".", venv: ".venv", message: "python scripts/pinokio_prepare.py --reset"
    } }
  ]
};
