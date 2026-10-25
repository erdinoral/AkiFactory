// Single repository: application and launchers update together.
module.exports = {
  run: [
    { method: "shell.run", params: { path: ".", message: "git pull --ff-only" } },
    { method: "script.start", params: { uri: "install.js" } }
  ]
};
