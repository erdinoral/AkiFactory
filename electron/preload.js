const { contextBridge, ipcRenderer } = require("electron");

let windowFocused = true;
ipcRenderer.on("window-focus-changed", (_evt, focused) => {
  windowFocused = !!focused;
});

contextBridge.exposeInMainWorld("akifactory", {
  saveVideo: (url, defaultName) => ipcRenderer.invoke("save-video", url, defaultName),
  openAssetsFolder: (section) => ipcRenderer.invoke("open-assets-folder", section),
  isWindowFocused: () => windowFocused,
  isWindowFocusedAsync: () => ipcRenderer.invoke("is-window-focused"),
  showNotification: (title, body) =>
    ipcRenderer.invoke("show-notification", { title, body }),
  isElectron: true,
});
