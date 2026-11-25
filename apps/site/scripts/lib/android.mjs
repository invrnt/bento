// Android distribution: the Digital Asset Links file that verifies the https://<site>/join
// App Link, and the APK download links/SHA-256 values on the Android and join pages.
// Everything comes from the `android` block of site.config.json.

export const ANDROID_ASSET_IDS = Object.freeze(["android-arm64", "android-universal"]);

const PACKAGE = /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$/u;
const FINGERPRINT = /^([0-9A-F]{2}:){31}[0-9A-F]{2}$/u;
const PLACEHOLDER = /^\[\[COMPLETAR:[^\]]*\]\]$/u;
const SHA256 = /^[0-9a-f]{64}$/u;
const TAG = /^(android-)?v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/u;
const FILE_NAME = /^[^/\\]+\.apk$/u;

export function isPlaceholder(value) {
  return typeof value === "string" && PLACEHOLDER.test(value);
}

/** Accepts `AB:CD:…` (32 bytes) in any case; returns it upper-cased, or the placeholder untouched. */
export function normalizeFingerprint(value) {
  if (isPlaceholder(value)) return value;
  if (typeof value !== "string") return null;
  const upper = value.trim().toUpperCase();
  return FINGERPRINT.test(upper) ? upper : null;
}

export function validateAndroidConfig(android) {
  if (!android || typeof android !== "object") throw new Error("site.config.json: android must be an object");
  if (!PACKAGE.test(android.package ?? "")) throw new Error("site.config.json: android.package must be an application id such as dev.bento.app");
  const raw = android.sha256CertFingerprints;
  if (!Array.isArray(raw) || raw.length === 0) {
    throw new Error("site.config.json: android.sha256CertFingerprints must list at least one signing certificate");
  }
  const fingerprints = raw.map((value, index) => {
    const normalized = normalizeFingerprint(value);
    if (!normalized) throw new Error(`site.config.json: android.sha256CertFingerprints[${index}] must look like AB:CD:… (32 bytes, from apksigner or keytool)`);
    return normalized;
  });
  if (new Set(fingerprints).size !== fingerprints.length) throw new Error("site.config.json: android.sha256CertFingerprints has duplicates");

  const release = android.release ?? null;
  if (release === null) return { package: android.package, sha256CertFingerprints: fingerprints, release: null };
  if (!TAG.test(release.tag ?? "")) throw new Error("site.config.json: android.release.tag must be a stable tag such as v1.2.3 or android-v1.2.3");
  const assets = release.assets ?? {};
  const sha256 = release.sha256 ?? {};
  for (const group of [assets, sha256]) {
    for (const key of Object.keys(group)) {
      if (!ANDROID_ASSET_IDS.includes(key)) throw new Error(`site.config.json: unknown Android release asset "${key}"`);
    }
  }
  for (const id of ANDROID_ASSET_IDS) {
    if (typeof assets[id] !== "string" || !FILE_NAME.test(assets[id])) {
      throw new Error(`site.config.json: android.release.assets.${id} must be the exact .apk file name published in the release`);
    }
    if (typeof sha256[id] !== "string" || !SHA256.test(sha256[id].toLowerCase())) {
      throw new Error(`site.config.json: android.release.sha256.${id} must be the 64-character SHA-256 of that APK`);
    }
  }
  const checksums = release.checksums ?? "SHA256SUMS-android";
  if (typeof checksums !== "string" || !/^[^/\\]+$/u.test(checksums)) throw new Error("site.config.json: android.release.checksums must be a file name");
  return {
    package: android.package,
    sha256CertFingerprints: fingerprints,
    release: {
      tag: release.tag,
      assets: { ...assets },
      sha256: Object.fromEntries(ANDROID_ASSET_IDS.map((id) => [id, sha256[id].toLowerCase()])),
      checksums,
    },
  };
}

/** Throws when a production build would publish a placeholder certificate fingerprint. */
export function assertProductionReady(android) {
  const placeholders = android.sha256CertFingerprints.filter(isPlaceholder);
  if (placeholders.length > 0) {
    throw new Error(
      "Production build blocked: site.config.json android.sha256CertFingerprints still holds a placeholder. "
      + "Add the SHA-256 fingerprint of the Android release signing certificate (see docs/dev/android.md).",
    );
  }
}

/**
 * The /.well-known/assetlinks.json document (Digital Asset Links). Placeholder fingerprints are
 * left out so a preview build never claims a certificate that does not exist.
 */
export function assetLinks(android) {
  const fingerprints = android.sha256CertFingerprints.filter((value) => !isPlaceholder(value));
  return [
    {
      relation: ["delegate_permission/common.handle_all_urls"],
      target: {
        namespace: "android_app",
        package_name: android.package,
        sha256_cert_fingerprints: fingerprints,
      },
    },
  ];
}

export function assetLinksJson(android) {
  return `${JSON.stringify(assetLinks(android), null, 2)}\n`;
}

function escapeHtml(value) {
  return value.replace(/&/gu, "&amp;").replace(/</gu, "&lt;").replace(/>/gu, "&gt;").replace(/"/gu, "&quot;");
}

function download(repository, tag, filename) {
  return `https://github.com/${repository}/releases/download/${encodeURIComponent(tag)}/${encodeURIComponent(filename)}`;
}

/**
 * Rewrites `data-android-asset` / `data-android-checksums` anchors to the exact release files and
 * fills `<code data-android-sha256="…">` with the APK hash. Without a release the markup keeps its
 * fallbacks (the latest-release page and a "listed in the release" note).
 */
export function applyAndroidRelease(html, repository, android) {
  const release = android.release;
  if (release === null) return html;
  const withLinks = html.replace(/<a\b[^>]*>/gu, (tag) => {
    const asset = /\bdata-android-asset="([^"]+)"/u.exec(tag)?.[1];
    const checksums = /\bdata-android-checksums\b/u.test(tag);
    if (!asset && !checksums) return tag;
    if (asset && !ANDROID_ASSET_IDS.includes(asset)) throw new Error(`Unknown data-android-asset "${asset}"`);
    const href = download(repository, release.tag, asset ? release.assets[asset] : release.checksums);
    if (!/\bhref="[^"]*"/u.test(tag)) throw new Error(`Download anchor without href: ${tag}`);
    return tag.replace(/\bhref="[^"]*"/u, `href="${escapeHtml(href)}"`);
  });
  return withLinks.replace(/(<code\b[^>]*\bdata-android-sha256="([^"]+)"[^>]*>)[\s\S]*?(<\/code>)/gu, (_match, open, id, close) => {
    if (!ANDROID_ASSET_IDS.includes(id)) throw new Error(`Unknown data-android-sha256 "${id}"`);
    return `${open}${release.sha256[id]}${close}`;
  });
}
