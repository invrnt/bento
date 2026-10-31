import { randomBytes } from "node:crypto";
import { lstat, mkdir, rename, unlink, writeFile } from "node:fs/promises";
import path from "node:path";
import { squirrelStubExecutable } from "./squirrel";

export const HIDDEN_ARGUMENT = "--hidden";

interface LoginItemApp {
  setLoginItemSettings(settings: { openAtLogin: boolean; path?: string; args?: string[] }): void;
  getLoginItemSettings(options?: { path?: string; args?: string[] }): { openAtLogin: boolean; wasOpenedAtLogin?: boolean };
}

export interface LoginItemFileSystem {
  mkdir(directory: string): Promise<void>;
  writeAtomic(filePath: string, contents: string): Promise<void>;
  remove(filePath: string): Promise<void>;
  lstat(filePath: string): Promise<{ isFile(): boolean; uid: number; mode: number }>;
}

export interface LoginItemOptions {
  platform: NodeJS.Platform;
  packaged: boolean;
  execPath: string;
  environment: NodeJS.ProcessEnv;
  homeDirectory: string;
  app: LoginItemApp;
  squirrelInstalled?: boolean;
  fs?: LoginItemFileSystem;
  /** Current POSIX user id (defaults to `process.getuid()`). */
  uid?: number;
}

const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f]/u;

/** Registers Bento to start in the tray at login (macOS/Windows login items, Linux XDG autostart). */
export class LoginItemController {
  private readonly fs: LoginItemFileSystem;

  constructor(private readonly options: LoginItemOptions) {
    this.fs = options.fs ?? defaultFileSystem;
  }

  /** Development builds never register the Electron binary as a login item. */
  get supported(): boolean {
    return this.options.packaged && ["darwin", "win32", "linux"].includes(this.options.platform);
  }

  async apply(enabled: boolean): Promise<void> {
    if (!this.supported) return;
    if (this.options.platform === "linux") {
      const target = this.autostartPath();
      if (enabled) {
        const executable = await this.linuxExecutable();
        await this.fs.mkdir(path.dirname(target));
        await this.fs.writeAtomic(target, linuxAutostartEntry(executable));
      } else {
        await this.fs.remove(target);
      }
      return;
    }
    if (this.options.platform === "win32") {
      this.options.app.setLoginItemSettings({ openAtLogin: enabled, path: this.windowsExecutable(), args: [HIDDEN_ARGUMENT] });
      return;
    }
    // macOS 13+ (SMAppService) cannot pass arguments; `wasOpenedAtLogin` selects the hidden start instead.
    this.options.app.setLoginItemSettings({ openAtLogin: enabled });
  }

  /** True when this launch should start in the tray without showing the window. */
  launchedHidden(args: readonly string[]): boolean {
    if (args.includes(HIDDEN_ARGUMENT)) return true;
    if (this.options.platform !== "darwin" || !this.options.packaged) return false;
    try {
      return this.options.app.getLoginItemSettings().wasOpenedAtLogin === true;
    } catch {
      return false;
    }
  }

  autostartPath(): string {
    const configured = this.options.environment.XDG_CONFIG_HOME;
    const configHome = configured && path.isAbsolute(configured) ? configured : path.join(this.options.homeDirectory, ".config");
    return path.join(configHome, "autostart", "bento.desktop");
  }

  /**
   * The AppImage file when this executable runs from it, otherwise `execPath`. `APPIMAGE` is inherited
   * environment, so it is used only while the AppImage runtime has mounted this very executable
   * (`APPDIR`) and it names an absolute regular file owned by the current user and not writable by
   * everyone; anything else is refused rather than written into the autostart entry.
   */
  private async linuxExecutable(): Promise<string> {
    const { environment, execPath } = this.options;
    const appImage = environment.APPIMAGE;
    if (!appImage || !isDescendant(environment.APPDIR, execPath)) return execPath;
    if (!await this.trustedAppImage(appImage)) throw new TypeError("The AppImage path cannot be used for autostart");
    return appImage;
  }

  private async trustedAppImage(candidate: string): Promise<boolean> {
    if (!path.isAbsolute(candidate) || path.normalize(candidate) !== candidate || CONTROL_CHARACTERS.test(candidate)) return false;
    try {
      const info = await this.fs.lstat(candidate);
      const uid = this.options.uid ?? process.getuid?.();
      return info.isFile() && (uid === undefined || info.uid === uid) && (info.mode & 0o002) === 0;
    } catch {
      return false;
    }
  }

  private windowsExecutable(): string {
    return this.options.squirrelInstalled ? squirrelStubExecutable(this.options.execPath) : this.options.execPath;
  }
}

export function linuxAutostartEntry(executable: string): string {
  if (!path.isAbsolute(executable) || /[\u0000-\u001f\u007f]/u.test(executable)) throw new TypeError("Autostart executable is invalid");
  return [
    "[Desktop Entry]",
    "Type=Application",
    "Version=1.0",
    "Name=Bento",
    `Exec=${desktopExecArgument(executable)} ${HIDDEN_ARGUMENT}`,
    // Matches the icon installed by the .deb (named after the package).
    "Icon=bento-desktop",
    "Terminal=false",
    "NoDisplay=false",
    "X-GNOME-Autostart-enabled=true",
    "",
  ].join("\n");
}

/** Quotes an Exec argument per the Desktop Entry spec (quoting, then string escaping, `%` doubled). */
export function desktopExecArgument(value: string): string {
  const quoted = /^[A-Za-z0-9_@+=:,./-]+$/u.test(value) ? value : `"${value.replace(/["`$\\]/gu, "\\$&")}"`;
  return quoted.replace(/%/gu, "%%").replace(/\\/gu, "\\\\");
}

function isDescendant(root: string | undefined, candidate: string): boolean {
  if (!root || !path.isAbsolute(root)) return false;
  const child = path.relative(root, candidate);
  return child !== "" && !child.startsWith("..") && !path.isAbsolute(child);
}

const defaultFileSystem: LoginItemFileSystem = {
  lstat: (filePath) => lstat(filePath),
  mkdir: async (directory) => { await mkdir(directory, { recursive: true, mode: 0o700 }); },
  writeAtomic: async (filePath, contents) => {
    const temporary = `${filePath}.${randomBytes(6).toString("hex")}.tmp`;
    try {
      await writeFile(temporary, contents, { encoding: "utf8", mode: 0o644, flag: "wx" });
      await rename(temporary, filePath);
    } catch (error) {
      await unlink(temporary).catch(() => undefined);
      throw error;
    }
  },
  remove: async (filePath) => {
    try {
      await unlink(filePath);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
  },
};
