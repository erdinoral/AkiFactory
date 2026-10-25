/**
 * Electron binary onarimi — npm postinstall bazen Windows'ta yarim kalir.
 * electron.exe yoksa cache zip'ten PowerShell ile cikarir.
 */
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const electronDir = path.join(__dirname, "node_modules", "electron");
const distDir = path.join(electronDir, "dist");
const pkg = require(path.join(electronDir, "package.json"));
const version = pkg.version;
const platformExe =
  process.platform === "win32"
    ? "electron.exe"
    : process.platform === "darwin"
      ? path.join("Electron.app", "Contents", "MacOS", "Electron")
      : "electron";
const exePath = path.join(distDir, platformExe);

function log(msg) {
  console.log(`[electron-repair] ${msg}`);
}

function writeMarkers() {
  fs.mkdirSync(distDir, { recursive: true });
  fs.writeFileSync(path.join(electronDir, "path.txt"), platformExe.replace(/\\/g, "/"));
  fs.writeFileSync(path.join(distDir, "version"), `v${version}`);
}

function isOk() {
  return fs.existsSync(exePath);
}

function findCachedZip() {
  const cacheRoot = path.join(process.env.LOCALAPPDATA || "", "electron", "Cache");
  if (!fs.existsSync(cacheRoot)) return null;
  const target = `electron-v${version}-win32-x64.zip`;
  const stack = [cacheRoot];
  while (stack.length) {
    const dir = stack.pop();
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const ent of entries) {
      const full = path.join(dir, ent.name);
      if (ent.isDirectory()) stack.push(full);
      else if (ent.isFile() && ent.name === target) return full;
    }
  }
  return null;
}

function extractWithPowerShell(zipPath) {
  log(`Zip aciliyor: ${zipPath}`);
  fs.rmSync(distDir, { recursive: true, force: true });
  fs.mkdirSync(distDir, { recursive: true });
  const dest = distDir.replace(/'/g, "''");
  const zip = zipPath.replace(/'/g, "''");
  execSync(
    `powershell -NoProfile -Command "Expand-Archive -LiteralPath '${zip}' -DestinationPath '${dest}' -Force"`,
    { stdio: "inherit" }
  );
}

function runInstallJs() {
  try {
    process.env.force_no_cache = "true";
    require(path.join(electronDir, "install.js"));
  } catch (err) {
    log(`install.js uyarisi: ${err.message || err}`);
  }
}

function main() {
  if (!fs.existsSync(electronDir)) {
    console.error("[electron-repair] node_modules/electron yok — once npm install calistirin.");
    process.exit(1);
  }

  if (isOk()) {
    writeMarkers();
    log("electron.exe hazir.");
    return;
  }

  log("electron.exe eksik — onarim basliyor...");
  runInstallJs();
  if (isOk()) {
    writeMarkers();
    log("install.js ile tamamlandi.");
    return;
  }

  if (process.platform === "win32") {
    const zip = findCachedZip();
    if (!zip) {
      console.error(
        "[electron-repair] Electron zip bulunamadi. Internet acikken:\n" +
          "  cd electron\n" +
          "  npm.cmd install\n"
      );
      process.exit(1);
    }
    extractWithPowerShell(zip);
    if (!isOk()) {
      console.error("[electron-repair] Zip acildi ama electron.exe yok.");
      process.exit(1);
    }
    writeMarkers();
    log("PowerShell ile tamamlandi.");
    return;
  }

  console.error("[electron-repair] Platform onarimi desteklenmiyor.");
  process.exit(1);
}

main();
