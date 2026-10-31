import { desktopBridge } from "../../api/settingsDesktop";
import type { DesktopPlatform } from "../../api/settingsDesktop";

/**
 * Tiny typed adapter over the Telegram-first additions to `window.bento`
 * (orchestration/architecture/desktop-bridge-telegram-first.md). Every member is
 * feature-detected so browser mode and older desktop builds keep working.
 */

export type DesktopPreferences = {
  autoDownloadUpdates: boolean;
  keepRunningInBackground: boolean;
  launchAtLogin: boolean;
};

export type DeepLink = { code: string; kind: "join" };
export type NavigationTarget = "activity" | "drive" | "settings" | "recovery-kit";
export type NavigateRequest = { attentionId?: string; target: NavigationTarget };
export type SavePdfResult = { fileName?: string; saved: boolean };

type TelegramFirstBridge = {
  onDeepLink?: (listener: (link: DeepLink) => void) => () => void;
  onNavigate?: (listener: (request: NavigateRequest) => void) => () => void;
  pickDirectory?: (options?: { title?: string }) => Promise<{ canceled: boolean; path?: string }>;
  preferences?: {
    get(): Promise<DesktopPreferences>;
    set(patch: Partial<DesktopPreferences>): Promise<DesktopPreferences>;
  };
  savePageAsPdf?: (request?: { suggestedName?: string }) => Promise<SavePdfResult>;
};

const pairingCodePattern = /^[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$/;
const noop = () => undefined;

function bridge(): TelegramFirstBridge | null {
  return desktopBridge() as unknown as TelegramFirstBridge | null;
}

export function hasDesktopPreferences(): boolean {
  const preferences = bridge()?.preferences;
  return typeof preferences?.get === "function" && typeof preferences.set === "function";
}

export async function getDesktopPreferences(): Promise<DesktopPreferences | null> {
  if (!hasDesktopPreferences()) return null;
  try {
    return normalizePreferences(await bridge()!.preferences!.get());
  } catch {
    return null;
  }
}

/** Applies a preference change (side effects first) and resolves with the full preferences. */
export async function setDesktopPreferences(patch: Partial<DesktopPreferences>): Promise<DesktopPreferences | null> {
  if (!hasDesktopPreferences()) return null;
  return normalizePreferences(await bridge()!.preferences!.set(patch)) ?? getDesktopPreferences();
}

/** The OS refused the login item (`preferences_launch_at_login_failed`, wrapped by Electron IPC). */
export function isLaunchAtLoginError(error: unknown): boolean {
  return String(error instanceof Error ? error.message : error).includes("preferences_launch_at_login_failed");
}

export function canSavePdf(): boolean {
  return typeof bridge()?.savePageAsPdf === "function";
}

/** Prints the current page (the recovery kit print view) to an A4 PDF chosen by the person. */
export async function savePageAsPdf(suggestedName?: string): Promise<SavePdfResult | null> {
  if (!canSavePdf()) return null;
  const result = await bridge()!.savePageAsPdf!(suggestedName ? { suggestedName } : undefined);
  return { fileName: typeof result?.fileName === "string" ? result.fileName : undefined, saved: Boolean(result?.saved) };
}

export function canPickDirectory(): boolean {
  return typeof bridge()?.pickDirectory === "function";
}

export async function pickDirectory(title?: string): Promise<string | null> {
  if (!canPickDirectory()) return null;
  const result = await bridge()!.pickDirectory!(title ? { title } : undefined);
  return !result.canceled && result.path ? result.path : null;
}

/** Subscribes to `bento://join` links (buffered by main until the first subscriber). */
export function onDeepLink(listener: (link: DeepLink) => void): () => void {
  const subscribe = bridge()?.onDeepLink;
  if (typeof subscribe !== "function") return noop;
  return subscribe((link) => {
    const code = typeof link?.code === "string" ? link.code.toUpperCase() : "";
    if (link?.kind === "join" && pairingCodePattern.test(code)) listener({ code, kind: "join" });
  });
}

/** Subscribes to notification clicks and turns each request into an in-app path. */
export function onNavigate(listener: (path: string) => void): () => void {
  const subscribe = bridge()?.onNavigate;
  if (typeof subscribe !== "function") return noop;
  return subscribe((request) => listener(navigationPath(request)));
}

/** Maps a desktop navigation request to a route; unknown targets fall back to Actividad. */
export function navigationPath(request: unknown): string {
  const { attentionId, target } = (request && typeof request === "object" ? request : {}) as Partial<NavigateRequest>;
  switch (target) {
    case "drive":
      return "/drive";
    case "settings":
      return "/settings";
    case "recovery-kit":
      return "/settings/recovery";
    default:
      return typeof attentionId === "string" && attentionId ? `/activity?attention=${encodeURIComponent(attentionId)}` : "/activity";
  }
}

/** `"os"` when device keys are wrapped by the OS store, `"file"` when the backend keeps a 0600 key file. */
export function secureStorageMode(platform: DesktopPlatform | null): "os" | "file" | null {
  const value = platform?.secureStorage as string | undefined;
  if (value === "os" || value === "available") return "os";
  if (value === "file" || value === "unavailable") return "file";
  return null;
}

function normalizePreferences(value: unknown): DesktopPreferences | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  if (
    typeof record.launchAtLogin !== "boolean" ||
    typeof record.keepRunningInBackground !== "boolean" ||
    typeof record.autoDownloadUpdates !== "boolean"
  ) {
    return null;
  }
  return {
    autoDownloadUpdates: record.autoDownloadUpdates,
    keepRunningInBackground: record.keepRunningInBackground,
    launchAtLogin: record.launchAtLogin,
  };
}
