import { access, readFile } from "node:fs/promises";
import { constants } from "node:fs";
import path from "node:path";
import { checkChecksums } from "./checksums.mjs";

/**
 * The bundled llama-server (smart search, D4). scripts/build-llama-server.{sh,ps1} is the only place the
 * llama.cpp pin lives; these helpers read it from there so the packaging scripts cannot drift.
 */
export const repositoryRoot = path.resolve(import.meta.dirname, "../../..");
export const buildScript = path.join(repositoryRoot, "scripts", "build-llama-server.sh");
/** Folder name inside the sidecar bundle and inside the packaged app's resources. */
export const LLAMA_RESOURCE_DIR = "llama-server";
export const LLAMA_BUILD_INFO = "bento-llama-server.json";
/** Development packaging without llama-server (never for releases; bento-release refuses it). */
export const SKIP_LLAMA_SERVER_ENV = "BENTO_SKIP_LLAMA_SERVER";
/** A prebuilt llama-server folder (same layout as the build script output) instead of building one. */
export const LLAMA_SERVER_DIR_ENV = "BENTO_LLAMA_SERVER_DIR";

export function llamaServerExecutable(platform = process.platform) {
  return platform === "win32" ? "llama-server.exe" : "llama-server";
}

export function skipLlamaServer(environment = process.env) {
  return environment[SKIP_LLAMA_SERVER_ENV] === "1";
}

/** dist/llama-server/<platform>-<arch>, the build scripts' predictable output folder. */
export function llamaBuildOutput(platform = process.platform, arch = process.arch, environment = process.env) {
  const override = environment[LLAMA_SERVER_DIR_ENV];
  return override ? path.resolve(override) : path.join(repositoryRoot, "dist", "llama-server", `${platform}-${arch}`);
}

/** `{ tag, buildNumber, commit, sourceUrl, sourceSha256, components }` parsed from the build script. */
export async function readLlamaPin(script = buildScript) {
  const text = await readFile(script, "utf8");
  const value = (name) => {
    const match = new RegExp(`^${name}="([^"]+)"$`, "mu").exec(text);
    if (!match) throw new Error(`${path.basename(script)} does not define ${name}`);
    return match[1];
  };
  const tag = value("LLAMA_CPP_TAG");
  const pin = {
    tag,
    buildNumber: value("LLAMA_CPP_BUILD_NUMBER"),
    commit: value("LLAMA_CPP_COMMIT"),
    sourceUrl: value("LLAMA_CPP_SOURCE_URL").replace("${LLAMA_CPP_TAG}", tag),
    sourceSha256: value("LLAMA_CPP_SOURCE_SHA256"),
    components: parseComponents(text),
  };
  if (!/^b\d+$/u.test(pin.tag) || pin.tag !== `b${pin.buildNumber}`) throw new Error(`Invalid llama.cpp pin ${pin.tag}/${pin.buildNumber}`);
  if (!/^[0-9a-f]{64}$/u.test(pin.sourceSha256)) throw new Error("LLAMA_CPP_SOURCE_SHA256 is not a SHA-256");
  if (!pin.sourceUrl.startsWith("https://github.com/ggml-org/llama.cpp/")) throw new Error("LLAMA_CPP_SOURCE_URL is not the ggml-org source");
  return pin;
}

/** The `component | license | text` rows of print_licenses(). */
function parseComponents(text) {
  const block = /print_licenses\(\) \{\n {2}cat <<'EOF'\n([\s\S]*?)\nEOF\n\}/u.exec(text);
  if (!block) throw new Error("build-llama-server.sh has no print_licenses list");
  return block[1].split("\n").filter(Boolean).map((line) => {
    const [name, license, where] = line.split(" | ");
    if (!name || !license || !where) throw new Error(`Malformed component line: ${line}`);
    return { name, license, where };
  });
}

/**
 * Problems with a llama-server folder (empty = fine): the executable, its build info matching the pin and
 * target, and every file against its SHA256SUMS. `compareHashes: false` is for code-signed packages,
 * where codesign/Authenticode rewrote the binaries after the build.
 */
export async function checkLlamaBundle(directory, { platform = process.platform, arch = process.arch, pin, compareHashes = true } = {}) {
  const problems = [];
  const executable = path.join(directory, llamaServerExecutable(platform));
  try {
    await access(executable, platform === "win32" ? constants.R_OK : constants.X_OK);
  } catch {
    return [`${llamaServerExecutable(platform)} is missing or not executable in ${directory}`];
  }
  let info;
  try {
    info = JSON.parse(await readFile(path.join(directory, LLAMA_BUILD_INFO), "utf8"));
  } catch {
    return [`${LLAMA_BUILD_INFO} is missing or invalid in ${directory}`];
  }
  const expected = pin ?? await readLlamaPin();
  if (info.tag !== expected.tag) problems.push(`llama-server was built from ${info.tag}, the pin is ${expected.tag}`);
  if (info.source_sha256 !== expected.sourceSha256) problems.push("llama-server was built from a source tarball with another digest");
  if (info.target !== `${platform}-${arch}`) problems.push(`llama-server was built for ${info.target}, not ${platform}-${arch}`);
  try {
    const sums = await checkChecksums(directory);
    if (compareHashes) problems.push(...sums);
    else problems.push(...sums.filter((problem) => !problem.endsWith("does not match its SHA-256")));
  } catch (error) {
    problems.push(`llama-server SHA256SUMS: ${error instanceof Error ? error.message : String(error)}`);
  }
  return problems;
}
