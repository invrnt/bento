import { createHash } from "node:crypto";
import { EventEmitter } from "node:events";
import { access, mkdir, mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { compareSemver, isStrictSemver, prepareForUpdateInstall, UpdateController } from "../src/main/updater";

const roots: string[] = [];
const artifactBytes = Buffer.from("verified bento package");
const artifactName = "bento_0.2.0_amd64.deb";
const artifactUrl = `https://github.com/invrnt/bento/releases/download/v0.2.0/${artifactName}`;
const manifestName = "bento-update-linux-x64.json";
const manifestUrl = `https://github.com/invrnt/bento/releases/download/v0.2.0/${manifestName}`;

class FakeAutoUpdater extends EventEmitter {
  setFeedURL = vi.fn();
  checkForUpdates = vi.fn();
  quitAndInstall = vi.fn();
}

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

describe("controlled desktop updater", () => {
  it("marks application shutdown before stopping services so before-quit cannot abort Squirrel", async () => {
    const order: string[] = [];
    await prepareForUpdateInstall(() => order.push("quitting"), async () => { order.push("stop"); });
    expect(order).toEqual(["quitting", "stop"]);
  });

  it("accepts only strict stable semver and compares without downgrade ambiguity", () => {
    expect(isStrictSemver("1.2.3")).toBe(true);
    for (const invalid of ["v1.2.3", "1.2", "01.2.3", "1.2.3-beta", "1.2.3+build"]) expect(isStrictSemver(invalid)).toBe(false);
    expect(compareSemver("10.0.0", "2.99.99")).toBe(1);
    expect(compareSemver("1.2.3", "1.2.3")).toBe(0);
  });

  it("checks metadata explicitly without downloading the package", async () => {
    const fixture = await setup();
    const state = await fixture.controller.check();
    expect(state).toMatchObject({ status: "available", currentVersion: "0.1.0", availableVersion: "0.2.0", installMode: "manual" });
    expect(fixture.fetch).toHaveBeenCalledTimes(2);
    expect(fixture.fetch.mock.calls.map((call) => call[0])).toEqual([expect.stringContaining("api.github.com/repos/invrnt/bento"), manifestUrl]);
    expect(fixture.autoUpdater.checkForUpdates).not.toHaveBeenCalled();
  });

  it("downloads only after the command and verifies bytes before exposing the package", async () => {
    const fixture = await setup();
    await fixture.controller.check();
    const states: string[] = [];
    fixture.controller.on("state", (state) => states.push(state.status));
    const state = await fixture.controller.download();
    expect(state.status).toBe("downloaded");
    expect(state.progress).toMatchObject({ percent: 100, transferredBytes: artifactBytes.length, totalBytes: artifactBytes.length });
    expect(fixture.fetch).toHaveBeenCalledTimes(3);
    expect(await readFile(path.join(fixture.root, "0.2.0", artifactName))).toEqual(artifactBytes);
    expect(states).toContain("downloading");
    const metadata = await stat(path.join(fixture.root, "0.2.0", "download.json"));
    expect(metadata.isFile()).toBe(true);
    if (process.platform !== "win32") expect(metadata.mode & 0o777).toBe(0o600);
  });

  it("rehydrates a verified download after relaunch without any network request", async () => {
    const fixture = await setup();
    await fixture.controller.check();
    await fixture.controller.download();
    fixture.fetch.mockClear();
    const relaunched = fixture.createController();
    const initializing = relaunched.initialize();
    expect(relaunched.state.status).toBe("idle");
    await expect(initializing).resolves.toMatchObject({ status: "downloaded", availableVersion: "0.2.0" });
    expect(fixture.fetch).not.toHaveBeenCalled();
    await expect(relaunched.install()).resolves.toEqual({ action: "manual", packageManager: "system-package-installer" });
  });

  it("rejects and removes a tampered persisted package on relaunch", async () => {
    const fixture = await setup();
    await fixture.controller.check();
    await fixture.controller.download();
    await writeFile(path.join(fixture.root, "0.2.0", artifactName), "tampered");
    const relaunched = fixture.createController();
    expect(await relaunched.initialize()).toMatchObject({ status: "idle" });
    await expect(access(path.join(fixture.root, "0.2.0"))).rejects.toThrow();
  });

  it("rejects persisted metadata that attempts to escape its version directory", async () => {
    const fixture = await setup();
    await fixture.controller.check();
    await fixture.controller.download();
    const metadataPath = path.join(fixture.root, "0.2.0", "download.json");
    const metadata = JSON.parse(await readFile(metadataPath, "utf8"));
    metadata.artifact.filename = "../outside.deb";
    await writeFile(metadataPath, JSON.stringify(metadata));
    const relaunched = fixture.createController();
    expect((await relaunched.initialize()).status).toBe("idle");
    await expect(access(path.join(fixture.root, "outside.deb"))).rejects.toThrow();
  });

  it("cleans old staging and partial files without deleting the valid download", async () => {
    const fixture = await setup();
    await fixture.controller.check();
    await fixture.controller.download();
    await mkdir(path.join(fixture.root, "0.1.9"));
    await writeFile(path.join(fixture.root, "0.1.9", "old.part"), "old");
    await writeFile(path.join(fixture.root, "root.part"), "partial");
    await writeFile(path.join(fixture.root, "0.2.0", "stale.part"), "partial");
    const relaunched = fixture.createController();
    expect((await relaunched.initialize()).status).toBe("downloaded");
    await expect(access(path.join(fixture.root, "0.1.9"))).rejects.toThrow();
    await expect(access(path.join(fixture.root, "root.part"))).rejects.toThrow();
    await expect(access(path.join(fixture.root, "0.2.0", "stale.part"))).rejects.toThrow();
    expect(await readFile(path.join(fixture.root, "0.2.0", artifactName))).toEqual(artifactBytes);
  });

  it("replaces an existing Windows target safely instead of relying on rename overwrite semantics", async () => {
    const fixture = await setup({ platform: "win32", includeSquirrel: true });
    await fixture.controller.check();
    const destination = path.join(fixture.root, "0.2.0", "bento-0.2.0-full.nupkg");
    await mkdir(path.dirname(destination), { recursive: true });
    await writeFile(destination, "stale package");
    expect((await fixture.controller.download()).status).toBe("downloaded");
    expect(await readFile(destination)).toEqual(artifactBytes);
  });

  it("aborts a check whose response headers never arrive", async () => {
    const fixture = await setup({ networkTimeoutMs: 10 });
    fixture.fetch.mockImplementation((_input, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
    }));
    expect((await fixture.controller.check()).error?.code).toBe("updates_network_timeout");
  });

  it("aborts an inactive manifest response during check", async () => {
    const fixture = await setup({ inactivityTimeoutMs: 10 });
    const normalFetch = fixture.fetch.getMockImplementation()!;
    fixture.fetch.mockImplementation(async (input, init) => {
      if (String(input) === manifestUrl) {
        const stream = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(new Uint8Array([123])); } });
        return new Response(stream, { status: 200 });
      }
      return normalFetch(input, init);
    });
    expect((await fixture.controller.check()).error?.code).toBe("updates_download_inactivity_timeout");
  });

  it("aborts an inactive package stream and removes its partial file", async () => {
    const fixture = await setup({ inactivityTimeoutMs: 10 });
    const normalFetch = fixture.fetch.getMockImplementation()!;
    fixture.fetch.mockImplementation(async (input, init) => {
      if (String(input).endsWith(artifactName)) {
        const stream = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(artifactBytes.subarray(0, 1)); } });
        return new Response(stream, { status: 200, headers: { "content-length": String(artifactBytes.length) } });
      }
      return normalFetch(input, init);
    });
    await fixture.controller.check();
    expect((await fixture.controller.download()).error?.code).toBe("updates_download_inactivity_timeout");
    await expect(access(path.join(fixture.root, "0.2.0", `${artifactName}.part`))).rejects.toThrow();
  });

  it("opens a verified Linux package honestly instead of claiming an in-app restart", async () => {
    const fixture = await setup();
    await fixture.controller.check();
    await fixture.controller.download();
    await expect(fixture.controller.install()).resolves.toEqual({ action: "manual", packageManager: "system-package-installer" });
    expect(fixture.openPath).toHaveBeenCalledWith(path.join(fixture.root, "0.2.0", artifactName));
    expect(fixture.beforeInstall).not.toHaveBeenCalled();
  });

  it("revalidates persisted bytes immediately before install", async () => {
    const fixture = await setup();
    await fixture.controller.check();
    await fixture.controller.download();
    await writeFile(path.join(fixture.root, "0.2.0", artifactName), "changed after verification");
    await expect(fixture.controller.install()).rejects.toThrow("updates_staging_invalid");
    expect(fixture.openPath).not.toHaveBeenCalled();
  });

  it("reports current or older releases as unavailable and never stages them", async () => {
    const fixture = await setup({ version: "0.1.0", currentVersion: "0.2.0" });
    expect(await fixture.controller.check()).toMatchObject({ status: "not-available", currentVersion: "0.2.0" });
    expect(fixture.autoUpdater.checkForUpdates).not.toHaveBeenCalled();
  });

  it.each([
    ["foreign repository URL", { artifactUrl: "https://github.com/attacker/bento/releases/download/v0.2.0/pkg.deb" }],
    ["missing GitHub digest", { omitArtifactDigest: true }],
    ["manifest checksum mismatch", { corruptManifestDigest: true }],
    ["package checksum mismatch", { corruptArtifactDigest: true }],
    ["path traversal filename", { artifactName: "../bento.deb" }],
  ])("fails closed for %s and exposes only a bounded error code", async (_label, options) => {
    const fixture = await setup(options);
    const checked = await fixture.controller.check();
    if (checked.status === "available") await fixture.controller.download();
    expect(fixture.controller.state.status).toBe("error");
    expect(fixture.controller.state.error?.code).toMatch(/^updates_[a-z_]+$/u);
    expect(JSON.stringify(fixture.controller.state)).not.toContain("attacker");
  });

  it("accepts Forge filenames with internal spaces while preserving basename validation", async () => {
    const name = "Bento-0.2.0 Setup.exe";
    const fixture = await setup({ platform: "win32", installerName: name, includeSquirrel: true });
    const state = await fixture.controller.check();
    // The installer name is accepted; the selected update payload remains the verified nupkg.
    expect(state.status).toBe("available");
  });

  it("does not call Electron autoUpdater on unsupported or development builds", async () => {
    const development = await setup({ isPackaged: false });
    expect((await development.controller.check()).error?.code).toBe("updates_development_build");
    expect(development.autoUpdater.checkForUpdates).not.toHaveBeenCalled();
  });

  it("stages a verified Windows package only during install, then preserves the updater quit path", async () => {
    const fixture = await setup({ platform: "win32", includeSquirrel: true });
    await fixture.controller.check();
    expect(fixture.autoUpdater.setFeedURL).not.toHaveBeenCalled();
    await fixture.controller.download();
    fixture.autoUpdater.checkForUpdates.mockImplementation(() => queueMicrotask(() => fixture.autoUpdater.emit("update-downloaded")));
    await expect(fixture.controller.install()).resolves.toEqual({ action: "restarting" });
    expect(fixture.autoUpdater.setFeedURL).toHaveBeenCalledWith(expect.objectContaining({ url: expect.stringMatching(/^http:\/\/127\.0\.0\.1:\d+\/[a-f0-9]+$/u) }));
    expect(fixture.beforeInstall).toHaveBeenCalledTimes(1);
    expect(fixture.autoUpdater.quitAndInstall).toHaveBeenCalledTimes(1);
    expect(fixture.beforeInstall.mock.invocationCallOrder[0]).toBeLessThan(fixture.autoUpdater.quitAndInstall.mock.invocationCallOrder[0]!);
  });

  it("recovers runtime services if quitAndInstall throws after they were stopped", async () => {
    const fixture = await setup({ platform: "win32", includeSquirrel: true });
    await fixture.controller.check();
    await fixture.controller.download();
    fixture.autoUpdater.checkForUpdates.mockImplementation(() => queueMicrotask(() => fixture.autoUpdater.emit("update-downloaded")));
    fixture.autoUpdater.quitAndInstall.mockImplementation(() => { throw new Error("sensitive native failure"); });
    await expect(fixture.controller.install()).rejects.toThrow("updates_auto_updater_failed");
    expect(fixture.recoverAfterInstallFailure).toHaveBeenCalledTimes(1);
    expect(fixture.controller.state).toMatchObject({ status: "error", error: { code: "updates_auto_updater_failed" } });
    expect(JSON.stringify(fixture.controller.state)).not.toContain("sensitive native failure");
  });

  it("recovers and clears quitting state when stopping services rejects", async () => {
    const fixture = await setup({ platform: "win32", includeSquirrel: true });
    await fixture.controller.check();
    await fixture.controller.download();
    fixture.autoUpdater.checkForUpdates.mockImplementation(() => queueMicrotask(() => fixture.autoUpdater.emit("update-downloaded")));
    fixture.beforeInstall.mockRejectedValueOnce(new Error("stop failed"));
    await expect(fixture.controller.install()).rejects.toThrow("updates_auto_updater_failed");
    expect(fixture.recoverAfterInstallFailure).toHaveBeenCalledTimes(1);
    expect(fixture.autoUpdater.quitAndInstall).not.toHaveBeenCalled();
  });

  it("uses a bounded watchdog to recover when quitAndInstall returns without exiting", async () => {
    const fixture = await setup({ platform: "win32", includeSquirrel: true });
    await fixture.controller.check();
    await fixture.controller.download();
    fixture.autoUpdater.checkForUpdates.mockImplementation(() => queueMicrotask(() => fixture.autoUpdater.emit("update-downloaded")));
    await fixture.controller.install();
    expect(fixture.scheduleInstallWatchdog).toHaveBeenCalledWith(expect.any(Function), 30_000);
    fixture.watchdogs[0]!();
    await vi.waitFor(() => expect(fixture.controller.state).toMatchObject({ status: "error", error: { code: "updates_install_did_not_exit" } }));
    expect(fixture.recoverAfterInstallFailure).toHaveBeenCalledTimes(1);
  });

  it("cancels the watchdog path when autoUpdater signals before-quit-for-update", async () => {
    const fixture = await setup({ platform: "win32", includeSquirrel: true });
    await fixture.controller.check();
    await fixture.controller.download();
    fixture.autoUpdater.checkForUpdates.mockImplementation(() => queueMicrotask(() => fixture.autoUpdater.emit("update-downloaded")));
    fixture.autoUpdater.quitAndInstall.mockImplementation(() => { fixture.autoUpdater.emit("before-quit-for-update"); });
    await fixture.controller.install();
    expect(fixture.scheduleInstallWatchdog).not.toHaveBeenCalled();
    expect(fixture.recoverAfterInstallFailure).not.toHaveBeenCalled();
  });
});

interface FixtureOptions {
  version?: string;
  currentVersion?: string;
  platform?: NodeJS.Platform;
  isPackaged?: boolean;
  artifactUrl?: string;
  artifactName?: string;
  artifactKind?: string;
  installerName?: string;
  omitArtifactDigest?: boolean;
  corruptManifestDigest?: boolean;
  corruptArtifactDigest?: boolean;
  includeSquirrel?: boolean;
  networkTimeoutMs?: number;
  inactivityTimeoutMs?: number;
}

async function setup(options: FixtureOptions = {}) {
  const root = await mkdtemp(path.join(tmpdir(), "bento-updater-"));
  roots.push(root);
  const version = options.version ?? "0.2.0";
  const platform = options.platform ?? "linux";
  const primaryName = options.artifactName ?? (platform === "win32" ? "bento-0.2.0-full.nupkg" : artifactName);
  const primaryKind = platform === "win32" ? "squirrel-package" : options.artifactKind ?? "installer";
  const primaryUrl = options.artifactUrl ?? `https://github.com/invrnt/bento/releases/download/v${version}/${encodeURIComponent(primaryName)}`;
  const artifactHash = createHash("sha256").update(artifactBytes).digest("hex");
  const sha1 = createHash("sha1").update(artifactBytes).digest("hex");
  const assets = [{ platform, arch: "x64", kind: primaryKind, filename: primaryName, url: primaryUrl, sha256: options.corruptArtifactDigest ? "0".repeat(64) : artifactHash, size: artifactBytes.length }];
  if (platform === "win32" && options.includeSquirrel) {
    const installerName = options.installerName ?? "Bento-0.2.0 Setup.exe";
    assets.push({ platform, arch: "x64", kind: "installer", filename: installerName, url: `https://github.com/invrnt/bento/releases/download/v0.2.0/${encodeURIComponent(installerName)}`, sha256: artifactHash, size: artifactBytes.length });
  }
  const manifest = {
    schemaVersion: 1,
    version,
    releaseName: `Bento ${version}`,
    notes: "Security update",
    publishedAt: "2026-08-25T12:00:00.000Z",
    commit: "a".repeat(40),
    repository: "invrnt/bento",
    target: `${platform}-x64`,
    assets,
    ...(platform === "win32" ? { squirrel: { nupkg: { filename: primaryName, url: primaryUrl, sha1, sha256: artifactHash, size: artifactBytes.length }, releasesContent: `${sha1.toUpperCase()} ${primaryUrl} ${artifactBytes.length}\n` } } : {}),
  };
  const manifestBytes = Buffer.from(JSON.stringify(manifest));
  const targetManifestName = `bento-update-${platform}-x64.json`;
  const targetManifestUrl = `https://github.com/invrnt/bento/releases/download/v${version}/${targetManifestName}`;
  const release = {
    tag_name: `v${version}`,
    name: `Bento ${version}`,
    body: "Security update",
    draft: false,
    prerelease: false,
    published_at: "2026-08-25T12:00:00.000Z",
    html_url: `https://github.com/invrnt/bento/releases/tag/v${version}`,
    assets: [
      { name: targetManifestName, state: "uploaded", size: manifestBytes.length, digest: `sha256:${options.corruptManifestDigest ? "0".repeat(64) : createHash("sha256").update(manifestBytes).digest("hex")}`, browser_download_url: targetManifestUrl },
      ...assets.map((asset) => ({ name: asset.filename, state: "uploaded", size: asset.size, digest: options.omitArtifactDigest ? null : `sha256:${asset.sha256}`, browser_download_url: asset.url })),
    ],
  };
  const fetch = vi.fn(async (input: string | URL | Request) => {
    const url = String(input);
    if (url.includes("api.github.com")) return response(JSON.stringify(release));
    if (url === targetManifestUrl) return response(manifestBytes);
    if (url === primaryUrl) return response(artifactBytes);
    throw new Error("unexpected request");
  });
  const autoUpdater = new FakeAutoUpdater();
  const openPath = vi.fn(async () => "");
  const beforeInstall = vi.fn(async () => undefined);
  const recoverAfterInstallFailure = vi.fn(async () => undefined);
  const watchdogs: Array<() => void> = [];
  const scheduleInstallWatchdog = vi.fn((callback: () => void) => { watchdogs.push(callback); return vi.fn(); });
  const controllerOptions = { currentVersion: options.currentVersion ?? "0.1.0", platform, arch: "x64", isPackaged: options.isPackaged ?? true, stagingRoot: root, autoUpdater, openPath, beforeInstall, recoverAfterInstallFailure, fetch: fetch as typeof globalThis.fetch, networkTimeoutMs: options.networkTimeoutMs, inactivityTimeoutMs: options.inactivityTimeoutMs, scheduleInstallWatchdog };
  const createController = () => new UpdateController(controllerOptions);
  const controller = createController();
  return { root, controller, createController, fetch, autoUpdater, openPath, beforeInstall, recoverAfterInstallFailure, scheduleInstallWatchdog, watchdogs };
}

function response(body: string | Uint8Array): Response {
  const bytes = typeof body === "string" ? Buffer.from(body) : body;
  return new Response(bytes, { status: 200, headers: { "content-length": String(bytes.byteLength) } });
}
