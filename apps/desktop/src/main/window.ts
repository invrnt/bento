import { BrowserWindow, nativeTheme, session } from "electron";
import path from "node:path";
import { BENTO_ORIGIN } from "../shared/contracts";
import { isAllowedNavigation } from "./protocol";

export interface WindowOptions {
  preloadPath?: string;
  recoveryMode?: boolean;
  /** False for `--hidden`/login starts: the renderer loads but the window stays in the tray. */
  showOnReady?: boolean;
}

export function createMainWindow(options: WindowOptions = {}): BrowserWindow {
  const window = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 880,
    minHeight: 640,
    show: false,
    // Matches the Bento tray token so the first frame never flashes.
    backgroundColor: nativeTheme.shouldUseDarkColors ? "#0c0e15" : "#f5f2ee",
    title: "Bento",
    webPreferences: {
      preload: options.preloadPath ?? path.join(__dirname, "../preload/index.js"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      nodeIntegrationInWorker: false,
      webSecurity: true,
      allowRunningInsecureContent: false,
      experimentalFeatures: false,
      navigateOnDragDrop: false,
      spellcheck: false,
    },
  });

  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", (event, url) => {
    if (!isAllowedNavigation(url)) event.preventDefault();
  });
  window.webContents.on("will-attach-webview", (event) => event.preventDefault());
  window.webContents.on("will-frame-navigate", (event) => {
    if (!isAllowedNavigation(event.url)) event.preventDefault();
  });
  if (options.showOnReady !== false) window.once("ready-to-show", () => window.show());
  void window.loadURL(`${BENTO_ORIGIN}/${options.recoveryMode ? "?recovery=1" : ""}`);
  return window;
}

export function lockDownSession(): void {
  session.defaultSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false));
  session.defaultSession.setPermissionCheckHandler(() => false);
}
