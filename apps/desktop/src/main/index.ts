import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { appendFile, mkdir, rename, stat, unlink } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {
  app,
  autoUpdater,
  BrowserWindow,
  dialog,
  ipcMain,
  Menu,
  nativeImage,
  Notification,
  powerMonitor,
  protocol,
  safeStorage,
  shell,
  Tray,
} from "electron";
import { ActivityMonitor } from "./activity";
import { WindowLifecycle } from "./background";
import { BootstrapStore } from "./bootstrap";
import { buildConfigRedactions, loadBuildConfig, sidecarRuntimeEnvironment } from "./build-config";
import { argumentsFromAdditionalData, DEEP_LINK_SCHEME, userArguments } from "./deep-links";
import { provisionDeviceWrappingKey } from "./device-key";
import { createStrings, MainStrings } from "./i18n";
import { registerIpcHandlers } from "./ipc";
import { LaunchRouter } from "./launch-router";
import { LoginItemController } from "./login-items";
import { DesktopNotifier } from "./notifications";
import { PdfSaver } from "./pdf";
import { PowerReporter } from "./power";
import { DesktopStateStore } from "./preferences";
import { registerBentoProtocol } from "./protocol";
import { RedactingLog } from "./redaction";
import { RendererEventQueue } from "./renderer-events";
import { LEGACY_SECRET_SETTING_KEYS, SecureSecretStore } from "./secrets";
import { SendToUploader } from "./send-to";
import { SettingsTransaction } from "./settings-transaction";
import { resolveSidecarCommand, SidecarSupervisor } from "./sidecars";
import { handleSquirrelEvent, squirrelEvent, squirrelStubExecutable, squirrelUpdateExecutable } from "./squirrel";
import { TrayController, trayModel } from "./tray";
import { UpdateScheduler } from "./update-scheduler";
import { prepareForUpdateInstall, UpdateController } from "./updater";
import { createMainWindow, lockDownSession } from "./window";
import { BENTO_ORIGIN, DeepLink, DesktopPreferences, DesktopPreferencesPatch, IPC_CHANNELS, NavigateRequest, PlatformMetadata } from "../shared/contracts";

protocol.registerSchemesAsPrivileged([{
  scheme: "bento",
  privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true, corsEnabled: false },
}]);

const smoke = process.env.BENTO_DESKTOP_SMOKE === "1";
const defaultApp = Boolean(process.defaultApp);
const launchArguments = userArguments(process.argv, defaultApp);
const squirrel = squirrelEvent(process.argv, process.platform);
const squirrelInstalled = process.platform === "win32" && app.isPackaged && existsSync(squirrelUpdateExecutable(process.execPath));
const launches = new LaunchRouter();
const deepLinks = new RendererEventQueue<DeepLink>(IPC_CHANNELS.deepLinkReceived);
const navigation = new RendererEventQueue<NavigateRequest>(IPC_CHANNELS.navigateRequested);
// Spanish until the OS locale can be read after `ready`.
let strings: MainStrings = createStrings([]);
let mainWindow: BrowserWindow | null = null;
let supervisor: SidecarSupervisor | null = null;
let windowLifecycle: WindowLifecycle | null = null;
let quitting = false;
let startHidden = false;

if (squirrel && squirrel !== "firstrun") {
  // Squirrel install/update/uninstall launches only adjust shortcuts and registrations, then quit.
  void app.whenReady()
    .then(() => handleSquirrelEvent(squirrel, {
      execPath: process.execPath,
      appDataDirectory: app.getPath("appData"),
      description: createStrings(app.getPreferredSystemLanguages()).language === "en" ? "Send to Bento" : "Enviar a Bento",
      runUpdate: (args) => runSquirrelUpdate(args),
      writeShortcutLink: (shortcutPath, operation, options) => shell.writeShortcutLink(shortcutPath, operation, options),
      removeFile: (filePath) => unlink(filePath),
      removeLoginItem: (stub) => app.setLoginItemSettings({ openAtLogin: false, path: stub, args: ["--hidden"] }),
      removeProtocolClient: (stub) => { app.removeAsDefaultProtocolClient(DEEP_LINK_SCHEME, stub, []); },
    }))
    .catch(() => true)
    .finally(() => app.quit());
} else if (!app.requestSingleInstanceLock({ bento: 1, args: launchArguments })) {
  app.quit();
} else {
  // macOS delivers URLs and files through events that can fire before `ready`.
  app.on("open-url", (event, url) => {
    event.preventDefault();
    launches.deepLink(url);
  });
  app.on("open-file", (event, filePath) => {
    event.preventDefault();
    launches.openFile(filePath);
  });
  app.on("second-instance", (_event, argv, _workingDirectory, additionalData) => {
    const request = launches.arguments(argumentsFromAdditionalData(additionalData) ?? userArguments(argv, defaultApp));
    // A plain relaunch focuses Bento; Send-to hand-offs and hidden starts stay in the background.
    if (!request.hidden && !request.deepLinks.length && !request.files.length) showMainWindow();
  });
  app.on("activate", () => showMainWindow());
  app.on("before-quit", (event) => {
    if (quitting || !supervisor) {
      quitting = true;
      return;
    }
    event.preventDefault();
    quitting = true;
    void supervisor.stop().finally(() => app.exit(0));
  });
  app.on("window-all-closed", () => app.quit());
  startHidden = launches.arguments(launchArguments).hidden;
  void app.whenReady().then(startDesktop).catch(async (error) => {
    await showRecovery(error);
  });
}

async function startDesktop(): Promise<void> {
  app.setAppLogsPath();
  if (process.platform === "win32" && app.isPackaged) app.setAppUserModelId("com.squirrel.bento.bento");
  strings = createStrings(app.getPreferredSystemLanguages());
  const userData = app.getPath("userData");
  const desktopData = path.join(userData, "bento-desktop");
  const logPath = path.join(app.getPath("logs"), "desktop.jsonl");
  await prepareLog(logPath);
  const knownSecrets: string[] = [];
  // The per-launch API tokens are redacted too, even though only main and the API ever hold them.
  const log = new RedactingLog(
    (line) => { void appendFile(logPath, `${line}\n`, { encoding: "utf8", mode: 0o600 }); },
    () => [...knownSecrets, ...(supervisor?.redactionValues() ?? [])],
  );
  const state = new DesktopStateStore(path.join(desktopData, "preferences.json"));
  if ((await state.load()).recovered) log.write("warn", "desktop preferences were reset to defaults");
  const bootstrapStore = new BootstrapStore(path.join(desktopData, "bootstrap.json"), path.join(userData, "bento-data"));
  const bootstrap = await bootstrapStore.load();
  const secretStore = new SecureSecretStore(path.join(desktopData, "secrets.json"), safeStorage);
  const removedLegacy = await secretStore.removeSecrets(LEGACY_SECRET_SETTING_KEYS);
  if (removedLegacy) log.write("info", "removed legacy Bot API secrets", { count: removedLegacy });
  const secretValues = await secretStore.values();
  knownSecrets.push(...Object.values(secretValues));
  const buildConfig = await loadBuildConfig({ packaged: app.isPackaged, resourcesPath: process.resourcesPath, environment: process.env });
  if (buildConfig.rejected.length) log.write("warn", "ignored invalid build configuration", { keys: buildConfig.rejected });
  knownSecrets.push(...buildConfigRedactions(buildConfig.config));
  const deviceKey = await provisionDeviceWrappingKey({ store: secretStore, dataDir: bootstrap.dataDir });
  if (deviceKey.key) knownSecrets.push(deviceKey.key);
  log.write("info", "device key store", { secureStorage: deviceKey.secureStorage, generated: deviceKey.generated });
  const runtimeEnvironment = sidecarRuntimeEnvironment({ packaged: app.isPackaged, buildConfig: buildConfig.config, environment: process.env });
  supervisor = new SidecarSupervisor({
    command: resolveSidecarCommand(process.resourcesPath, app.isPackaged, path.resolve(app.getAppPath(), "../api")),
    dataDir: bootstrap.dataDir,
    secretEnvironment: secretValues,
    runtimeEnvironment: runtimeEnvironment.set,
    strippedEnvironment: runtimeEnvironment.strip,
    deviceWrappingKey: deviceKey.key,
    log,
  });
  const sidecars = supervisor;
  registerBentoProtocol(protocol, path.join(app.getAppPath(), "dist", "renderer"), sidecars);
  lockDownSession();
  await sidecars.start();
  const transaction = new SettingsTransaction(sidecars, secretStore, bootstrapStore, bootstrap);
  const updates = new UpdateController({
    currentVersion: app.getVersion(),
    platform: process.platform,
    arch: process.arch,
    isPackaged: app.isPackaged,
    stagingRoot: path.join(desktopData, "updates"),
    autoUpdater,
    openPath: (filePath) => shell.openPath(filePath),
    beforeInstall: () => prepareForUpdateInstall(() => { quitting = true; }, () => sidecars.stop()),
    recoverAfterInstallFailure: async () => {
      quitting = false;
      await sidecars.start();
    },
  });
  const scheduler = app.isPackaged && !smoke
    ? new UpdateScheduler({ updates, autoDownload: () => state.preferences.autoDownloadUpdates })
    : null;
  const loginItems = new LoginItemController({
    platform: process.platform,
    packaged: app.isPackaged && !smoke,
    execPath: process.execPath,
    environment: process.env,
    homeDirectory: os.homedir(),
    app,
    squirrelInstalled,
  });
  startHidden ||= loginItems.launchedHidden(launchArguments);

  const trayRoot = app.isPackaged ? path.join(process.resourcesPath, "tray") : path.join(app.getAppPath(), "resources", "tray");
  const activity = new ActivityMonitor({ client: sidecars, isReady: () => sidecars.status.state === "ready" });
  const power = new PowerReporter({ monitor: powerMonitor, client: sidecars, isReady: () => sidecars.status.state === "ready" });
  const notifier = new DesktopNotifier({
    platform: process.platform,
    strings,
    supported: () => Notification.isSupported(),
    create: (options) => new Notification(options),
    memory: state,
    activate: (request) => {
      showMainWindow();
      if (request) navigation.push(request);
    },
    quiet: () => Boolean(mainWindow && !mainWindow.isDestroyed() && mainWindow.isVisible() && mainWindow.isFocused()),
    icon: process.platform === "linux" ? path.join(trayRoot, "notification.png") : undefined,
  });
  windowLifecycle = new WindowLifecycle({
    platform: process.platform,
    dock: app.dock,
    keepRunningInBackground: () => state.preferences.keepRunningInBackground,
    isQuitting: () => quitting,
    onHiddenToBackground: () => { void notifier.backgroundNotice().catch(() => undefined); },
  });
  let tray: TrayController | null = null;
  const refreshTray = (): void => {
    try {
      tray?.render(trayModel({ lifecycle: sidecars.status.state, activity: activity.state, update: updates.state }, strings));
    } catch (error) {
      log.write("warn", "tray update failed", { error: String(error) });
    }
  };
  try {
    tray = new TrayController({
      platform: process.platform,
      iconRoot: trayRoot,
      strings,
      createTray: (image) => new Tray(image as Electron.NativeImage),
      loadImage: (filePath) => nativeImage.createFromPath(filePath),
      buildMenu: (template) => Menu.buildFromTemplate(template),
      actions: {
        open: () => showMainWindow(),
        setBackupPaused: (paused) => { void activity.setPaused(paused).then(refreshTray); },
        installUpdate: () => { void updates.install().catch(() => undefined); },
        quit: () => app.quit(),
      },
    });
    refreshTray();
  } catch (error) {
    tray = null;
    log.write("warn", "tray unavailable", { error: String(error) });
  }

  sidecars.on("status", (status) => {
    mainWindow?.webContents.send(IPC_CHANNELS.lifecycleChanged, status);
    refreshTray();
    if (status.state === "ready") {
      void power.apiRestarted();
      void activity.refresh();
    }
  });
  updates.on("state", (updateState) => {
    mainWindow?.webContents.send(IPC_CHANNELS.updatesChanged, updateState);
    refreshTray();
  });
  activity.on("state", (activityState: ActivityMonitor["state"]) => {
    refreshTray();
    void notifier.attention(activityState.activity?.attention ?? []).catch(() => undefined);
  });
  powerMonitor.on("suspend", () => activity.suspend());
  powerMonitor.on("resume", () => {
    activity.resume();
    void power.report();
  });
  // OS shutdown/reboot (Linux/macOS): stop sidecars through the normal quit path.
  powerMonitor.on("shutdown", () => app.quit());

  const pdf = new PdfSaver({
    window: () => mainWindow,
    documentsDirectory: () => app.getPath("documents"),
    defaultFileName: strings.pdf.defaultFileName,
    dialogTitle: strings.pdf.dialogTitle,
    filterName: strings.pdf.filterName,
    showSaveDialog: (window, options) => dialog.showSaveDialog(window as BrowserWindow, options),
  });
  const preferences = {
    get: (): DesktopPreferences => state.preferences,
    set: async (patch: DesktopPreferencesPatch): Promise<DesktopPreferences> => {
      const next = await state.updatePreferences(patch, async (candidate, previous) => {
        if (candidate.launchAtLogin === previous.launchAtLogin) return;
        try {
          await loginItems.apply(candidate.launchAtLogin);
        } catch {
          throw new Error("preferences_launch_at_login_failed");
        }
      });
      if (patch.autoDownloadUpdates !== undefined) void scheduler?.autoDownloadChanged();
      return next;
    },
  };
  registerIpcHandlers({
    ipcMain,
    window: () => mainWindow,
    lifecycleStatus: () => sidecars.status,
    platform: async (): Promise<PlatformMetadata> => ({
      desktop: true,
      platform: process.platform,
      arch: process.arch,
      version: app.getVersion(),
      secureStorage: deviceKey.secureStorage,
      locale: strings.locale,
      recoveryMode: sidecars.status.recoveryMode,
    }),
    applySettings: (request, progress) => transaction.apply(request, progress),
    runProbe: (request) => sidecars.runProbe(request),
    updates,
    preferences,
    deepLinks,
    navigation,
    savePageAsPdf: (event, request) => pdf.save(event, request),
  });

  mainWindow = createMainWindow({ showOnReady: !startHidden });
  attachMainWindow(mainWindow);
  if (startHidden && process.platform === "darwin") app.dock?.hide();

  const uploader = new SendToUploader({
    client: sidecars,
    waitUntilReady: () => sidecars.waitUntilReady(),
    onComplete: (summary) => notifier.sendToSummary(summary),
    log,
  });
  launches.attach({
    deepLink: (link) => {
      deepLinks.push(link);
      showMainWindow();
    },
    rejectedDeepLink: () => log.write("warn", "rejected deep link"),
    files: (paths) => { void uploader.enqueue(paths); },
  });

  activity.start();
  power.start();
  void updates.initialize();
  void scheduler?.start();
  if (app.isPackaged && !smoke) {
    registerProtocolClient();
    if (state.preferences.launchAtLogin) {
      // Re-register so the login item follows the current executable (updates, AppImage moves).
      void loginItems.apply(true).catch(() => log.write("warn", "launch at login could not be refreshed"));
    }
  }
  if (smoke) {
    mainWindow.webContents.once("did-finish-load", () => setTimeout(() => app.quit(), 250));
  }
}

function attachMainWindow(window: BrowserWindow): void {
  windowLifecycle?.attach(window);
  window.webContents.on("did-start-navigation", (details) => {
    // A new document must subscribe again; until then events stay buffered.
    if (details.isMainFrame && !details.isSameDocument) {
      deepLinks.reset();
      navigation.reset();
    }
  });
  window.webContents.on("render-process-gone", () => {
    deepLinks.reset();
    navigation.reset();
  });
  window.on("session-end", () => app.quit());
  window.on("closed", () => {
    if (mainWindow === window) mainWindow = null;
  });
}

function showMainWindow(): void {
  if (!mainWindow || mainWindow.isDestroyed()) {
    if (!supervisor || !windowLifecycle) return;
    mainWindow = createMainWindow();
    attachMainWindow(mainWindow);
  }
  windowLifecycle?.show(mainWindow);
}

function registerProtocolClient(): void {
  try {
    if (process.platform === "win32") {
      app.setAsDefaultProtocolClient(DEEP_LINK_SCHEME, squirrelInstalled ? squirrelStubExecutable(process.execPath) : process.execPath, []);
    } else {
      app.setAsDefaultProtocolClient(DEEP_LINK_SCHEME);
    }
  } catch {
    // Registration is best effort; packaged metadata (Info.plist, .desktop MimeType) also declares the scheme.
  }
}

function runSquirrelUpdate(args: string[]): Promise<void> {
  return new Promise((resolve) => {
    const child = spawn(squirrelUpdateExecutable(process.execPath), args, { detached: true, stdio: "ignore" });
    const timeout = setTimeout(resolve, 10_000);
    child.once("error", () => { clearTimeout(timeout); resolve(); });
    child.once("close", () => { clearTimeout(timeout); resolve(); });
  });
}

async function showRecovery(error: unknown): Promise<void> {
  const message = error instanceof Error ? error.message : "Desktop startup failed";
  if (smoke) {
    console.error(`Bento packaged smoke startup failed: ${safeDiagnostic(message)}`);
    app.exit(1);
    return;
  }
  try {
    if (protocol.isProtocolHandled("bento")) protocol.unhandle("bento");
    protocol.handle("bento", () => new Response(recoveryHtml(safeDiagnostic(message)), {
      headers: {
        "content-type": "text/html; charset=utf-8",
        "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'",
      },
    }));
    lockDownSession();
    mainWindow = new BrowserWindow({
      width: 720,
      height: 480,
      title: "Bento — Recuperación",
      webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false, webSecurity: true },
    });
    mainWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    await mainWindow.loadURL(`${BENTO_ORIGIN}/recovery`);
  } catch {
    app.exit(1);
  }
}

function recoveryHtml(diagnostic: string): string {
  return `<!doctype html><html lang="es"><meta charset="utf-8"><title>Bento — Recuperación</title><style>:root{color-scheme:light dark}body{font:15px/1.6 system-ui,sans-serif;background:light-dark(#f5f2ee,#0c0e15);color:light-dark(#221d18,#eff0f4);margin:0;padding:56px 48px;max-width:680px}h1{font-size:22px;letter-spacing:-.02em;margin:24px 0 8px}p{color:light-dark(#655f59,#a5a9b2);margin:0 0 24px}code{display:block;padding:16px;background:light-dark(#fff,#1b1e26);border:1px solid light-dark(#e2dfdb,#272a32);border-radius:14px;font:13px/1.5 ui-monospace,monospace;overflow-wrap:anywhere}</style><svg width="40" height="40" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="9" style="fill:light-dark(#221d18,#eff0f4)"/><rect x="4.5" y="5" width="10.5" height="22" rx="3.5" style="fill:light-dark(#f5f2ee,#0c0e15)"/><rect x="17" y="5" width="10.5" height="10" rx="3.5" style="fill:light-dark(#f5f2ee,#0c0e15)"/><rect x="17" y="17" width="10.5" height="10" rx="3.5" style="fill:light-dark(#f5f2ee,#0c0e15)"/><circle cx="22.25" cy="22" r="2.75" fill="#e94f13"/></svg><h1>Bento no pudo iniciar</h1><p>Tus datos permanecen en el equipo. Revisa el diagnóstico seguro y vuelve a abrir la aplicación.</p><code>${escapeHtml(diagnostic)}</code></html>`;
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/gu, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" })[character]!);
}

function safeDiagnostic(message: string): string {
  return message
    .replace(/Bearer\s+\S+/giu, "Bearer [REDACTED]")
    .replace(/([?&](?:token|secret|password)=)[^&\s]+/giu, "$1[REDACTED]")
    .slice(0, 500);
}

async function prepareLog(filePath: string): Promise<void> {
  await mkdir(path.dirname(filePath), { recursive: true, mode: 0o700 });
  try {
    if ((await stat(filePath)).size > 5 * 1024 * 1024) await rename(filePath, `${filePath}.1`);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
}
