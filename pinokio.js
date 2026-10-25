// Reference: examples/mochi/pinokio.js dynamic installation/running menus.
module.exports = {
  version: "8.0",
  title: "AkiFactory",
  description: "Türkçe kısa video stüdyosu: stok video, seslendirme, altyazı ve isteğe bağlı Qwen AI kapak. Windows 10/11 x64.",
  icon: "assets/icon.png",
  menu: async (kernel, info) => {
    if (kernel.platform !== "win32") return [{ text: "Bu sürüm Windows 10/11 x64 içindir", href: "README-PINOKIO.md" }];
    for (const [file, label] of [["install.js", "Kuruluyor"], ["update.js", "Güncelleniyor"], ["reset.js", "Ortam sıfırlanıyor"], ["cover-install.js", "AI kapak motoru kuruluyor"]]) {
      if (info.running(file)) return [{ default: true, icon: "fa-solid fa-terminal", text: label, href: file }];
    }
    if (info.running("start.js")) {
      const local = info.local("start.js");
      return [
        ...(local?.url ? [{ default: true, icon: "fa-solid fa-rocket", text: "AkiFactory'yi aç", href: local.url }] : []),
        { default: !local?.url, icon: "fa-solid fa-terminal", text: "Terminal", href: "start.js" }
      ];
    }
    const installed = info.exists(".venv/Scripts/python.exe") && info.exists(".aki_pinokio_installed");
    return [
      ...(installed ? [{ default: true, icon: "fa-solid fa-power-off", text: "Başlat", href: "start.js" }] : []),
      { default: !installed, icon: "fa-solid fa-plug", text: "Kur / Onar", href: "install.js" },
      ...(installed ? [
        { icon: "fa-solid fa-image", text: "AI kapak motorunu kur (isteğe bağlı)", href: "cover-install.js", confirm: "Yaklaşık 30 GB Qwen modeli ve CUDA bağımlılıkları indirilir. En az 50 GB boş alan ve NVIDIA GPU önerilir. Devam?" },
        { icon: "fa-solid fa-arrows-rotate", text: "Güncelle", href: "update.js", confirm: "Üretimler bittikten sonra güncelleyin. GitHub deposundaki son sürüm alınacak." },
        { icon: "fa-solid fa-rotate-left", text: "Python ortamını sıfırla", href: "reset.js", confirm: "Çalışan işleri durdurun. Python ortamı yedeklenir; modeller, API anahtarları ve videolar korunur. Devam?" }
      ] : []),
      { icon: "fa-solid fa-book", text: "Kullanım / Kurulum", href: "README-PINOKIO.md" }
    ];
  }
};
