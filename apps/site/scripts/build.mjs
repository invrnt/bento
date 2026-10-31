// Build = copy src/ to dist/, minify HTML/CSS conservatively, and resolve download links.
import { mkdir, readFile, readdir, rm, writeFile, copyFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { minifyCss, minifyHtml } from "./lib/minify.mjs";
import { applyRelease, validateConfig } from "./lib/release.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

export async function build({
  source = path.join(root, "src"),
  output = path.join(root, "dist"),
  config,
} = {}) {
  const resolvedConfig = validateConfig(config ?? JSON.parse(await readFile(path.join(root, "site.config.json"), "utf8")));
  await rm(output, { recursive: true, force: true });
  const files = await walk(source);
  for (const file of files) {
    const relative = path.relative(source, file);
    const target = path.join(output, relative);
    await mkdir(path.dirname(target), { recursive: true });
    if (file.endsWith(".html")) {
      const html = await readFile(file, "utf8");
      await writeFile(target, minifyHtml(applyRelease(html, resolvedConfig)), "utf8");
    } else if (file.endsWith(".css")) {
      await writeFile(target, minifyCss(await readFile(file, "utf8")), "utf8");
    } else {
      await copyFile(file, target);
    }
  }
  return { output, files: files.length, release: resolvedConfig.release?.tag ?? null };
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
  const summary = await build();
  const release = summary.release ? `release ${summary.release}` : "downloads → latest release page";
  console.log(`Built ${summary.files} files into ${path.relative(process.cwd(), summary.output) || "."} (${release}).`);
}
