// Checks that every relative link (and heading anchor) in the repository's Markdown
// documentation resolves: README.md, docs/**, and this package's README.
import assert from "node:assert/strict";
import { readFile, readdir, stat } from "node:fs/promises";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const siteRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(siteRoot, "../..");

async function walkMarkdown(directory) {
  const result = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const full = path.join(directory, entry.name);
    if (entry.isDirectory()) result.push(...(await walkMarkdown(full)));
    else if (entry.name.endsWith(".md")) result.push(full);
  }
  return result;
}

async function kind(target) {
  try {
    const info = await stat(target);
    return info.isDirectory() ? "dir" : "file";
  } catch {
    return null;
  }
}

/** Removes fenced code blocks and inline code so their contents are not treated as links. */
function stripCode(markdown) {
  return markdown
    .replace(/^(```|~~~)[^\n]*\n[\s\S]*?^\1[^\n]*$/gmu, "")
    .replace(/`[^`\n]*`/gu, "");
}

/** GitHub heading anchors (github-slugger rules), including -1, -2 suffixes for duplicates. */
export function anchorsFor(markdown) {
  const anchors = new Set();
  const seen = new Map();
  const withoutFences = markdown.replace(/^(```|~~~)[^\n]*\n[\s\S]*?^\1[^\n]*$/gmu, "");
  for (const match of withoutFences.matchAll(/^#{1,6}[ \t]+(.+?)[ \t#]*$/gmu)) {
    const text = match[1]
      .replace(/!\[([^\]]*)\]\([^)]*\)/gu, "$1")
      .replace(/\[([^\]]*)\]\([^)]*\)/gu, "$1")
      .replace(/<[^>]+>/gu, "")
      .replace(/[`*~]/gu, "");
    const base = text.toLowerCase().replace(/[^\p{L}\p{M}\p{N}\p{Pc}\- ]/gu, "").replace(/ /gu, "-");
    const count = seen.get(base) ?? 0;
    anchors.add(count === 0 ? base : `${base}-${count}`);
    seen.set(base, count + 1);
  }
  for (const match of markdown.matchAll(/<a\s+(?:id|name)="([^"]+)"/gu)) anchors.add(match[1]);
  return anchors;
}

function links(markdown) {
  const result = [];
  for (const match of stripCode(markdown).matchAll(/!?\[(?:[^\]\\]|\\.)*\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)/gu)) {
    result.push(match[1]);
  }
  return result;
}

const files = [
  path.join(repoRoot, "README.md"),
  path.join(siteRoot, "README.md"),
  ...(await walkMarkdown(path.join(repoRoot, "docs"))),
].sort();

describe("documentation links", () => {
  it("finds the documentation set", () => {
    const relative = files.map((file) => path.relative(repoRoot, file));
    for (const expected of [
      "README.md",
      "docs/telegram-setup.md",
      "docs/user/es/primeros-pasos.md",
      "docs/user/en/getting-started.md",
      "docs/legal/es/privacidad.md",
      "docs/legal/en/terms.md",
      "docs/dev/README.md",
    ]) {
      assert.ok(relative.includes(expected), `${expected} is missing`);
    }
  });

  it("resolves every relative link and anchor", async () => {
    const problems = [];
    const cache = new Map();
    const anchorsOf = async (file) => {
      if (!cache.has(file)) cache.set(file, anchorsFor(await readFile(file, "utf8")));
      return cache.get(file);
    };
    for (const file of files) {
      const where = path.relative(repoRoot, file);
      for (const href of links(await readFile(file, "utf8"))) {
        if (/^(https:|mailto:)/u.test(href)) continue;
        if (/^http:\/\/(127\.0\.0\.1|localhost)[:/]/u.test(href)) continue;
        if (/^[a-z][a-z0-9+.-]*:/iu.test(href)) {
          problems.push(`${where}: unexpected link scheme ${href}`);
          continue;
        }
        if (href.startsWith("/")) {
          problems.push(`${where}: use a relative path instead of ${href}`);
          continue;
        }
        const [rawTarget, rawAnchor] = href.split("#");
        const target = rawTarget === "" ? file : path.resolve(path.dirname(file), decodeURIComponent(rawTarget));
        const found = await kind(target);
        if (!found) {
          problems.push(`${where}: broken link ${href}`);
          continue;
        }
        if (rawAnchor !== undefined && found === "file" && target.endsWith(".md")) {
          const anchor = decodeURIComponent(rawAnchor);
          if (!(await anchorsOf(target)).has(anchor)) problems.push(`${where}: missing anchor ${href}`);
        }
      }
    }
    assert.deepEqual(problems, []);
  });

  it("keeps Spanish and English user guides and legal documents in parity", async () => {
    for (const [directory, count] of [["docs/user", 12], ["docs/legal", 3]]) {
      const es = (await readdir(path.join(repoRoot, directory, "es"))).filter((name) => name.endsWith(".md"));
      const en = (await readdir(path.join(repoRoot, directory, "en"))).filter((name) => name.endsWith(".md"));
      assert.equal(es.length, count, `${directory}/es`);
      assert.equal(en.length, count, `${directory}/en`);
    }
  });
});

describe("anchorsFor", () => {
  it("follows GitHub's slug rules", () => {
    const anchors = anchorsFor("# Título\n## ¿Qué ve Telegram?\n## If pairing with a code doesn’t work\n## `STORAGE_BACKEND` modes\n## Uso\n## Uso\n```\n# not a heading\n```\n");
    for (const anchor of ["título", "qué-ve-telegram", "if-pairing-with-a-code-doesnt-work", "storage_backend-modes", "uso", "uso-1"]) {
      assert.ok(anchors.has(anchor), anchor);
    }
    assert.ok(!anchors.has("not-a-heading"));
  });
});
