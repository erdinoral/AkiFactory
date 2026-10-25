const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("akifactorySplash", {
  onProgress: (handler) => {
    ipcRenderer.on("boot-progress", (_evt, data) => {
      try {
        handler(data);
      } catch (e) {
        console.error(e);
      }
    });
  },
});
