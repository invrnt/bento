import { createHash, createPrivateKey, createPublicKey } from "node:crypto";
import { execFile } from "node:child_process";
import { mkdtemp, mkdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { describe, expect, it } from "vitest";
import { encodeUpdatePublicKey, parseUpdatePublicKey, verifyUpdateManifestSignature } from "../src/main/update-signature";

const run = promisify(execFile);
const desktopRoot = path.resolve(import.meta.dirname, "..");

describe("release metadata scripts", () => {
  it("creates checksums only for distributables and SBOM files", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "bento-checksums-"));
    try {
      const source = path.join(root, "source");
      const staged = path.join(root, "staged");
      const makerDirectory = path.join(source, "make", "zip", "linux", "x64");
      await mkdir(makerDirectory, { recursive: true });
      await writeFile(path.join(makerDirectory, "Bento.zip"), "artifact");
      await writeFile(path.join(source, "bento-linux.cdx.json"), "{}\n");
      await mkdir(path.join(source, "Bento-linux-x64"));
      await writeFile(path.join(source, "Bento-linux-x64", "bento"), "packaged executable");
      await run(process.execPath, [path.join(desktopRoot, "scripts", "stage-artifacts.mjs"), source, staged]);
      await run(process.execPath, [path.join(desktopRoot, "scripts", "checksums.mjs"), staged, "SHA256SUMS-test"]);
      const checksum = await readFile(path.join(staged, "SHA256SUMS-test"), "utf8");
      expect(checksum.trim().split("\n")).toHaveLength(2);
      expect(checksum).toContain(createHash("sha256").update("artifact").digest("hex"));
      expect(checksum).toContain("  Bento.zip");
      expect(checksum).not.toContain("make/");
      expect(checksum).not.toContain("Bento-linux-x64/bento");
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("creates a CycloneDX document from both locked ecosystems", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "bento-sbom-"));
    try {
      const output = path.join(root, "bento.cdx.json");
      await run(process.execPath, [path.join(desktopRoot, "scripts", "generate-sbom.mjs"), output]);
      const bom = JSON.parse(await readFile(output, "utf8")) as {
        bomFormat: string;
        specVersion: string;
        metadata: { component: { version: string } };
        components: unknown[];
      };
      expect(bom.bomFormat).toBe("CycloneDX");
      expect(bom.specVersion).toBe("1.5");
      expect(bom.metadata.component.version).toBe("0.1.0");
      expect(bom.components.length).toBeGreaterThan(100);
      const components = bom.components as Array<{ name: string; purl: string }>;
      const scoped = components.find((component) => component.name === "@babel/core");
      expect(scoped?.purl).toMatch(/^pkg:npm\/%40babel\/core@[^/]+$/u);
      expect(components.every((component) => !component.name.includes("node_modules/"))).toBe(true);
      expect(components.filter((component) => component.purl.startsWith("pkg:npm/")).every((component) => !component.purl.includes("%2F"))).toBe(true);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("rejects flattened artifact basename collisions", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "bento-stage-collision-"));
    try {
      const source = path.join(root, "source", "make");
      await mkdir(path.join(source, "one"), { recursive: true });
      await mkdir(path.join(source, "two"), { recursive: true });
      await writeFile(path.join(source, "one", "Bento.zip"), "one");
      await writeFile(path.join(source, "two", "bento.ZIP"), "two");
      await expect(run(process.execPath, [
        path.join(desktopRoot, "scripts", "stage-artifacts.mjs"),
        path.dirname(source),
        path.join(root, "staged"),
      ])).rejects.toThrow();
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("collects a globally flat release set and rejects cross-platform collisions", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "bento-release-assets-"));
    try {
      const source = path.join(root, "source");
      const destination = path.join(root, "destination");
      await mkdir(path.join(source, "linux"), { recursive: true });
      await mkdir(path.join(source, "windows"), { recursive: true });
      await writeFile(path.join(source, "linux", "Bento-linux.zip"), "linux");
      await writeFile(path.join(source, "windows", "BentoSetup.exe"), "windows");
      const script = path.join(desktopRoot, "scripts", "collect-release-assets.mjs");
      await run(process.execPath, [script, source, destination]);
      expect(await readFile(path.join(destination, "Bento-linux.zip"), "utf8")).toBe("linux");
      expect(await readFile(path.join(destination, "BentoSetup.exe"), "utf8")).toBe("windows");
      await writeFile(path.join(source, "windows", "bento-LINUX.ZIP"), "collision");
      await expect(run(process.execPath, [script, source, path.join(root, "collision")])).rejects.toThrow();
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("accepts only a tag exactly matching the desktop package version", async () => {
    const script = path.join(desktopRoot, "scripts", "validate-release-tag.mjs");
    await expect(run(process.execPath, [script, "v0.1.0"])).resolves.toMatchObject({ stdout: expect.stringContaining("v0.1.0") });
    await expect(run(process.execPath, [script, "v0.1.1"])).rejects.toThrow();
    await expect(run(process.execPath, [script, "v0.1.0-rc.1"])).rejects.toThrow();
  });

  it.each([
    ["patch", "0.1.1"],
    ["minor", "0.2.0"],
    ["major", "1.0.0"],
  ])("bumps %s consistently in package and lock metadata", async (kind, expectedVersion) => {
    const root = await mkdtemp(path.join(tmpdir(), "bento-version-"));
    try {
      await createVersionFixture(root);
      await run(process.execPath, [path.join(desktopRoot, "scripts", "bump-version.mjs"), kind, root]);
      const packageJson = JSON.parse(await readFile(path.join(root, "apps/desktop/package.json"), "utf8"));
      const lock = JSON.parse(await readFile(path.join(root, "apps/desktop/package-lock.json"), "utf8"));
      expect(packageJson.version).toBe(expectedVersion);
      expect(lock.version).toBe(expectedVersion);
      expect(lock.packages[""].version).toBe(expectedVersion);
      for (const filename of [
        "apps/api/pyproject.toml",
        "apps/api/uv.lock",
        "apps/api/src/bento/__init__.py",
        "apps/api/src/bento/infrastructure/settings.py",
        "apps/api/src/bento/domain/settings_registry.py",
      ]) expect(await readFile(path.join(root, filename), "utf8")).toContain(expectedVersion);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("refuses to bump inconsistent package and lock versions", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "bento-version-mismatch-"));
    try {
      await createVersionFixture(root);
      await writeFile(path.join(root, "apps/desktop/package-lock.json"), `${JSON.stringify({ version: "0.0.9", packages: { "": { version: "0.0.9" } } })}\n`);
      await expect(run(process.execPath, [path.join(desktopRoot, "scripts", "bump-version.mjs"), "patch", root])).rejects.toThrow();
      expect(JSON.parse(await readFile(path.join(root, "apps/desktop/package.json"), "utf8")).version).toBe("0.1.0");
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it.each([
    ["linux", "x64", ["bento_0.1.0_amd64.deb", "Bento-0.1.0-linux-x64.zip"]],
    ["darwin", "x64", ["Bento-0.1.0-x64.dmg", "Bento-0.1.0-x64.zip"]],
    ["darwin", "arm64", ["Bento-0.1.0-arm64.dmg", "Bento-0.1.0-arm64.zip"]],
  ])("creates a hashed updater manifest for %s-%s", async (platform, arch, filenames) => {
    const root = await mkdtemp(path.join(tmpdir(), "bento-update-manifest-"));
    try {
      for (const filename of filenames) await writeFile(path.join(root, filename), `contents:${filename}`);
      const output = await generateManifest(root, platform, arch);
      expect(output.schemaVersion).toBe(1);
      expect(output.version).toBe("0.1.0");
      expect(output.releaseName).toBe("Bento 0.1.0");
      expect(output.notes).toContain("0.1.0");
      expect(output.publishedAt).toBe("2026-08-25T12:00:00.000Z");
      expect(output.target).toBe(`${platform}-${arch}`);
      expect(output.commit).toBe("a".repeat(40));
      expect(output.assets).toHaveLength(2);
      for (const asset of output.assets) {
        expect(asset).toMatchObject({ platform, arch });
        expect(asset.kind).toMatch(/^[a-z-]+$/u);
        expect(asset.url).toBe(`https://github.com/invrnt/bento/releases/download/v0.1.0/${encodeURIComponent(asset.filename)}`);
        expect(asset.sha256).toMatch(/^[a-f0-9]{64}$/u);
        expect(asset.size).toBeGreaterThan(0);
      }
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("generates a signing key and signs manifests without printing private key material", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "bento-sign-manifest-"));
    const script = path.join(desktopRoot, "scripts", "sign-update-manifest.mjs");
    try {
      const keyPath = path.join(root, "signing.pem");
      const generated = await run(process.execPath, [script, "--generate-key", keyPath]);
      const pem = await readFile(keyPath, "utf8");
      const publicKey = /BENTO_UPDATE_PUBLIC_KEY=(\S+)/u.exec(generated.stdout)?.[1];
      expect(publicKey && parseUpdatePublicKey(publicKey)).toBeTruthy();
      expect(encodeUpdatePublicKey(createPublicKey(createPrivateKey(pem)))).toBe(publicKey);
      if (process.platform !== "win32") expect((await stat(keyPath)).mode & 0o777).toBe(0o600);
      await expect(run(process.execPath, [script, "--generate-key", keyPath])).rejects.toThrow();
      expect(await readFile(keyPath, "utf8")).toBe(pem);

      const manifest = path.join(root, "bento-update-linux-x64.json");
      await writeFile(manifest, '{"schemaVersion":1}\n');
      const environment = { ...process.env, BENTO_UPDATE_SIGNING_KEY: pem, BENTO_UPDATE_PUBLIC_KEY: publicKey };
      const signed = await run(process.execPath, [script, manifest], { env: environment });
      const signature = await readFile(`${manifest}.sig`);
      expect(verifyUpdateManifestSignature(await readFile(manifest), signature, parseUpdatePublicKey(publicKey!)!)).toBe(true);
      const keyBody = pem.split("\n")[1]!;
      for (const output of [generated.stdout, generated.stderr, signed.stdout, signed.stderr]) expect(output).not.toContain(keyBody);

      // A build key that the release is not signed with would brick updates; refuse it.
      const other = path.join(root, "other.pem");
      const otherKey = /BENTO_UPDATE_PUBLIC_KEY=(\S+)/u.exec((await run(process.execPath, [script, "--generate-key", other])).stdout)![1]!;
      const mismatch = run(process.execPath, [script, manifest], { env: { ...environment, BENTO_UPDATE_PUBLIC_KEY: otherKey } });
      await expect(mismatch).rejects.toMatchObject({ stderr: expect.stringContaining("does not belong") });
      await expect(run(process.execPath, [script, manifest], { env: { ...process.env, BENTO_UPDATE_SIGNING_KEY: "garbage" } }))
        .rejects.toMatchObject({ stderr: expect.not.stringContaining("garbage") });
      await expect(run(process.execPath, [script, path.join(root, "notes.json")], { env: environment })).rejects.toThrow();

      // Rotation: both keys sign; builds embedding either key accept the release.
      const rotation = { ...process.env, BENTO_UPDATE_SIGNING_KEY: `${pem}\n${await readFile(other, "utf8")}`, BENTO_UPDATE_PUBLIC_KEY: otherKey };
      await run(process.execPath, [script, manifest], { env: rotation });
      const dual = await readFile(`${manifest}.sig`);
      for (const key of [publicKey!, otherKey]) expect(verifyUpdateManifestSignature(await readFile(manifest), dual, parseUpdatePublicKey(key)!)).toBe(true);

      // `release:manifest` signs automatically when the signing secret is present.
      await writeFile(path.join(root, "bento_0.1.0_amd64.deb"), "deb");
      await writeFile(path.join(root, "Bento-linux-x64-0.1.0.zip"), "zip");
      await rm(manifest);
      await rm(`${manifest}.sig`);
      await run(process.execPath, [
        path.join(desktopRoot, "scripts", "generate-update-manifest.mjs"),
        "--stage", root, "--platform", "linux", "--arch", "x64", "--tag", "v0.1.0",
        "--published-at", "2026-08-25T12:00:00.000Z", "--commit", "a".repeat(40),
      ], { env: environment });
      expect(verifyUpdateManifestSignature(await readFile(manifest), await readFile(`${manifest}.sig`), parseUpdatePublicKey(publicKey!)!)).toBe(true);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("embeds verified Squirrel metadata in the Windows updater manifest", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "bento-windows-manifest-"));
    try {
      const nupkg = "bento-0.1.0-full.nupkg";
      const contents = Buffer.from("signed squirrel package");
      await writeFile(path.join(root, "Bento-0.1.0 Setup.exe"), "signed installer");
      await writeFile(path.join(root, nupkg), contents);
      const sha1 = createHash("sha1").update(contents).digest("hex");
      await writeFile(path.join(root, "RELEASES"), `${sha1.toUpperCase()} ${nupkg} ${contents.length}\n`);
      const output = await generateManifest(root, "win32", "x64");
      expect(output.squirrel.nupkg).toMatchObject({ filename: nupkg, sha1, size: contents.length });
      expect(output.squirrel.releasesContent).toBe(`${sha1.toUpperCase()} https://github.com/invrnt/bento/releases/download/v0.1.0/${nupkg} ${contents.length}\n`);
      await writeFile(path.join(root, "RELEASES"), `${"0".repeat(40)} ${nupkg} ${contents.length}\n`);
      await expect(generateManifest(root, "win32", "x64")).rejects.toThrow();
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});

interface UpdateManifest {
  schemaVersion: number;
  version: string;
  releaseName: string;
  notes: string;
  publishedAt: string;
  target: string;
  commit: string;
  assets: Array<{ platform: string; arch: string; kind: string; filename: string; url: string; sha256: string; size: number }>;
  squirrel: { nupkg: { filename: string; sha1: string; size: number }; releasesContent: string };
}

async function generateManifest(root: string, platform: string, arch: string): Promise<UpdateManifest> {
  await run(process.execPath, [
    path.join(desktopRoot, "scripts", "generate-update-manifest.mjs"),
    "--stage", root,
    "--platform", platform,
    "--arch", arch,
    "--tag", "v0.1.0",
    "--published-at", "2026-08-25T12:00:00.000Z",
    "--commit", "a".repeat(40),
  ]);
  return JSON.parse(await readFile(path.join(root, `bento-update-${platform}-${arch}.json`), "utf8")) as UpdateManifest;
}

async function createVersionFixture(root: string): Promise<void> {
  const files: Record<string, string> = {
    "apps/desktop/package.json": `${JSON.stringify({ version: "0.1.0" })}\n`,
    "apps/desktop/package-lock.json": `${JSON.stringify({ version: "0.1.0", packages: { "": { version: "0.1.0" } } })}\n`,
    "apps/api/pyproject.toml": "[project]\nname = \"bento-api\"\nversion = \"0.1.0\"\n",
    "apps/api/uv.lock": "[[package]]\nname = \"bento-api\"\nversion = \"0.1.0\"\nsource = { editable = \".\" }\n",
    "apps/api/src/bento/__init__.py": "__version__ = \"0.1.0\"\n",
    "apps/api/src/bento/infrastructure/settings.py": "class Settings:\n    app_version: str = \"0.1.0\"\n",
    "apps/api/src/bento/domain/settings_registry.py": "entry = _field(\"app_version\", (\"APP_VERSION\",), \"advanced\", Type.STRING, \"0.1.0\", editable=False)\n",
  };
  for (const [filename, contents] of Object.entries(files)) {
    await mkdir(path.dirname(path.join(root, filename)), { recursive: true });
    await writeFile(path.join(root, filename), contents);
  }
}
