import path from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";

const electron = vi.hoisted(() => ({
  showOpenDialog: vi.fn(),
}));

vi.mock("electron", () => ({
  dialog: { showOpenDialog: electron.showOpenDialog },
  BrowserWindow: class {},
}));

import { IPC_CHANNELS, registerIpcHandlers } from "../src/main/ipc";

type Handler = (event: unknown, payload?: unknown) => Promise<unknown>;

function setup() {
  const handlers = new Map<string, Handler>();
  const ipcMain = {
    handle: vi.fn((channel: string, handler: Handler) => handlers.set(channel, handler)),
    removeHandler: vi.fn((channel: string) => handlers.delete(channel)),
  };
  const send = vi.fn();
  const mainFrame = { processId: 4, routingId: 1, parent: null };
  const webContents = { send, mainFrame, isDestroyed: () => false };
  const window = { webContents, isDestroyed: () => false };
  const dependencies = {
    ipcMain: ipcMain as never,
    window: () => window as never,
    platform: vi.fn(async () => ({ desktop: true as const } as never)),
    lifecycleStatus: vi.fn(() => ({ state: "ready" as const, recoveryMode: false })),
    applySettings: vi.fn(async () => ({ ok: true, revision: 2 })),
    runProbe: vi.fn(async () => ({ status: "ok" as const })),
    updates: {
      state: { status: "idle" as const, installMode: "manual" as const, currentVersion: "0.1.0" },
      check: vi.fn(async () => ({ status: "not-available" as const, installMode: "manual" as const, currentVersion: "0.1.0" })),
      download: vi.fn(async () => ({ status: "downloaded" as const, installMode: "manual" as const, currentVersion: "0.1.0" })),
      install: vi.fn(async () => ({ action: "manual" as const })),
    },
    preferences: {
      get: vi.fn(() => ({ keepRunningInBackground: true, launchAtLogin: false, autoDownloadUpdates: true })),
      set: vi.fn(async (patch: Record<string, boolean>) => ({ keepRunningInBackground: true, launchAtLogin: false, autoDownloadUpdates: true, ...patch })),
    },
    deepLinks: { subscribe: vi.fn(), unsubscribe: vi.fn() },
    navigation: { subscribe: vi.fn(), unsubscribe: vi.fn() },
    savePageAsPdf: vi.fn(async () => ({ saved: true, fileName: "kit.pdf" })),
  };
  const dispose = registerIpcHandlers(dependencies);
  const trustedEvent = {
    senderFrame: { url: "bento://app/settings", ...mainFrame },
    sender: webContents,
  };
  Object.assign(webContents, { getURL: () => "bento://app/settings" });
  return { dependencies, dispose, handlers, ipcMain, send, trustedEvent, webContents };
}

describe("main IPC handlers", () => {
  beforeEach(() => vi.clearAllMocks());

  it("registers and removes only the allowlisted command channels", () => {
    const { dispose, handlers, ipcMain } = setup();
    expect([...handlers.keys()].sort()).toEqual(
      [
        IPC_CHANNELS.platform,
        IPC_CHANNELS.lifecycleStatus,
        IPC_CHANNELS.pickDirectory,
        IPC_CHANNELS.pickFile,
        IPC_CHANNELS.settingsApply,
        IPC_CHANNELS.settingsProbe,
        IPC_CHANNELS.updatesState,
        IPC_CHANNELS.updatesCheck,
        IPC_CHANNELS.updatesDownload,
        IPC_CHANNELS.updatesInstall,
        IPC_CHANNELS.preferencesGet,
        IPC_CHANNELS.preferencesSet,
        IPC_CHANNELS.deepLinkSubscribe,
        IPC_CHANNELS.deepLinkUnsubscribe,
        IPC_CHANNELS.navigateSubscribe,
        IPC_CHANNELS.navigateUnsubscribe,
        IPC_CHANNELS.savePageAsPdf,
      ].sort(),
    );
    dispose();
    expect(ipcMain.removeHandler).toHaveBeenCalledTimes(17);
    expect(handlers.size).toBe(0);
  });

  it.each([
    "https://attacker.example",
    "bento://evil/settings",
    "file:///tmp/index.html",
    "javascript:alert(1)",
    "not a url",
  ])("rejects an untrusted sender before invoking dependencies: %s", async (url) => {
    const { dependencies, handlers } = setup();
    const handler = handlers.get(IPC_CHANNELS.platform)!;
    await expect(handler({ senderFrame: { url }, sender: { getURL: () => url } })).rejects.toThrow();
    expect(dependencies.platform).not.toHaveBeenCalled();
  });

  it("validates settings before application and sends progress on a fixed outbound channel", async () => {
    const { dependencies, handlers, send, trustedEvent } = setup();
    const handler = handlers.get(IPC_CHANNELS.settingsApply)!;
    const payload = { revision: 1, values: { ocr_enabled: false }, secrets: {} };
    await expect(handler(trustedEvent, payload)).resolves.toEqual({ ok: true, revision: 2 });
    const progress = dependencies.applySettings.mock.calls[0]?.[1];
    progress?.({ phase: "validating", status: "started" });
    expect(send).toHaveBeenCalledWith(IPC_CHANNELS.settingsProgress, {
      phase: "validating",
      status: "started",
    });

    await expect(handler(trustedEvent, { ...payload, arbitraryCommand: "open-shell" })).rejects.toThrow(TypeError);
    expect(dependencies.applySettings).toHaveBeenCalledTimes(1);
  });

  it("uses native pickers with fixed capabilities and rejects an unsafe returned path", async () => {
    const { handlers, trustedEvent } = setup();
    const safePath = path.join(path.parse(process.cwd()).root, "tmp", "bento-data");
    electron.showOpenDialog.mockResolvedValueOnce({ canceled: false, filePaths: [safePath] });
    await expect(handlers.get(IPC_CHANNELS.pickDirectory)!(trustedEvent, { title: "Datos" })).resolves.toEqual({
      canceled: false,
      path: safePath,
    });
    expect(electron.showOpenDialog).toHaveBeenCalledWith(expect.anything(), {
      title: "Datos",
      properties: ["openDirectory", "createDirectory", "promptToCreate"],
    });

    electron.showOpenDialog.mockResolvedValueOnce({ canceled: false, filePaths: [path.parse(process.cwd()).root] });
    await expect(handlers.get(IPC_CHANNELS.pickFile)!(trustedEvent, {})).rejects.toThrow(/root/i);
  });

  it("never forwards hostile probes", async () => {
    const { dependencies, handlers, trustedEvent } = setup();
    const handler = handlers.get(IPC_CHANNELS.settingsProbe)!;
    await expect(handler(trustedEvent, { kind: "ffmpeg" })).resolves.toEqual({ status: "ok" });
    await expect(handler(trustedEvent, { kind: "shell", command: "whoami" })).rejects.toThrow(TypeError);
    await expect(handler(trustedEvent, { kind: "telegram", secrets: { token: "new-secret" } })).rejects.toThrow(TypeError);
    expect(dependencies.runProbe).toHaveBeenCalledTimes(1);
  });

  it("validates update senders and rejects command-like payloads", async () => {
    const { dependencies, handlers, trustedEvent } = setup();
    const check = handlers.get(IPC_CHANNELS.updatesCheck)!;
    await expect(check(trustedEvent)).resolves.toMatchObject({ status: "not-available" });
    await expect(check(trustedEvent, { url: "https://attacker.example", command: "download" })).rejects.toThrow(TypeError);
    await expect(check({ senderFrame: { url: "https://attacker.example" }, sender: { getURL: () => "https://attacker.example" } })).rejects.toThrow(/Untrusted/u);
    expect(dependencies.updates.check).toHaveBeenCalledTimes(1);
  });

  it("validates preference patches before applying them", async () => {
    const { dependencies, handlers, trustedEvent } = setup();
    await expect(handlers.get(IPC_CHANNELS.preferencesGet)!(trustedEvent)).resolves.toMatchObject({ launchAtLogin: false });
    await expect(handlers.get(IPC_CHANNELS.preferencesGet)!(trustedEvent, { launchAtLogin: true })).rejects.toThrow(TypeError);
    await expect(handlers.get(IPC_CHANNELS.preferencesSet)!(trustedEvent, { launchAtLogin: true })).resolves.toMatchObject({ launchAtLogin: true });
    await expect(handlers.get(IPC_CHANNELS.preferencesSet)!(trustedEvent, { launchAtLogin: "true" })).rejects.toThrow(TypeError);
    await expect(handlers.get(IPC_CHANNELS.preferencesSet)!(trustedEvent, { dataDir: "/" })).rejects.toThrow(TypeError);
    expect(dependencies.preferences.set).toHaveBeenCalledTimes(1);
    expect(dependencies.preferences.set).toHaveBeenCalledWith({ launchAtLogin: true });
  });

  it("subscribes buffered streams only for the main window's top-level frame", async () => {
    const { dependencies, handlers, trustedEvent, webContents } = setup();
    await handlers.get(IPC_CHANNELS.deepLinkSubscribe)!(trustedEvent);
    await handlers.get(IPC_CHANNELS.navigateSubscribe)!(trustedEvent);
    await handlers.get(IPC_CHANNELS.deepLinkUnsubscribe)!(trustedEvent);
    expect(dependencies.deepLinks.subscribe).toHaveBeenCalledWith(webContents);
    expect(dependencies.navigation.subscribe).toHaveBeenCalledWith(webContents);
    expect(dependencies.deepLinks.unsubscribe).toHaveBeenCalledWith(webContents);

    const subframe = { ...trustedEvent, senderFrame: { ...trustedEvent.senderFrame, routingId: 9, parent: {} } };
    await expect(handlers.get(IPC_CHANNELS.deepLinkSubscribe)!(subframe)).rejects.toThrow(/main window/u);
    const otherContents = { ...webContents };
    await expect(handlers.get(IPC_CHANNELS.navigateSubscribe)!({ ...trustedEvent, sender: otherContents })).rejects.toThrow(/main window/u);
    await expect(handlers.get(IPC_CHANNELS.deepLinkSubscribe)!(trustedEvent, { replay: true })).rejects.toThrow(TypeError);
    expect(dependencies.deepLinks.subscribe).toHaveBeenCalledTimes(1);
    expect(dependencies.navigation.subscribe).toHaveBeenCalledTimes(1);
  });

  it("validates PDF requests and never forwards HTML or paths", async () => {
    const { dependencies, handlers, trustedEvent } = setup();
    const save = handlers.get(IPC_CHANNELS.savePageAsPdf)!;
    await expect(save(trustedEvent, { suggestedName: "Kit.pdf" })).resolves.toEqual({ saved: true, fileName: "kit.pdf" });
    await expect(save(trustedEvent, { html: "<p>x</p>" })).rejects.toThrow(TypeError);
    await expect(save(trustedEvent, { suggestedName: "../../x.pdf" })).rejects.toThrow(TypeError);
    await expect(save({ senderFrame: { url: "https://attacker.example" }, sender: { getURL: () => "https://attacker.example" } }, {})).rejects.toThrow(/Untrusted/u);
    expect(dependencies.savePageAsPdf).toHaveBeenCalledTimes(1);
    expect(dependencies.savePageAsPdf.mock.calls[0]?.[1]).toEqual({ suggestedName: "Kit.pdf" });
  });
});
