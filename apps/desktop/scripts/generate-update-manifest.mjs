import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { readFile, readdir, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { signManifestFiles } from "./sign-update-manifest.mjs";

const options = parseOptions(process.argv.slice(2));
const platform = requiredChoice(options, "platform", ["darwin", "linux", "win32"]);
const arch = requiredChoice(options, "arch", ["arm64", "x64"]);
if (platform !== "darwin" && arch !== "x64") throw new Error(`${platform}-${arch} is not a supported release target`);
const stage = path.resolve(required(options, "stage"));
const tag = required(options, "tag");
const version = tag.startsWith("v") ? tag.slice(1) : "";
if (!/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/u.test(version)) throw new Error(`Release tag is not stable SemVer: ${tag}`);
const publishedAt = new Date(required(options, "published-at"));
if (Number.isNaN(publishedAt.valueOf())) throw new Error("published-at must be a valid ISO-8601 timestamp");
const commit = required(options, "commit");
if (!/^[a-f0-9]{40}$/u.test(commit)) throw new Error("commit must be a full lowercase Git SHA");

const repository = "invrnt/bento";
const baseUrl = `https://github.com/${repository}/releases/download/${encodeURIComponent(tag)}`;
const files = (await readdir(stage, { withFileTypes: true }))
  .filter((entry) => entry.isFile())
  .map((entry) => entry.name)
  .filter((filename) => !filename.startsWith("SHA256SUMS") && !filename.startsWith("bento-update-"))
  .sort();
const selected = selectAssets(platform, files);
const assets = [];
for (const [kind, filename] of selected) {
  const fullPath = path.join(stage, filename);
  assets.push({
    platform,
    arch,
    kind,
    filename,
    url: `${baseUrl}/${encodeURIComponent(filename)}`,
    sha256: await digest(fullPath, "sha256"),
    size: (await stat(fullPath)).size,
  });
}

const manifest = {
  schemaVersion: 1,
  version,
  releaseName: `Bento ${version}`,
  notes: `Actualización estable de Bento ${version}.`,
  publishedAt: publishedAt.toISOString(),
  commit,
  repository,
  target: `${platform}-${arch}`,
  assets,
  ...(platform === "win32" ? { squirrel: await windowsMetadata(stage, assets, baseUrl) } : {}),
};
const output = path.join(stage, `bento-update-${platform}-${arch}.json`);
await writeFile(output, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
console.log(output);
// Signed whenever the signing secret is available (the release workflow signs in its publish job).
if (process.env.BENTO_UPDATE_SIGNING_KEY?.trim()) {
  const [signed] = await signManifestFiles([output], {
    signingKeyText: process.env.BENTO_UPDATE_SIGNING_KEY,
    expectedPublicKey: process.env.BENTO_UPDATE_PUBLIC_KEY?.trim() || undefined,
  });
  console.log(`${output}.sig (key ids: ${signed.keyIds.join(", ")})`);
}

function selectAssets(targetPlatform, filenames) {
  const rules = targetPlatform === "win32"
    ? [["installer", /Setup\.exe$/iu], ["squirrel-package", /-full\.nupkg$/iu], ["squirrel-releases", /^RELEASES$/u]]
    : targetPlatform === "darwin"
      ? [["installer", /\.dmg$/iu], ["update-archive", /\.zip$/iu]]
      : [["installer", /\.deb$/iu], ["portable-archive", /\.zip$/iu]];
  return rules.map(([kind, pattern]) => {
    const matches = filenames.filter((filename) => pattern.test(filename));
    if (matches.length !== 1) throw new Error(`Expected exactly one ${kind} artifact for ${targetPlatform}; found ${matches.length}`);
    if (kind !== "squirrel-releases" && !matches[0].includes(version)) throw new Error(`${matches[0]} does not include release version ${version}`);
    return [kind, matches[0]];
  });
}

async function windowsMetadata(root, releaseAssets, releaseBaseUrl) {
  const releasesAsset = releaseAssets.find((asset) => asset.kind === "squirrel-releases");
  const nupkgAsset = releaseAssets.find((asset) => asset.kind === "squirrel-package");
  const raw = await readFile(path.join(root, releasesAsset.filename), "utf8");
  const lines = raw.trim().split(/\r?\n/u).filter(Boolean);
  if (lines.length !== 1) throw new Error(`Expected one Squirrel RELEASES entry; found ${lines.length}`);
  const match = /^([A-Fa-f0-9]{40})\s+(\S+)\s+(\d+)$/u.exec(lines[0]);
  if (!match) throw new Error("Squirrel RELEASES entry is invalid");
  if (path.basename(match[2]) !== nupkgAsset.filename) throw new Error("Squirrel RELEASES does not reference the staged nupkg");
  const sha1 = await digest(path.join(root, nupkgAsset.filename), "sha1");
  if (match[1].toLowerCase() !== sha1 || Number(match[3]) !== nupkgAsset.size) throw new Error("Squirrel RELEASES hash or size does not match the nupkg");
  const nupkgUrl = `${releaseBaseUrl}/${encodeURIComponent(nupkgAsset.filename)}`;
  return {
    releasesContent: `${sha1.toUpperCase()} ${nupkgUrl} ${nupkgAsset.size}\n`,
    nupkg: { filename: nupkgAsset.filename, url: nupkgUrl, sha1, sha256: nupkgAsset.sha256, size: nupkgAsset.size },
  };
}

async function digest(filename, algorithm) {
  const hash = createHash(algorithm);
  for await (const chunk of createReadStream(filename)) hash.update(chunk);
  return hash.digest("hex");
}

function parseOptions(arguments_) {
  const result = {};
  for (let index = 0; index < arguments_.length; index += 2) {
    const name = arguments_[index];
    const value = arguments_[index + 1];
    if (!name?.startsWith("--") || value === undefined) throw new Error(`Invalid argument near ${name ?? "end"}`);
    result[name.slice(2)] = value;
  }
  return result;
}

function required(values, key) {
  if (!values[key]) throw new Error(`--${key} is required`);
  return values[key];
}

function requiredChoice(values, key, choices) {
  const value = required(values, key);
  if (!choices.includes(value)) throw new Error(`--${key} must be one of ${choices.join(", ")}`);
  return value;
}
