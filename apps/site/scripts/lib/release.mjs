// Download links default to the GitHub "latest release" page, which always resolves.
// When site.config.json names a published release, anchors marked with
// data-asset / data-checksums are pointed at the exact release files instead.

export const ASSET_IDS = Object.freeze([
  "windows-x64",
  "macos-arm64",
  "macos-x64",
  "linux-x64-deb",
  "linux-x64-zip",
]);

const CHECKSUM_TARGETS = Object.freeze({
  "windows-x64": "windows-x64",
  "macos-arm64": "macos-arm64",
  "macos-x64": "macos-x64",
  "linux-x64": "linux-x64",
});

const TAG = /^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/u;
const REPOSITORY = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/u;

export function validateConfig(config) {
  if (!config || typeof config !== "object") throw new Error("site.config.json must be an object");
  if (!REPOSITORY.test(config.repository ?? "")) throw new Error("site.config.json: repository must look like owner/name");
  const release = config.release ?? null;
  if (release === null) return { repository: config.repository, release: null };
  if (!TAG.test(release.tag ?? "")) throw new Error("site.config.json: release.tag must be a stable tag such as v1.2.3");
  const assets = release.assets ?? {};
  for (const id of ASSET_IDS) {
    const filename = assets[id];
    if (typeof filename !== "string" || filename.trim() === "" || /[/\\]/u.test(filename)) {
      throw new Error(`site.config.json: release.assets.${id} must be the exact file name published in the release`);
    }
  }
  for (const key of Object.keys(assets)) {
    if (!ASSET_IDS.includes(key)) throw new Error(`site.config.json: unknown release asset "${key}"`);
  }
  return { repository: config.repository, release: { tag: release.tag, assets: { ...assets } } };
}

export function releaseUrl(repository, tag, filename) {
  return `https://github.com/${repository}/releases/download/${encodeURIComponent(tag)}/${encodeURIComponent(filename)}`;
}

export function applyRelease(html, config) {
  const { repository, release } = validateConfig(config);
  if (release === null) return html;
  return html.replace(/<a\b[^>]*>/gu, (tag) => {
    const asset = /\bdata-asset="([^"]+)"/u.exec(tag)?.[1];
    const checksums = /\bdata-checksums="([^"]+)"/u.exec(tag)?.[1];
    if (!asset && !checksums) return tag;
    let href;
    if (asset) {
      if (!ASSET_IDS.includes(asset)) throw new Error(`Unknown data-asset "${asset}"`);
      href = releaseUrl(repository, release.tag, release.assets[asset]);
    } else {
      const target = CHECKSUM_TARGETS[checksums];
      if (!target) throw new Error(`Unknown data-checksums "${checksums}"`);
      href = releaseUrl(repository, release.tag, `SHA256SUMS-${target}`);
    }
    if (!/\bhref="[^"]*"/u.test(tag)) throw new Error(`Download anchor without href: ${tag}`);
    return tag.replace(/\bhref="[^"]*"/u, `href="${href.replace(/&/gu, "&amp;")}"`);
  });
}
