import { access, readdir, readFile } from "node:fs/promises";
import path from "node:path";

const desktopRoot = path.resolve(import.meta.dirname, "..");
const rootArgument = process.argv.slice(2).find((argument) => !argument.startsWith("--"));
const releaseRoot = path.resolve(rootArgument ?? path.join(desktopRoot, "../../dist/desktop"));
const packageOnly = process.argv.includes("--package-only");
const files = await walk(releaseRoot);
const relative = files.map((filename) => path.relative(releaseRoot, filename).split(path.sep).join("/"));
const packageMarker = `-${process.platform}-${process.arch}`;
const packageDirectory = (await readdir(releaseRoot, { withFileTypes: true }))
  .find((entry) => entry.isDirectory() && entry.name.endsWith(packageMarker));
if (!packageDirectory) throw new Error(`Missing native ${process.platform}/${process.arch} package in ${releaseRoot}`);

const requiredSuffixes = process.platform === "win32"
  ? [".exe", ".nupkg"]
  : process.platform === "darwin"
    ? [".dmg", ".zip"]
    : [".deb", ".zip"];
if (!packageOnly) {
  for (const suffix of requiredSuffixes) {
    if (!relative.some((filename) => filename.endsWith(suffix))) throw new Error(`Maker did not produce a ${suffix} artifact`);
  }
}

if (relative.some((filename) => /(^|\/)\.env(?:\.|$)/u.test(filename))) {
  throw new Error("A plaintext .env file was included in the packaged release");
}
if (!relative.some((filename) => /resources\/bento-sidecar\/bento-sidecar(?:\.exe)?$/iu.test(filename))) {
  throw new Error("The platform-native Python sidecar is missing from the package");
}
if (!relative.some((filename) => /resources\/build-config\.json$/iu.test(filename))) {
  throw new Error("The desktop build configuration resource is missing from the package");
}
for (const state of ["idle", "syncing", "paused", "attention"]) {
  if (!relative.some((filename) => new RegExp(`resources/tray/tray-${state}(?:Template|-linux)?\\.png$`, "iu").test(filename))) {
    throw new Error(`The ${state} tray icon is missing from the package`);
  }
}
const asarSuffix = `${path.sep}resources${path.sep}app.asar`.toLocaleLowerCase("en-US");
const asar = files.find((filename) => filename.toLocaleLowerCase("en-US").endsWith(asarSuffix));
if (!asar) throw new Error("The production app.asar is missing");
const asarContents = await readFile(asar);
for (const marker of ["http://localhost:5173", "electron/default_app"]) {
  if (asarContents.includes(Buffer.from(marker))) throw new Error(`Development marker found in app.asar: ${marker}`);
}
await access(path.join(desktopRoot, "resources", "icons", process.platform === "darwin" ? "bento.icns" : process.platform === "win32" ? "bento.ico" : "bento.png"));

async function walk(directory) {
  const result = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) result.push(...await walk(target));
    else if (entry.isFile()) result.push(target);
  }
  return result;
}
