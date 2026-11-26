// Indexable pages, the sitemap and IndexNow. One list feeds both, so a page added to the
// sitemap is also pinged to search engines on deploy.

export const SITEMAP_PAIRS = [
  { es: "/", en: "/en/", priority: "1.0" },
  { es: "/android/", en: "/en/android/", priority: "0.9" },
  { es: "/security/", en: "/en/security/", priority: "0.8" },
  { es: "/privacy/", en: "/en/privacy/", priority: "0.5" },
  { es: "/terms/", en: "/en/terms/", priority: "0.5" },
];

export const INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow";

// IndexNow keys are public by design (served at /<key>.txt): 8-128 of a-z, A-Z, 0-9 and "-".
const INDEXNOW_KEY = /^[A-Za-z0-9-]{8,128}$/u;

export function validateIndexNowKey(key) {
  if (key === undefined || key === null) return null;
  if (typeof key !== "string" || !INDEXNOW_KEY.test(key)) {
    throw new Error("site.config.json: indexNowKey must be 8-128 characters of a-z, A-Z, 0-9 or - (or null)");
  }
  return key;
}

export function indexableUrls(origin) {
  return SITEMAP_PAIRS.flatMap((pair) => [`${origin}${pair.es}`, `${origin}${pair.en}`]);
}

export function buildSitemap(origin) {
  const lines = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">',
  ];
  for (const pair of SITEMAP_PAIRS) {
    for (const locPath of [pair.es, pair.en]) {
      lines.push("  <url>");
      lines.push(`    <loc>${origin}${locPath}</loc>`);
      lines.push(`    <xhtml:link rel="alternate" hreflang="es" href="${origin}${pair.es}"/>`);
      lines.push(`    <xhtml:link rel="alternate" hreflang="en" href="${origin}${pair.en}"/>`);
      lines.push(`    <xhtml:link rel="alternate" hreflang="x-default" href="${origin}${pair.en}"/>`);
      lines.push(`    <priority>${pair.priority}</priority>`);
      lines.push("  </url>");
    }
  }
  lines.push("</urlset>");
  return `${lines.join("\n")}\n`;
}

export function indexNowPayload(origin, key, urls = indexableUrls(origin)) {
  return {
    host: new URL(origin).host,
    key,
    keyLocation: `${origin}/${key}.txt`,
    urlList: urls,
  };
}
