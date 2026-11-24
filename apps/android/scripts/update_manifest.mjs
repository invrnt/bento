import { createHash, createPublicKey } from "node:crypto";
import { createReadStream } from "node:fs";
import { readdir, readFile, rename, rm, stat, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

// Android entry of the Ed25519-signed update manifest (product/android.md §2). Same schema, signature format and key
// as the desktop (apps/desktop/scripts/generate-update-manifest.mjs + sign-update-manifest.mjs); the format code is
// imported from apps/desktop/src/main/update-signature.ts so there is one implementation.
//
//   node update_manifest.mjs generate --apk <file> --arch arm64|universal --version X.Y.Z --commit <sha>
//        --cert-sha256 <hex>[,<hex>] --out <dir> [--base-url <url>] [--published-at <iso>] [--min-sdk 29]
//        Writes <out>/bento-update-android-<arch>.json and, when a signing key is configured, the detached .sig.
//   node update_manifest.mjs verify <manifest.json>...      checks each .sig against BENTO_UPDATE_PUBLIC_KEY
//   node update_manifest.mjs feed --root <dir> --origin http://127.0.0.1:8799
//        Writes a GitHub-shaped releases listing for the local dry-run feed (<root>/repos/invrnt/bento/releases).
//
// Signing key: BENTO_UPDATE_SIGNING_KEY_FILE (path to the PKCS#8 PEM) or BENTO_UPDATE_SIGNING_KEY (PEM text, as in the
// desktop workflow). Key material is never printed.

const here = path.dirname(fileURLToPath(import.meta.url));
const desktop = path.resolve(here, "../../desktop");
const REPOSITORY = "invrnt/bento";
const PACKAGE_NAME = "dev.bento.app";
const ARCHES = { arm64: "arm64-v8a", universal: "universal" };
const SEMVER = /^(0|[1-9]\d{0,2})\.(0|[1-9]\d{0,2})\.(0|[1-9]\d{0,2})$/u;

let formats;
async function signatureFormat() {
  formats ??= {
    ...(await import(pathToFileURL(path.join(desktop, "src/main/update-signature.ts")).href)),
    ...(await import(pathToFileURL(path.join(desktop, "scripts/sign-update-manifest.mjs")).href)),
  };
  return formats;
}

export function versionCode(version) {
  const match = SEMVER.exec(version);
  if (!match) throw new Error(`Version is not X.Y.Z (each part below 1000): ${version}`);
  return Number(match[1]) * 1_000_000 + Number(match[2]) * 1_000 + Number(match[3]);
}

export function manifestName(arch) {
  if (!(arch in ARCHES)) throw new Error(`--arch must be one of ${Object.keys(ARCHES).join(", ")}`);
  return `bento-update-android-${arch}.json`;
}

export function apkName(version, arch) {
  return `bento-android-${version}-${ARCHES[arch]}.apk`;
}

export async function signingKeyText(environment = process.env) {
  const file = environment.BENTO_UPDATE_SIGNING_KEY_FILE?.trim();
  if (file) return readFile(file, "utf8");
  return environment.BENTO_UPDATE_SIGNING_KEY?.trim() ? environment.BENTO_UPDATE_SIGNING_KEY : undefined;
}

export async function buildManifest({ apk, arch, version, commit, certs, baseUrl, publishedAt, minSdk = 29 }) {
  const code = versionCode(version);
  if (!/^[a-f0-9]{40}$/u.test(commit)) throw new Error("--commit must be a full lowercase Git SHA");
  if (certs.length === 0 || certs.some((cert) => !/^[a-f0-9]{64}$/u.test(cert))) throw new Error("--cert-sha256 must be lowercase SHA-256 hex");
  const filename = path.basename(apk);
  if (filename !== apkName(version, arch)) throw new Error(`APK must be named ${apkName(version, arch)}`);
  const base = (baseUrl ?? `https://github.com/${REPOSITORY}/releases/download/${encodeURIComponent(`android-v${version}`)}`).replace(/\/+$/u, "");
  return {
    schemaVersion: 1,
    version,
    releaseName: `Bento ${version}`,
    notes: `Actualización estable de Bento ${version}.`,
    publishedAt: new Date(publishedAt ?? Date.now()).toISOString(),
    commit,
    repository: REPOSITORY,
    target: `android-${arch}`,
    assets: [
      {
        platform: "android",
        arch,
        kind: "apk",
        filename,
        url: `${base}/${encodeURIComponent(filename)}`,
        sha256: await sha256(apk),
        size: (await stat(apk)).size,
      },
    ],
    android: { packageName: PACKAGE_NAME, versionCode: code, minSdk, signingCertificateSha256: certs },
  };
}

/** Signs `<manifest>` into `<manifest>.sig` with every configured key; returns the key ids. */
export async function signManifest(manifestPath, keyText, expectedPublicKey) {
  const { parseSigningKeys, encodeUpdatePublicKey, encodeUpdateSignature, signUpdateManifest, updateKeyId, verifyUpdateManifestSignature } =
    await signatureFormat();
  const keys = parseSigningKeys(keyText);
  const publicKeys = keys.map((key) => createPublicKey(key));
  if (expectedPublicKey && !publicKeys.some((key) => encodeUpdatePublicKey(key) === expectedPublicKey)) {
    throw new Error("BENTO_UPDATE_PUBLIC_KEY does not belong to the signing key; the app would reject this release");
  }
  const bytes = await readFile(manifestPath);
  const signature = Buffer.from(encodeUpdateSignature(signUpdateManifest(bytes, keys)), "utf8");
  for (const key of publicKeys) if (!verifyUpdateManifestSignature(bytes, signature, key)) throw new Error("Signature self-check failed");
  const target = `${manifestPath}.sig`;
  const temporary = `${target}.${process.pid}.tmp`;
  try {
    await writeFile(temporary, signature, { mode: 0o644 });
    await rename(temporary, target);
  } catch (error) {
    await rm(temporary, { force: true });
    throw error;
  }
  return publicKeys.map((key) => updateKeyId(key));
}

export async function verifyManifest(manifestPath, publicKeyText) {
  const { parseUpdatePublicKey, verifyUpdateManifestSignature } = await signatureFormat();
  const key = parseUpdatePublicKey(publicKeyText ?? "");
  if (!key) throw new Error("BENTO_UPDATE_PUBLIC_KEY is not base64 of a raw 32-byte Ed25519 key");
  const ok = verifyUpdateManifestSignature(await readFile(manifestPath), await readFile(`${manifestPath}.sig`), key);
  if (!ok) throw new Error(`${path.basename(manifestPath)}: signature does not verify`);
}

/** GitHub-shaped `releases` listing over the <root>/download/android-v… folders, for the local dry-run feed. */
export async function writeFeed(root, origin) {
  const downloads = path.join(root, "download");
  const tags = (await readdir(downloads, { withFileTypes: true })).filter((entry) => entry.isDirectory()).map((entry) => entry.name).sort();
  const releases = [];
  for (const tag of tags) {
    const files = (await readdir(path.join(downloads, tag))).sort();
    releases.push({
      tag_name: tag,
      draft: false,
      prerelease: false,
      assets: files.map((name) => ({ name, state: "uploaded", browser_download_url: `${origin}/download/${tag}/${name}` })),
    });
  }
  const listing = path.join(root, "repos", REPOSITORY, "releases");
  await mkdir(path.dirname(listing), { recursive: true });
  await writeFile(listing, `${JSON.stringify(releases.reverse(), null, 2)}\n`);
  return listing;
}

async function sha256(file) {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(file)) hash.update(chunk);
  return hash.digest("hex");
}

function options(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 2) {
    const name = argv[index];
    const value = argv[index + 1];
    if (!name?.startsWith("--") || value === undefined) throw new Error(`Invalid argument near ${name ?? "end"}`);
    result[name.slice(2)] = value;
  }
  return result;
}

function required(values, key) {
  if (!values[key]) throw new Error(`--${key} is required`);
  return values[key];
}

async function main([command, ...rest]) {
  if (command === "generate") {
    const values = options(rest);
    const arch = required(values, "arch");
    const out = path.resolve(required(values, "out"));
    const manifest = await buildManifest({
      apk: path.resolve(required(values, "apk")),
      arch,
      version: required(values, "version"),
      commit: required(values, "commit"),
      certs: required(values, "cert-sha256").split(",").map((cert) => cert.trim().toLowerCase()).filter(Boolean),
      baseUrl: values["base-url"],
      publishedAt: values["published-at"],
      minSdk: values["min-sdk"] ? Number(values["min-sdk"]) : undefined,
    });
    const output = path.join(out, manifestName(arch));
    await writeFile(output, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
    console.log(`wrote ${path.basename(output)}`);
    const keyText = await signingKeyText();
    if (keyText) {
      const ids = await signManifest(output, keyText, process.env.BENTO_UPDATE_PUBLIC_KEY?.trim() || undefined);
      console.log(`signed ${path.basename(output)}.sig (key ids: ${ids.join(", ")})`);
    } else {
      console.log("no signing key configured: manifest left unsigned");
    }
    return;
  }
  if (command === "verify") {
    for (const file of rest) {
      await verifyManifest(path.resolve(file), process.env.BENTO_UPDATE_PUBLIC_KEY?.trim());
      console.log(`verified ${path.basename(file)}.sig`);
    }
    return;
  }
  if (command === "feed") {
    const values = options(rest);
    console.log(await writeFeed(path.resolve(required(values, "root")), required(values, "origin")));
    return;
  }
  throw new Error("Usage: update_manifest.mjs generate|verify|feed …");
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    await main(process.argv.slice(2));
  } catch (error) {
    console.error(`update_manifest: ${error instanceof Error ? error.message : "failed"}`);
    process.exit(1);
  }
}
