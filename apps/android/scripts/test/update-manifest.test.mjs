import assert from "node:assert/strict";
import { generateKeyPairSync, createHash } from "node:crypto";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { apkName, buildManifest, signManifest, verifyManifest, versionCode, writeFeed } from "../update_manifest.mjs";

const commit = "0123456789abcdef0123456789abcdef01234567";
const cert = "a".repeat(64);

async function fixture() {
  const dir = await mkdtemp(path.join(tmpdir(), "bento-manifest-"));
  const apk = path.join(dir, apkName("1.2.3", "arm64"));
  await writeFile(apk, Buffer.from("not really an apk"));
  return { dir, apk };
}

function keys() {
  const { privateKey, publicKey } = generateKeyPairSync("ed25519");
  const raw = Buffer.from(publicKey.export({ format: "jwk" }).x, "base64url").toString("base64");
  return { pem: privateKey.export({ format: "pem", type: "pkcs8" }), raw };
}

test("version codes match app/build.gradle.kts and core/update", () => {
  assert.equal(versionCode("1.2.3"), 1_002_003);
  assert.equal(versionCode("0.1.0"), 1_000);
  assert.throws(() => versionCode("1.2"));
  assert.throws(() => versionCode("1.1000.0"));
});

test("manifest has the desktop schema plus the android block", async () => {
  const { apk } = await fixture();
  const manifest = await buildManifest({ apk, arch: "arm64", version: "1.2.3", commit, certs: [cert], publishedAt: "2026-11-24T00:00:00Z" });
  assert.equal(manifest.schemaVersion, 1);
  assert.equal(manifest.target, "android-arm64");
  assert.equal(manifest.repository, "invrnt/bento");
  assert.deepEqual(manifest.android, { packageName: "dev.bento.app", versionCode: 1_002_003, minSdk: 29, signingCertificateSha256: [cert] });
  const [asset] = manifest.assets;
  assert.equal(asset.url, "https://github.com/invrnt/bento/releases/download/android-v1.2.3/bento-android-1.2.3-arm64-v8a.apk");
  assert.equal(asset.sha256, createHash("sha256").update("not really an apk").digest("hex"));
  assert.equal(asset.size, 17);
});

test("wrongly named APKs and bad certs are refused", async () => {
  const { apk } = await fixture();
  await assert.rejects(buildManifest({ apk, arch: "universal", version: "1.2.3", commit, certs: [cert] }));
  await assert.rejects(buildManifest({ apk, arch: "arm64", version: "1.2.3", commit, certs: ["A".repeat(64)] }));
});

test("signs with the desktop format and verifies; a tampered manifest fails", async () => {
  const { dir, apk } = await fixture();
  const key = keys();
  const manifestPath = path.join(dir, "bento-update-android-arm64.json");
  await writeFile(manifestPath, JSON.stringify(await buildManifest({ apk, arch: "arm64", version: "1.2.3", commit, certs: [cert] })));
  const ids = await signManifest(manifestPath, key.pem, key.raw);
  assert.equal(ids.length, 1);
  await verifyManifest(manifestPath, key.raw);
  await assert.rejects(signManifest(manifestPath, key.pem, keys().raw), /does not belong/u);
  await writeFile(manifestPath, (await readFile(manifestPath, "utf8")).replace("1.2.3", "1.2.4"));
  await assert.rejects(verifyManifest(manifestPath, key.raw), /does not verify/u);
});

test("local feed lists every dry-run release", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "bento-feed-"));
  for (const tag of ["android-v0.1.0", "android-v0.1.1"]) {
    const dir = path.join(root, "download", tag);
    await (await import("node:fs/promises")).mkdir(dir, { recursive: true });
    await writeFile(path.join(dir, "bento-update-android-universal.json"), "{}");
  }
  const listing = JSON.parse(await readFile(await writeFeed(root, "http://127.0.0.1:8799"), "utf8"));
  assert.deepEqual(listing.map((release) => release.tag_name), ["android-v0.1.1", "android-v0.1.0"]);
  assert.equal(listing[0].assets[0].browser_download_url, "http://127.0.0.1:8799/download/android-v0.1.1/bento-update-android-universal.json");
});
