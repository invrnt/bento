import { createHash, KeyObject } from "node:crypto";
import { EventEmitter } from "node:events";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { vi } from "vitest";
import { UpdateController } from "../../src/main/updater";
import { encodeUpdateSignature, signUpdateManifest } from "../../src/main/update-signature";

// Shared release/manifest fixture for the controlled updater and its background scheduler.
const roots: string[] = [];
export const artifactBytes = Buffer.from("verified bento package");
export const artifactName = "bento_0.2.0_amd64.deb";
export const artifactUrl = `https://github.com/invrnt/bento/releases/download/v0.2.0/${artifactName}`;
export const manifestName = "bento-update-linux-x64.json";
export const manifestUrl = `https://github.com/invrnt/bento/releases/download/v0.2.0/${manifestName}`;

export class FakeAutoUpdater extends EventEmitter {
  setFeedURL = vi.fn();
  checkForUpdates = vi.fn();
  quitAndInstall = vi.fn();
}

export async function cleanupUpdateFixtures(): Promise<void> {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
}

export interface FixtureOptions {
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
  /** Ed25519 keys that sign the manifest; a `<manifest>.sig` asset is published when given. */
  signWith?: KeyObject[];
  /** Replaces the published signature bytes (its GitHub digest still matches). */
  signatureBytes?: Buffer;
  corruptSignatureDigest?: boolean;
  updatePublicKey?: string | null;
}

export async function setup(options: FixtureOptions = {}) {
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
  const signatureBytes = options.signatureBytes ?? (options.signWith ? Buffer.from(encodeUpdateSignature(signUpdateManifest(manifestBytes, options.signWith))) : null);
  const signatureUrl = `${targetManifestUrl}.sig`;
  const signatureAssets = signatureBytes
    ? [{ name: `${targetManifestName}.sig`, state: "uploaded", size: signatureBytes.length, digest: `sha256:${options.corruptSignatureDigest ? "0".repeat(64) : createHash("sha256").update(signatureBytes).digest("hex")}`, browser_download_url: signatureUrl }]
    : [];
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
      ...signatureAssets,
      ...assets.map((asset) => ({ name: asset.filename, state: "uploaded", size: asset.size, digest: options.omitArtifactDigest ? null : `sha256:${asset.sha256}`, browser_download_url: asset.url })),
    ],
  };
  const fetch = vi.fn(async (input: string | URL | Request) => {
    const url = String(input);
    if (url.includes("api.github.com")) return response(JSON.stringify(release));
    if (url === targetManifestUrl) return response(manifestBytes);
    if (signatureBytes && url === signatureUrl) return response(signatureBytes);
    if (url === primaryUrl) return response(artifactBytes);
    throw new Error("unexpected request");
  });
  const autoUpdater = new FakeAutoUpdater();
  const openPath = vi.fn(async () => "");
  const beforeInstall = vi.fn(async () => undefined);
  const recoverAfterInstallFailure = vi.fn(async () => undefined);
  const watchdogs: Array<() => void> = [];
  const scheduleInstallWatchdog = vi.fn((callback: () => void) => { watchdogs.push(callback); return vi.fn(); });
  const warn = vi.fn();
  const controllerOptions = { currentVersion: options.currentVersion ?? "0.1.0", platform, arch: "x64", isPackaged: options.isPackaged ?? true, stagingRoot: root, autoUpdater, openPath, beforeInstall, recoverAfterInstallFailure, fetch: fetch as typeof globalThis.fetch, networkTimeoutMs: options.networkTimeoutMs, inactivityTimeoutMs: options.inactivityTimeoutMs, scheduleInstallWatchdog, updatePublicKey: options.updatePublicKey, warn };
  const createController = () => new UpdateController(controllerOptions);
  const controller = createController();
  return { root, controller, createController, fetch, autoUpdater, openPath, beforeInstall, recoverAfterInstallFailure, scheduleInstallWatchdog, watchdogs, warn, signatureUrl, manifestBytes };
}

function response(body: string | Uint8Array): Response {
  const bytes = typeof body === "string" ? Buffer.from(body) : body;
  return new Response(bytes, { status: 200, headers: { "content-length": String(bytes.byteLength) } });
}
