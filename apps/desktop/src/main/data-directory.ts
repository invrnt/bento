import { cp, lstat, mkdir, readdir, realpath, stat, statfs } from "node:fs/promises";
import path from "node:path";
import { validateSafePath } from "./validation";

export type DataMigrationMode = "copy" | "use-empty";

export class DataDirectoryMigrator {
  constructor(
    private readonly getAvailableBytes: (directory: string) => Promise<number> = availableBytes,
    /** Current POSIX user; `undefined` (Windows) skips the ownership check. */
    private readonly currentUid: () => number | undefined = () => process.getuid?.(),
  ) {}

  async validate(sourceValue: string, destinationValue: string, mode: DataMigrationMode | undefined): Promise<string> {
    if (!mode) throw new Error("Choose whether to copy the current data or use an empty directory");
    const source = validateSafePath(sourceValue);
    const destination = validateSafePath(destinationValue);
    if ((await lstat(source)).isSymbolicLink()) throw new Error("The current data directory cannot be a symbolic link");
    await mkdir(destination, { recursive: true, mode: 0o700 });
    if ((await lstat(destination)).isSymbolicLink()) throw new Error("The new data directory cannot be a symbolic link");
    const realSource = await realpath(source);
    const realDestination = await realpath(destination);
    if (realSource === realDestination) throw new Error("The new data directory must be different");
    const uid = this.currentUid();
    if (uid !== undefined) {
      // Another account could read or plant files in a directory it owns or that anyone can write.
      const owner = await stat(realDestination);
      if (owner.uid !== uid) throw new Error("The new data directory must belong to the current user");
      if (owner.mode & 0o002) throw new Error("The new data directory must not be writable by other users");
    }
    const relation = path.relative(realSource, realDestination);
    const reverse = path.relative(realDestination, realSource);
    if ((!relation.startsWith("..") && !path.isAbsolute(relation)) || (!reverse.startsWith("..") && !path.isAbsolute(reverse))) {
      throw new Error("Data directories cannot contain one another");
    }
    if ((await readdir(realDestination)).length !== 0) throw new Error("The new data directory must be empty");
    if (mode === "copy") {
      const required = await directorySize(source);
      const available = await this.getAvailableBytes(realDestination);
      if (available < Math.ceil(required * 1.1)) throw new Error("The destination does not have enough free space");
    }
    return realDestination;
  }

  async execute(source: string, destination: string, mode: DataMigrationMode): Promise<void> {
    if (mode === "copy") {
      for (const entry of await readdir(source, { withFileTypes: true })) {
        await cp(path.join(source, entry.name), path.join(destination, entry.name), {
          recursive: true,
          force: false,
          errorOnExist: true,
        });
      }
    }
  }
}

async function directorySize(root: string): Promise<number> {
  let total = 0;
  for (const entry of await readdir(root, { withFileTypes: true })) {
    const candidate = path.join(root, entry.name);
    if (entry.isSymbolicLink()) throw new Error("The current data directory contains an unsupported symbolic link");
    if (entry.isDirectory()) total += await directorySize(candidate);
    else if (entry.isFile()) total += (await stat(candidate)).size;
  }
  return total;
}

async function availableBytes(directory: string): Promise<number> {
  const value = await statfs(directory);
  return Number(value.bavail) * Number(value.bsize);
}
