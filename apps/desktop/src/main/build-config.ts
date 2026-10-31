import { readFile } from "node:fs/promises";
import path from "node:path";

export const BUILD_CONFIG_FILE = "build-config.json";
export const BUILD_CONFIG_KEYS = [
  "BENTO_TELEGRAM_API_ID",
  "BENTO_TELEGRAM_API_HASH",
  "BENTO_RELAY_URL",
  "BENTO_PUBLIC_SITE_URL",
] as const;

export type BuildConfigKey = typeof BUILD_CONFIG_KEYS[number];
export type BuildConfig = Partial<Record<BuildConfigKey, string>>;

export interface BuildConfigResult {
  config: BuildConfig;
  /** Keys present but invalid; never contains values. */
  rejected: string[];
  source: "packaged" | "environment";
}

/** Always removed from the inherited environment; only desktop main may provide these. */
export const ALWAYS_STRIPPED_ENVIRONMENT = ["BENTO_DEVICE_WRAPPING_KEY", "BENTO_DEV_STORAGE_BACKEND"] as const;

const MAX_BUILD_CONFIG_BYTES = 64 * 1024;
const MAX_VALUE_LENGTH = 2048;
const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

interface ParseOptions {
  /** Unpackaged runs may point to a loopback relay/site over plain ws/http. */
  allowLoopbackInsecure: boolean;
}

export function parseBuildConfig(value: unknown, options: ParseOptions): Omit<BuildConfigResult, "source"> {
  const config: BuildConfig = {};
  const rejected: string[] = [];
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return { config, rejected: ["_document"] };
  }
  for (const [key, candidate] of Object.entries(value as Record<string, unknown>)) {
    if (!(BUILD_CONFIG_KEYS as readonly string[]).includes(key)) {
      rejected.push(/^[A-Z][A-Z0-9_]{0,63}$/u.test(key) ? key : "_unknown");
      continue;
    }
    const typedKey = key as BuildConfigKey;
    if (typeof candidate !== "string" || candidate.length === 0) {
      if (candidate !== undefined && candidate !== "") rejected.push(typedKey);
      continue;
    }
    if (validBuildValue(typedKey, candidate, options)) config[typedKey] = candidate;
    else rejected.push(typedKey);
  }
  return { config, rejected };
}

export function validBuildValue(key: BuildConfigKey, value: string, options: ParseOptions): boolean {
  if (value.length > MAX_VALUE_LENGTH || /[\u0000- \u007f]/u.test(value)) return false;
  switch (key) {
    case "BENTO_TELEGRAM_API_ID":
      return /^[1-9][0-9]{0,11}$/u.test(value);
    case "BENTO_TELEGRAM_API_HASH":
      return /^[a-f0-9]{32}$/iu.test(value);
    case "BENTO_RELAY_URL":
      return validServiceUrl(value, ["wss:", "https:"], ["ws:", "http:"], options);
    case "BENTO_PUBLIC_SITE_URL":
      return validServiceUrl(value, ["https:"], ["http:"], options);
  }
}

function validServiceUrl(value: string, secure: string[], insecure: string[], options: ParseOptions): boolean {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return false;
  }
  if (url.username || url.password || url.search || url.hash || !url.hostname) return false;
  if (secure.includes(url.protocol)) return true;
  return options.allowLoopbackInsecure && insecure.includes(url.protocol) && LOOPBACK_HOSTS.has(url.hostname);
}

export interface LoadBuildConfigOptions {
  packaged: boolean;
  resourcesPath: string;
  environment: NodeJS.ProcessEnv;
  read?: (filePath: string) => Promise<string>;
}

/** Packaged builds read only the generated resource file; development reads the parent environment. */
export async function loadBuildConfig(options: LoadBuildConfigOptions): Promise<BuildConfigResult> {
  if (!options.packaged) {
    const candidate = Object.fromEntries(BUILD_CONFIG_KEYS.flatMap((key) => {
      const value = options.environment[key];
      return value === undefined ? [] : [[key, value]];
    }));
    return { ...parseBuildConfig(candidate, { allowLoopbackInsecure: true }), source: "environment" };
  }
  const read = options.read ?? ((filePath: string) => readFile(filePath, "utf8"));
  let raw: string;
  try {
    raw = await read(path.join(options.resourcesPath, BUILD_CONFIG_FILE));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return { config: {}, rejected: [], source: "packaged" };
    return { config: {}, rejected: ["_document"], source: "packaged" };
  }
  if (Buffer.byteLength(raw, "utf8") > MAX_BUILD_CONFIG_BYTES) return { config: {}, rejected: ["_document"], source: "packaged" };
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { config: {}, rejected: ["_document"], source: "packaged" };
  }
  return { ...parseBuildConfig(parsed, { allowLoopbackInsecure: false }), source: "packaged" };
}

export interface SidecarRuntimeEnvironment {
  /** Non-secret runtime configuration added to every sidecar spawn. */
  set: Record<string, string>;
  /** Inherited variables removed before spawning. */
  strip: string[];
}

export function sidecarRuntimeEnvironment(options: {
  packaged: boolean;
  buildConfig: BuildConfig;
  environment: NodeJS.ProcessEnv;
}): SidecarRuntimeEnvironment {
  const set: Record<string, string> = { ...options.buildConfig } as Record<string, string>;
  // Only validated build values reach sidecars; invalid or (when packaged) inherited ones are dropped.
  const strip: string[] = [...ALWAYS_STRIPPED_ENVIRONMENT, ...BUILD_CONFIG_KEYS.filter((key) => !(key in set))];
  if (options.packaged) {
    // Packaged release builds run as production, where the backend refuses the simulated Telegram cloud.
    set.ENVIRONMENT = "production";
    if (options.environment.STORAGE_BACKEND === "fake") strip.push("STORAGE_BACKEND");
  } else if (options.environment.BENTO_DEV_STORAGE_BACKEND === "fake") {
    set.STORAGE_BACKEND = "fake";
  }
  return { set, strip };
}

/** Values that must never appear in logs even though they are not user secrets. */
export function buildConfigRedactions(config: BuildConfig): string[] {
  return config.BENTO_TELEGRAM_API_HASH ? [config.BENTO_TELEGRAM_API_HASH] : [];
}
