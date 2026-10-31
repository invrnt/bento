import { mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WindowLifecycle } from "../src/main/background";
import { desktopExecArgument, HIDDEN_ARGUMENT, linuxAutostartEntry, LoginItemController } from "../src/main/login-items";
import { DEFAULT_PREFERENCES, DesktopStateStore } from "../src/main/preferences";
import { handleSquirrelEvent, sendToShortcutPath, squirrelEvent, squirrelStubExecutable } from "../src/main/squirrel";

const roots: string[] = [];

async function temporary(): Promise<string> {
  const root = await mkdtemp(path.join(os.tmpdir(), "bento-lifecycle-"));
  roots.push(root);
  return root;
}

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

describe("desktop preferences", () => {
  it("defaults to running in the background, auto-downloading updates, and login launch off until onboarding", async () => {
    const store = new DesktopStateStore(path.join(await temporary(), "preferences.json"));
    await store.load();
    expect(store.preferences).toEqual({ keepRunningInBackground: true, launchAtLogin: false, autoDownloadUpdates: true });
    expect(DEFAULT_PREFERENCES).toEqual(store.preferences);
  });

  it("persists patches atomically with owner-only permissions", async () => {
    const file = path.join(await temporary(), "desktop", "preferences.json");
    const store = new DesktopStateStore(file);
    await store.load();
    await expect(store.updatePreferences({ launchAtLogin: true })).resolves.toMatchObject({ launchAtLogin: true });
    const reloaded = new DesktopStateStore(file);
    await reloaded.load();
    expect(reloaded.preferences.launchAtLogin).toBe(true);
    if (process.platform !== "win32") expect((await stat(file)).mode & 0o777).toBe(0o600);
    expect(JSON.parse(await readFile(file, "utf8"))).toMatchObject({ schemaVersion: 1, preferences: { launchAtLogin: true } });
  });

  it("does not persist a preference whose side effect fails", async () => {
    const file = path.join(await temporary(), "preferences.json");
    const store = new DesktopStateStore(file);
    await store.load();
    const effect = vi.fn(async () => { throw new Error("preferences_launch_at_login_failed"); });
    await expect(store.updatePreferences({ launchAtLogin: true }, effect)).rejects.toThrow("preferences_launch_at_login_failed");
    expect(effect).toHaveBeenCalledWith({ ...DEFAULT_PREFERENCES, launchAtLogin: true }, DEFAULT_PREFERENCES);
    expect(store.preferences.launchAtLogin).toBe(false);
    await expect(readFile(file)).rejects.toMatchObject({ code: "ENOENT" });
  });

  it("recovers from corrupt or hostile documents with safe defaults", async () => {
    for (const contents of ["{not json", JSON.stringify({ schemaVersion: 2 }), JSON.stringify({ schemaVersion: 1, preferences: { launchAtLogin: "yes" } })]) {
      const file = path.join(await temporary(), "preferences.json");
      await writeFile(file, contents);
      const store = new DesktopStateStore(file);
      await expect(store.load()).resolves.toEqual({ recovered: true });
      expect(store.preferences).toEqual(DEFAULT_PREFERENCES);
    }
    const file = path.join(await temporary(), "preferences.json");
    await writeFile(file, JSON.stringify({
      schemaVersion: 1,
      preferences: { keepRunningInBackground: false, unknown: true },
      internal: { backgroundNoticeShown: true, notifiedAttentionIds: ["ok", "../bad", 7] },
    }));
    const store = new DesktopStateStore(file);
    await store.load();
    expect(store.preferences).toEqual({ ...DEFAULT_PREFERENCES, keepRunningInBackground: false });
    expect([...store.notifiedAttentionIds]).toEqual(["ok"]);
    expect(store.backgroundNoticeShown).toBe(true);
  });

  it("remembers a bounded set of notified attention ids", async () => {
    const store = new DesktopStateStore(path.join(await temporary(), "preferences.json"));
    await store.load();
    await store.rememberAttention(Array.from({ length: 600 }, (_value, index) => `id-${index}`));
    expect(store.notifiedAttentionIds.size).toBe(500);
    expect(store.notifiedAttentionIds.has("id-599")).toBe(true);
    expect(store.notifiedAttentionIds.has("id-0")).toBe(false);
  });
});

describe("launch at login", () => {
  function controller(platform: NodeJS.Platform, overrides: Partial<ConstructorParameters<typeof LoginItemController>[0]> = {}) {
    const app = { setLoginItemSettings: vi.fn(), getLoginItemSettings: vi.fn(() => ({ openAtLogin: false, wasOpenedAtLogin: true })) };
    const fs = {
      mkdir: vi.fn(async () => undefined),
      writeAtomic: vi.fn(async () => undefined),
      remove: vi.fn(async () => undefined),
      lstat: vi.fn(async () => ({ isFile: () => true, uid: 1000, mode: 0o100755 })),
    };
    const login = new LoginItemController({
      platform,
      packaged: true,
      execPath: platform === "win32" ? "C:\\Users\\Ana\\AppData\\Local\\bento\\app-0.2.0\\bento.exe" : "/usr/lib/bento-desktop/bento",
      environment: {},
      homeDirectory: "/home/ana",
      app,
      fs,
      uid: 1000,
      ...overrides,
    });
    return { app, fs, login };
  }

  it("uses the Squirrel stub with --hidden on Windows", async () => {
    const { app, login } = controller("win32", { squirrelInstalled: true });
    await login.apply(true);
    expect(app.setLoginItemSettings).toHaveBeenCalledWith({
      openAtLogin: true,
      path: "C:\\Users\\Ana\\AppData\\Local\\bento\\bento.exe",
      args: [HIDDEN_ARGUMENT],
    });
    await login.apply(false);
    expect(app.setLoginItemSettings).toHaveBeenLastCalledWith(expect.objectContaining({ openAtLogin: false }));
  });

  it("uses login items on macOS and starts hidden when opened at login", async () => {
    const { app, login } = controller("darwin");
    await login.apply(true);
    expect(app.setLoginItemSettings).toHaveBeenCalledWith({ openAtLogin: true });
    expect(login.launchedHidden([])).toBe(true);
    app.getLoginItemSettings.mockReturnValue({ openAtLogin: true, wasOpenedAtLogin: false });
    expect(login.launchedHidden([])).toBe(false);
    expect(login.launchedHidden(["--hidden"])).toBe(true);
  });

  // XDG autostart and AppImage trust use POSIX paths and ownership; they only ship on Linux.
  it.skipIf(process.platform === "win32")("writes and removes an XDG autostart entry on Linux", async () => {
    const { app, fs, login } = controller("linux", {
      execPath: "/tmp/.mount_BentoA1b2C3/bento",
      environment: { XDG_CONFIG_HOME: "/home/ana/.cfg", APPIMAGE: "/home/ana/Apps/Bento.AppImage", APPDIR: "/tmp/.mount_BentoA1b2C3" },
    });
    await login.apply(true);
    expect(fs.mkdir).toHaveBeenCalledWith(path.join("/home/ana/.cfg", "autostart"));
    const [target, contents] = fs.writeAtomic.mock.calls[0] as unknown as [string, string];
    expect(target).toBe(path.join("/home/ana/.cfg", "autostart", "bento.desktop"));
    expect(contents).toContain("Exec=/home/ana/Apps/Bento.AppImage --hidden\n");
    expect(contents).toContain("X-GNOME-Autostart-enabled=true");
    await login.apply(false);
    expect(fs.remove).toHaveBeenCalledWith(target);
    expect(app.setLoginItemSettings).not.toHaveBeenCalled();

    const fallback = controller("linux", { environment: { XDG_CONFIG_HOME: "relative/config" } });
    expect(fallback.login.autostartPath()).toBe(path.join("/home/ana", ".config", "autostart", "bento.desktop"));
  });

  it.skipIf(process.platform === "win32")("uses an inherited APPIMAGE only when it is this app's own trusted AppImage", async () => {
    const mounted = { execPath: "/tmp/.mount_BentoA1b2C3/bento" };
    const environment = { APPIMAGE: "/home/ana/Apps/Bento.AppImage", APPDIR: "/tmp/.mount_BentoA1b2C3" };
    const exec = (fs: { writeAtomic: { mock: { calls: unknown[][] } } }) => /Exec=(.*) --hidden/u.exec(String(fs.writeAtomic.mock.calls[0]?.[1]))?.[1];

    // Inherited from some other AppImage (we are not running from its mount): ignored.
    const inherited = controller("linux", { environment: { APPIMAGE: "/home/ana/Apps/Other.AppImage", APPDIR: "/tmp/.mount_Other" } });
    await inherited.login.apply(true);
    expect(exec(inherited.fs)).toBe("/usr/lib/bento-desktop/bento");
    expect(inherited.fs.lstat).not.toHaveBeenCalled();

    const untrusted: Array<[string, Partial<{ isFile: () => boolean; uid: number; mode: number }> | Error, Record<string, string>?]> = [
      ["owned by another user", { uid: 0 }],
      ["writable by everyone", { mode: 0o100777 }],
      ["not a regular file (symlink, directory)", { isFile: () => false }],
      ["missing", new Error("ENOENT")],
      ["relative", {}, { APPIMAGE: "Apps/Bento.AppImage" }],
      ["not normalized", {}, { APPIMAGE: "/home/ana/Apps/../Apps/Bento.AppImage" }],
    ];
    for (const [, stats, extra] of untrusted) {
      const { fs, login } = controller("linux", { ...mounted, environment: { ...environment, ...extra } });
      fs.lstat.mockImplementation(async () => {
        if (stats instanceof Error) throw stats;
        return { isFile: () => true, uid: 1000, mode: 0o100755, ...stats };
      });
      await expect(login.apply(true)).rejects.toThrow(TypeError);
      expect(fs.writeAtomic).not.toHaveBeenCalled();
    }

    const trusted = controller("linux", { ...mounted, environment });
    await trusted.login.apply(true);
    expect(exec(trusted.fs)).toBe("/home/ana/Apps/Bento.AppImage");
    expect(trusted.fs.lstat).toHaveBeenCalledWith("/home/ana/Apps/Bento.AppImage");
  });

  it("writes the real autostart file atomically", async () => {
    const home = await temporary();
    const login = new LoginItemController({
      platform: "linux", packaged: true, execPath: "/opt/Bento/bento", environment: {}, homeDirectory: home,
      app: { setLoginItemSettings: vi.fn(), getLoginItemSettings: vi.fn(() => ({ openAtLogin: false })) },
    });
    await login.apply(true);
    const file = path.join(home, ".config", "autostart", "bento.desktop");
    expect(await readFile(file, "utf8")).toContain("Exec=/opt/Bento/bento --hidden");
    await login.apply(false);
    await expect(readFile(file)).rejects.toMatchObject({ code: "ENOENT" });
    await expect(login.apply(false)).resolves.toBeUndefined();
  });

  it("never registers development builds", async () => {
    const { app, fs, login } = controller("linux", { packaged: false });
    await login.apply(true);
    expect(login.supported).toBe(false);
    expect(fs.writeAtomic).not.toHaveBeenCalled();
    expect(app.setLoginItemSettings).not.toHaveBeenCalled();
  });

  it("quotes Exec arguments per the Desktop Entry specification", () => {
    expect(desktopExecArgument("/opt/Bento/bento")).toBe("/opt/Bento/bento");
    expect(desktopExecArgument("/home/ana/My Apps/Bento 100%.AppImage")).toBe('"/home/ana/My Apps/Bento 100%%.AppImage"');
    expect(desktopExecArgument('/tmp/a"b$c`d\\e')).toBe('"/tmp/a\\\\"b\\\\$c\\\\`d\\\\\\\\e"');
    expect(() => linuxAutostartEntry("/tmp/evil\nExec=rm -rf ~")).toThrow(TypeError);
    expect(() => linuxAutostartEntry("relative/bento")).toThrow(TypeError);
  });
});

describe("background window lifecycle", () => {
  function windowFixture() {
    let closeListener!: (event: { preventDefault(): void }) => void;
    const window = {
      on: vi.fn((_event: "close", listener: (event: { preventDefault(): void }) => void) => { closeListener = listener; }),
      show: vi.fn(), hide: vi.fn(), focus: vi.fn(), restore: vi.fn(),
      isMinimized: vi.fn(() => true), isDestroyed: vi.fn(() => false),
    };
    return { window, close: () => { const event = { preventDefault: vi.fn() }; closeListener(event); return event; } };
  }

  it("hides instead of closing, notifies on hide, and hides the macOS dock only while closed", () => {
    const dock = { hide: vi.fn(), show: vi.fn() };
    const hidden = vi.fn();
    const lifecycle = new WindowLifecycle({ platform: "darwin", dock, keepRunningInBackground: () => true, isQuitting: () => false, onHiddenToBackground: hidden });
    const { window, close } = windowFixture();
    lifecycle.attach(window);
    const event = close();
    expect(event.preventDefault).toHaveBeenCalledOnce();
    expect(window.hide).toHaveBeenCalledOnce();
    expect(dock.hide).toHaveBeenCalledOnce();
    expect(hidden).toHaveBeenCalledOnce();
    lifecycle.show(window);
    expect(dock.show).toHaveBeenCalledOnce();
    expect(window.restore).toHaveBeenCalledOnce();
    expect(window.show).toHaveBeenCalledOnce();
    expect(window.focus).toHaveBeenCalledOnce();
  });

  it("never blocks quitting or a disabled background preference", () => {
    let quitting = false;
    let keepRunning = true;
    const dock = { hide: vi.fn(), show: vi.fn() };
    const lifecycle = new WindowLifecycle({ platform: "linux", dock, keepRunningInBackground: () => keepRunning, isQuitting: () => quitting, onHiddenToBackground: vi.fn() });
    const { window, close } = windowFixture();
    lifecycle.attach(window);
    quitting = true;
    expect(close().preventDefault).not.toHaveBeenCalled();
    quitting = false;
    keepRunning = false;
    expect(close().preventDefault).not.toHaveBeenCalled();
    keepRunning = true;
    expect(close().preventDefault).toHaveBeenCalled();
    expect(dock.hide).not.toHaveBeenCalled();
  });
});

describe("Windows Squirrel events and Send To", () => {
  const execPath = "C:\\Users\\Ana\\AppData\\Local\\bento\\app-0.2.0\\bento.exe";
  const appData = "C:\\Users\\Ana\\AppData\\Roaming";

  function dependencies() {
    return {
      execPath,
      appDataDirectory: appData,
      description: "Enviar a Bento",
      runUpdate: vi.fn(async () => undefined),
      writeShortcutLink: vi.fn(() => true),
      removeFile: vi.fn(async () => undefined),
      removeLoginItem: vi.fn(),
      removeProtocolClient: vi.fn(),
    };
  }

  it("detects Squirrel launches only on Windows", () => {
    expect(squirrelEvent(["bento.exe", "--squirrel-install", "0.2.0"], "win32")).toBe("install");
    expect(squirrelEvent(["bento.exe", "--squirrel-updated"], "win32")).toBe("updated");
    expect(squirrelEvent(["bento.exe", "--squirrel-uninstall"], "win32")).toBe("uninstall");
    expect(squirrelEvent(["bento.exe", "--squirrel-install"], "linux")).toBeNull();
    expect(squirrelEvent(["bento.exe", "C:\\file.jpg"], "win32")).toBeNull();
  });

  it.each(["install", "updated"] as const)("creates the Send To shortcut pointing at the stub on %s", async (event) => {
    const deps = dependencies();
    await expect(handleSquirrelEvent(event, deps)).resolves.toBe(true);
    expect(deps.runUpdate).toHaveBeenCalledWith(["--createShortcut", "bento.exe"]);
    expect(deps.writeShortcutLink).toHaveBeenCalledWith(
      "C:\\Users\\Ana\\AppData\\Roaming\\Microsoft\\Windows\\SendTo\\Bento.lnk",
      "create",
      expect.objectContaining({ target: "C:\\Users\\Ana\\AppData\\Local\\bento\\bento.exe", appUserModelId: "com.squirrel.bento.bento" }),
    );
  });

  it("removes shortcuts, the login item, and the protocol handler on uninstall", async () => {
    const deps = dependencies();
    await expect(handleSquirrelEvent("uninstall", deps)).resolves.toBe(true);
    expect(deps.runUpdate).toHaveBeenCalledWith(["--removeShortcut", "bento.exe"]);
    expect(deps.removeFile).toHaveBeenCalledWith(sendToShortcutPath(appData));
    expect(deps.removeLoginItem).toHaveBeenCalledWith(squirrelStubExecutable(execPath));
    expect(deps.removeProtocolClient).toHaveBeenCalledWith(squirrelStubExecutable(execPath));
  });

  it("continues normal startup on first run and quits when obsolete", async () => {
    await expect(handleSquirrelEvent("firstrun", dependencies())).resolves.toBe(false);
    const deps = dependencies();
    await expect(handleSquirrelEvent("obsolete", deps)).resolves.toBe(true);
    expect(deps.writeShortcutLink).not.toHaveBeenCalled();
  });
});
