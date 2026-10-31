import type { MenuItemConstructorOptions } from "electron";

/**
 * Chromium/Node switches that open a debugging endpoint. Packaged builds refuse to start with any of
 * them (Electron fuses already disable the Node `--inspect` family; this also covers Chromium's
 * remote debugging, which no fuse controls).
 */
const DEBUGGING_SWITCH = /^--?(remote-debugging-[a-z-]+|inspect(?:-[a-z-]+)?)(?:=|$)/iu;
// Chromium also accepts `/switch` on Windows.
const WINDOWS_DEBUGGING_SWITCH = /^(?:--?|\/)(remote-debugging-[a-z-]+|inspect(?:-[a-z-]+)?)(?:=|$)/iu;
export const DEBUGGING_SWITCHES = ["remote-debugging-port", "remote-debugging-pipe", "remote-debugging-address", "inspect", "inspect-brk", "inspect-port", "inspect-brk-node"] as const;

/** Names (never values) of debugging switches in `argv` or already applied to the command line. */
export function debuggingSwitches(
  argv: readonly string[],
  hasSwitch: (name: string) => boolean = () => false,
  platform: NodeJS.Platform = process.platform,
): string[] {
  const pattern = platform === "win32" ? WINDOWS_DEBUGGING_SWITCH : DEBUGGING_SWITCH;
  const found = new Set<string>();
  for (const argument of argv) {
    if (argument === "--") break;
    const match = pattern.exec(argument);
    if (match) found.add(match[1]!.toLowerCase());
  }
  for (const name of DEBUGGING_SWITCHES) if (hasSwitch(name)) found.add(name);
  return [...found];
}

/**
 * Application menu for packaged builds: standard roles only, without reload, force reload, or
 * developer tools (Electron's default View menu ships all three with keyboard shortcuts).
 */
export function applicationMenuTemplate(platform: NodeJS.Platform, labels: { view: string }): MenuItemConstructorOptions[] {
  const view: MenuItemConstructorOptions = {
    label: labels.view,
    submenu: [{ role: "resetZoom" }, { role: "zoomIn" }, { role: "zoomOut" }, { type: "separator" }, { role: "togglefullscreen" }],
  };
  return platform === "darwin"
    ? [{ role: "appMenu" }, { role: "editMenu" }, view, { role: "windowMenu" }]
    : [{ role: "fileMenu" }, { role: "editMenu" }, view, { role: "windowMenu" }];
}
