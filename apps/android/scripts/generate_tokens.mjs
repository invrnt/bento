#!/usr/bin/env node
// Generates core/designsystem tokens from apps/web/src/styles/tokens.css (design-system/android.md §1).
//
//   node generate_tokens.mjs           write BentoTokens.kt and bento_colors.xml (values/ + values-night/)
//   node generate_tokens.mjs --check   exit 1 when the committed files differ from a fresh generation
//
// OKLCH is converted to sRGB at generation time with the CSS Color 4 gamut-mapping algorithm
// (chroma reduction until the clipped color is within ΔEOK 0.02), the same one browsers use.

import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
export const paths = {
  tokensCss: join(here, "../../web/src/styles/tokens.css"),
  kotlin: join(here, "../core/designsystem/src/main/kotlin/dev/bento/designsystem/generated/BentoTokens.kt"),
  colorsLight: join(here, "../core/designsystem/src/main/res/values/bento_colors.xml"),
  colorsNight: join(here, "../core/designsystem/src/main/res/values-night/bento_colors.xml"),
};

/** Documented mobile exceptions applied on top of the web tokens (design-system/android.md §2–§3). */
export const mobile = {
  radiusControl: 12, // fields and buttons at 48 dp
  radiusHero: 24,
  touchTarget: 48,
  denseVisual: 40,
  gutterCompact: 16,
  gutterMedium: 24,
  spacingBase: 4,
};

// ---------- Color math ----------

function oklabToLinearSrgb(L, a, b) {
  const l_ = L + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = L - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = L - 0.0894841775 * a - 1.291485548 * b;
  const l = l_ ** 3;
  const m = m_ ** 3;
  const s = s_ ** 3;
  return [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ];
}

function linearSrgbToOklab(r, g, b) {
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ];
}

const encode = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
const clip01 = (c) => Math.min(1, Math.max(0, c));
const inGamut = (rgb, eps = 1e-6) => rgb.every((c) => c >= -eps && c <= 1 + eps);

function oklchToLinear(L, C, h) {
  const rad = (h * Math.PI) / 180;
  return oklabToLinearSrgb(L, C * Math.cos(rad), C * Math.sin(rad));
}

function deltaEOK(rgbA, rgbB) {
  const a = linearSrgbToOklab(...rgbA);
  const b = linearSrgbToOklab(...rgbB);
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

/** CSS Color 4 §13.2 gamut mapping (binary search on chroma, JND 0.02), result in linear sRGB. */
function gamutMap(L, C, h) {
  if (L >= 1) return [1, 1, 1];
  if (L <= 0) return [0, 0, 0];
  const origin = oklchToLinear(L, C, h);
  if (inGamut(origin)) return origin;
  const JND = 0.02;
  const EPS = 0.0001;
  let clipped = origin.map(clip01);
  if (deltaEOK(clipped, origin) < JND) return clipped;
  let min = 0;
  let max = C;
  let minInGamut = true;
  while (max - min > EPS) {
    const chroma = (min + max) / 2;
    const current = oklchToLinear(L, chroma, h);
    if (minInGamut && inGamut(current)) {
      min = chroma;
      continue;
    }
    clipped = current.map(clip01);
    const E = deltaEOK(clipped, current);
    if (E < JND) {
      if (JND - E < EPS) return clipped;
      minInGamut = false;
      min = chroma;
    } else {
      max = chroma;
    }
  }
  return clipped;
}

/** `oklch(L C h / a)` → { r, g, b, a } with 8-bit channels. */
export function oklchToSrgb(L, C, h, alpha = 1) {
  const linear = gamutMap(L, C, h);
  const [r, g, b] = linear.map((c) => Math.round(clip01(encode(clip01(c))) * 255));
  return { r, g, b, a: Math.round(alpha * 255) };
}

export function parseOklch(text) {
  const match = text.trim().match(/^oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*(?:\/\s*([\d.]+))?\s*\)$/);
  if (!match) throw new Error(`Unsupported color: ${text}`);
  const [, L, C, h, a] = match;
  return oklchToSrgb(Number(L), Number(C), Number(h), a === undefined ? 1 : Number(a));
}

export const toHex = ({ r, g, b }) => `#${[r, g, b].map((c) => c.toString(16).padStart(2, "0")).join("")}`;
const toArgbHex = ({ r, g, b, a }) => [a, r, g, b].map((c) => c.toString(16).padStart(2, "0").toUpperCase()).join("");

// ---------- CSS parsing ----------

/** Splits on commas that are not inside parentheses. */
function splitTopLevel(value) {
  const parts = [];
  let depth = 0;
  let current = "";
  for (const char of value) {
    if (char === "(") depth += 1;
    if (char === ")") depth -= 1;
    if (char === "," && depth === 0) {
      parts.push(current.trim());
      current = "";
    } else {
      current += char;
    }
  }
  if (current.trim()) parts.push(current.trim());
  return parts;
}

/** Returns { light, dark } colors for `light-dark(a, b)` or a single value. */
function parseThemedColor(value) {
  const ld = value.match(/^light-dark\((.*)\)$/s);
  if (ld) {
    const [light, dark] = splitTopLevel(ld[1]);
    return { light: parseOklch(light), dark: parseOklch(dark) };
  }
  const color = parseOklch(value);
  return { light: color, dark: color };
}

function declarations(css) {
  const out = new Map();
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, "");
  for (const match of stripped.matchAll(/(--[\w-]+)\s*:\s*([^;{}]+);/g)) {
    out.set(match[1], match[2].replace(/\s+/g, " ").trim());
  }
  return out;
}

const camel = (name) => name.replace(/-([a-z0-9])/g, (_, c) => c.toUpperCase());
const remToDp = (value) => {
  const rem = value.match(/^(-?[\d.]+)rem$/);
  if (rem) return Number(rem[1]) * 16;
  const px = value.match(/^(-?[\d.]+)px$/);
  if (px) return Number(px[1]);
  throw new Error(`Unsupported length: ${value}`);
};
const ms = (value) => {
  const m = value.match(/^([\d.]+)(ms|s)$/);
  if (!m) throw new Error(`Unsupported duration: ${value}`);
  return m[2] === "s" ? Number(m[1]) * 1000 : Number(m[1]);
};

function parseShadow(value) {
  return splitTopLevel(value).map((layer) => {
    const inset = layer.startsWith("inset ");
    const body = inset ? layer.slice(6) : layer;
    const colorStart = body.search(/(light-dark|oklch)\(/);
    const lengths = body.slice(0, colorStart).trim().split(/\s+/).map((l) => (l === "0" ? 0 : remToDp(l)));
    const [x = 0, y = 0, blur = 0, spread = 0] = lengths;
    return { inset, x, y, blur, spread, color: parseThemedColor(body.slice(colorStart).trim()) };
  });
}

export function parseTokens(css) {
  const decl = declarations(css);
  const colors = [];
  for (const [name, value] of decl) {
    if (!name.startsWith("--color-") || value === "initial") continue;
    colors.push({ name: name.slice("--color-".length), ...parseThemedColor(value) });
  }
  const text = [];
  for (const [name, value] of decl) {
    const m = name.match(/^--text-([\w]+)$/);
    if (m) text.push({ name: m[1], size: remToDp(value), lineHeight: remToDp(decl.get(`${name}--line-height`)) });
  }
  const tracking = [...decl].filter(([n]) => n.startsWith("--tracking-")).map(([n, v]) => ({ name: n.slice(11), em: Number(v.replace("em", "")) }));
  const radius = [...decl].filter(([n]) => n.startsWith("--radius-")).map(([n, v]) => ({ name: n.slice(9), dp: remToDp(v) }));
  const shadows = [...decl].filter(([n]) => n.startsWith("--shadow-")).map(([n, v]) => ({ name: n.slice(9), layers: parseShadow(v) }));
  const easing = [...decl]
    .filter(([n]) => n.startsWith("--ease-"))
    .map(([n, v]) => ({ name: n.slice(7), points: v.match(/cubic-bezier\(([^)]+)\)/)[1].split(",").map(Number) }));
  const animations = [...decl]
    .filter(([n]) => n.startsWith("--animate-"))
    .map(([n, v]) => ({ name: n.slice(10), ms: ms(v.split(" ")[1]) }));
  const durations = [...decl].filter(([n]) => n.startsWith("--duration-")).map(([n, v]) => ({ name: n.slice(11), ms: ms(v) }));
  const sizes = [...decl]
    .filter(([n]) => n.startsWith("--size-"))
    .map(([n, v]) => ({ name: n.slice(7), dp: remToDp(v) }));
  return { colors, text, tracking, radius, shadows, easing, animations, durations, sizes };
}

// ---------- Emitters ----------

const header = (source) =>
  `// GENERATED by apps/android/scripts/generate_tokens.mjs from ${source}. Do not edit; run \`npm run generate\` in apps/android/scripts.`;

const kNum = (n) => {
  const s = Number(n.toFixed(4)).toString();
  return s.includes(".") ? `${s}f` : `${s}f`;
};
const kDp = (n) => `${Number(n.toFixed(3))}.dp`.replace(/^(\d+)\.dp$/, "$1.dp");

const singleColors = new Set(["white", "black", "on-accent", "on-danger", "media", "media-raised"]);

export function emitKotlin(tokens) {
  const themed = tokens.colors.filter((c) => !["media", "media-raised"].includes(c.name));
  const lines = [];
  lines.push(header("apps/web/src/styles/tokens.css"));
  lines.push("@file:Suppress(\"MagicNumber\", \"ktlint\")");
  lines.push("");
  lines.push("package dev.bento.designsystem.generated");
  lines.push("");
  lines.push("import androidx.compose.animation.core.CubicBezierEasing");
  lines.push("import androidx.compose.runtime.Immutable");
  lines.push("import androidx.compose.ui.graphics.Color");
  lines.push("import androidx.compose.ui.unit.Dp");
  lines.push("import androidx.compose.ui.unit.dp");
  lines.push("");
  lines.push("/** Every color token of one theme, converted from OKLCH to sRGB. */");
  lines.push("@Immutable");
  lines.push("public data class BentoColorTokens(");
  for (const c of themed) lines.push(`    val ${camel(c.name)}: Color,`);
  lines.push(")");
  lines.push("");
  lines.push("/** One shadow layer: CSS `x y blur spread color`, in dp. */");
  lines.push("@Immutable");
  lines.push("public data class BentoShadowLayer(val x: Dp, val y: Dp, val blur: Dp, val spread: Dp, val color: Color, val inset: Boolean)");
  lines.push("");
  lines.push("@Immutable");
  lines.push("public data class BentoShadowTokens(");
  for (const s of tokens.shadows) lines.push(`    val ${camel(s.name)}: List<BentoShadowLayer>,`);
  lines.push(")");
  lines.push("");
  lines.push("public object BentoTokens {");
  for (const theme of ["light", "dark"]) {
    lines.push(`    public val ${theme === "light" ? "LightColors" : "DarkColors"}: BentoColorTokens = BentoColorTokens(`);
    for (const c of themed) {
      const comment = singleColors.has(c.name) ? "" : `, // ${toHex(c[theme])}${c[theme].a < 255 ? ` @ ${(c[theme].a / 255).toFixed(3)}` : ""}`;
      lines.push(`        ${camel(c.name)} = Color(0x${toArgbHex(c[theme])})${comment || ","}`);
    }
    lines.push("    )");
    lines.push("");
  }
  for (const theme of ["light", "dark"]) {
    lines.push(`    public val ${theme === "light" ? "LightShadows" : "DarkShadows"}: BentoShadowTokens = BentoShadowTokens(`);
    for (const s of tokens.shadows) {
      const layers = s.layers
        .map((l) => `BentoShadowLayer(${kDp(l.x)}, ${kDp(l.y)}, ${kDp(l.blur)}, ${kDp(l.spread)}, Color(0x${toArgbHex(l.color[theme])}), inset = ${l.inset})`)
        .join(", ");
      lines.push(`        ${camel(s.name)} = listOf(${layers}),`);
    }
    lines.push("    )");
    lines.push("");
  }
  lines.push("    /** The media viewer is always dark, regardless of theme (brand.md §14). */");
  for (const name of ["media", "media-raised"]) {
    const c = tokens.colors.find((x) => x.name === name);
    lines.push(`    public val ${camel(name)}: Color = Color(0x${toArgbHex(c.light)}) // ${toHex(c.light)}`);
  }
  lines.push("");
  lines.push("    public object Radius {");
  for (const r of tokens.radius) lines.push(`        public val ${camel(r.name === "2xl" ? "xxl" : r.name)}: Dp = ${kDp(r.dp)}`);
  lines.push("        /** Mobile exception: 48 dp fields and buttons use 12 dp (design-system/android.md §3). */");
  lines.push(`        public val controlMobile: Dp = ${kDp(mobile.radiusControl)}`);
  lines.push("    }");
  lines.push("");
  lines.push("    /** 4 dp base unit (brand.md §6). */");
  lines.push("    public object Spacing {");
  for (const step of [0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 12, 16]) {
    lines.push(`        public val s${String(step).replace(".", "_")}: Dp = ${kDp(step * mobile.spacingBase)}`);
  }
  lines.push(`        public val gutterCompact: Dp = ${kDp(mobile.gutterCompact)}`);
  lines.push(`        public val gutterMedium: Dp = ${kDp(mobile.gutterMedium)}`);
  lines.push("    }");
  lines.push("");
  lines.push("    public object Size {");
  for (const s of tokens.sizes) lines.push(`        public val ${camel(s.name)}: Dp = ${kDp(s.dp)}`);
  lines.push(`        public val touchTarget: Dp = ${kDp(mobile.touchTarget)}`);
  lines.push(`        public val denseVisual: Dp = ${kDp(mobile.denseVisual)}`);
  lines.push("    }");
  lines.push("");
  lines.push("    /** Brand type scale in px (= sp); the mobile step-up lives in BentoTypography. */");
  lines.push("    public object Text {");
  for (const t of tokens.text) {
    const name = camel(t.name.replace(/^(\d)xl$/, "xl$1").replace(/^2xs$/, "xxs"));
    lines.push(`        public val ${name}: Pair<Float, Float> = ${kNum(t.size)} to ${kNum(t.lineHeight)}`);
  }
  for (const t of tokens.tracking) lines.push(`        public val tracking${camel("-" + t.name)}: Float = ${kNum(t.em)} // em`);
  lines.push("    }");
  lines.push("");
  lines.push("    public object Duration {");
  for (const d of tokens.durations) lines.push(`        public const val ${camel(d.name)}: Int = ${d.ms}`);
  for (const a of tokens.animations) lines.push(`        public const val ${camel(a.name)}: Int = ${a.ms}`);
  lines.push("    }");
  lines.push("");
  lines.push("    public object Easing {");
  for (const e of tokens.easing) {
    lines.push(`        public val ${camel("ease-" + e.name)}: CubicBezierEasing = CubicBezierEasing(${e.points.map(kNum).join(", ")})`);
  }
  lines.push("    }");
  lines.push("}");
  lines.push("");
  return lines.join("\n");
}

const xmlName = (name) => `bento_${name.replace(/-/g, "_")}`;

export function emitColorsXml(tokens, theme) {
  const lines = ['<?xml version="1.0" encoding="utf-8"?>'];
  lines.push(`<!-- ${header("apps/web/src/styles/tokens.css").slice(3)} -->`);
  lines.push("<!-- Color resources for system surfaces (launcher, splash, notification, AVD). Compose uses BentoTokens. -->");
  lines.push("<resources>");
  for (const c of tokens.colors) {
    const v = c[theme];
    const hex = v.a < 255 ? `#${toArgbHex(v)}` : toHex(v).toUpperCase();
    lines.push(`    <color name="${xmlName(c.name)}">${hex}</color>`);
  }
  if (theme === "light") {
    lines.push("    <!-- Launcher layers never follow night mode: the icon is one object. -->");
    for (const name of ["tray", "ink", "shu"]) {
      const c = tokens.colors.find((x) => x.name === name);
      lines.push(`    <color name="bento_brand_${name}">${toHex(c.light).toUpperCase()}</color>`);
    }
  }
  lines.push("</resources>");
  lines.push("");
  return lines.join("\n");
}

export function generate(css) {
  const tokens = parseTokens(css);
  return {
    [paths.kotlin]: emitKotlin(tokens),
    [paths.colorsLight]: emitColorsXml(tokens, "light"),
    [paths.colorsNight]: emitColorsXml(tokens, "dark"),
  };
}

export function writeOrCheck(outputs, check) {
  const drift = [];
  for (const [file, content] of Object.entries(outputs)) {
    const current = existsSync(file) ? readFileSync(file, "utf8") : null;
    if (current === content) continue;
    if (check) {
      drift.push(relative(process.cwd(), file));
    } else {
      mkdirSync(dirname(file), { recursive: true });
      writeFileSync(file, content);
    }
  }
  return drift;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const check = process.argv.includes("--check");
  const drift = writeOrCheck(generate(readFileSync(paths.tokensCss, "utf8")), check);
  if (drift.length) {
    console.error(`Design tokens drifted from tokens.css; run \`npm run generate\` in apps/android/scripts:\n  ${drift.join("\n  ")}`);
    process.exit(1);
  }
  if (!check) console.log("Bento tokens generated.");
}
