import path from "node:path";

export type SquirrelEvent = "install" | "updated" | "uninstall" | "obsolete" | "firstrun";

const EVENTS: Record<string, SquirrelEvent> = {
  "--squirrel-install": "install",
  "--squirrel-updated": "updated",
  "--squirrel-uninstall": "uninstall",
  "--squirrel-obsolete": "obsolete",
  "--squirrel-firstrun": "firstrun",
};

export function squirrelEvent(argv: readonly string[], platform: NodeJS.Platform): SquirrelEvent | null {
  if (platform !== "win32") return null;
  return EVENTS[argv[1] ?? ""] ?? null;
}

/** Squirrel's stub one level above `app-<version>` forwards arguments to the newest version. */
export function squirrelStubExecutable(execPath: string): string {
  return path.win32.resolve(path.win32.dirname(execPath), "..", path.win32.basename(execPath));
}

export function squirrelUpdateExecutable(execPath: string): string {
  return path.win32.resolve(path.win32.dirname(execPath), "..", "Update.exe");
}

export function sendToShortcutPath(appDataDirectory: string): string {
  return path.win32.join(appDataDirectory, "Microsoft", "Windows", "SendTo", "Bento.lnk");
}

export interface SquirrelDependencies {
  execPath: string;
  appDataDirectory: string;
  description: string;
  runUpdate(args: string[]): Promise<void>;
  writeShortcutLink(shortcutPath: string, operation: "create", options: {
    target: string;
    description: string;
    icon: string;
    iconIndex: number;
    appUserModelId: string;
  }): boolean;
  removeFile(filePath: string): Promise<void>;
  removeLoginItem(stubExecutable: string): void;
  removeProtocolClient(stubExecutable: string): void;
}

/**
 * Handles Squirrel lifecycle launches. Returns true when the process must quit immediately
 * (every event except `firstrun`).
 */
export async function handleSquirrelEvent(event: SquirrelEvent, dependencies: SquirrelDependencies): Promise<boolean> {
  if (event === "firstrun") return false;
  if (event === "obsolete") return true;
  const executableName = path.win32.basename(dependencies.execPath);
  const stub = squirrelStubExecutable(dependencies.execPath);
  const shortcut = sendToShortcutPath(dependencies.appDataDirectory);
  if (event === "install" || event === "updated") {
    await dependencies.runUpdate(["--createShortcut", executableName]).catch(() => undefined);
    dependencies.writeShortcutLink(shortcut, "create", {
      target: stub,
      description: dependencies.description,
      icon: stub,
      iconIndex: 0,
      appUserModelId: `com.squirrel.bento.${executableName.replace(/\.exe$/iu, "")}`,
    });
    return true;
  }
  await dependencies.runUpdate(["--removeShortcut", executableName]).catch(() => undefined);
  await dependencies.removeFile(shortcut).catch(() => undefined);
  try { dependencies.removeLoginItem(stub); } catch { /* best effort */ }
  try { dependencies.removeProtocolClient(stub); } catch { /* best effort */ }
  return true;
}
