import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { generate, oklchToSrgb, parseOklch, parseTokens, paths, toHex, writeOrCheck } from "../generate_tokens.mjs";
import { emitIcons, generateIcons, lucideVersions, readManifest, svgToPaths, _internal } from "../generate_icons.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(paths.tokensCss, "utf8");
const brand = readFileSync(join(here, "../../../../orchestration/design-system/brand.md"), "utf8");

test("oklch conversion hits known anchors", () => {
  assert.equal(toHex(oklchToSrgb(1, 0, 0)), "#ffffff");
  assert.equal(toHex(oklchToSrgb(0, 0, 0)), "#000000");
  // CSS Color 4 reference: oklch(0.628 0.2577 29.23) is sRGB red.
  assert.equal(toHex(oklchToSrgb(0.62796, 0.25768, 29.2339)), "#ff0000");
  assert.equal(parseOklch("oklch(1 0 0 / 0.5)").a, 128);
});

test("out-of-gamut colors are chroma-reduced, not clipped per channel", () => {
  const mapped = oklchToSrgb(0.7, 0.4, 145);
  for (const c of [mapped.r, mapped.g, mapped.b]) assert.ok(c >= 0 && c <= 255);
  // Lightness is preserved within a small tolerance by the CSS algorithm.
  const naive = oklchToSrgb(0.7, 0.13, 145);
  assert.ok(Math.abs(mapped.g - naive.g) < 40);
});

test("every brand.md hex matches the generated sRGB value (±2 per channel)", () => {
  const tokens = parseTokens(css);
  const byName = new Map(tokens.colors.map((c) => [c.name, c]));
  const rows = [...brand.matchAll(/^\|\s*`([a-z-]+)`(?:\s*\/\s*`([a-z-]+)`)?[^|]*\|[^|]*?\|\s*`(#[0-9a-f]{6})`(?:\s*\/\s*`(#[0-9a-f]{6})`)?\s*\|\s*`(#[0-9a-f]{6})`(?:\s*\/\s*`(#[0-9a-f]{6})`)?\s*\|/gm)];
  const twoCol = [...brand.matchAll(/^\|\s*`([a-z-]+)`(?:\s*\/\s*`([a-z-]+)`)?[^|]*\|\s*`(#[0-9a-f]{6})`(?:\s*\/\s*`(#[0-9a-f]{6})`)?\s*\|\s*`(#[0-9a-f]{6})`(?:\s*\/\s*`(#[0-9a-f]{6})`)?\s*\|/gm)];
  const checks = [];
  for (const m of [...rows, ...twoCol]) {
    const [, a, b, la, lb, da, db] = m;
    checks.push([a, la, da]);
    if (b && lb) checks.push([b, lb, db]);
  }
  assert.ok(checks.length >= 15, `parsed ${checks.length} brand rows`);
  const channels = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  for (const [name, light, dark] of checks) {
    const token = byName.get(name);
    assert.ok(token, `token ${name} exists`);
    for (const [expected, actual, theme] of [[light, token.light, "light"], [dark, token.dark, "dark"]]) {
      const got = channels(toHex(actual));
      const want = channels(expected);
      const off = Math.max(...got.map((g, i) => Math.abs(g - want[i])));
      assert.ok(off <= 2, `${name} ${theme}: brand ${expected}, generated ${toHex(actual)}`);
    }
  }
});

test("all color tokens of tokens.css reach Kotlin and the color resources", () => {
  const out = generate(css);
  const kotlin = out[paths.kotlin];
  const light = out[paths.colorsLight];
  const night = out[paths.colorsNight];
  const names = [...css.matchAll(/--color-([\w-]+):\s*(?!initial)/g)].map((m) => m[1]);
  assert.ok(names.length >= 60, `found ${names.length} color tokens`);
  for (const name of names) {
    const camel = name.replace(/-([a-z0-9])/g, (_, c) => c.toUpperCase());
    assert.match(kotlin, new RegExp(`\\b${camel}\\b`), `kotlin has ${camel}`);
    assert.match(light, new RegExp(`name="bento_${name.replace(/-/g, "_")}"`));
    assert.match(night, new RegExp(`name="bento_${name.replace(/-/g, "_")}"`));
  }
  assert.match(kotlin, /controlMobile: Dp = 12\.dp/);
  assert.match(kotlin, /easeOut: CubicBezierEasing = CubicBezierEasing\(0\.16f, 1f, 0\.3f, 1f\)/);
  assert.match(kotlin, /const val fast: Int = 120/);
  assert.match(kotlin, /const val slow: Int = 260/);
});

test("generation is deterministic and --check reports drift", () => {
  assert.deepEqual(generate(css), generate(css));
  const fake = { [paths.kotlin]: "different" };
  assert.deepEqual(writeOrCheck(fake, true).length, 1);
  assert.deepEqual(writeOrCheck(generate(css), true), [], "committed tokens are up to date");
  assert.deepEqual(writeOrCheck(generateIcons(), true), [], "committed icons are up to date");
});

test("svg primitives convert to paths", () => {
  assert.equal(_internal.rectPath({ width: 10, height: 4 }), "M0 0h10v4h-10Z");
  assert.match(_internal.rectPath({ x: 2, y: 2, width: 20, height: 20, rx: 2 }), /^M4 2H20A2 2 0 0 1 22 4/);
  assert.equal(_internal.pointsPath("1 2 3 4 5 6", true), "M1 2L3 4L5 6Z");
  const paths = svgToPaths('<svg><circle cx="12" cy="8" r="2" /><line x1="1" y1="2" x2="3" y2="4" /><path d="M0 0h1" /></svg>');
  assert.deepEqual(paths, ["M10 8A2 2 0 1 0 14 8A2 2 0 1 0 10 8Z", "M1 2L3 4", "M0 0h1"]);
  assert.throws(() => svgToPaths("<svg></svg>"));
});

test("icons.json uses the pinned lucide version and canonical names", () => {
  const { lucide, web } = lucideVersions();
  assert.equal(lucide, web);
  const manifest = readManifest();
  const names = manifest.icons.map((i) => i.name);
  for (const canonical of ["Images", "SquareLibrary", "Heart", "FolderClosed", "FileText", "Activity", "Settings2", "Upload", "FolderUp", "Download", "PencilLine", "FolderInput", "Trash2", "Eye", "RotateCw", "Search", "Smartphone", "CloudUpload", "CloudOff", "ScanLine", "QrCode", "Share2", "Lock"]) {
    assert.ok(names.includes(canonical), `${canonical} listed`);
  }
  assert.throws(() => emitIcons({ icons: [{ name: "bad-name", lucide: "x", use: "" }] }, () => "", "0"));
  assert.throws(() => emitIcons({ icons: [{ name: "X", lucide: "x", use: "" }, { name: "X", lucide: "x", use: "" }] }, () => '<path d="M0 0"/>', "0"));
  const kotlin = generateIcons();
  const text = Object.values(kotlin)[0];
  assert.match(text, /object BentoNavIcons \{[\s\S]*val Images: ImageVector by lazy \{ imagesIcon\(1\.75f/);
  assert.match(text, /val HeartFilled: ImageVector/);
});
