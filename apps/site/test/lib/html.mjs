// Tiny, dependency-free HTML start-tag scanner. Good enough for the site's own,
// hand-written markup; not a general HTML parser.

const ATTRIBUTE = /([^\s"'<>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/gu;

export function decodeEntities(value) {
  return value
    .replace(/&quot;/gu, '"')
    .replace(/&#39;/gu, "'")
    .replace(/&lt;/gu, "<")
    .replace(/&gt;/gu, ">")
    .replace(/&amp;/gu, "&");
}

export function stripComments(html) {
  return html.replace(/<!--[\s\S]*?-->/gu, "");
}

export function tags(html) {
  const result = [];
  const source = stripComments(html);
  const pattern = /<([a-zA-Z][a-zA-Z0-9-]*)(\s[^<>]*?)?\s*(\/?)>/gu;
  for (const match of source.matchAll(pattern)) {
    const attrs = {};
    for (const attribute of (match[2] ?? "").matchAll(ATTRIBUTE)) {
      const name = attribute[1].toLowerCase();
      const value = attribute[2] ?? attribute[3] ?? attribute[4] ?? "";
      attrs[name] = decodeEntities(value);
    }
    result.push({ name: match[1].toLowerCase(), attrs, index: match.index });
  }
  return result;
}

export function elementText(html, tagName) {
  const pattern = new RegExp(`<${tagName}\\b[^>]*>([\\s\\S]*?)</${tagName}>`, "giu");
  return [...stripComments(html).matchAll(pattern)].map((match) => match[1]);
}

export function textContent(fragment) {
  return decodeEntities(fragment.replace(/<[^>]*>/gu, " ")).replace(/\s+/gu, " ").trim();
}
