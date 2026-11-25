// Build = copy src/ to dist/, minify HTML/CSS conservatively, resolve download links, and
// generate /.well-known/assetlinks.json from site.config.json.
// `--production` (used by `npm run deploy`) refuses placeholder Android certificate fingerprints.
import { mkdir, readFile, readdir, rm, writeFile, copyFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { minifyCss, minifyHtml } from "./lib/minify.mjs";
import { applyRelease, validateConfig } from "./lib/release.mjs";
import { applyAndroidRelease, assertProductionReady, assetLinksJson } from "./lib/android.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

export async function build({
  source = path.join(root, "src"),
  output = path.join(root, "dist"),
  config,
  production = false,
} = {}) {
  const resolvedConfig = validateConfig(config ?? JSON.parse(await readFile(path.join(root, "site.config.json"), "utf8")));
  const { android } = resolvedConfig;
  if (android === null) throw new Error("site.config.json: the android block is required (package and signing certificate fingerprints)");
  if (production) assertProductionReady(android);
  await rm(output, { recursive: true, force: true });
  const files = await walk(source);
  for (const file of files) {
    const relative = path.relative(source, file);
    const target = path.join(output, relative);
    await mkdir(path.dirname(target), { recursive: true });
    if (file.endsWith(".html")) {
      const html = await readFile(file, "utf8");
      const resolved = applyAndroidRelease(applyRelease(html, resolvedConfig), resolvedConfig.repository, android);
      await writeFile(target, minifyHtml(resolved), "utf8");
    } else if (file.endsWith(".css")) {
      await writeFile(target, minifyCss(await readFile(file, "utf8")), "utf8");
    } else {
      await copyFile(file, target);
    }
  }
  // Served byte-for-byte at this exact path (no redirect); _headers sets application/json.
  await mkdir(path.join(output, ".well-known"), { recursive: true });
  await writeFile(path.join(output, ".well-known", "assetlinks.json"), assetLinksJson(android), "utf8");
  return {
    output,
    files: files.length + 1,
    release: resolvedConfig.release?.tag ?? null,
    androidRelease: android.release?.tag ?? null,
    androidFingerprints: android.sha256CertFingerprints.length,
  };
}

async function walk(directory) {
  const result = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (entry.name.startsWith(".")) continue;
    const full = path.join(directory, entry.name);
    if (entry.isDirectory()) result.push(...(await walk(full)));
    else if (entry.isFile()) result.push(full);
  }
  return result.sort();
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const production = process.argv.includes("--production");
  let summary;
  try {
    summary = await build({ production });
  } catch (error) {
    console.error(error.message);
    process.exit(1);
  }
  const release = summary.release ? `release ${summary.release}` : "downloads → latest release page";
  console.log(`Built ${summary.files} files into ${path.relative(process.cwd(), summary.output) || "."} (${release}).`);
}
