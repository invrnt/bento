import { createHash, KeyObject, randomBytes } from "node:crypto";
import { createReadStream } from "node:fs";
import { chmod, lstat, mkdir, open, readdir, readFile, rename, rm, unlink, writeFile } from "node:fs/promises";
import { createServer, Server } from "node:http";
import path from "node:path";
import { EventEmitter } from "node:events";
import { UpdateInstallMode, UpdateInstallResult, UpdateState } from "../shared/contracts";
import { MAX_UPDATE_SIGNATURE_BYTES, parseUpdatePublicKey, UPDATE_SIGNATURE_SUFFIX, verifyUpdateManifestSignature } from "./update-signature";

const OWNER = "invrnt";
const REPOSITORY = "bento";
const API_URL = `https://api.github.com/repos/${OWNER}/${REPOSITORY}/releases/latest`;
const MAX_MANIFEST_BYTES = 512 * 1024;
const MAX_RELEASE_BYTES = 1536 * 1024 * 1024;
const MAX_RELEASE_NOTES = 20_000;
const MAX_REDIRECTS = 5;
const INSTALL_TIMEOUT_MS = 120_000;
const QUIT_WATCHDOG_MS = 30_000;
const NETWORK_TIMEOUT_MS = 20_000;
const INACTIVITY_TIMEOUT_MS = 30_000;
const METADATA_NAME = "download.json";
const METADATA_SCHEMA_VERSION = 1;
const MAX_METADATA_BYTES = 64 * 1024;
const SHA256 = /^[a-f0-9]{64}$/u;
const SEMVER = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/u;

interface ReleaseAsset {
  name: string;
  state: string;
  size: number;
  digest?: string | null;
  browser_download_url: string;
}

interface GitHubRelease {
  tag_name: string;
  name?: string | null;
  body?: string | null;
  draft: boolean;
  prerelease: boolean;
  published_at?: string | null;
  html_url: string;
  assets: ReleaseAsset[];
}

interface UpdateArtifact {
  platform: "darwin" | "win32" | "linux";
  arch: "x64" | "arm64";
  kind: string;
  filename: string;
  url: string;
  sha256: string;
  size: number;
}

interface UpdateManifest {
  schemaVersion: 1;
  version: string;
  repository: string;
  target: string;
  publishedAt: string;
  commit: string;
  assets: UpdateArtifact[];
  squirrel?: {
    nupkg: { filename: string; url: string; sha1: string; sha256: string; size: number };
    releasesContent: string;
  };
}

interface Candidate {
  version: string;
  artifact: UpdateArtifact;
  asset: ReleaseAsset;
  release: GitHubRelease;
  expectedSha1?: string;
}

interface DownloadedCandidate extends Candidate {
  filePath: string;
  sha1: string;
}

interface DownloadMetadata {
  schemaVersion: 1;
  version: string;
  platform: "darwin" | "win32" | "linux";
  arch: "x64" | "arm64";
  artifact: UpdateArtifact;
  sha1: string;
  release: { name?: string; notes?: string; publishedAt?: string; url: string };
}

interface AutoUpdaterLike {
  setFeedURL(options: { url: string; headers?: Record<string, string>; serverType?: string }): void;
  checkForUpdates(): void;
  quitAndInstall(): void;
  once(event: "update-downloaded", listener: (...args: unknown[]) => void): this;
  once(event: "update-not-available", listener: (...args: unknown[]) => void): this;
  once(event: "error", listener: (error: Error) => void): this;
  once(event: "before-quit-for-update", listener: (...args: unknown[]) => void): this;
  removeListener(event: string, listener: (...args: never[]) => void): this;
}

export interface UpdateControllerOptions {
  currentVersion: string;
  platform: NodeJS.Platform;
  arch: string;
  isPackaged: boolean;
  stagingRoot: string;
  autoUpdater: AutoUpdaterLike;
  openPath: (filePath: string) => Promise<string>;
  beforeInstall: () => Promise<void>;
  recoverAfterInstallFailure?: () => Promise<void>;
  fetch?: typeof globalThis.fetch;
  /**
   * Ed25519 key embedded at build time (base64 of the raw 32 bytes). When present, every manifest
   * must carry a valid `<manifest>.sig`; `null` means a key was configured but is unusable, which
   * fails closed. Absent keeps hash-only verification and warns once.
   */
  updatePublicKey?: string | null;
  warn?: (message: string) => void;
  now?: () => number;
  networkTimeoutMs?: number;
  inactivityTimeoutMs?: number;
  scheduleInstallWatchdog?: (callback: () => void, delayMs: number) => () => void;
}

export class UpdateController extends EventEmitter {
  private stateValue: UpdateState;
  private candidate: Candidate | null = null;
  private downloaded: DownloadedCandidate | null = null;
  private busy: "check" | "download" | "install" | null = null;
  private initialization: Promise<UpdateState> | null = null;
  private readonly fetchImpl: typeof globalThis.fetch;
  private readonly now: () => number;
  private readonly trust: { key: KeyObject } | { key: null; configured: boolean };
  private warnedUnsigned = false;

  constructor(private readonly options: UpdateControllerOptions) {
    super();
    if (!isStrictSemver(options.currentVersion)) throw new Error("The packaged application version is not valid semver");
    this.fetchImpl = options.fetch ?? globalThis.fetch;
    this.now = options.now ?? Date.now;
    const key = typeof options.updatePublicKey === "string" ? parseUpdatePublicKey(options.updatePublicKey) : null;
    this.trust = key ? { key } : { key: null, configured: options.updatePublicKey !== undefined };
    this.stateValue = {
      status: "idle",
      currentVersion: options.currentVersion,
      installMode: installMode(options.platform, options.isPackaged),
    };
  }

  get state(): UpdateState {
    return structuredClone(this.stateValue);
  }

  initialize(): Promise<UpdateState> {
    this.initialization ??= this.initializeOnce();
    return this.initialization;
  }

  private async initializeOnce(): Promise<UpdateState> {
    if (!this.options.isPackaged || !supportedPlatform(this.options.platform, this.options.arch)) return this.state;
    try {
      const restored = await restoreDownloaded(this.options);
      if (restored) {
        this.downloaded = restored;
        this.candidate = restored;
        this.update(downloadedState(restored));
      }
    } catch {
      this.update({ status: "error", progress: undefined, error: { code: "updates_staging_invalid" } });
    }
    return this.state;
  }

  async check(): Promise<UpdateState> {
    await this.initialization;
    this.begin("check");
    this.candidate = null;
    this.update({ status: "checking", progress: undefined, error: undefined });
    try {
      if (!this.options.isPackaged) throw updaterError("updates_development_build");
      if (!supportedPlatform(this.options.platform, this.options.arch)) throw updaterError("updates_platform_unsupported");
      const release = await this.fetchJson<GitHubRelease>(API_URL, 2 * MAX_MANIFEST_BYTES, "api");
      const candidate = await this.validateRelease(release);
      if (compareSemver(candidate.version, this.options.currentVersion) <= 0) {
        this.update({
          status: "not-available",
          availableVersion: undefined,
          releaseName: undefined,
          releaseNotes: undefined,
          releaseDate: undefined,
          releaseUrl: undefined,
        });
        return this.state;
      }
      this.candidate = candidate;
      if (this.downloaded?.version === candidate.version) {
        this.update(downloadedState(this.downloaded));
        return this.state;
      }
      this.update({
        status: "available",
        availableVersion: candidate.version,
        releaseName: boundedText(release.name ?? release.tag_name, 200),
        releaseNotes: boundedText(release.body ?? "", MAX_RELEASE_NOTES) || undefined,
        releaseDate: validDate(release.published_at) ? release.published_at! : undefined,
        releaseUrl: validateReleasePage(release.html_url),
      });
      return this.state;
    } catch (error) {
      if (this.downloaded) this.update({ ...downloadedState(this.downloaded), error: { code: safeErrorCode(error) } });
      else this.fail(error);
      return this.state;
    } finally {
      this.busy = null;
    }
  }

  async download(): Promise<UpdateState> {
    await this.initialization;
    this.begin("download");
    try {
      if (!this.candidate || this.stateValue.status !== "available") throw updaterError("updates_nothing_to_download");
      const candidate = this.candidate;
      const destinationDirectory = path.join(this.options.stagingRoot, candidate.version);
      await mkdir(destinationDirectory, { recursive: true, mode: 0o700 });
      const destination = path.join(destinationDirectory, candidate.artifact.filename);
      const temporary = `${destination}.part`;
      await unlink(temporary).catch(ignoreMissing);
      this.update({
        status: "downloading",
        error: undefined,
        progress: { percent: 0, transferredBytes: 0, totalBytes: candidate.artifact.size, bytesPerSecond: 0 },
      });
      const hashes = await this.downloadArtifact(candidate, temporary);
      if (candidate.expectedSha1 && hashes.sha1 !== candidate.expectedSha1) {
        await unlink(temporary).catch(() => undefined);
        throw updaterError("updates_artifact_checksum_mismatch");
      }
      await replaceFile(temporary, destination);
      this.downloaded = { ...candidate, filePath: destination, sha1: hashes.sha1 };
      await persistDownloaded(this.options.stagingRoot, this.downloaded);
      await cleanupStaging(this.options.stagingRoot, this.downloaded);
      this.update(downloadedState(this.downloaded, this.stateValue.progress?.bytesPerSecond));
      return this.state;
    } catch (error) {
      this.fail(error);
      return this.state;
    } finally {
      this.busy = null;
    }
  }

  async install(): Promise<UpdateInstallResult> {
    await this.initialization;
    this.begin("install");
    try {
      if (!this.downloaded || this.stateValue.status !== "downloaded") throw updaterError("updates_not_downloaded");
      if (!await verifyDownloadedFile(this.downloaded)) throw updaterError("updates_staging_invalid");
      if (this.stateValue.installMode === "manual") {
        this.update({ status: "installing", error: undefined });
        const failure = await this.options.openPath(this.downloaded.filePath);
        if (failure) throw updaterError("updates_package_manager_failed");
        this.update({ status: "downloaded" });
        return { action: "manual", packageManager: "system-package-installer" };
      }
      if (this.stateValue.installMode !== "automatic") throw updaterError("updates_install_unsupported");
      this.update({ status: "installing", error: undefined });
      await this.stageWithAutoUpdater(this.downloaded);
      const updater = this.options.autoUpdater;
      let quitObserved = false;
      let cancelWatchdog = (): void => undefined;
      const beforeQuit = (): void => { quitObserved = true; cancelWatchdog(); };
      updater.once("before-quit-for-update", beforeQuit);
      try {
        await this.options.beforeInstall();
        updater.quitAndInstall();
        if (!quitObserved) {
          cancelWatchdog = this.scheduleWatchdog(() => {
            updater.removeListener("before-quit-for-update", beforeQuit as never);
            void Promise.resolve(this.options.recoverAfterInstallFailure?.())
              .catch(() => undefined)
              .finally(() => this.fail(updaterError("updates_install_did_not_exit")));
          });
        }
      } catch {
        cancelWatchdog();
        updater.removeListener("before-quit-for-update", beforeQuit as never);
        await Promise.resolve(this.options.recoverAfterInstallFailure?.()).catch(() => undefined);
        throw updaterError("updates_auto_updater_failed");
      }
      return { action: "restarting" };
    } catch (error) {
      this.fail(error);
      throw error;
    } finally {
      this.busy = null;
    }
  }

  private async validateRelease(release: GitHubRelease): Promise<Candidate> {
    if (!release || typeof release !== "object" || release.draft || release.prerelease || !Array.isArray(release.assets)) {
      throw updaterError("updates_release_invalid");
    }
    const version = normalizeTag(release.tag_name);
    if (!version || !isStrictSemver(version)) throw updaterError("updates_version_invalid");
    validateReleasePage(release.html_url, version);
    const manifestAsset = uniqueAsset(release.assets, manifestName(this.options.platform, this.options.arch));
    validateAssetMetadata(manifestAsset, MAX_MANIFEST_BYTES, version);
    const expectedManifestDigest = githubDigest(manifestAsset.digest);
    const manifestBytes = await this.fetchBytes(manifestAsset.browser_download_url, MAX_MANIFEST_BYTES, "asset");
    if (sha256(manifestBytes) !== expectedManifestDigest) throw updaterError("updates_manifest_checksum_mismatch");
    await this.verifyManifestSignature(release, manifestAsset.name, version, manifestBytes);
    let manifest: unknown;
    try {
      manifest = JSON.parse(new TextDecoder().decode(manifestBytes));
    } catch {
      throw updaterError("updates_manifest_invalid");
    }
    const validated = validateManifest(manifest, version, this.options.platform, this.options.arch);
    const artifact = selectArtifact(validated.assets, this.options.platform);
    const asset = uniqueAsset(release.assets, artifact.filename);
    validateAssetMetadata(asset, MAX_RELEASE_BYTES, version);
    if (asset.size !== artifact.size || githubDigest(asset.digest) !== artifact.sha256 || asset.browser_download_url !== artifact.url) {
      throw updaterError("updates_artifact_metadata_mismatch");
    }
    if (this.options.platform === "win32") validateSquirrel(validated, artifact);
    return { version, artifact, asset, release, expectedSha1: validated.squirrel?.nupkg.sha1 };
  }

  /** Signature check before the manifest is parsed; GitHub digests alone do not survive a release takeover. */
  private async verifyManifestSignature(release: GitHubRelease, manifest: string, version: string, manifestBytes: Uint8Array): Promise<void> {
    if (!this.trust.key) {
      if (this.trust.configured) throw updaterError("updates_signature_key_invalid");
      if (!this.warnedUnsigned) {
        this.warnedUnsigned = true;
        this.options.warn?.("update manifest signatures are not verified: this build has no update public key");
      }
      return;
    }
    const signatureName = `${manifest}${UPDATE_SIGNATURE_SUFFIX}`;
    const matches = release.assets.filter((item) => item?.name === signatureName && item.state === "uploaded");
    if (matches.length !== 1) throw updaterError("updates_signature_missing");
    const asset = matches[0]!;
    validateAssetMetadata(asset, MAX_UPDATE_SIGNATURE_BYTES, version);
    const signature = await this.fetchBytes(asset.browser_download_url, MAX_UPDATE_SIGNATURE_BYTES, "asset");
    if (sha256(signature) !== githubDigest(asset.digest) || !verifyUpdateManifestSignature(manifestBytes, signature, this.trust.key)) {
      throw updaterError("updates_signature_invalid");
    }
  }

  private async downloadArtifact(candidate: Candidate, temporary: string): Promise<{ sha1: string }> {
    const abort = new AbortController();
    const response = await this.safeFetch(candidate.asset.browser_download_url, "asset", abort);
    if (!response.ok || !response.body) { abort.abort(); throw updaterError("updates_download_failed"); }
    const declared = contentLength(response.headers.get("content-length"));
    if (declared !== null && declared !== candidate.artifact.size) { abort.abort(); throw updaterError("updates_artifact_size_mismatch"); }
    const file = await open(temporary, "w", 0o600);
    const digest = createHash("sha256");
    const legacyDigest = createHash("sha1");
    const started = this.now();
    let transferred = 0;
    try {
      const reader = response.body.getReader();
      while (true) {
        const { done, value } = await readWithInactivity(reader, abort, this.options.inactivityTimeoutMs ?? INACTIVITY_TIMEOUT_MS);
        if (done) break;
        transferred += value.byteLength;
        if (transferred > candidate.artifact.size || transferred > MAX_RELEASE_BYTES) {
          throw updaterError("updates_artifact_too_large");
        }
        digest.update(value);
        legacyDigest.update(value);
        await file.write(value);
        const elapsedSeconds = Math.max((this.now() - started) / 1000, 0.001);
        this.update({
          status: "downloading",
          progress: {
            percent: Math.min(99.9, transferred / candidate.artifact.size * 100),
            transferredBytes: transferred,
            totalBytes: candidate.artifact.size,
            bytesPerSecond: Math.round(transferred / elapsedSeconds),
          },
        });
      }
    } catch (error) {
      abort.abort();
      await file.close();
      await unlink(temporary).catch(() => undefined);
      throw error;
    }
    await file.close();
    if (transferred !== candidate.artifact.size) {
      await unlink(temporary).catch(() => undefined);
      throw updaterError("updates_artifact_size_mismatch");
    }
    if (digest.digest("hex") !== candidate.artifact.sha256) {
      await unlink(temporary).catch(() => undefined);
      throw updaterError("updates_artifact_checksum_mismatch");
    }
    return { sha1: legacyDigest.digest("hex") };
  }

  private async stageWithAutoUpdater(downloaded: DownloadedCandidate): Promise<void> {
    const token = randomBytes(24).toString("hex");
    const server = await localFeed(downloaded, token);
    const address = server.address();
    if (!address || typeof address === "string") {
      await closeServer(server);
      throw updaterError("updates_feed_failed");
    }
    const base = `http://127.0.0.1:${address.port}/${token}`;
    const updater = this.options.autoUpdater;
    try {
      updater.setFeedURL({
        url: this.options.platform === "darwin" ? `${base}/feed.json` : base,
        ...(this.options.platform === "darwin" ? { serverType: "json" } : {}),
      });
      await waitForUpdater(updater);
    } finally {
      await closeServer(server);
    }
  }

  private async fetchJson<T>(url: string, maximum: number, kind: "api" | "asset"): Promise<T> {
    const bytes = await this.fetchBytes(url, maximum, kind);
    try {
      return JSON.parse(new TextDecoder().decode(bytes)) as T;
    } catch {
      throw updaterError("updates_response_invalid");
    }
  }

  private async fetchBytes(url: string, maximum: number, kind: "api" | "asset"): Promise<Uint8Array> {
    const abort = new AbortController();
    const response = await this.safeFetch(url, kind, abort);
    if (!response.ok || !response.body) { abort.abort(); throw updaterError("updates_network_failed"); }
    const declared = contentLength(response.headers.get("content-length"));
    if (declared !== null && declared > maximum) { abort.abort(); throw updaterError("updates_response_too_large"); }
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    let total = 0;
    try {
      while (true) {
        const { done, value } = await readWithInactivity(reader, abort, this.options.inactivityTimeoutMs ?? INACTIVITY_TIMEOUT_MS);
        if (done) break;
        total += value.byteLength;
        if (total > maximum) throw updaterError("updates_response_too_large");
        chunks.push(value);
      }
    } catch (error) {
      abort.abort();
      void reader.cancel().catch(() => undefined);
      throw error;
    }
    const result = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.byteLength; }
    return result;
  }

  private async safeFetch(initial: string, kind: "api" | "asset", abort: AbortController): Promise<Response> {
    let url = initial;
    for (let redirect = 0; redirect <= MAX_REDIRECTS; redirect += 1) {
      validateRemoteUrl(url, kind, redirect > 0);
      const timeout = setTimeout(() => abort.abort(), this.options.networkTimeoutMs ?? NETWORK_TIMEOUT_MS);
      let response: Response;
      try {
        response = await this.fetchImpl(url, {
          redirect: "manual",
          signal: abort.signal,
          headers: {
            Accept: kind === "api" ? "application/vnd.github+json" : "application/octet-stream",
            "User-Agent": `Bento/${this.options.currentVersion}`,
            ...(kind === "api" ? { "X-GitHub-Api-Version": "2022-11-28" } : {}),
          },
        });
      } catch {
        if (abort.signal.aborted) throw updaterError("updates_network_timeout");
        throw updaterError("updates_network_failed");
      } finally {
        clearTimeout(timeout);
      }
      if (![301, 302, 303, 307, 308].includes(response.status)) return response;
      const location = response.headers.get("location");
      if (!location) throw updaterError("updates_redirect_invalid");
      void response.body?.cancel().catch(() => undefined);
      url = new URL(location, url).toString();
    }
    throw updaterError("updates_too_many_redirects");
  }

  private begin(operation: typeof this.busy): void {
    if (this.busy) throw updaterError("updates_operation_in_progress");
    this.busy = operation;
  }

  private scheduleWatchdog(callback: () => void): () => void {
    if (this.options.scheduleInstallWatchdog) return this.options.scheduleInstallWatchdog(callback, QUIT_WATCHDOG_MS);
    const timeout = setTimeout(callback, QUIT_WATCHDOG_MS);
    return () => clearTimeout(timeout);
  }

  private update(patch: Partial<UpdateState>): void {
    this.stateValue = { ...this.stateValue, ...patch };
    this.emit("state", this.state);
  }

  private fail(error: unknown): void {
    const code = error instanceof UpdateError ? error.code : "updates_unexpected_error";
    this.update({ status: "error", progress: undefined, error: { code } });
  }
}

class UpdateError extends Error {
  constructor(readonly code: string) { super(code); }
}

function updaterError(code: string): UpdateError { return new UpdateError(code); }

function installMode(platform: NodeJS.Platform, packaged: boolean): UpdateInstallMode {
  if (!packaged) return "unsupported";
  if (platform === "darwin" || platform === "win32") return "automatic";
  if (platform === "linux") return "manual";
  return "unsupported";
}

function supportedPlatform(platform: NodeJS.Platform, arch: string): boolean {
  return ["darwin", "win32", "linux"].includes(platform) && ["x64", "arm64"].includes(arch);
}

export function isStrictSemver(value: string): boolean { return SEMVER.test(value); }

export function compareSemver(left: string, right: string): number {
  if (!isStrictSemver(left) || !isStrictSemver(right)) throw updaterError("updates_version_invalid");
  const a = left.split(".").map(Number);
  const b = right.split(".").map(Number);
  for (let index = 0; index < 3; index += 1) {
    if (a[index]! !== b[index]!) return a[index]! > b[index]! ? 1 : -1;
  }
  return 0;
}

export async function prepareForUpdateInstall(markQuitting: () => void, stopRuntime: () => Promise<void>): Promise<void> {
  markQuitting();
  await stopRuntime();
}

function downloadedState(downloaded: DownloadedCandidate, bytesPerSecond?: number): Partial<UpdateState> {
  return {
    status: "downloaded",
    availableVersion: downloaded.version,
    releaseName: boundedText(downloaded.release.name ?? downloaded.release.tag_name, 200),
    releaseNotes: boundedText(downloaded.release.body ?? "", MAX_RELEASE_NOTES) || undefined,
    releaseDate: validDate(downloaded.release.published_at) ? downloaded.release.published_at! : undefined,
    releaseUrl: validateReleasePage(downloaded.release.html_url, downloaded.version),
    progress: { percent: 100, transferredBytes: downloaded.artifact.size, totalBytes: downloaded.artifact.size, bytesPerSecond },
    error: undefined,
  };
}

async function persistDownloaded(stagingRoot: string, downloaded: DownloadedCandidate): Promise<void> {
  const metadata: DownloadMetadata = {
    schemaVersion: METADATA_SCHEMA_VERSION,
    version: downloaded.version,
    platform: downloaded.artifact.platform,
    arch: downloaded.artifact.arch,
    artifact: downloaded.artifact,
    sha1: downloaded.sha1,
    release: {
      name: boundedText(downloaded.release.name ?? downloaded.release.tag_name, 200),
      notes: boundedText(downloaded.release.body ?? "", MAX_RELEASE_NOTES) || undefined,
      publishedAt: validDate(downloaded.release.published_at) ? downloaded.release.published_at! : undefined,
      url: validateReleasePage(downloaded.release.html_url, downloaded.version),
    },
  };
  const directory = path.join(stagingRoot, downloaded.version);
  const destination = path.join(directory, METADATA_NAME);
  const temporary = `${destination}.part`;
  try {
    await writeFile(temporary, `${JSON.stringify(metadata)}\n`, { encoding: "utf8", mode: 0o600, flag: "w" });
    await chmod(temporary, 0o600);
    await replaceFile(temporary, destination);
  } catch (error) {
    await unlink(temporary).catch(ignoreMissing);
    throw error;
  }
}

async function restoreDownloaded(options: UpdateControllerOptions): Promise<DownloadedCandidate | null> {
  await mkdir(options.stagingRoot, { recursive: true, mode: 0o700 });
  const rootInfo = await lstat(options.stagingRoot);
  if (!rootInfo.isDirectory() || rootInfo.isSymbolicLink()) throw updaterError("updates_staging_invalid");
  await chmod(options.stagingRoot, 0o700);
  const restored: DownloadedCandidate[] = [];
  for (const entry of await readdir(options.stagingRoot, { withFileTypes: true })) {
    const entryPath = path.join(options.stagingRoot, entry.name);
    if (!entry.isDirectory() || entry.isSymbolicLink()) {
      await rm(entryPath, { recursive: true, force: true });
      continue;
    }
    try {
      const candidate = await restoreDirectory(entryPath, entry.name, options);
      if (candidate) restored.push(candidate);
      else await rm(entryPath, { recursive: true, force: true });
    } catch {
      await rm(entryPath, { recursive: true, force: true });
    }
  }
  restored.sort((left, right) => compareSemver(right.version, left.version));
  const selected = restored[0] ?? null;
  await cleanupStaging(options.stagingRoot, selected);
  return selected;
}

async function restoreDirectory(directory: string, directoryName: string, options: UpdateControllerOptions): Promise<DownloadedCandidate | null> {
  if (!isStrictSemver(directoryName) || compareSemver(directoryName, options.currentVersion) <= 0) return null;
  const metadataPath = path.join(directory, METADATA_NAME);
  const metadataInfo = await lstat(metadataPath);
  if (!metadataInfo.isFile() || metadataInfo.isSymbolicLink() || metadataInfo.size <= 0 || metadataInfo.size > MAX_METADATA_BYTES) return null;
  const value = JSON.parse(await readFile(metadataPath, "utf8")) as unknown;
  const metadata = validateDownloadMetadata(value, directoryName, options.platform, options.arch);
  const filePath = path.join(directory, metadata.artifact.filename);
  if (path.dirname(filePath) !== directory) return null;
  const fileInfo = await lstat(filePath);
  if (!fileInfo.isFile() || fileInfo.isSymbolicLink() || fileInfo.size !== metadata.artifact.size) return null;
  const hashes = await hashFile(filePath);
  if (hashes.sha256 !== metadata.artifact.sha256 || hashes.sha1 !== metadata.sha1) return null;
  const release: GitHubRelease = {
    tag_name: `v${metadata.version}`,
    name: metadata.release.name,
    body: metadata.release.notes,
    draft: false,
    prerelease: false,
    published_at: metadata.release.publishedAt,
    html_url: metadata.release.url,
    assets: [],
  };
  const asset: ReleaseAsset = {
    name: metadata.artifact.filename,
    state: "uploaded",
    size: metadata.artifact.size,
    digest: `sha256:${metadata.artifact.sha256}`,
    browser_download_url: metadata.artifact.url,
  };
  return { version: metadata.version, artifact: metadata.artifact, asset, release, expectedSha1: metadata.sha1, filePath, sha1: metadata.sha1 };
}

function validateDownloadMetadata(value: unknown, directoryName: string, platform: NodeJS.Platform, arch: string): DownloadMetadata {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw updaterError("updates_staging_invalid");
  const metadata = value as Partial<DownloadMetadata>;
  if (metadata.schemaVersion !== METADATA_SCHEMA_VERSION || metadata.version !== directoryName || !isStrictSemver(metadata.version) ||
    metadata.platform !== platform || metadata.arch !== arch || !metadata.artifact || metadata.artifact.platform !== platform ||
    metadata.artifact.arch !== arch || typeof metadata.artifact.kind !== "string" || metadata.artifact.kind.length > 40 ||
    typeof metadata.artifact.filename !== "string" || !safeAssetName(metadata.artifact.filename) ||
    typeof metadata.artifact.url !== "string" || typeof metadata.artifact.sha256 !== "string" || !SHA256.test(metadata.artifact.sha256) ||
    !Number.isSafeInteger(metadata.artifact.size) || metadata.artifact.size <= 0 || metadata.artifact.size > MAX_RELEASE_BYTES ||
    !validArtifactExtension(metadata.artifact.kind, metadata.artifact.platform, metadata.artifact.filename) ||
    typeof metadata.sha1 !== "string" || !/^[a-f0-9]{40}$/u.test(metadata.sha1) || !metadata.release ||
    typeof metadata.release.url !== "string" || (metadata.release.name !== undefined && (typeof metadata.release.name !== "string" || metadata.release.name.length > 200)) ||
    (metadata.release.notes !== undefined && (typeof metadata.release.notes !== "string" || metadata.release.notes.length > MAX_RELEASE_NOTES)) ||
    (metadata.release.publishedAt !== undefined && !validDate(metadata.release.publishedAt))) {
    throw updaterError("updates_staging_invalid");
  }
  if ((metadata.release.name !== undefined && boundedText(metadata.release.name, 200) !== metadata.release.name) ||
    (metadata.release.notes !== undefined && boundedText(metadata.release.notes, MAX_RELEASE_NOTES) !== metadata.release.notes)) {
    throw updaterError("updates_staging_invalid");
  }
  validateAssetDownloadUrl(metadata.artifact.url, metadata.artifact.filename, metadata.version);
  validateReleasePage(metadata.release.url, metadata.version);
  return metadata as DownloadMetadata;
}

async function hashFile(filePath: string): Promise<{ sha256: string; sha1: string }> {
  const strong = createHash("sha256");
  const legacy = createHash("sha1");
  await new Promise<void>((resolve, reject) => {
    const stream = createReadStream(filePath);
    stream.on("data", (chunk) => { strong.update(chunk); legacy.update(chunk); });
    stream.once("error", reject);
    stream.once("end", resolve);
  });
  return { sha256: strong.digest("hex"), sha1: legacy.digest("hex") };
}

async function verifyDownloadedFile(downloaded: DownloadedCandidate): Promise<boolean> {
  try {
    const info = await lstat(downloaded.filePath);
    if (!info.isFile() || info.isSymbolicLink() || info.size !== downloaded.artifact.size) return false;
    const hashes = await hashFile(downloaded.filePath);
    return hashes.sha256 === downloaded.artifact.sha256 && hashes.sha1 === downloaded.sha1;
  } catch {
    return false;
  }
}

async function cleanupStaging(stagingRoot: string, keep: DownloadedCandidate | null): Promise<void> {
  for (const entry of await readdir(stagingRoot, { withFileTypes: true })) {
    const entryPath = path.join(stagingRoot, entry.name);
    if (!keep || entry.name !== keep.version || !entry.isDirectory() || entry.isSymbolicLink()) {
      await rm(entryPath, { recursive: true, force: true });
      continue;
    }
    for (const child of await readdir(entryPath, { withFileTypes: true })) {
      if (child.name !== METADATA_NAME && child.name !== keep.artifact.filename) {
        await rm(path.join(entryPath, child.name), { recursive: true, force: true });
      }
    }
  }
}

async function replaceFile(source: string, destination: string): Promise<void> {
  await unlink(destination).catch(ignoreMissing);
  await rename(source, destination);
}

function ignoreMissing(error: unknown): void {
  if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
}

function safeErrorCode(error: unknown): string {
  return error instanceof UpdateError ? error.code : "updates_unexpected_error";
}

function normalizeTag(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const normalized = value.startsWith("v") ? value.slice(1) : value;
  return isStrictSemver(normalized) && (value === normalized || value === `v${normalized}`) ? normalized : null;
}

function manifestName(platform: NodeJS.Platform, arch: string): string {
  if (!supportedPlatform(platform, arch)) throw updaterError("updates_platform_unsupported");
  return `bento-update-${platform}-${arch}.json`;
}

function validateManifest(value: unknown, releaseVersion: string, platform: NodeJS.Platform, arch: string): UpdateManifest {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw updaterError("updates_manifest_invalid");
  const manifest = value as Partial<UpdateManifest>;
  if (manifest.schemaVersion !== 1 || manifest.version !== releaseVersion || manifest.repository !== `${OWNER}/${REPOSITORY}` ||
    manifest.target !== `${platform}-${arch}` || !validDate(manifest.publishedAt) ||
    typeof manifest.commit !== "string" || !/^[a-f0-9]{40}$/u.test(manifest.commit) ||
    !Array.isArray(manifest.assets) || manifest.assets.length === 0 || manifest.assets.length > 8) {
    throw updaterError("updates_manifest_invalid");
  }
  const assets = manifest.assets.map((item) => {
    if (!item || item.platform !== platform || item.arch !== arch || typeof item.kind !== "string" || item.kind.length > 40 ||
      typeof item.filename !== "string" || !safeAssetName(item.filename) || typeof item.url !== "string" ||
      typeof item.sha256 !== "string" || !SHA256.test(item.sha256) || !Number.isSafeInteger(item.size) || item.size <= 0 ||
      item.size > MAX_RELEASE_BYTES || !validArtifactExtension(item.kind, item.platform, item.filename)) {
      throw updaterError("updates_manifest_invalid");
    }
    validateAssetDownloadUrl(item.url, item.filename, releaseVersion);
    return item;
  });
  if (new Set(assets.map((item) => item.filename)).size !== assets.length || new Set(assets.map((item) => item.kind)).size !== assets.length) {
    throw updaterError("updates_manifest_invalid");
  }
  return { ...manifest, schemaVersion: 1, version: releaseVersion, assets } as UpdateManifest;
}

function selectArtifact(artifacts: UpdateArtifact[], platform: NodeJS.Platform): UpdateArtifact {
  const expectedKind = platform === "darwin" ? "update-archive" : platform === "win32" ? "squirrel-package" : "installer";
  const matches = artifacts.filter((item) => item.kind === expectedKind);
  if (matches.length !== 1) throw updaterError("updates_artifact_unavailable");
  return matches[0]!;
}

function validateSquirrel(manifest: UpdateManifest, artifact: UpdateArtifact): void {
  const squirrel = manifest.squirrel;
  if (!squirrel || !squirrel.nupkg || typeof squirrel.releasesContent !== "string" || squirrel.releasesContent.length > 1024) {
    throw updaterError("updates_manifest_invalid");
  }
  const nupkg = squirrel.nupkg;
  if (nupkg.filename !== artifact.filename || nupkg.url !== artifact.url || nupkg.sha256 !== artifact.sha256 ||
    nupkg.size !== artifact.size || typeof nupkg.sha1 !== "string" || !/^[a-f0-9]{40}$/u.test(nupkg.sha1)) {
    throw updaterError("updates_manifest_invalid");
  }
  const line = /^([A-F0-9]{40}) (https:\/\/[^\s]+) (\d+)\n$/u.exec(squirrel.releasesContent);
  if (!line || line[1]!.toLowerCase() !== nupkg.sha1 || line[2] !== nupkg.url || Number(line[3]) !== nupkg.size) {
    throw updaterError("updates_manifest_invalid");
  }
}

function uniqueAsset(assets: ReleaseAsset[], name: string): ReleaseAsset {
  const matches = assets.filter((item) => item?.name === name && item.state === "uploaded");
  if (matches.length !== 1) throw updaterError("updates_asset_invalid");
  return matches[0]!;
}

function validateAssetMetadata(asset: ReleaseAsset, maximum: number, version: string): void {
  if (!safeAssetName(asset.name) || !Number.isSafeInteger(asset.size) || asset.size <= 0 || asset.size > maximum) {
    throw updaterError("updates_asset_invalid");
  }
  validateAssetDownloadUrl(asset.browser_download_url, asset.name, version);
  githubDigest(asset.digest);
}

function validArtifactExtension(kind: string, platform: string, name: string): boolean {
  if (platform === "darwin") return (kind === "update-archive" && name.endsWith(".zip")) || (kind === "installer" && name.endsWith(".dmg"));
  if (platform === "win32") return (kind === "squirrel-package" && name.endsWith("-full.nupkg")) ||
    (kind === "squirrel-releases" && name === "RELEASES") || (kind === "installer" && name.endsWith("Setup.exe"));
  return (kind === "installer" && name.endsWith(".deb")) || (kind === "portable-archive" && name.endsWith(".zip"));
}

function githubDigest(value: unknown): string {
  if (typeof value !== "string" || !value.startsWith("sha256:") || !SHA256.test(value.slice(7))) {
    throw updaterError("updates_digest_missing");
  }
  return value.slice(7);
}

function safeAssetName(value: string): boolean {
  return value.length > 0 && value.length <= 160 && value.trim() === value && !/[\\/\u0000-\u001f\u007f]/u.test(value) && value !== "." && value !== "..";
}

function validateAssetDownloadUrl(value: string, expectedName?: string, expectedVersion?: string): void {
  const url = new URL(value);
  if (url.protocol !== "https:" || url.username || url.password || url.host !== "github.com" ||
    !url.pathname.startsWith(`/${OWNER}/${REPOSITORY}/releases/download/`)) {
    throw updaterError("updates_url_rejected");
  }
  if (expectedVersion && !url.pathname.startsWith(`/${OWNER}/${REPOSITORY}/releases/download/v${expectedVersion}/`)) {
    throw updaterError("updates_url_rejected");
  }
  if (expectedName) {
    let basename: string;
    try { basename = decodeURIComponent(url.pathname.slice(url.pathname.lastIndexOf("/") + 1)); } catch { throw updaterError("updates_url_rejected"); }
    if (basename !== expectedName || !safeAssetName(basename)) throw updaterError("updates_url_rejected");
  }
}

function validateReleasePage(value: string, expectedVersion?: string): string {
  const url = new URL(value);
  if (url.protocol !== "https:" || url.username || url.password || url.origin !== "https://github.com" ||
    !url.pathname.startsWith(`/${OWNER}/${REPOSITORY}/releases/tag/`) || url.search || url.hash) {
    throw updaterError("updates_url_rejected");
  }
  if (expectedVersion && url.pathname !== `/${OWNER}/${REPOSITORY}/releases/tag/v${expectedVersion}`) throw updaterError("updates_url_rejected");
  return value;
}

function validateRemoteUrl(value: string, kind: "api" | "asset", redirected: boolean): void {
  const url = new URL(value);
  if (url.protocol !== "https:" || url.username || url.password) throw updaterError("updates_url_rejected");
  if (kind === "api") {
    if (value !== API_URL) throw updaterError("updates_url_rejected");
    return;
  }
  if (!redirected) return validateAssetDownloadUrl(value);
  const redirectHosts = new Set(["objects.githubusercontent.com", "release-assets.githubusercontent.com", "github-releases.githubusercontent.com"]);
  if (!redirectHosts.has(url.hostname)) throw updaterError("updates_redirect_rejected");
}

function contentLength(value: string | null): number | null {
  if (value === null) return null;
  if (!/^\d+$/u.test(value)) throw updaterError("updates_content_length_invalid");
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 0) throw updaterError("updates_content_length_invalid");
  return parsed;
}

async function readWithInactivity(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  abort: AbortController,
  timeoutMs: number,
): Promise<ReadableStreamReadResult<Uint8Array>> {
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      reader.read(),
      new Promise<never>((_resolve, reject) => {
        timeout = setTimeout(() => {
          reject(updaterError("updates_download_inactivity_timeout"));
          abort.abort();
          void reader.cancel().catch(() => undefined);
        }, timeoutMs);
      }),
    ]);
  } finally {
    if (timeout) clearTimeout(timeout);
  }
}

function sha256(value: Uint8Array): string { return createHash("sha256").update(value).digest("hex"); }

function validDate(value: unknown): boolean {
  return typeof value === "string" && value.length <= 64 && Number.isFinite(Date.parse(value));
}

function boundedText(value: string, maximum: number): string { return value.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/gu, "").slice(0, maximum); }

async function localFeed(downloaded: DownloadedCandidate, token: string): Promise<Server> {
  const server = createServer((request, response) => {
    if (request.method !== "GET" || !request.url) { response.writeHead(405).end(); return; }
    const pathname = new URL(request.url, "http://127.0.0.1").pathname;
    const root = `/${token}`;
    if (pathname === `${root}/feed.json` && downloaded.artifact.platform === "darwin") {
      const body = JSON.stringify({
        url: `http://127.0.0.1:${(server.address() as { port: number }).port}${root}/${encodeURIComponent(downloaded.artifact.filename)}`,
        name: downloaded.version,
        version: downloaded.version,
        pub_date: downloaded.release.published_at,
      });
      response.writeHead(200, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body), "Cache-Control": "no-store" });
      response.end(body);
      return;
    }
    if (pathname === `${root}/RELEASES` && downloaded.artifact.platform === "win32") {
      const body = `${downloaded.sha1.toUpperCase()} ${downloaded.artifact.filename} ${downloaded.artifact.size}\n`;
      response.writeHead(200, { "Content-Type": "text/plain", "Content-Length": Buffer.byteLength(body), "Cache-Control": "no-store" });
      response.end(body);
      return;
    }
    if (pathname === `${root}/${encodeURIComponent(downloaded.artifact.filename)}`) {
      response.writeHead(200, { "Content-Type": "application/octet-stream", "Content-Length": downloaded.artifact.size, "Cache-Control": "no-store" });
      createReadStream(downloaded.filePath).on("error", () => response.destroy()).pipe(response);
      return;
    }
    response.writeHead(404).end();
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  return server;
}

async function waitForUpdater(updater: AutoUpdaterLike): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const cleanup = (): void => {
      clearTimeout(timeout);
      updater.removeListener("update-downloaded", downloaded as never);
      updater.removeListener("update-not-available", unavailable as never);
      updater.removeListener("error", failed as never);
    };
    const downloaded = (): void => { cleanup(); resolve(); };
    const unavailable = (): void => { cleanup(); reject(updaterError("updates_staged_update_not_found")); };
    const failed = (): void => { cleanup(); reject(updaterError("updates_auto_updater_failed")); };
    const timeout = setTimeout(() => { cleanup(); reject(updaterError("updates_auto_updater_timeout")); }, INSTALL_TIMEOUT_MS);
    updater.once("update-downloaded", downloaded);
    updater.once("update-not-available", unavailable);
    updater.once("error", failed);
    try { updater.checkForUpdates(); } catch { cleanup(); reject(updaterError("updates_auto_updater_failed")); }
  });
}

async function closeServer(server: Server): Promise<void> {
  if (!server.listening) return;
  await new Promise<void>((resolve) => server.close(() => resolve()));
}
