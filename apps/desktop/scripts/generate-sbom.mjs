import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { readLlamaPin } from "./llama-server.mjs";

const repositoryRoot = path.resolve(import.meta.dirname, "../../..");
const output = path.resolve(process.argv[2] ?? path.join(repositoryRoot, "dist", "desktop", "bento-sbom.cdx.json"));
const desktopPackage = JSON.parse(await readFile(path.join(repositoryRoot, "apps/desktop/package.json"), "utf8"));
const suppliedVersion = process.env.BENTO_RELEASE_VERSION;
const componentVersion = suppliedVersion?.startsWith("v") ? suppliedVersion.slice(1) : suppliedVersion ?? desktopPackage.version;
const components = new Map();

for (const lockPath of ["apps/web/package-lock.json", "apps/desktop/package-lock.json"]) {
  const lock = JSON.parse(await readFile(path.join(repositoryRoot, lockPath), "utf8"));
  for (const [location, dependency] of Object.entries(lock.packages ?? {})) {
    if (!location.startsWith("node_modules/") || !dependency.version) continue;
    const name = location.split("node_modules/").at(-1);
    if (!name) continue;
    const purl = npmPurl(name, dependency.version);
    const key = `npm:${purl}`;
    components.set(key, {
      type: "library",
      name,
      version: dependency.version,
      "bom-ref": purl,
      purl,
    });
  }
}

const uvLock = await readFile(path.join(repositoryRoot, "apps/api/uv.lock"), "utf8");
for (const block of uvLock.split("[[package]]").slice(1)) {
  const name = block.match(/^\s*name\s*=\s*"([^"]+)"/mu)?.[1];
  const version = block.match(/^\s*version\s*=\s*"([^"]+)"/mu)?.[1];
  if (!name || !version) continue;
  const key = `pypi:${name}@${version}`;
  components.set(key, {
    type: "library",
    name,
    version,
    "bom-ref": `pkg:pypi/${name}@${version}`,
    purl: `pkg:pypi/${name}@${version}`,
  });
}

// llama-server is built from source by scripts/build-llama-server.{sh,ps1}; its pin is the source of truth.
const llama = await readLlamaPin();
const llamaPurl = `pkg:github/ggml-org/llama.cpp@${llama.tag}`;
components.set(`github:${llamaPurl}`, {
  type: "application",
  name: "llama.cpp",
  version: llama.tag,
  "bom-ref": llamaPurl,
  purl: llamaPurl,
  description: "llama-server, the local embedding server of smart search",
  licenses: [{ license: { id: "MIT" } }],
  hashes: [{ alg: "SHA-256", content: llama.sourceSha256 }],
  externalReferences: [{ type: "distribution", url: llama.sourceUrl }],
  properties: [{ name: "bento:llama-cpp-commit", value: llama.commit }],
  // Vendored into the llama.cpp tree at this tag and compiled into llama-server.
  components: llama.components.filter((component) => !component.name.startsWith("llama.cpp")).map((component) => ({
    type: "library",
    name: component.name,
    version: `vendored-${llama.tag}`,
    "bom-ref": `${llamaPurl}#${component.name.replace(/[^A-Za-z0-9._-]+/gu, "-")}`,
    licenses: [/^[A-Za-z0-9.+-]+$/u.test(component.license) ? { license: { id: component.license } } : { license: { name: component.license } }],
  })),
});

const lockDigest = createHash("sha256").update(uvLock).digest("hex");
const bom = {
  bomFormat: "CycloneDX",
  specVersion: "1.5",
  serialNumber: `urn:uuid:${uuidFromHex(lockDigest)}`,
  version: 1,
  metadata: {
    timestamp: new Date().toISOString(),
    component: { type: "application", name: "Bento Desktop", version: componentVersion },
    properties: [{ name: "bento:uv-lock-sha256", value: lockDigest }],
  },
  components: [...components.values()].sort((left, right) => left["bom-ref"].localeCompare(right["bom-ref"])),
};
await mkdir(path.dirname(output), { recursive: true });
await writeFile(output, `${JSON.stringify(bom, null, 2)}\n`, "utf8");

function uuidFromHex(hex) {
  const value = `${hex.slice(0, 12)}4${hex.slice(13, 16)}a${hex.slice(17, 20)}${hex.slice(20, 32)}`;
  return `${value.slice(0, 8)}-${value.slice(8, 12)}-${value.slice(12, 16)}-${value.slice(16, 20)}-${value.slice(20)}`;
}

function npmPurl(name, version) {
  if (!name.startsWith("@")) return `pkg:npm/${encodeURIComponent(name)}@${encodeURIComponent(version)}`;
  const separator = name.indexOf("/");
  if (separator <= 1 || separator === name.length - 1) throw new Error(`Invalid scoped npm package name: ${name}`);
  const namespace = name.slice(0, separator);
  const packageName = name.slice(separator + 1);
  return `pkg:npm/${encodeURIComponent(namespace)}/${encodeURIComponent(packageName)}@${encodeURIComponent(version)}`;
}
