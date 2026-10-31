import path from "node:path";
import { fileURLToPath } from "node:url";
import { DeepLink } from "../shared/contracts";

export const DEEP_LINK_SCHEME = "bento";
export const PAIRING_CODE = /^[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$/u;
const MAX_DEEP_LINK_LENGTH = 256;
const MAX_ARGUMENTS = 10_000;
const MAX_ARGUMENT_LENGTH = 32_768;

/** Accepts only `bento://join?v=1&c=<code>`; everything else is rejected without echoing it. */
export function parseDeepLink(value: unknown): DeepLink | null {
  if (typeof value !== "string" || value.length === 0 || value.length > MAX_DEEP_LINK_LENGTH) return null;
  if (/[\u0000- \u007f-\u009f]/u.test(value)) return null;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  if (url.protocol !== `${DEEP_LINK_SCHEME}:` || url.hostname !== "join") return null;
  if (url.username || url.password || url.port || url.hash) return null;
  if (url.pathname !== "" && url.pathname !== "/") return null;
  const keys = [...url.searchParams.keys()];
  if (keys.length !== 2 || !keys.includes("v") || !keys.includes("c") || new Set(keys).size !== 2) return null;
  if (url.searchParams.get("v") !== "1") return null;
  const code = (url.searchParams.get("c") ?? "").toUpperCase();
  if (!PAIRING_CODE.test(code)) return null;
  return { kind: "join", code };
}

export interface LaunchRequest {
  /** `--hidden`: start in the tray without showing the window. */
  hidden: boolean;
  /** Raw `bento:` candidates; validate with `parseDeepLink`. */
  deepLinks: string[];
  /** Absolute local paths (from argv paths or `file://` URLs); validate before use. */
  files: string[];
}

/** Arguments supplied by the user/OS, excluding the executable and (in development) the app path. */
export function userArguments(argv: readonly string[], defaultApp: boolean): string[] {
  return argv.slice(defaultApp ? 2 : 1);
}

export function parseLaunchArguments(args: readonly unknown[]): LaunchRequest {
  const request: LaunchRequest = { hidden: false, deepLinks: [], files: [] };
  for (const candidate of args.slice(0, MAX_ARGUMENTS)) {
    if (typeof candidate !== "string" || candidate.length === 0 || candidate.length > MAX_ARGUMENT_LENGTH) continue;
    if (candidate === "--hidden") {
      request.hidden = true;
      continue;
    }
    if (candidate.startsWith("-")) continue;
    if (/^bento:/iu.test(candidate)) {
      request.deepLinks.push(candidate);
      continue;
    }
    if (/^file:/iu.test(candidate)) {
      try {
        const filePath = fileURLToPath(candidate);
        if (path.isAbsolute(filePath) && !filePath.includes("\0")) request.files.push(filePath);
      } catch {
        // Ignore non-local or malformed file URLs.
      }
      continue;
    }
    if (path.isAbsolute(candidate) && !candidate.includes("\0")) request.files.push(candidate);
  }
  return request;
}

/** Second instances send their arguments as `additionalData`; argv is a fallback because Chromium may reorder it. */
export function argumentsFromAdditionalData(value: unknown): string[] | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const data = value as { bento?: unknown; args?: unknown };
  if (data.bento !== 1 || !Array.isArray(data.args) || data.args.length > MAX_ARGUMENTS) return null;
  if (!data.args.every((item) => typeof item === "string" && item.length <= MAX_ARGUMENT_LENGTH)) return null;
  return data.args as string[];
}
