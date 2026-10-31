// Refuses to publish while owner placeholders ([[COMPLETAR: …]]) remain in the built site.
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const MARKER = /\[\[COMPLETAR:[^\]]*\]\]/gu;

async function walk(directory) {
  const result = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const full = path.join(directory, entry.name);
    if (entry.isDirectory()) result.push(...(await walk(full)));
    else if (/\.(html|css|js|txt|svg)$/u.test(entry.name) || entry.name === "_headers") result.push(full);
  }
  return result;
}

export async function findPlaceholders(directory) {
  const findings = [];
  for (const file of (await walk(directory)).sort()) {
    const text = await readFile(file, "utf8");
    for (const match of text.matchAll(MARKER)) findings.push({ file: path.relative(directory, file), marker: match[0] });
  }
  return findings;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const findings = await findPlaceholders(path.join(root, "dist"));
  if (findings.length > 0) {
    console.error(`Publishing blocked: ${findings.length} owner placeholder(s) remain (legal review required).`);
    for (const { file, marker } of findings) console.error(`  ${file}: ${marker}`);
    console.error("Fill them in apps/site/src (and docs/legal), or use `npm run deploy:preview` for a review deployment.");
    process.exit(1);
  }
  console.log("No placeholders left.");
}
