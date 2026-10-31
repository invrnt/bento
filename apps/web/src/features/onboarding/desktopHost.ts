import { desktopBridge } from "../../api/settingsDesktop";

/**
 * Tiny typed adapter over the Telegram-first additions to `window.bento`
 * (see orchestration/architecture/desktop-bridge-telegram-first.md). Every call is
 * feature-detected so browser mode and older desktop builds keep working.
 */

export type DesktopPreferences = {
  autoDownloadUpdates: boolean;
  keepRunningInBackground: boolean;
  launchAtLogin: boolean;
};

export type DeepLink = { code: string; kind: "join" };

type PdfResult = { canceled: boolean; path?: string };

type TelegramFirstBridge = {
  onDeepLink?: (listener: (link: DeepLink) => void) => () => void;
  onNavigate?: (listener: (path: string) => void) => () => void;
  pickDirectory?: (options?: { title?: string }) => Promise<{ canceled: boolean; path?: string }>;
  preferences?: {
    get(): Promise<DesktopPreferences>;
    set(partial: Partial<DesktopPreferences>): Promise<unknown>;
  };
  savePageAsPdf?: (options: { suggestedName: string }) => Promise<PdfResult>;
};

const pairingCodePattern = /^[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$/;
const noop = () => undefined;

function bridge(): TelegramFirstBridge | null {
  return desktopBridge() as unknown as TelegramFirstBridge | null;
}

export function isDesktop(): boolean {
  return bridge() !== null;
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

/** Saves a partial preference change and returns the effective preferences. */
export async function setDesktopPreferences(partial: Partial<DesktopPreferences>): Promise<DesktopPreferences | null> {
  if (!hasDesktopPreferences()) return null;
  const result = await bridge()!.preferences!.set(partial);
  return normalizePreferences(result) ?? getDesktopPreferences();
}

export function canSavePdf(): boolean {
  return typeof bridge()?.savePageAsPdf === "function";
}

export async function savePageAsPdf(suggestedName: string): Promise<PdfResult | null> {
  if (!canSavePdf()) return null;
  return bridge()!.savePageAsPdf!({ suggestedName });
}

export function canPickDirectory(): boolean {
  return typeof bridge()?.pickDirectory === "function";
}

export async function pickDirectory(title?: string): Promise<string | null> {
  if (!canPickDirectory()) return null;
  const result = await bridge()!.pickDirectory!(title ? { title } : undefined);
  return !result.canceled && result.path ? result.path : null;
}

/** Subscribes to `bento://join` links; only well-formed pairing codes reach the listener. */
export function onDeepLink(listener: (link: DeepLink) => void): () => void {
  const subscribe = bridge()?.onDeepLink;
  if (typeof subscribe !== "function") return noop;
  return subscribe((link) => {
    const code = typeof link?.code === "string" ? link.code.toUpperCase() : "";
    if (link?.kind === "join" && pairingCodePattern.test(code)) listener({ code, kind: "join" });
  });
}

/** Subscribes to navigation requests from the tray or notifications; only in-app paths pass. */
export function onNavigate(listener: (path: string) => void): () => void {
  const subscribe = bridge()?.onNavigate;
  if (typeof subscribe !== "function") return noop;
  return subscribe((path) => {
    if (isInternalPath(path)) listener(path);
  });
}

export function isInternalPath(path: unknown): path is string {
  return typeof path === "string" && path.length <= 512 && /^\/(?!\/)[^\s\\]*$/.test(path) && !path.includes("://");
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
