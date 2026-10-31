import { createHash, createPublicKey, KeyObject, sign, verify } from "node:crypto";

// Ed25519 signatures over the exact bytes of a per-target update manifest, published as the
// detached release asset `<manifest>.sig`. Shared by the updater and scripts/sign-update-manifest.mjs
// (loaded through Node type stripping, so keep this file to erasable TypeScript and node: imports).
//
//   message   = "bento-update-manifest:v1" || 0x00 || manifest bytes
//   .sig file = {"schemaVersion":1,"algorithm":"ed25519","signatures":[{"keyId","signature"}]}
//   keyId     = first 16 hex characters of SHA-256(raw 32-byte public key)
//
// Several signatures allow key rotation: releases are signed with the old and the new key until
// every supported build embeds the new public key.

export const UPDATE_SIGNATURE_SUFFIX = ".sig";
export const MAX_UPDATE_SIGNATURE_BYTES = 4096;
export const MAX_UPDATE_SIGNATURES = 4;

const CONTEXT = Buffer.from("bento-update-manifest:v1\u0000", "utf8");
const RAW_PUBLIC_KEY = /^[A-Za-z0-9+/]{43}=$/u;
const SIGNATURE = /^[A-Za-z0-9+/]{86}==$/u;
const KEY_ID = /^[a-f0-9]{16}$/u;

export interface UpdateSignatureEntry {
  keyId: string;
  signature: string;
}

export interface UpdateSignatureDocument {
  schemaVersion: 1;
  algorithm: "ed25519";
  signatures: UpdateSignatureEntry[];
}

/** Ed25519 public key from canonical base64 of its raw 32 bytes, or `null`. */
export function parseUpdatePublicKey(value: string): KeyObject | null {
  if (typeof value !== "string" || !RAW_PUBLIC_KEY.test(value)) return null;
  const raw = Buffer.from(value, "base64");
  if (raw.length !== 32 || raw.toString("base64") !== value) return null;
  try {
    return createPublicKey({ key: { kty: "OKP", crv: "Ed25519", x: raw.toString("base64url") }, format: "jwk" });
  } catch {
    return null;
  }
}

/** Canonical base64 of the raw public key (the `updatePublicKey` build-config format). */
export function encodeUpdatePublicKey(key: KeyObject): string {
  return rawPublicKey(key).toString("base64");
}

export function updateKeyId(key: KeyObject): string {
  return createHash("sha256").update(rawPublicKey(key)).digest("hex").slice(0, 16);
}

export function signUpdateManifest(manifest: Uint8Array, privateKeys: readonly KeyObject[]): UpdateSignatureDocument {
  if (privateKeys.length === 0 || privateKeys.length > MAX_UPDATE_SIGNATURES) throw new Error("Expected one to four signing keys");
  return {
    schemaVersion: 1,
    algorithm: "ed25519",
    signatures: privateKeys.map((privateKey) => {
      if (privateKey.type !== "private" || privateKey.asymmetricKeyType !== "ed25519") throw new Error("Signing keys must be Ed25519 private keys");
      return { keyId: updateKeyId(privateKey), signature: sign(null, signedMessage(manifest), privateKey).toString("base64") };
    }),
  };
}

export function encodeUpdateSignature(document: UpdateSignatureDocument): string {
  return `${JSON.stringify(document)}\n`;
}

/** True only for a well-formed signature document with a valid signature by `publicKey`. */
export function verifyUpdateManifestSignature(manifest: Uint8Array, signatureFile: Uint8Array, publicKey: KeyObject): boolean {
  const document = parseSignatureDocument(signatureFile);
  if (!document) return false;
  const keyId = updateKeyId(publicKey);
  const message = signedMessage(manifest);
  return document.signatures.some((entry) => {
    if (entry.keyId !== keyId) return false;
    try {
      return verify(null, message, publicKey, Buffer.from(entry.signature, "base64"));
    } catch {
      return false;
    }
  });
}

function parseSignatureDocument(bytes: Uint8Array): UpdateSignatureDocument | null {
  if (bytes.byteLength === 0 || bytes.byteLength > MAX_UPDATE_SIGNATURE_BYTES) return null;
  let value: unknown;
  try {
    value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    return null;
  }
  if (!isPlainObject(value) || !hasExactKeys(value, ["schemaVersion", "algorithm", "signatures"])) return null;
  if (value.schemaVersion !== 1 || value.algorithm !== "ed25519") return null;
  const signatures = value.signatures;
  if (!Array.isArray(signatures) || signatures.length === 0 || signatures.length > MAX_UPDATE_SIGNATURES) return null;
  for (const entry of signatures) {
    if (!isPlainObject(entry) || !hasExactKeys(entry, ["keyId", "signature"])) return null;
    if (typeof entry.keyId !== "string" || !KEY_ID.test(entry.keyId)) return null;
    if (typeof entry.signature !== "string" || !SIGNATURE.test(entry.signature)) return null;
  }
  return value as unknown as UpdateSignatureDocument;
}

function signedMessage(manifest: Uint8Array): Buffer {
  return Buffer.concat([CONTEXT, manifest]);
}

function rawPublicKey(key: KeyObject): Buffer {
  const publicKey = key.type === "public" ? key : createPublicKey(key);
  if (publicKey.asymmetricKeyType !== "ed25519") throw new Error("Update keys must be Ed25519");
  const jwk = publicKey.export({ format: "jwk" });
  if (typeof jwk.x !== "string") throw new Error("Update keys must be Ed25519");
  return Buffer.from(jwk.x, "base64url");
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === keys.length && keys.every((key) => actual.includes(key));
}
