// Validates the built site (dist/): internal links and anchors, no external requests,
// strict CSP, basic accessibility, es/en parity, and the download-link rewrite.
import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, stat, writeFile, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, it, before } from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "../scripts/build.mjs";
import { findPlaceholders } from "../scripts/check-placeholders.mjs";
import { headersFor, parseCsp, parseHeaders } from "../scripts/lib/headers.mjs";
import { applyRelease, ASSET_IDS, validateConfig } from "../scripts/lib/release.mjs";
import { elementText, tags, textContent } from "./lib/html.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(root, "dist");
const ALLOWED_EXTERNAL_HOSTS = new Set(["github.com", "telegram.org"]);

async function walk(directory) {
  const result = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const full = path.join(directory, entry.name);
    if (entry.isDirectory()) result.push(...(await walk(full)));
    else result.push(full);
  }
  return result.sort();
}

async function exists(file) {
  try {
    return (await stat(file)).isFile();
  } catch {
    return false;
  }
}

function urlPathFor(file) {
  const relative = `/${path.relative(dist, file).split(path.sep).join("/")}`;
  return relative.endsWith("/index.html") ? relative.slice(0, -"index.html".length) : relative;
}

async function resolveInternal(urlPath) {
  const clean = decodeURIComponent(urlPath);
  if (clean.endsWith("/")) return (await exists(path.join(dist, clean, "index.html"))) ? path.join(dist, clean, "index.html") : null;
  if (await exists(path.join(dist, clean))) return path.join(dist, clean);
  if (await exists(path.join(dist, clean, "index.html"))) return path.join(dist, clean, "index.html");
  return null;
}

const pages = new Map();

before(async () => {
  for (const file of await walk(dist)) {
    if (!file.endsWith(".html")) continue;
    const html = await readFile(file, "utf8");
    const all = tags(html);
    const ids = all.map((tag) => tag.attrs.id).filter(Boolean);
    pages.set(file, { html, tags: all, ids: new Set(ids), idList: ids, urlPath: urlPathFor(file) });
  }
});

describe("site structure", () => {
  it("contains every Spanish page with an English counterpart", () => {
    const paths = [...pages.values()].map((page) => page.urlPath).sort();
    assert.deepEqual(paths, [
      "/",
      "/404.html",
      "/android/",
      "/en/",
      "/en/android/",
      "/en/join/",
      "/en/privacy/",
      "/en/security/",
      "/en/terms/",
      "/join/",
      "/privacy/",
      "/security/",
      "/terms/",
    ]);
  });

  it("links every page to its other-language alternate", async () => {
    const { origin } = JSON.parse(await readFile(path.join(root, "site.config.json"), "utf8"));
    const stripOrigin = (href) => (origin && href?.startsWith(`${origin}/`) ? href.slice(origin.length) : href);
    for (const [file, page] of pages) {
      if (page.urlPath === "/404.html") continue;
      const alternates = page.tags.filter((tag) => tag.name === "link" && tag.attrs.rel === "alternate");
      const byLang = Object.fromEntries(alternates.map((tag) => [tag.attrs.hreflang, stripOrigin(tag.attrs.href)]));
      const isEnglish = page.urlPath.startsWith("/en/");
      const spanish = isEnglish ? page.urlPath.slice(3) : page.urlPath;
      assert.equal(byLang.es, spanish, file);
      assert.equal(byLang.en, `/en${spanish}`, file);
      if (!page.urlPath.endsWith("/join/")) {
        assert.equal(byLang["x-default"], `/en${spanish}`, file);
        const canonical = page.tags.find((tag) => tag.name === "link" && tag.attrs.rel === "canonical");
        assert.equal(stripOrigin(canonical?.attrs.href), page.urlPath, `${file}: canonical`);
      }
      const switcher = page.tags.find((tag) => tag.name === "a" && tag.attrs.class === "lang-switch");
      assert.equal(switcher?.attrs.href, isEnglish ? spanish : `/en${spanish}`, file);
    }
  });
});

describe("links", () => {
  it("resolves every internal link and fragment", async () => {
    const problems = [];
    for (const page of pages.values()) {
      for (const tag of page.tags) {
        const href = tag.name === "a" || tag.name === "link" ? tag.attrs.href : tag.attrs.src;
        if (href === undefined || !["a", "link", "script", "img", "source"].includes(tag.name)) continue;
        if (/^[a-z][a-z0-9+.-]*:/iu.test(href)) continue; // checked by the external-link test
        if (href.startsWith("#")) {
          if (href !== "#" && !page.ids.has(href.slice(1))) problems.push(`${page.urlPath}: missing anchor ${href}`);
          continue;
        }
        if (!href.startsWith("/")) {
          problems.push(`${page.urlPath}: use root-relative links, got ${href}`);
          continue;
        }
        const [urlPath, fragment] = href.split("#");
        const target = await resolveInternal(urlPath);
        if (!target) {
          problems.push(`${page.urlPath}: broken link ${href}`);
          continue;
        }
        if (fragment && !pages.get(target)?.ids.has(fragment)) problems.push(`${page.urlPath}: missing anchor ${href}`);
      }
    }
    assert.deepEqual(problems, []);
  });

  it("only links out to allowed hosts over https, and to bento:// only from the join pages", () => {
    const problems = [];
    for (const page of pages.values()) {
      for (const tag of page.tags) {
        if (tag.name !== "a" || tag.attrs.href === undefined || !/^[a-z][a-z0-9+.-]*:/iu.test(tag.attrs.href)) continue;
        const href = tag.attrs.href;
        if (href.startsWith("bento:")) {
          if (!page.urlPath.endsWith("/join/") || href !== "bento://join") problems.push(`${page.urlPath}: unexpected ${href}`);
          continue;
        }
        const url = new URL(href);
        if (url.protocol !== "https:" || !ALLOWED_EXTERNAL_HOSTS.has(url.hostname)) problems.push(`${page.urlPath}: external link ${href}`);
      }
    }
    assert.deepEqual(problems, []);
  });

  it("keeps ids unique on every page", () => {
    for (const page of pages.values()) {
      assert.equal(page.ids.size, page.idList.length, `duplicate id on ${page.urlPath}`);
    }
  });
});

describe("no external requests", () => {
  it("loads only same-origin resources and has no inline code or styles", async () => {
    const { origin } = JSON.parse(await readFile(path.join(root, "site.config.json"), "utf8"));
    const isSameOriginMetadataLink = (tag) =>
      (tag.attrs.rel === "canonical" || tag.attrs.rel === "alternate")
      && origin
      && (tag.attrs.href ?? "").startsWith(`${origin}/`);
    const problems = [];
    for (const page of pages.values()) {
      for (const tag of page.tags) {
        const where = `${page.urlPath} <${tag.name}>`;
        for (const name of Object.keys(tag.attrs)) {
          if (name.startsWith("on")) problems.push(`${where}: inline handler ${name}`);
          if (name === "style") problems.push(`${where}: inline style`);
          if (name === "srcset" || name === "poster" || name === "action" || name === "formaction" || name === "ping") problems.push(`${where}: ${name}`);
        }
        if (["iframe", "object", "embed", "form", "style", "base", "frame", "video", "audio"].includes(tag.name)) problems.push(`${where}: element not allowed`);
        if (tag.name === "meta" && tag.attrs["http-equiv"]) problems.push(`${where}: http-equiv not allowed`);
        if (tag.name === "link" && !(tag.attrs.href ?? "").startsWith("/") && !isSameOriginMetadataLink(tag)) problems.push(`${where}: external link element`);
        if (tag.name === "img" && (!("alt" in tag.attrs) || !(tag.attrs.src ?? "").startsWith("/"))) problems.push(`${where}: image must be same-origin with alt`);
        if (tag.name === "script") {
          if (tag.attrs.type === "application/ld+json") {
            if (tag.attrs.src) problems.push(`${where}: ld+json must not load external src`);
          } else {
            if (!(tag.attrs.src ?? "").startsWith("/assets/")) problems.push(`${where}: script must be a same-origin file`);
            if (tag.attrs.type !== "module") problems.push(`${where}: scripts must be modules`);
          }
        }
      }
      for (const match of page.html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/giu)) {
        const isJsonLd = /type="application\/ld\+json"/iu.test(match[1]);
        if (isJsonLd) {
          try {
            const parsed = JSON.parse(match[2]);
            if (parsed["@context"] !== "https://schema.org") problems.push(`${page.urlPath}: ld+json invalid @context`);
          } catch {
            problems.push(`${page.urlPath}: invalid JSON-LD`);
          }
        } else if (match[2].trim() !== "") {
          problems.push(`${page.urlPath}: inline script`);
        }
      }
    }
    assert.deepEqual(problems, []);
  });

  it("uses only same-origin URLs in CSS", async () => {
    const css = await readFile(path.join(dist, "assets/site.css"), "utf8");
    assert.doesNotMatch(css, /@import/iu);
    for (const match of css.matchAll(/url\(\s*["']?([^"')]+)["']?\s*\)/gu)) {
      assert.ok(match[1].startsWith("/assets/"), `CSS url ${match[1]}`);
      assert.ok(await exists(path.join(dist, match[1])), `CSS url ${match[1]} missing`);
    }
  });

  it("ships scripts that never touch the network, storage or HTML sinks", async () => {
    const forbidden = [
      /\bfetch\s*\(/u,
      /XMLHttpRequest/u,
      /WebSocket/u,
      /EventSource/u,
      /sendBeacon/u,
      /importScripts/u,
      /new\s+Image\b/u,
      /\.src\s*=/u,
      /https?:\/\//u,
      /innerHTML|outerHTML|insertAdjacentHTML|document\.write/u,
      /\beval\s*\(|new\s+Function\b/u,
      /localStorage|sessionStorage|indexedDB|document\.cookie/u,
      /\blocation\s*\.\s*(assign|replace|href\s*=)/u,
      /\bwindow\.open\b/u,
      /\bconsole\./u, // never log (the join page handles pairing codes)
    ];
    const scripts = (await walk(dist)).filter((file) => file.endsWith(".js"));
    assert.ok(scripts.length >= 2);
    for (const file of scripts) {
      const source = await readFile(file, "utf8");
      for (const pattern of forbidden) assert.doesNotMatch(source, pattern, `${path.relative(dist, file)} matches ${pattern}`);
      for (const match of source.matchAll(/\bimport\b[^"'`]*["'`]([^"'`]+)["'`]/gu)) {
        assert.ok(match[1].startsWith("./"), `${path.relative(dist, file)} imports ${match[1]}`);
      }
    }
  });

  it("serves a strict Content-Security-Policy and privacy headers on every page", async () => {
    const rules = parseHeaders(await readFile(path.join(dist, "_headers"), "utf8"));
    for (const page of pages.values()) {
      const headers = headersFor(rules, page.urlPath);
      const csp = parseCsp(headers["Content-Security-Policy"] ?? "");
      assert.deepEqual(csp.get("default-src"), ["'none'"], page.urlPath);
      assert.deepEqual(csp.get("script-src"), ["'self'"], page.urlPath);
      assert.deepEqual(csp.get("style-src"), ["'self'"], page.urlPath);
      assert.deepEqual(csp.get("connect-src"), ["'none'"], page.urlPath);
      assert.deepEqual(csp.get("form-action"), ["'none'"], page.urlPath);
      assert.deepEqual(csp.get("frame-ancestors"), ["'none'"], page.urlPath);
      assert.deepEqual(csp.get("base-uri"), ["'none'"], page.urlPath);
      for (const [directive, sources] of csp) {
        for (const source of sources) {
          assert.ok(!/^(https?:|\*|'unsafe-|data:|blob:)/u.test(source), `${directive} ${source}`);
        }
      }
      assert.equal(headers["Referrer-Policy"], "no-referrer");
      assert.equal(headers["X-Content-Type-Options"], "nosniff");
      if (page.urlPath.endsWith("/join/")) {
        assert.equal(headers["X-Robots-Tag"], "noindex");
        assert.equal(headers["Cache-Control"], "no-store");
      }
    }
  });
});

describe("accessibility basics", () => {
  it("declares language, title, one h1, a main landmark and a working skip link", () => {
    for (const page of pages.values()) {
      const html = page.tags.find((tag) => tag.name === "html");
      const english = page.urlPath.startsWith("/en/");
      assert.equal(html?.attrs.lang, english ? "en" : "es", page.urlPath);
      const titles = elementText(page.html, "title").map(textContent);
      assert.equal(titles.length, 1, page.urlPath);
      assert.ok(titles[0].includes("Bento"), page.urlPath);
      assert.equal(page.tags.filter((tag) => tag.name === "h1").length, 1, `${page.urlPath} h1 count`);
      const main = page.tags.filter((tag) => tag.name === "main");
      assert.equal(main.length, 1, page.urlPath);
      const skip = page.tags.find((tag) => tag.name === "a" && tag.attrs.class === "skip-link");
      assert.equal(skip?.attrs.href, `#${main[0].attrs.id}`, page.urlPath);
      assert.ok(page.tags.some((tag) => tag.name === "meta" && tag.attrs.name === "viewport"), page.urlPath);
    }
  });

  it("hides decorative SVGs, names links and buttons, and labels navigation", () => {
    const problems = [];
    for (const page of pages.values()) {
      for (const tag of page.tags) {
        if (tag.name === "svg" && tag.attrs["aria-hidden"] !== "true" && tag.attrs.role !== "img") problems.push(`${page.urlPath}: svg without aria-hidden`);
        if (tag.name === "nav" && !tag.attrs["aria-label"] && !tag.attrs["aria-labelledby"]) problems.push(`${page.urlPath}: unlabeled nav`);
      }
      for (const element of ["a", "button", "summary"]) {
        for (const body of elementText(page.html, element)) {
          if (textContent(body.replace(/<svg[\s\S]*?<\/svg>/gu, "")) === "" && !body.includes("data-join-code")) problems.push(`${page.urlPath}: empty <${element}>`);
        }
      }
    }
    assert.deepEqual(problems, []);
  });

  it("keeps at most one shu element (the logo ume) per page", () => {
    for (const page of pages.values()) {
      assert.ok((page.html.match(/class="ume"/gu) ?? []).length <= 1, page.urlPath);
    }
  });
});

describe("honest copy", () => {
  it("states the Telegram API disclosure on every page", () => {
    for (const page of pages.values()) {
      const text = textContent(page.html);
      const disclosure = page.urlPath.startsWith("/en/")
        ? "Bento uses the Telegram API and is not affiliated with Telegram."
        : "Bento usa la API de Telegram y no está afiliado a Telegram.";
      assert.ok(text.includes(disclosure), page.urlPath);
    }
  });

  it("qualifies the storage claim wherever it is made", () => {
    for (const urlPath of ["/", "/en/"]) {
      const page = [...pages.values()].find((candidate) => candidate.urlPath === urlPath);
      const text = textContent(page.html);
      assert.ok(urlPath === "/" ? text.includes("no lo garantiza por contrato") : text.includes("does not guarantee one by contract"));
      assert.ok(page.ids.has(urlPath === "/" ? "limites" : "limits"));
    }
  });

  it("lists the optional smart search model download, with no personal data, on both privacy pages", () => {
    const expectations = {
      "/privacy/": {
        service: "Modelo de búsqueda inteligente (opcional)",
        when: "Solo si activas la búsqueda por significado",
        claims: ["huggingface.co", "github.com", "no se envía ningún dato de tus archivos", "el modelo funciona en tu dispositivo"],
      },
      "/en/privacy/": {
        service: "Smart search model (optional)",
        when: "Only if you turn on search by meaning",
        claims: ["huggingface.co", "github.com", "no data about your files is sent", "the model runs on your device"],
      },
    };
    for (const [urlPath, expected] of Object.entries(expectations)) {
      const page = [...pages.values()].find((candidate) => candidate.urlPath === urlPath);
      assert.ok(page, urlPath);
      const rows = elementText(page.html, "tr").map((row) => elementText(row, "td").map(textContent));
      const row = rows.find((cells) => cells[0] === expected.service);
      assert.ok(row, `${urlPath} lists the smart search model download`);
      assert.equal(row.length, 3, urlPath);
      assert.ok(row[1].startsWith(expected.when), urlPath);
      for (const claim of expected.claims) assert.ok(row[2].includes(claim), `${urlPath}: ${claim}`);
    }
  });
});

describe("downloads", () => {
  it("offers every release asset on both home pages", () => {
    for (const urlPath of ["/", "/en/"]) {
      const page = [...pages.values()].find((candidate) => candidate.urlPath === urlPath);
      const assets = page.tags.filter((tag) => tag.attrs["data-asset"]).map((tag) => tag.attrs["data-asset"]).sort();
      assert.deepEqual(assets, [...ASSET_IDS].sort(), urlPath);
      for (const tag of page.tags.filter((candidate) => candidate.attrs["data-asset"] || candidate.attrs["data-checksums"])) {
        assert.ok(tag.attrs.href.startsWith("https://github.com/invrnt/bento/releases/"), tag.attrs.href);
      }
    }
  });

  it("points download buttons at exact release files when a release is configured", () => {
    const config = {
      repository: "invrnt/bento",
      release: {
        tag: "v1.2.3",
        assets: {
          "windows-x64": "Bento-1.2.3 Setup.exe",
          "macos-arm64": "Bento-1.2.3-arm64.dmg",
          "macos-x64": "Bento-1.2.3-x64.dmg",
          "linux-x64-deb": "bento_1.2.3_amd64.deb",
          "linux-x64-zip": "Bento-linux-x64-1.2.3.zip",
        },
      },
    };
    const html = '<a class="button" data-asset="windows-x64" href="https://github.com/invrnt/bento/releases/latest">W</a>'
      + '<a data-checksums="linux-x64" href="https://github.com/invrnt/bento/releases/latest">S</a><a href="/x/">keep</a>';
    const output = applyRelease(html, config);
    assert.match(output, /href="https:\/\/github\.com\/invrnt\/bento\/releases\/download\/v1\.2\.3\/Bento-1\.2\.3%20Setup\.exe"/u);
    assert.match(output, /href="https:\/\/github\.com\/invrnt\/bento\/releases\/download\/v1\.2\.3\/SHA256SUMS-linux-x64"/u);
    assert.match(output, /<a href="\/x\/">keep<\/a>/u);
    assert.equal(applyRelease(html, { repository: "invrnt/bento", release: null }), html);
  });

  it("rejects incomplete or unsafe release configuration", () => {
    assert.throws(() => validateConfig({ repository: "nope", release: null }));
    assert.throws(() => validateConfig({ repository: "invrnt/bento", release: { tag: "latest", assets: {} } }));
    assert.throws(() => validateConfig({ repository: "invrnt/bento", release: { tag: "v1.0.0", assets: { "windows-x64": "a.exe" } } }));
    const assets = Object.fromEntries(ASSET_IDS.map((id) => [id, `${id}.bin`]));
    assert.throws(() => validateConfig({ repository: "invrnt/bento", release: { tag: "v1.0.0", assets: { ...assets, "windows-x64": "../evil.exe" } } }));
    assert.throws(() => validateConfig({ repository: "invrnt/bento", release: { tag: "v1.0.0", assets: { ...assets, extra: "x" } } }));
    assert.doesNotThrow(() => validateConfig({ repository: "invrnt/bento", release: { tag: "v1.0.0", assets } }));
  });

  it("builds a release-configured copy of the site", async () => {
    const output = await mkdtemp(path.join(tmpdir(), "bento-site-"));
    try {
      const assets = Object.fromEntries(ASSET_IDS.map((id) => [id, `Bento-${id}-9.9.9.bin`]));
      const android = { package: "dev.bento.app", sha256CertFingerprints: ["[[COMPLETAR: release]]"], release: null };
      await build({ output, config: { repository: "invrnt/bento", release: { tag: "v9.9.9", assets }, android } });
      const html = await readFile(path.join(output, "en/index.html"), "utf8");
      for (const id of ASSET_IDS) assert.ok(html.includes(`/releases/download/v9.9.9/Bento-${id}-9.9.9.bin`), id);
      assert.ok(!html.includes('data-asset="windows-x64" href="https://github.com/invrnt/bento/releases/latest"'));
    } finally {
      await rm(output, { recursive: true, force: true });
    }
  });
});

describe("link previews", () => {
  it("gives both home pages a same-site share image that exists", async () => {
    for (const page of pages.values()) {
      if (page.urlPath !== "/" && page.urlPath !== "/en/") continue;
      const meta = Object.fromEntries(page.tags.filter((tag) => tag.name === "meta" && (tag.attrs.property || tag.attrs.name)).map((tag) => [tag.attrs.property ?? tag.attrs.name, tag.attrs.content]));
      for (const key of ["og:title", "og:description", "og:image", "og:image:alt", "twitter:card"]) assert.ok(meta[key], `${page.urlPath}: ${key}`);
      assert.equal(meta["twitter:image"], meta["og:image"]);
      const { origin } = JSON.parse(await readFile(path.join(root, "site.config.json"), "utf8"));
      const image = origin && meta["og:image"].startsWith(`${origin}/`) ? meta["og:image"].slice(origin.length) : meta["og:image"];
      assert.ok(image.startsWith("/"), `${page.urlPath}: share image must be on this site, got ${meta["og:image"]}`);
      assert.ok(await resolveInternal(image), `${page.urlPath}: missing ${image}`);
    }
  });

  it("makes share URLs absolute only when the public origin is configured", async () => {
    const output = await mkdtemp(path.join(tmpdir(), "bento-site-"));
    try {
      const android = { package: "dev.bento.app", sha256CertFingerprints: ["[[COMPLETAR: release]]"], release: null };
      await build({ output, config: { repository: "invrnt/bento", origin: "https://bento.example", release: null, android } });
      const html = await readFile(path.join(output, "index.html"), "utf8");
      assert.match(html, /property="og:image" content="https:\/\/bento\.example\/assets\/social\/og-es\.jpg"/u);
      assert.match(html, /property="og:url" content="https:\/\/bento\.example\/"/u);
      await assert.rejects(build({ output, config: { repository: "invrnt/bento", origin: "http://bento.example/", release: null, android } }));
    } finally {
      await rm(output, { recursive: true, force: true });
    }
  });
});

describe("seo", () => {
  it("emits sitemap.xml referencing every indexable page and links it from robots.txt", async () => {
    const { origin } = JSON.parse(await readFile(path.join(root, "site.config.json"), "utf8"));
    assert.ok(origin, "origin must be configured");
    const sitemap = await readFile(path.join(dist, "sitemap.xml"), "utf8");
    for (const loc of ["/", "/en/", "/security/", "/en/security/", "/privacy/", "/en/privacy/", "/terms/", "/en/terms/"]) {
      assert.ok(sitemap.includes(`<loc>${origin}${loc}</loc>`), `sitemap missing ${loc}`);
    }
    assert.ok(!sitemap.includes("/join/"), "sitemap must exclude /join/");
    assert.ok(!sitemap.includes("/404.html"), "sitemap must exclude /404.html");
    const robots = await readFile(path.join(dist, "robots.txt"), "utf8");
    assert.ok(robots.includes(`Sitemap: ${origin}/sitemap.xml`));
  });

  it("includes SoftwareApplication and FAQPage JSON-LD on both home pages", () => {
    for (const urlPath of ["/", "/en/"]) {
      const page = [...pages.values()].find((candidate) => candidate.urlPath === urlPath);
      const blocks = [...page.html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/gu)].map((m) => JSON.parse(m[1]));
      const types = new Set(blocks.flatMap((doc) => (Array.isArray(doc["@graph"]) ? doc["@graph"].map((n) => n["@type"]) : [doc["@type"]])));
      assert.ok(types.has("SoftwareApplication"), `${urlPath}: SoftwareApplication`);
      assert.ok(types.has("FAQPage"), `${urlPath}: FAQPage`);
    }
  });
});

describe("publishing guard", () => {
  it("finds owner placeholders and passes a clean tree", async () => {
    const directory = await mkdtemp(path.join(tmpdir(), "bento-placeholders-"));
    try {
      await mkdir(path.join(directory, "privacy"), { recursive: true });
      await writeFile(path.join(directory, "index.html"), "<p>ok</p>");
      assert.deepEqual(await findPlaceholders(directory), []);
      await writeFile(path.join(directory, "privacy/index.html"), "<p>[[COMPLETAR: nombre legal del responsable]]</p>");
      assert.deepEqual(await findPlaceholders(directory), [
        { file: path.join("privacy", "index.html"), marker: "[[COMPLETAR: nombre legal del responsable]]" },
      ]);
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  });
});
