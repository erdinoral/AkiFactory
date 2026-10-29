const { app, BrowserWindow, dialog, ipcMain, Notification, nativeImage, session } = require("electron");
const { spawn, spawnSync } = require("child_process");
const path = require("path");
const fs = require("fs");
const http = require("http");

const APP_ID = "com.akiyom.akifactory";

/** Ikinci AkiFactory.bat — onceki motoru oldurup bu hatayi tetiklemesin */
const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
      // Bat tekrar tiklaninca eski JS/CSS kalmasin
      mainWindow.webContents.reloadIgnoringCache();
    } else if (splashWindow && !splashWindow.isDestroyed()) {
      splashWindow.show();
      splashWindow.focus();
    }
  });
}

let lastBackendError = "";
let backendReadyData = null;
let backendAutoRestartCount = 0;
const BACKEND_AUTO_RESTART_MAX = 4;
/** Pencere kapanirken motoru yeniden baslatma / yetim surec birakma */
let appShuttingDown = false;
let backendRestartTimer = null;

function appRoot() {
  if (app.isPackaged) {
    return process.resourcesPath;
  }
  return path.resolve(__dirname, "..");
}

function electronPidFile() {
  return path.join(appRoot(), ".aki_electron.pid");
}

function writeElectronPid() {
  try {
    fs.writeFileSync(electronPidFile(), String(process.pid), "utf8");
  } catch (e) {
    console.error("[electron pid]", e);
  }
}

function clearElectronPid() {
  try {
    fs.unlinkSync(electronPidFile());
  } catch {
    /* yok */
  }
}

function resolveAsset(...parts) {
  const candidates = [
    path.join(appRoot(), "assets", ...parts),
    path.join(__dirname, "..", "assets", ...parts),
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  return null;
}

function appIcon() {
  const ico = resolveAsset("akifactory.ico");
  if (ico) return nativeImage.createFromPath(ico);
  const png = resolveAsset("akifactory-256.png");
  if (png) return nativeImage.createFromPath(png);
  return undefined;
}

function notificationIconPath() {
  return resolveAsset("akifactory-256.png") || resolveAsset("akifactory.ico");
}

function backendScript() {
  return path.join(appRoot(), "scripts", "run_backend.py");
}

let backendProc = null;
let splashWindow = null;
let mainWindow = null;
let serverBase = "";

function pythonExe() {
  const venvPy = path.join(appRoot(), ".venv", "Scripts", "python.exe");
  if (fs.existsSync(venvPy)) return venvPy;
  return "python";
}

// venv Scripts/python.exe kucuk bir yonlendiricidir; pyvenv.cfg icindeki
// taban Python yolu bu PC'de gecerli degilse "kod 103" ile aninda kapanir.
// Python baslatilmadan ONCE pyvenv.cfg'yi paketteki python-base'e cevir.
function fixPyvenvCfg() {
  try {
    const base = path.join(appRoot(), "python-base");
    const basePy = path.join(base, "python.exe");
    const cfg = path.join(appRoot(), ".venv", "pyvenv.cfg");
    if (!fs.existsSync(basePy) || !fs.existsSync(cfg)) return;

    const lines = fs.readFileSync(cfg, "utf8").split(/\r?\n/);
    let changed = false;
    const out = lines.map((line) => {
      if (/^home\s*=/.test(line)) {
        const next = `home = ${base}`;
        if (line !== next) changed = true;
        return next;
      }
      if (/^executable\s*=/.test(line)) {
        const next = `executable = ${basePy}`;
        if (line !== next) changed = true;
        return next;
      }
      if (/^command\s*=/.test(line)) {
        // Eski PC yolu kalintisi — sessizce temizle
        changed = true;
        return `command = ${basePy} -m venv`;
      }
      return line;
    });
    if (changed) {
      fs.writeFileSync(cfg, out.join("\n") + "\n", "utf8");
    }
  } catch (e) {
    console.error("[pyvenv fix]", e);
    try {
      dialog.showErrorBox(
        "AkiFactory — Python path",
        "Could not update pyvenv.cfg. The install folder may not be writable.\n" +
          "Fix: install the app in your user folder (not Program Files) or run it as administrator.\n\n" +
          String(e && e.message ? e.message : e)
      );
    } catch (_) {
      /* splash oncesi dialog bazen yok */
    }
  }
}

function pythonEnv() {
  // PYTHONHOME ayarlama! venv redirector'i pyvenv.cfg'ye guvenir; PYTHONHOME
  // set edilirse venv site-packages devre disi kalir ve importlar kirilir.
  const env = {
    ...process.env,
    AKI_ELECTRON: "1",
    AKI_PACKAGED: app.isPackaged ? "1" : "0",
    PYTHONIOENCODING: "utf-8",
  };
  // Paketli kurulum: yazilabilir kullanici verisi (Program Files sorununu onler).
  // Gelistirmede proje data/ kullanilsin — AKI_DATA_DIR zorlanmaz.
  if (app.isPackaged) {
    const local =
      process.env.LOCALAPPDATA || process.env.APPDATA || "";
    const dataDir = local
      ? path.join(local, "AkiFactory", "data")
      : path.join(appRoot(), "data");
    try {
      fs.mkdirSync(dataDir, { recursive: true });
    } catch (_) {
      /* ignore */
    }
    env.AKI_DATA_DIR = dataDir;
  }
  return env;
}

function createSplash() {
  const icon = appIcon();
  splashWindow = new BrowserWindow({
    width: 520,
    height: 430,
    frame: false,
    resizable: false,
    center: true,
    show: true,
    icon,
    backgroundColor: "#0a0a0c",
    webPreferences: {
      preload: path.join(__dirname, "splash-preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  splashWindow.loadFile(path.join(__dirname, "splash.html"));
}

async function createMain(url) {
  const icon = appIcon();
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 960,
    minHeight: 640,
    title: "AkiFactory — Akiyom",
    icon,
    show: false,
    autoHideMenuBar: true,
    backgroundColor: "#0a0a0c",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.once("ready-to-show", () => {
    if (splashWindow && !splashWindow.isDestroyed()) {
      splashWindow.close();
      splashWindow = null;
    }
    mainWindow.maximize();
    mainWindow.show();
    mainWindow.focus();
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  mainWindow.on("focus", () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send("window-focus-changed", true);
    }
  });
  mainWindow.on("blur", () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send("window-focus-changed", false);
    }
  });

  // Her acilista Electron HTTP onbellegini temizle — bat ile guncelleme gorunsun
  try {
    await session.defaultSession.clearCache();
  } catch (e) {
    console.warn("[cache]", e);
  }
  const sep = url.includes("?") ? "&" : "?";
  mainWindow.loadURL(`${url}${sep}_boot=${Date.now()}`);
}

function parseBackendLine(line) {
  const trimmed = line.trim();
  if (!trimmed) return null;
  if (trimmed.startsWith("AKI_PROGRESS ")) {
    return { type: "progress", data: JSON.parse(trimmed.slice(13)) };
  }
  if (trimmed.startsWith("AKI_READY ")) {
    return { type: "ready", data: JSON.parse(trimmed.slice(10)) };
  }
  if (trimmed.startsWith("AKI_ERROR ")) {
    return { type: "error", data: JSON.parse(trimmed.slice(10)) };
  }
  return null;
}

function sendSplashProgress(data) {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.webContents.send("boot-progress", data);
  }
}

function spawnBackendProcess() {
  const script = backendScript();
  if (!fs.existsSync(script)) {
    throw new Error(`Backend script not found: ${script}`);
  }
  fixPyvenvCfg();
  return spawn(pythonExe(), ["-u", script], {
    cwd: appRoot(),
    env: pythonEnv(),
    windowsHide: true,
  });
}

function wireBackendProcess(proc, { onReady, onFail, allowRestart = false }) {
  let settled = !onReady;
  let buffer = "";

  const fail = (err) => {
    if (settled) return;
    settled = true;
    onFail(err instanceof Error ? err : new Error(String(err)));
  };

  const onStdout = (chunk) => {
    buffer += chunk.toString("utf8");
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() || "";
    for (const line of lines) {
      let parsed;
      try {
        parsed = parseBackendLine(line);
      } catch (e) {
        console.error("[backend parse]", line, e);
        continue;
      }
      if (!parsed) continue;
      if (parsed.type === "progress") {
        sendSplashProgress(parsed.data);
      } else if (parsed.type === "ready") {
        if (!settled && onReady) {
          settled = true;
          backendReadyData = parsed.data;
          backendAutoRestartCount = 0;
          onReady(parsed.data);
        }
      } else if (parsed.type === "error") {
        lastBackendError = parsed.data?.error || lastBackendError;
        fail(new Error(parsed.data?.error || "Baslangic basarisiz"));
      }
    }
  };

  proc.stdout.on("data", onStdout);
  proc.stderr.on("data", (d) => {
    const text = d.toString("utf8").trim();
    if (text) console.error("[backend]", text);
  });
  proc.on("error", fail);
  proc.on("exit", (code) => {
    const tryRestart = () => {
      if (appShuttingDown || !allowRestart) return false;
      if (!mainWindow || mainWindow.isDestroyed()) return false;
      if (backendAutoRestartCount >= BACKEND_AUTO_RESTART_MAX) {
        dialog.showErrorBox(
          "AkiFactory",
          lastBackendError ||
            "The background engine could not be restarted. Close the window and start AkiFactory again."
        );
        app.quit();
        return true;
      }
      backendAutoRestartCount += 1;
      settled = false;
      console.warn(`[backend] Restarting (${backendAutoRestartCount}/${BACKEND_AUTO_RESTART_MAX})…`);
      if (backendRestartTimer) clearTimeout(backendRestartTimer);
      backendRestartTimer = setTimeout(() => {
        backendRestartTimer = null;
        // Zamanlayici ateslendiginde pencere / quit durumunu tekrar kontrol et
        if (appShuttingDown || !mainWindow || mainWindow.isDestroyed()) return;
        try {
          backendProc = spawnBackendProcess();
          wireBackendProcess(backendProc, {
            onReady: (data) => {
              serverBase = `http://${data.ui_host}:${data.ui_port}`;
              if (mainWindow && !mainWindow.isDestroyed()) {
                mainWindow.webContents.reload();
              }
            },
            onFail: () => {},
            allowRestart: true,
          });
        } catch (e) {
          dialog.showErrorBox("AkiFactory", e.message || String(e));
          app.quit();
        }
      }, 2500);
      return true;
    };

    if (!settled) {
      if (tryRestart()) return;
      fail(new Error(`Python backend beklenmedik sekilde kapandi (kod ${code}).`));
      return;
    }
    tryRestart();
  });
}

function startBackend() {
  return new Promise((resolve, reject) => {
    try {
      backendProc = spawnBackendProcess();
    } catch (e) {
      reject(e);
      return;
    }
    wireBackendProcess(backendProc, {
      onReady: resolve,
      onFail: reject,
      allowRestart: true,
    });
  });
}

function waitForHttp(url, timeoutMs = 90000) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;
    const tick = () => {
      const req = http.get(url, (res) => {
        res.resume();
        resolve(true);
      });
      req.on("error", () => {
        if (Date.now() > deadline) {
          reject(new Error(`Arayuz acilmadi: ${url}`));
          return;
        }
        setTimeout(tick, 300);
      });
      req.setTimeout(2000, () => {
        req.destroy();
      });
    };
    tick();
  });
}

function postJson(url, body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const u = new URL(url);
    const req = http.request(
      {
        hostname: u.hostname,
        port: u.port,
        path: u.pathname,
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(data),
        },
      },
      (res) => {
        let raw = "";
        res.on("data", (c) => {
          raw += c;
        });
        res.on("end", () => {
          try {
            resolve({ status: res.statusCode, data: raw ? JSON.parse(raw) : {} });
          } catch {
            resolve({ status: res.statusCode, data: { raw } });
          }
        });
      }
    );
    req.on("error", reject);
    req.write(data);
    req.end();
  });
}

function readPidFile(name) {
  try {
    const p = path.join(appRoot(), name);
    if (!fs.existsSync(p)) return 0;
    const n = parseInt(fs.readFileSync(p, "utf8").trim(), 10);
    return Number.isFinite(n) && n > 0 ? n : 0;
  } catch {
    return 0;
  }
}

function killPidTree(pid) {
  if (!pid || pid <= 0) return;
  try {
    if (process.platform === "win32") {
      // Senkron: Electron cikmadan once agac kapansin (eski spawn async yetim birakiyordu)
      spawnSync("taskkill", ["/pid", String(pid), "/f", "/t"], {
        windowsHide: true,
        timeout: 20000,
      });
    } else {
      try {
        process.kill(pid, "SIGTERM");
      } catch {
        /* already gone */
      }
    }
  } catch (e) {
    console.error("[backend stop]", pid, e);
  }
}

function stopBackend() {
  appShuttingDown = true;
  if (backendRestartTimer) {
    clearTimeout(backendRestartTimer);
    backendRestartTimer = null;
  }

  const pids = new Set();
  if (backendProc && backendProc.pid) pids.add(backendProc.pid);
  for (const name of [".aki_pid", ".aki_engine_pid"]) {
    const pid = readPidFile(name);
    if (pid) pids.add(pid);
  }

  for (const pid of pids) {
    killPidTree(pid);
  }

  backendProc = null;

  for (const name of [".aki_pid", ".aki_engine_pid", ".aki_ui_port", ".aki_electron.pid"]) {
    try {
      fs.unlinkSync(path.join(appRoot(), name));
    } catch {
      /* ignore */
    }
  }
}

ipcMain.handle("save-video", async (_evt, url, defaultName) => {
  if (!serverBase) return { ok: false, error: "Server is not ready" };
  const name = defaultName || "akifactory.mp4";
  const { canceled, filePath } = await dialog.showSaveDialog(mainWindow, {
    defaultPath: name,
    filters: [{ name: "MP4 Video", extensions: ["mp4"] }],
  });
  if (canceled || !filePath) return { ok: false, cancelled: true };

  try {
    const resolved = await postJson(`${serverBase}/api/desktop/resolve-video`, { url });
    if (resolved.status === 200 && resolved.data?.path) {
      await fs.promises.copyFile(resolved.data.path, filePath);
      return { ok: true, path: filePath };
    }
  } catch {
    /* fetch fallback */
  }

  const fullUrl = url.startsWith("http") ? url : `${serverBase}${url}`;
  const res = await fetch(fullUrl);
  if (!res.ok) throw new Error("Video indirilemedi");
  const buf = Buffer.from(await res.arrayBuffer());
  await fs.promises.writeFile(filePath, buf);
  return { ok: true, path: filePath };
});

ipcMain.handle("open-assets-folder", async (_evt, section) => {
  if (!serverBase) return { ok: false, error: "Server is not ready" };
  const r = await postJson(`${serverBase}/api/settings/open-folder`, { section });
  if (r.status >= 400) {
    return { ok: false, error: r.data?.detail || "Klasor acilamadi" };
  }
  return { ok: true, section };
});

ipcMain.handle("is-window-focused", () => {
  if (!mainWindow || mainWindow.isDestroyed()) return false;
  return mainWindow.isFocused() && !mainWindow.isMinimized();
});

ipcMain.handle("show-notification", (_evt, payload) => {
  const title = String(payload?.title || "AkiFactory").slice(0, 120);
  const body = String(payload?.body || "").slice(0, 280);
  if (!title || !body) return { ok: false, error: "Bos bildirim" };
  if (!Notification.isSupported()) return { ok: false, error: "Desteklenmiyor" };
  try {
    const icon = notificationIconPath();
    const n = new Notification({
      title,
      body,
      icon: icon || undefined,
      silent: false,
    });
    n.on("click", () => {
      if (!mainWindow || mainWindow.isDestroyed()) return;
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    });
    n.show();
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e.message || String(e) };
  }
});

app.whenReady().then(async () => {
  if (!gotSingleInstanceLock) return;
  writeElectronPid();
  if (process.platform === "win32") {
    app.setAppUserModelId(APP_ID);
  }
  createSplash();
  try {
    const ready = await startBackend();
    serverBase = `http://${ready.ui_host}:${ready.ui_port}`;
    await waitForHttp(serverBase);
    await createMain(serverBase);
    for (const w of ready.warnings || []) {
      console.warn("[uyari]", w);
    }
  } catch (e) {
    if (splashWindow && !splashWindow.isDestroyed()) splashWindow.close();
    dialog.showErrorBox("AkiFactory — Failed to start", e.message || String(e));
    stopBackend();
    app.quit();
  }
});

app.on("window-all-closed", () => {
  appShuttingDown = true;
  stopBackend();
  clearElectronPid();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  appShuttingDown = true;
  // once daha: cikis sirasinda motor yeniden dogmasin
  if (backendRestartTimer) {
    clearTimeout(backendRestartTimer);
    backendRestartTimer = null;
  }
  stopBackend();
  clearElectronPid();
});
