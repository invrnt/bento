import { createPrivateKey, createPublicKey, generateKeyPairSync } from "node:crypto";
import { readFile, rename, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

// Signs per-target updater manifests (`bento-update-<platform>-<arch>.json`) with Ed25519 and writes
// the detached `<manifest>.sig` next to each one. Private keys come only from BENTO_UPDATE_SIGNING_KEY
// (one or more PKCS#8 PEM blocks; several sign a rotation release) and are never printed.
//
//   node scripts/sign-update-manifest.mjs <manifest.json>...   sign (BENTO_UPDATE_PUBLIC_KEY, when set,
//                                                              must belong to one of the signing keys)
//   node scripts/sign-update-manifest.mjs --generate-key <out.pem>   new key (0600); prints the public key
//   node scripts/sign-update-manifest.mjs --public-key               public key(s) of BENTO_UPDATE_SIGNING_KEY
//
// See docs/desktop/releasing.md for key generation, storage, and rotation.

const SIGNING_KEY_ENV = "BENTO_UPDATE_SIGNING_KEY";
const PUBLIC_KEY_ENV = "BENTO_UPDATE_PUBLIC_KEY";
const MANIFEST_NAME = /^bento-update-(?:darwin|linux|win32)-(?:x64|arm64)\.json$/u;
const PEM_BLOCK = /-----BEGIN ([A-Z0-9 ]+)-----[\s\S]+?-----END \1-----/gu;

let runtime;
async function signatures() {
  // Node.js 22.18+/24 strips types natively, so the updater's own format code is reused.
  runtime ??= await import("../src/main/update-signature.ts");
  return runtime;
}

/** Ed25519 private keys from PEM text; messages never include key material. */
export function parseSigningKeys(text) {
  if (typeof text !== "string" || !text.trim()) throw new Error(`${SIGNING_KEY_ENV} is not set`);
  const normalized = text.includes("\\n") && !text.includes("\n") ? text.replaceAll("\\n", "\n") : text;
  const blocks = normalized.match(PEM_BLOCK) ?? [];
  if (blocks.length === 0) throw new Error(`${SIGNING_KEY_ENV} must contain PEM-encoded PKCS#8 Ed25519 private keys`);
  return blocks.map((block, index) => {
    let key;
    try {
      key = createPrivateKey({ key: block, format: "pem" });
    } catch {
      throw new Error(`${SIGNING_KEY_ENV} key #${index + 1} could not be parsed`);
    }
    if (key.asymmetricKeyType !== "ed25519") throw new Error(`${SIGNING_KEY_ENV} key #${index + 1} is not an Ed25519 key`);
    return key;
  });
}

export async function signManifestFiles(manifestPaths, { signingKeyText, expectedPublicKey } = {}) {
  const { encodeUpdatePublicKey, encodeUpdateSignature, parseUpdatePublicKey, signUpdateManifest, updateKeyId, verifyUpdateManifestSignature } = await signatures();
  if (manifestPaths.length === 0) throw new Error("No updater manifests to sign");
  const keys = parseSigningKeys(signingKeyText);
  const publicKeys = keys.map((key) => createPublicKey(key));
  if (new Set(publicKeys.map((key) => updateKeyId(key))).size !== publicKeys.length) throw new Error("Duplicate signing keys");
  if (expectedPublicKey) {
    if (!parseUpdatePublicKey(expectedPublicKey)) throw new Error(`${PUBLIC_KEY_ENV} is not base64 of a raw 32-byte Ed25519 key`);
    if (!publicKeys.some((key) => encodeUpdatePublicKey(key) === expectedPublicKey)) {
      throw new Error(`${PUBLIC_KEY_ENV} does not belong to any key in ${SIGNING_KEY_ENV}; builds would reject this release`);
    }
  }
  const written = [];
  for (const manifestPath of manifestPaths) {
    if (!MANIFEST_NAME.test(path.basename(manifestPath))) throw new Error(`Not an updater manifest: ${path.basename(manifestPath)}`);
    const manifest = await readFile(manifestPath);
    const signature = Buffer.from(encodeUpdateSignature(signUpdateManifest(manifest, keys)), "utf8");
    for (const publicKey of publicKeys) {
      if (!verifyUpdateManifestSignature(manifest, signature, publicKey)) throw new Error("Signature self-check failed");
    }
    const target = `${manifestPath}.sig`;
    const temporary = `${target}.${process.pid}.tmp`;
    try {
      await writeFile(temporary, signature, { flag: "wx", mode: 0o644 });
      await rename(temporary, target);
    } catch (error) {
      await rm(temporary, { force: true });
      throw error;
    }
    written.push({ manifest: path.basename(manifestPath), signature: path.basename(target), keyIds: publicKeys.map((key) => updateKeyId(key)) });
  }
  return written;
}

export async function generateSigningKey(outputPath) {
  const { encodeUpdatePublicKey } = await signatures();
  const { privateKey, publicKey } = generateKeyPairSync("ed25519");
  const pem = privateKey.export({ format: "pem", type: "pkcs8" });
  // Exclusive create: never overwrite an existing key.
  await writeFile(outputPath, pem, { flag: "wx", mode: 0o600 });
  return encodeUpdatePublicKey(publicKey);
}

async function main(arguments_) {
  const { encodeUpdatePublicKey } = await signatures();
  if (arguments_[0] === "--generate-key") {
    if (arguments_.length !== 2) throw new Error("Usage: --generate-key <out.pem>");
    const publicKey = await generateSigningKey(path.resolve(arguments_[1]));
    console.log(`Wrote a new Ed25519 signing key to ${arguments_[1]} (keep it secret; store it as ${SIGNING_KEY_ENV}).`);
    console.log(`${PUBLIC_KEY_ENV}=${publicKey}`);
    return;
  }
  if (arguments_[0] === "--public-key") {
    for (const key of parseSigningKeys(process.env[SIGNING_KEY_ENV])) console.log(encodeUpdatePublicKey(createPublicKey(key)));
    return;
  }
  const written = await signManifestFiles(arguments_.map((value) => path.resolve(value)), {
    signingKeyText: process.env[SIGNING_KEY_ENV],
    expectedPublicKey: process.env[PUBLIC_KEY_ENV]?.trim() || undefined,
  });
  for (const item of written) console.log(`signed ${item.manifest} -> ${item.signature} (key ids: ${item.keyIds.join(", ")})`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    await main(process.argv.slice(2));
  } catch (error) {
    console.error(`sign-update-manifest: ${error instanceof Error ? error.message : "failed"}`);
    process.exit(1);
  }
}
