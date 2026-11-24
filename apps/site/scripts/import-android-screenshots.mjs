// Copies the Android Roborazzi goldens (light theme) used on /android/ into src/assets/android/
// as small WebP files. Run after the goldens change; the output is committed so the site build
// stays dependency-free. Requires ImageMagick 7 (`magick`) with WebP support.
//   node apps/site/scripts/import-android-screenshots.mjs
import { spawnSync } from "node:child_process";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const features = path.resolve(root, "../android/feature");

export const SCREENSHOT_WIDTH = 480;

/** Golden (relative to apps/android/feature) → published name under /assets/android/. */
export const SCREENSHOTS = Object.freeze([
  { golden: "photos/screenshots/photos-grid/light.png", name: "fotos.webp" },
  { golden: "files/screenshots/list/light.png", name: "archivos.webp" },
  { golden: "search/screenshots/results/light.png", name: "buscar.webp" },
  { golden: "collections/screenshots/collections-hub/light.png", name: "biblioteca.webp" },
]);

export function convert({ golden, name }, output = path.join(root, "src/assets/android")) {
  const result = spawnSync(
    "magick",
    [
      path.join(features, golden),
      "-resize", `${SCREENSHOT_WIDTH}x`,
      "-strip",
      "-quality", "82",
      "-define", "webp:method=6",
      path.join(output, name),
    ],
    { stdio: "inherit" },
  );
  if (result.status !== 0) throw new Error(`magick failed for ${golden}`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await mkdir(path.join(root, "src/assets/android"), { recursive: true });
  for (const shot of SCREENSHOTS) {
    convert(shot);
    console.log(`${shot.golden} → src/assets/android/${shot.name}`);
  }
}
