import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

/**
 * `node checksums.mjs [root] [name]` writes `<sha256>  <relative/path>` lines for every file under root.
 * The helpers are shared with build-sidecar.mjs and verify-artifacts.mjs, which check the llama-server
 * bundle against the SHA256SUMS that scripts/build-llama-server.{sh,ps1} write next to it.
 */
export async function writeChecksums(root, outputName = "SHA256SUMS") {
  const files = (await walk(root)).filter((filename) => !path.basename(filename).startsWith("SHA256SUMS")).sort();
  if (files.length === 0) throw new Error(`No release artifacts found under ${root}`);
  const lines = [];
  for (const filename of files) lines.push(`${await sha256(filename)}  ${relativeName(root, filename)}`);
  await mkdir(root, { recursive: true });
  await writeFile(path.join(root, outputName), `${lines.join("\n")}\n`, "utf8");
  return lines;
}

/** `{ relative/path: sha256 }` from a SHA256SUMS text; refuses absolute paths and `..`. */
export function parseChecksums(text) {
  const entries = new Map();
  for (const [index, line] of text.split(/\r?\n/u).entries()) {
    if (!line.trim()) continue;
    const match = /^([0-9a-f]{64}) [ *](.+)$/u.exec(line);
    if (!match) throw new Error(`SHA256SUMS line ${index + 1} is not "<sha256>  <file>"`);
    const name = match[2];
    if (path.isAbsolute(name) || name.includes("\\") || name.split("/").some((part) => part === ".." || part === "")) {
      throw new Error(`SHA256SUMS line ${index + 1} names an unsafe path`);
    }
    if (entries.has(name)) throw new Error(`SHA256SUMS lists ${name} twice`);
    entries.set(name, match[1]);
  }
  return entries;
}

/** Problems (empty when every file listed in `root/SHA256SUMS` exists with its digest and nothing is unlisted). */
export async function checkChecksums(root, sumsName = "SHA256SUMS") {
  const entries = parseChecksums(await readFile(path.join(root, sumsName), "utf8"));
  const problems = [];
  const present = new Set((await walk(root)).map((filename) => relativeName(root, filename)).filter((name) => !path.basename(name).startsWith("SHA256SUMS")));
  for (const [name, digest] of entries) {
    if (!present.has(name)) problems.push(`${name} is listed but missing`);
    else if (await sha256(path.join(root, ...name.split("/"))) !== digest) problems.push(`${name} does not match its SHA-256`);
  }
  for (const name of [...present].sort()) if (!entries.has(name)) problems.push(`${name} is not listed in ${sumsName}`);
  return problems;
}

export async function walk(directory) {
  const result = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) result.push(...await walk(target));
    else if (entry.isFile()) result.push(target);
  }
  return result;
}

export async function sha256(filename) {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(filename)) hash.update(chunk);
  return hash.digest("hex");
}

function relativeName(root, filename) {
  return path.relative(root, filename).split(path.sep).join("/");
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const desktopRoot = path.resolve(import.meta.dirname, "..");
  const releaseRoot = path.resolve(process.argv[2] ?? path.join(desktopRoot, "../../dist/desktop"));
  await writeChecksums(releaseRoot, process.argv[3] ?? "SHA256SUMS");
}
