// Reference: examples/comfy/start.js: daemon, captured URL, local.set.
module.exports = {
  daemon: true,
  run: [
    { method: "shell.run", params: {
      path: ".", venv: ".venv", env: { PYTHONUTF8: "1", PYTHONUNBUFFERED: "1" },
      message: ".venv\\Scripts\\python.exe scripts/pinokio_run.py",
      on: [{ event: "/AKIFACTORY_READY (http:\\/\\/[0-9.:]+)/", done: true }]
    } },
    { when: "{{input && input.event && input.event[1]}}", method: "local.set", params: { url: "{{input.event[1]}}" } }
  ]
};
