// Android distribution: assetlinks.json generation and serving, the production guard for the
// release certificate fingerprint, APK download links/SHA-256 on the pages, and the screenshots.
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "../scripts/build.mjs";
import { createPreviewServer } from "../scripts/serve.mjs";
import { headersFor, parseHeaders } from "../scripts/lib/headers.mjs";
import {
  ANDROID_ASSET_IDS,
  applyAndroidRelease,
  assertProductionReady,
  assetLinks,
  validateAndroidConfig,
} from "../scripts/lib/android.mjs";
import { SCREENSHOTS } from "../scripts/import-android-screenshots.mjs";
import { tags } from "./lib/html.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(root, "../..");
const dist = path.join(root, "dist");

const RELEASE_FP = "14:6D:E9:83:C5:73:06:50:D8:EE:B9:95:2F:34:FC:64:16:A0:83:42:E6:1D:BE:A8:8A:04:96:B2:3F:CF:44:E5";
const UPLOAD_FP = "fa:c6:17:45:dc:09:03:78:6f:b9:ed:e6:2a:96:2b:39:9f:73:48:f0:bb:6f:89:9b:83:32:66:75:91:03:3b:9c";
const PLACEHOLDER = "[[COMPLETAR: huella SHA-256 del certificado de firma de release de Android]]";
const HASH_A = "a".repeat(64);
const HASH_B = "0123456789abcdef".repeat(4);

function androidConfig(overrides = {}) {
  return { package: "dev.bento.app", sha256CertFingerprints: [RELEASE_FP], release: null, ...overrides };
}

function siteConfig(android) {
  return { repository: "invrnt/bento", release: null, android };
}

const androidRelease = {
  tag: "android-v1.4.0",
  assets: { "android-arm64": "bento-android-1.4.0-arm64-v8a.apk", "android-universal": "bento-android-1.4.0-universal.apk" },
  sha256: { "android-arm64": HASH_A, "android-universal": HASH_B.toUpperCase() },
};

async function withTempBuild(config, run, options = {}) {
  const output = await mkdtemp(path.join(tmpdir(), "bento-site-android-"));
  try {
    await build({ output, config, ...options });
    return await run(output);
  } finally {
    await rm(output, { recursive: true, force: true });
  }
}

describe("assetlinks.json", () => {
  it("declares handle_all_urls for the package with upper-cased fingerprints", () => {
    const android = validateAndroidConfig(androidConfig({ sha256CertFingerprints: [RELEASE_FP, UPLOAD_FP] }));
    assert.deepEqual(assetLinks(android), [
      {
        relation: ["delegate_permission/common.handle_all_urls"],
        target: {
          namespace: "android_app",
          package_name: "dev.bento.app",
          sha256_cert_fingerprints: [RELEASE_FP, UPLOAD_FP.toUpperCase()],
        },
      },
    ]);
  });

  it("leaves placeholder fingerprints out of the published file", () => {
    const android = validateAndroidConfig(androidConfig({ sha256CertFingerprints: [PLACEHOLDER] }));
    assert.deepEqual(assetLinks(android)[0].target.sha256_cert_fingerprints, []);
  });

  it("rejects malformed configuration", () => {
    assert.throws(() => validateAndroidConfig(undefined));
    assert.throws(() => validateAndroidConfig(androidConfig({ package: "Bento" })));
    assert.throws(() => validateAndroidConfig(androidConfig({ package: "dev.bento.app/../x" })));
    assert.throws(() => validateAndroidConfig(androidConfig({ sha256CertFingerprints: [] })));
    assert.throws(() => validateAndroidConfig(androidConfig({ sha256CertFingerprints: ["14:6D:E9"] })));
    assert.throws(() => validateAndroidConfig(androidConfig({ sha256CertFingerprints: [RELEASE_FP.replace(/:/gu, "")] })));
    assert.throws(() => validateAndroidConfig(androidConfig({ sha256CertFingerprints: [RELEASE_FP, RELEASE_FP.toLowerCase()] })));
    assert.throws(() => validateAndroidConfig(androidConfig({ sha256CertFingerprints: ["TODO"] })));
  });

  it("blocks production builds while the release fingerprint is a placeholder", async () => {
    const pending = validateAndroidConfig(androidConfig({ sha256CertFingerprints: [PLACEHOLDER, UPLOAD_FP] }));
    assert.throws(() => assertProductionReady(pending), /placeholder/u);
    assert.doesNotThrow(() => assertProductionReady(validateAndroidConfig(androidConfig())));
    await assert.rejects(
      withTempBuild(siteConfig(androidConfig({ sha256CertFingerprints: [PLACEHOLDER] })), async () => {}, { production: true }),
      /Production build blocked/u,
    );
  });

  it("is written at /.well-known/assetlinks.json by a production build with a real fingerprint", async () => {
    await withTempBuild(
      siteConfig(androidConfig()),
      async (output) => {
        const document = JSON.parse(await readFile(path.join(output, ".well-known/assetlinks.json"), "utf8"));
        assert.deepEqual(document[0].target.sha256_cert_fingerprints, [RELEASE_FP]);
      },
      { production: true },
    );
  });

  it("matches the Android application id and the checked-in site configuration", async () => {
    const config = JSON.parse(await readFile(path.join(root, "site.config.json"), "utf8"));
    const gradle = await readFile(path.join(repoRoot, "apps/android/app/build.gradle.kts"), "utf8");
    assert.equal(config.android.package, /applicationId\s*=\s*"([^"]+)"/u.exec(gradle)?.[1]);
    const published = JSON.parse(await readFile(path.join(dist, ".well-known/assetlinks.json"), "utf8"));
    assert.deepEqual(published, assetLinks(validateAndroidConfig(config.android)));
  });

  it("is declared as JSON in _headers", async () => {
    const rules = parseHeaders(await readFile(path.join(dist, "_headers"), "utf8"));
    assert.equal(headersFor(rules, "/.well-known/assetlinks.json")["Content-Type"], "application/json");
  });

  it("is served by the preview server as application/json with no redirect", async () => {
    const server = await createPreviewServer(dist);
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    try {
      const base = `http://127.0.0.1:${server.address().port}`;
      const response = await fetch(`${base}/.well-known/assetlinks.json`, { redirect: "manual" });
      assert.equal(response.status, 200);
      assert.equal(response.headers.get("content-type"), "application/json");
      assert.ok(Array.isArray(await response.json()));
      // The App Link path is /join; Pages answers with a same-origin redirect that browsers
      // follow keeping the fragment (the code never reaches the server either way).
      const join = await fetch(`${base}/join`, { redirect: "manual" });
      assert.equal(join.status, 308);
      assert.equal(join.headers.get("location"), "/join/");
    } finally {
      await new Promise((resolve) => server.close(resolve));
    }
  });
});

describe("Android release links", () => {
  it("validates the release block", () => {
    assert.doesNotThrow(() => validateAndroidConfig(androidConfig({ release: androidRelease })));
    assert.throws(() => validateAndroidConfig(androidConfig({ release: { ...androidRelease, tag: "latest" } })));
    assert.throws(() => validateAndroidConfig(androidConfig({ release: { ...androidRelease, assets: { "android-arm64": "x.apk" } } })));
    assert.throws(() => validateAndroidConfig(androidConfig({ release: { ...androidRelease, assets: { ...androidRelease.assets, "android-arm64": "../x.apk" } } })));
    assert.throws(() => validateAndroidConfig(androidConfig({ release: { ...androidRelease, assets: { ...androidRelease.assets, "android-arm64": "x.zip" } } })));
    assert.throws(() => validateAndroidConfig(androidConfig({ release: { ...androidRelease, sha256: { ...androidRelease.sha256, "android-arm64": "abc" } } })));
    assert.throws(() => validateAndroidConfig(androidConfig({ release: { ...androidRelease, sha256: { ...androidRelease.sha256, extra: HASH_A } } })));
  });

  it("rewrites download anchors and fills SHA-256 values", () => {
    const android = validateAndroidConfig(androidConfig({ release: androidRelease }));
    const html = '<a data-android-asset="android-arm64" href="https://github.com/invrnt/bento/releases/latest">A</a>'
      + '<code class="hash" data-android-sha256="android-universal">pending</code>'
      + '<a data-android-checksums href="https://github.com/invrnt/bento/releases/latest">S</a><a href="/x/">keep</a>';
    const output = applyAndroidRelease(html, "invrnt/bento", android);
    assert.match(output, /href="https:\/\/github\.com\/invrnt\/bento\/releases\/download\/android-v1\.4\.0\/bento-android-1\.4\.0-arm64-v8a\.apk"/u);
    assert.match(output, new RegExp(`<code class="hash" data-android-sha256="android-universal">${HASH_B}</code>`, "u"));
    assert.match(output, /href="https:\/\/github\.com\/invrnt\/bento\/releases\/download\/android-v1\.4\.0\/SHA256SUMS-android"/u);
    assert.match(output, /<a href="\/x\/">keep<\/a>/u);
    assert.equal(applyAndroidRelease(html, "invrnt/bento", validateAndroidConfig(androidConfig())), html);
    assert.throws(() => applyAndroidRelease('<a data-android-asset="ios" href="#">x</a>', "invrnt/bento", android));
  });

  it("builds pages that point at the exact APKs and show their hashes", async () => {
    await withTempBuild(siteConfig(androidConfig({ release: androidRelease })), async (output) => {
      for (const page of ["android/index.html", "en/android/index.html"]) {
        const html = await readFile(path.join(output, page), "utf8");
        assert.ok(html.includes("/releases/download/android-v1.4.0/bento-android-1.4.0-arm64-v8a.apk"), page);
        assert.ok(html.includes("/releases/download/android-v1.4.0/bento-android-1.4.0-universal.apk"), page);
        assert.ok(html.includes(HASH_A) && html.includes(HASH_B), page);
      }
      for (const page of ["join/index.html", "en/join/index.html", "index.html", "en/index.html"]) {
        const html = await readFile(path.join(output, page), "utf8");
        assert.ok(html.includes("/releases/download/android-v1.4.0/bento-android-1.4.0-arm64-v8a.apk"), page);
      }
    });
  });
});

describe("Android download page", () => {
  for (const page of ["android/index.html", "en/android/index.html"]) {
    it(`${page} offers both APKs with their SHA-256 and the checksum file`, async () => {
      const all = tags(await readFile(path.join(dist, page), "utf8"));
      const assets = all.filter((tag) => tag.attrs["data-android-asset"]).map((tag) => tag.attrs["data-android-asset"]);
      assert.deepEqual([...new Set(assets)].sort(), [...ANDROID_ASSET_IDS].sort());
      const hashes = all.filter((tag) => tag.name === "code" && tag.attrs["data-android-sha256"]).map((tag) => tag.attrs["data-android-sha256"]);
      assert.deepEqual(hashes.sort(), [...ANDROID_ASSET_IDS].sort());
      assert.ok(all.some((tag) => tag.name === "a" && "data-android-checksums" in tag.attrs));
    });

    it(`${page} shows the phone screenshots with alt text and real dimensions`, async () => {
      const images = tags(await readFile(path.join(dist, page), "utf8")).filter((tag) => tag.name === "img");
      assert.ok(images.length >= 3);
      for (const image of images) {
        assert.ok(image.attrs.src.startsWith("/assets/android/") && image.attrs.src.endsWith(".webp"), image.attrs.src);
        assert.ok((image.attrs.alt ?? "").length > 20, image.attrs.src);
        const bytes = await readFile(path.join(dist, image.attrs.src));
        assert.equal(bytes.subarray(0, 4).toString("latin1"), "RIFF");
        assert.equal(bytes.subarray(8, 12).toString("latin1"), "WEBP");
        assert.ok(bytes.length <= 40 * 1024, `${image.attrs.src} is ${bytes.length} bytes`);
        assert.deepEqual([Number(image.attrs.width), Number(image.attrs.height)], webpSize(bytes), image.attrs.src);
      }
    });
  }

  it("publishes every imported screenshot", async () => {
    for (const { name } of SCREENSHOTS) assert.ok((await stat(path.join(dist, "assets/android", name))).isFile(), name);
  });
});

/** Width/height from a VP8, VP8L or VP8X WebP header. */
function webpSize(bytes) {
  const chunk = bytes.subarray(12, 16).toString("latin1");
  if (chunk === "VP8X") return [1 + bytes.readUIntLE(24, 3), 1 + bytes.readUIntLE(27, 3)];
  if (chunk === "VP8L") {
    const bits = bytes.readUInt32LE(21);
    return [(bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1];
  }
  if (chunk === "VP8 ") return [bytes.readUInt16LE(26) & 0x3fff, bytes.readUInt16LE(28) & 0x3fff];
  throw new Error(`Unknown WebP chunk ${chunk}`);
}
