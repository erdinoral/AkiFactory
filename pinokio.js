// Reference: examples/mochi/pinokio.js dynamic installation/running menus.
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
    if (info.running("start.js")) {
      const local = info.local("start.js");
      return [
        ...(local?.url ? [{ default: true, icon: "fa-solid fa-rocket", text: "Open AkiFactory", href: local.url }] : []),
        { default: !local?.url, icon: "fa-solid fa-terminal", text: "Terminal", href: "start.js" }
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
