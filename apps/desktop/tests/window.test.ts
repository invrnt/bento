import { describe, expect, it, vi } from "vitest";

const electron = vi.hoisted(() => {
  const instances: FakeWindow[] = [];
  class FakeWindow {
    options: Record<string, unknown>;
    webContents = {
      setWindowOpenHandler: vi.fn(),
      on: vi.fn(),
    };
    once = vi.fn();
    show = vi.fn();
    loadURL = vi.fn(async () => undefined);
    constructor(options: Record<string, unknown>) {
      this.options = options;
      instances.push(this);
    }
  }
  return {
    FakeWindow,
    instances,
    setPermissionRequestHandler: vi.fn(),
    setPermissionCheckHandler: vi.fn(),
  };
});

vi.mock("electron", () => ({
  BrowserWindow: electron.FakeWindow,
  nativeTheme: { shouldUseDarkColors: false },
  session: {
    defaultSession: {
      setPermissionRequestHandler: electron.setPermissionRequestHandler,
      setPermissionCheckHandler: electron.setPermissionCheckHandler,
    },
  },
}));

import { lockDownSession, createMainWindow } from "../src/main/window";

describe("BrowserWindow security", () => {
  it("creates a sandboxed, isolated renderer without Node or insecure features", () => {
    const window = createMainWindow({ preloadPath: "/opt/bento/preload.js" }) as unknown as InstanceType<typeof electron.FakeWindow>;
    expect(window.options.webPreferences).toMatchObject({
      preload: "/opt/bento/preload.js",
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      nodeIntegrationInWorker: false,
      webSecurity: true,
      allowRunningInsecureContent: false,
      experimentalFeatures: false,
      navigateOnDragDrop: false,
    });
    expect(window.options.webPreferences).not.toHaveProperty("webviewTag", true);
    expect(window.loadURL).toHaveBeenCalledWith("bento://app/");
  });

  it("denies new windows, webviews, remote navigation, and subframe navigation", () => {
    const window = createMainWindow() as unknown as InstanceType<typeof electron.FakeWindow>;
    const openHandler = window.webContents.setWindowOpenHandler.mock.calls[0]?.[0] as () => unknown;
    expect(openHandler()).toEqual({ action: "deny" });

    const handlers = Object.fromEntries(window.webContents.on.mock.calls.map(([event, handler]) => [event, handler]));
    for (const eventName of ["will-navigate", "will-frame-navigate"]) {
      const preventDefault = vi.fn();
      if (eventName === "will-frame-navigate") handlers[eventName]?.({ url: "https://attacker.example", preventDefault });
      else handlers[eventName]?.({ preventDefault }, "https://attacker.example");
      expect(preventDefault).toHaveBeenCalledOnce();
    }
    const preventWebview = vi.fn();
    handlers["will-attach-webview"]?.({ preventDefault: preventWebview });
    expect(preventWebview).toHaveBeenCalledOnce();
  });

  it("denies every Chromium permission request and check", () => {
    lockDownSession();
    const requestHandler = electron.setPermissionRequestHandler.mock.calls.at(-1)?.[0] as (
      contents: unknown,
      permission: string,
      callback: (allowed: boolean) => void,
    ) => void;
    const callback = vi.fn();
    requestHandler({}, "media", callback);
    expect(callback).toHaveBeenCalledWith(false);
    expect((electron.setPermissionCheckHandler.mock.calls.at(-1)?.[0] as () => boolean)()).toBe(false);
  });

  it("keeps the window hidden for tray/login starts", () => {
    const window = createMainWindow({ showOnReady: false }) as unknown as InstanceType<typeof electron.FakeWindow>;
    expect(window.once).not.toHaveBeenCalledWith("ready-to-show", expect.any(Function));
    expect(window.loadURL).toHaveBeenCalledWith("bento://app/");
    const visible = createMainWindow() as unknown as InstanceType<typeof electron.FakeWindow>;
    expect(visible.once).toHaveBeenCalledWith("ready-to-show", expect.any(Function));
  });
});
