import { access, mkdir, rename, writeFile } from "node:fs/promises";
import path from "node:path";

// Writes resources/build-config.json (packaged as an extra resource) from BENTO_TELEGRAM_API_ID,
// BENTO_TELEGRAM_API_HASH, BENTO_RELAY_URL, BENTO_PUBLIC_SITE_URL, and BENTO_UPDATE_PUBLIC_KEY (written
// as `updatePublicKey`: base64 of the raw 32-byte Ed25519 key that verifies update manifests).
// Absent values are omitted. Values are validated with the runtime parser and are never printed;
// only key names are reported.
//
//   --keep-existing     keep a file written by an earlier step (CI writes it from secrets before `make`)
//   --require-telegram  fail unless the Telegram API credentials are present (production releases)

const desktopRoot = path.resolve(import.meta.dirname, "..");
const target = path.join(desktopRoot, "resources", "build-config.json");
const keepExisting = process.argv.includes("--keep-existing");
const requireTelegram = process.argv.includes("--require-telegram");

if (keepExisting && await exists(target)) {
  console.log("build-config: keeping existing resources/build-config.json");
  process.exit(0);
}

let runtime;
try {
  // Node.js 22.18+/24 strips types natively, so the runtime validator is reused instead of duplicated.
  runtime = await import("../src/main/build-config.ts");
} catch (error) {
  console.error(`build-config: could not load the runtime validator (${error?.code ?? "unknown"}); use Node.js 24.`);
  process.exit(1);
}
const { BUILD_CONFIG_KEYS, UPDATE_PUBLIC_KEY_ENV, UPDATE_PUBLIC_KEY_FIELD, parseBuildConfig } = runtime;

const candidate = {};
for (const key of BUILD_CONFIG_KEYS) {
  const value = process.env[key]?.trim();
  if (value) candidate[key] = value;
}
const updatePublicKey = process.env[UPDATE_PUBLIC_KEY_ENV]?.trim();
if (updatePublicKey) candidate[UPDATE_PUBLIC_KEY_FIELD] = updatePublicKey;
const parsed = parseBuildConfig(candidate, { allowLoopbackInsecure: false });
const { rejected } = parsed;
const config = parsed.updatePublicKey ? { ...parsed.config, [UPDATE_PUBLIC_KEY_FIELD]: parsed.updatePublicKey } : parsed.config;
if (rejected.length) {
  console.error(`build-config: invalid values for ${rejected.join(", ")}`);
  process.exit(1);
}
if (requireTelegram && (!config.BENTO_TELEGRAM_API_ID || !config.BENTO_TELEGRAM_API_HASH)) {
  console.error("Production release blocked: BENTO_TELEGRAM_API_ID and BENTO_TELEGRAM_API_HASH are required.");
  process.exit(1);
}

await mkdir(path.dirname(target), { recursive: true });
const temporary = `${target}.${process.pid}.tmp`;
// World-readable on purpose: installed packages are root-owned and the app reads it as the user.
await writeFile(temporary, `${JSON.stringify(config, null, 2)}\n`, { encoding: "utf8", mode: 0o644 });
await rename(temporary, target);
const keys = Object.keys(config);
console.log(`build-config: wrote ${keys.length} key(s)${keys.length ? `: ${keys.join(", ")}` : ""}`);

async function exists(filePath) {
  try {
    await access(filePath);
    return true;
  } catch {
    return false;
  }
}
