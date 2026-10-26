// Reference: examples/mochi/pinokio.js dynamic installation/running menus.
const fs = require("fs");
const path = require("path");
const http = require("http");

// A junction can make Pinokio's script status use a different root path.
// Only expose a saved loopback port after confirming the AkiFactory API.
async function activeUrl() {
  let port;
  try { port = Number(fs.readFileSync(path.join(__dirname, ".aki_ui_port"), "utf8").trim()); }
  catch { return null; }
  if (!Number.isInteger(port) || port < 1 || port > 65535) return null;
  const url = `http://127.0.0.1:${port}`;
  return new Promise((resolve) => {
    const req = http.get(`${url}/api/version`, (res) => {
      let body = "";
      res.on("data", (chunk) => { body += chunk; });
      res.on("end", () => {
        try { resolve(res.statusCode === 200 && JSON.parse(body).api_json_safe ? url : null); }
        catch { resolve(null); }
      });
      res.on("error", () => resolve(null));
    });
    req.setTimeout(1000, () => { req.destroy(); resolve(null); });
    req.on("error", () => resolve(null));
  });
}
module.exports = {
  version: "8.0",
  title: "AkiFactory",
  description: "Short video studio: stock footage, narration, subtitles and optional local Qwen AI covers. Windows 10/11 x64.",
  icon: "assets/akifactory-256.png",
  menu: async (kernel, info) => {
    if (kernel.platform !== "win32") return [{ text: "This version requires Windows 10/11 x64", href: "README-PINOKIO.md" }];
    for (const [file, label] of [["install.js", "Installing"], ["update.js", "Updating"], ["reset.js", "Resetting environment"], ["cover-install.js", "Installing AI cover engine"]]) {
      if (info.running(file)) return [{ default: true, icon: "fa-solid fa-terminal", text: label, href: file }];
    }
    const liveUrl = await activeUrl();
    if (info.running("start.js") || liveUrl) {
      const local = info.local("start.js");
      const url = liveUrl || local?.url;
      return [
        ...(url ? [{ default: true, icon: "fa-solid fa-rocket", text: "Open AkiFactory", href: url }] : []),
        { default: !url, icon: "fa-solid fa-terminal", text: "Terminal", href: "start.js" }
      ];
    }
    const installed = info.exists(".venv/Scripts/python.exe") && info.exists(".aki_pinokio_installed");
    return [
      ...(installed ? [{ default: true, icon: "fa-solid fa-power-off", text: "Start", href: "start.js" }] : []),
      { default: !installed, icon: "fa-solid fa-plug", text: "Install / Repair", href: "install.js" },
      ...(installed ? [
        { icon: "fa-solid fa-image", text: "Install AI cover engine (optional)", href: "cover-install.js", confirm: "Downloads about 30 GB of Qwen models plus CUDA dependencies. At least 50 GB of free space and an NVIDIA GPU are recommended. Continue?" },
        { icon: "fa-solid fa-arrows-rotate", text: "Update", href: "update.js", confirm: "Finish all generations before updating. Downloads the latest version from GitHub." },
        { icon: "fa-solid fa-rotate-left", text: "Reset Python environment", href: "reset.js", confirm: "Stop all running jobs first. The Python environment is backed up; models, API keys and videos are preserved. Continue?" }
      ] : []),
      { icon: "fa-solid fa-book", text: "Documentation / Setup", href: "README-PINOKIO.md" }
    ];
  }
};
