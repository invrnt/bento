import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import path from "node:path";

// Usage: node scripts/generate-icons.mjs [--only=app|tray]
const desktopRoot = path.resolve(import.meta.dirname, "..");
const output = path.join(desktopRoot, "resources", "icons");
const trayOutput = path.join(desktopRoot, "resources", "tray");
const source = path.join(output, "bento-icon.svg");
const only = process.argv.find((argument) => argument.startsWith("--only="))?.slice("--only=".length);
if (only && only !== "app" && only !== "tray") throw new Error("--only must be app or tray");

async function generateAppIcons() {
  await mkdir(output, { recursive: true });
  const png = path.join(output, "bento.png");
  await run("rsvg-convert", ["--width", "1024", "--height", "1024", source, "--output", png]);

  const sizes = [16, 32, 48, 64, 128, 256, 512];
  const iconPngs = [];
  for (const size of sizes) {
    const target = path.join(output, `bento-${size}.png`);
    await run("magick", [png, "-resize", `${size}x${size}`, target]);
    iconPngs.push(target);
  }
  await run("magick", [...iconPngs, path.join(output, "bento.ico")]);

  const icnsChunks = [
    ["ic07", path.join(output, "bento-128.png")],
    ["ic08", path.join(output, "bento-256.png")],
    ["ic09", path.join(output, "bento-512.png")],
    ["ic10", png],
  ];
  const chunks = [];
  for (const [kind, filename] of icnsChunks) {
    const contents = await readFile(filename);
    const header = Buffer.alloc(8);
    header.write(kind, 0, "ascii");
    header.writeUInt32BE(contents.length + 8, 4);
    chunks.push(header, contents);
  }
  const body = Buffer.concat(chunks);
  const header = Buffer.alloc(8);
  header.write("icns", 0, "ascii");
  header.writeUInt32BE(body.length + 8, 4);
  await writeFile(path.join(output, "bento.icns"), Buffer.concat([header, body]));
  await Promise.all(iconPngs.map((filename) => rm(filename)));
}

// Tray variants reuse the brand mark geometry (32×32, outer radius 9, three compartments) and change
// only the glyph in the lower-right compartment: ume dot (idle), arrow (syncing), bars (paused), alert.
const COMPARTMENTS = [
  { x: 4.5, y: 5, width: 10.5, height: 22 },
  { x: 17, y: 5, width: 10.5, height: 10 },
  { x: 17, y: 17, width: 10.5, height: 10 },
];
const GLYPHS = {
  idle: { color: "#e94f13", shape: (fill) => `<circle cx="22.25" cy="22" r="2.75" fill="${fill}"/>` },
  syncing: { color: "#3857d8", shape: (fill) => `<path d="M22.25 18.4 L25.9 22.1 H23.55 V25.6 H20.95 V22.1 H18.6 Z" fill="${fill}"/>` },
  paused: {
    color: "#655f59",
    shape: (fill) => `<rect x="19.85" y="18.9" width="1.9" height="6.2" rx="0.6" fill="${fill}"/><rect x="22.75" y="18.9" width="1.9" height="6.2" rx="0.6" fill="${fill}"/>`,
  },
  attention: {
    color: "#dd9314",
    shape: (fill, cut) => cut
      ? `<mask id="alert"><circle cx="22.25" cy="22" r="3.6" fill="#fff"/><rect x="21.6" y="19.4" width="1.3" height="3.4" rx="0.65" fill="#000"/><circle cx="22.25" cy="24.5" r="0.75" fill="#000"/></mask><circle cx="22.25" cy="22" r="3.6" fill="${fill}" mask="url(#alert)"/>`
      : `<circle cx="22.25" cy="22" r="3.6" fill="${fill}"/><rect x="21.6" y="19.4" width="1.3" height="3.4" rx="0.65" fill="#221d18"/><circle cx="22.25" cy="24.5" r="0.75" fill="#221d18"/>`,
  },
};

function compartments(fill) {
  return COMPARTMENTS.map((item) => `<rect x="${item.x}" y="${item.y}" width="${item.width}" height="${item.height}" rx="3.5" fill="${fill}"/>`).join("");
}

function colorTraySvg(state) {
  const glyph = GLYPHS[state];
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">` +
    `<rect x="0.5" y="0.5" width="31" height="31" rx="8.5" fill="#221d18" stroke="#f5f2ee" stroke-opacity="0.55"/>` +
    compartments("#f5f2ee") + glyph.shape(glyph.color, false) + `</svg>`;
}

// macOS template images: black + alpha only; compartments are cut out of the box.
function templateTraySvg(state) {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">` +
    `<mask id="box"><rect width="32" height="32" fill="#fff"/>${compartments("#000")}</mask>` +
    `<rect width="32" height="32" rx="9" fill="#000" mask="url(#box)"/>` +
    GLYPHS[state].shape("#000", true) + `</svg>`;
}

async function generateTrayIcons() {
  await mkdir(trayOutput, { recursive: true });
  const scratch = path.join(tmpdir(), `bento-tray-${process.pid}`);
  await mkdir(scratch, { recursive: true });
  try {
    for (const state of Object.keys(GLYPHS)) {
      const color = path.join(scratch, `${state}.svg`);
      const template = path.join(scratch, `${state}-template.svg`);
      await writeFile(color, colorTraySvg(state));
      await writeFile(template, templateTraySvg(state));
      await render(color, 16, path.join(trayOutput, `tray-${state}.png`));
      await render(color, 32, path.join(trayOutput, `tray-${state}@2x.png`));
      await render(color, 32, path.join(trayOutput, `tray-${state}-linux.png`));
      await render(template, 16, path.join(trayOutput, `tray-${state}Template.png`));
      await render(template, 32, path.join(trayOutput, `tray-${state}Template@2x.png`));
    }
    await render(source, 128, path.join(trayOutput, "notification.png"));
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
}

function render(svg, size, target) {
  return run("rsvg-convert", ["--width", String(size), "--height", String(size), svg, "--output", target]);
}

async function run(command, args) {
  const child = spawn(command, args, { stdio: "inherit" });
  const code = await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (value) => resolve(value ?? 1));
  });
  if (code !== 0) throw new Error(`${command} failed with exit code ${code}`);
}

if (only !== "tray") await generateAppIcons();
if (only !== "app") await generateTrayIcons();
