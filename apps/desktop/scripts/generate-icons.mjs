import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import path from "node:path";

const desktopRoot = path.resolve(import.meta.dirname, "..");
const output = path.join(desktopRoot, "resources", "icons");
const source = path.join(output, "bento-icon.svg");
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

async function run(command, args) {
  const child = spawn(command, args, { stdio: "inherit" });
  const code = await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (value) => resolve(value ?? 1));
  });
  if (code !== 0) throw new Error(`${command} failed with exit code ${code}`);
}
