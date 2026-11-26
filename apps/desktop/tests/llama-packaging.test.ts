import { createHash } from "node:crypto";
import { EventEmitter } from "node:events";
import { execFile } from "node:child_process";
import { chmod, mkdir, mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { PassThrough } from "node:stream";
import { promisify } from "node:util";
import { describe, expect, it, vi } from "vitest";
import {
  LLAMA_SERVER_PATH_ENV,
  llamaServerPathForCommand,
  POWER_STATE_FILE_ENV,
  readBatteryPercent,
  resolveLlamaServerPath,
  SidecarSupervisor,
} from "../src/main/sidecars";
// @ts-expect-error -- plain ES module shared by the packaging scripts (no type declarations).
import { checkChecksums, parseChecksums, writeChecksums } from "../scripts/checksums.mjs";
// @ts-expect-error -- plain ES module shared by the packaging scripts (no type declarations).
import { checkLlamaBundle, llamaBuildOutput, llamaServerExecutable, readLlamaPin } from "../scripts/llama-server.mjs";

const run = promisify(execFile);
const desktopRoot = path.resolve(import.meta.dirname, "..");
const repositoryRoot = path.resolve(desktopRoot, "../..");

interface Pin {
  tag: string;
  buildNumber: string;
  commit: string;
  sourceUrl: string;
  sourceSha256: string;
  components: Array<{ name: string; license: string; where: string }>;
}

async function temporaryDirectory(prefix: string): Promise<string> {
  return mkdtemp(path.join(tmpdir(), prefix));
}

/** A fake build-script output folder: executable, a library, licenses, build info and SHA256SUMS. */
async function fakeBundle(root: string, pin: Pin, target = `${process.platform}-${process.arch}`): Promise<string> {
  const directory = path.join(root, "llama-server");
  await mkdir(path.join(directory, "licenses"), { recursive: true });
  const executable = path.join(directory, llamaServerExecutable() as string);
  await writeFile(executable, "#!/bin/sh\necho 'version: 1.1.0-dev (build 12777)'\n");
  await chmod(executable, 0o755);
  await writeFile(path.join(directory, process.platform === "win32" ? "ggml-cpu-haswell.dll" : "libggml-cpu-haswell.so"), "cpu backend");
  await writeFile(path.join(directory, "licenses", "LICENSE-llama.cpp"), "MIT License\n");
  await writeFile(path.join(directory, "bento-llama-server.json"), JSON.stringify({
    schema_version: 1, name: "llama-server", tag: pin.tag, source_sha256: pin.sourceSha256, target, license: "MIT",
  }));
  await writeChecksums(directory);
  return directory;
}

class FakeChild extends EventEmitter {
  pid = 7;
  exitCode: number | null = null;
  stdout = new PassThrough();
  stderr = new PassThrough();
  kill(): boolean {
    this.exit(0);
    return true;
  }
  exit(code: number): void {
    if (this.exitCode !== null) return;
    this.exitCode = code;
    this.emit("exit", code, null);
  }
}

function supervisorWith(options: { dataDir: string; command?: { executable: string; prefixArguments: string[] }; batteryPercent?: () => Promise<number | null> }) {
  const launches: Array<{ command: string; env: NodeJS.ProcessEnv }> = [];
  const fetch = vi.fn(async () => new Response(JSON.stringify({ status: "ready" }), { status: 200, headers: { "content-type": "application/json" } }));
  const command = options.command ?? { executable: "/opt/Bento/resources/bento-sidecar/bento-sidecar", prefixArguments: [] };
  const supervisor = new SidecarSupervisor({
    command,
    dataDir: options.dataDir,
    randomToken: () => "unguessable-per-launch-token-1234567890",
    fetch,
    delay: async () => undefined,
    batteryPercent: options.batteryPercent ?? (async () => null),
    batteryPollMs: 3_600_000,
    spawnProcess: (_executable, arguments_, spawnOptions) => {
      const child = new FakeChild();
      // The sidecar subcommand follows the launch command's prefix (`uv run bento-sidecar migrate`).
      const subcommand = arguments_[command.prefixArguments.length] ?? "";
      launches.push({ command: subcommand, env: spawnOptions.env });
      if (subcommand === "migrate") queueMicrotask(() => child.exit(0));
      if (subcommand === "api") queueMicrotask(() => child.stdout.write("BENTO_API_READY {\"port\":43127}\n"));
      return child;
    },
  });
  return { fetch, launches, supervisor };
}

describe("bundled llama-server location", () => {
  it("always uses the packaged binary in packaged builds and ignores the environment there", () => {
    const environment = { [LLAMA_SERVER_PATH_ENV]: "/tmp/evil-llama-server" };
    expect(resolveLlamaServerPath("/opt/Bento/resources", true, environment, "linux"))
      .toBe(path.join("/opt/Bento/resources", "llama-server", "llama-server"));
    expect(resolveLlamaServerPath("C:/Bento/resources", true, environment, "win32")).toMatch(/llama-server[\\/]llama-server\.exe$/u);
    expect(resolveLlamaServerPath("/opt/Bento/resources", false, environment, "linux")).toBe("/tmp/evil-llama-server");
    expect(resolveLlamaServerPath("/opt/Bento/resources", false, {}, "linux")).toBeNull();
  });

  it("derives the path from the packaged sidecar layout, not from uv development commands", () => {
    expect(llamaServerPathForCommand({ executable: path.join("/opt/Bento/resources", "bento-sidecar", "bento-sidecar"), prefixArguments: [] }, {}, "linux"))
      .toBe(path.join("/opt/Bento/resources", "llama-server", "llama-server"));
    expect(llamaServerPathForCommand({ executable: path.join("C:/Bento/resources", "bento-sidecar", "bento-sidecar.exe"), prefixArguments: [] }, {}, "win32"))
      .toMatch(/llama-server\.exe$/u);
    expect(llamaServerPathForCommand({ executable: "uv", prefixArguments: ["run", "--project", "/src/api", "bento-sidecar"] }, {}, "linux")).toBeNull();
    expect(llamaServerPathForCommand({ executable: "uv", prefixArguments: ["run"] }, { [LLAMA_SERVER_PATH_ENV]: "/dev/llama-server" }, "linux"))
      .toBe("/dev/llama-server");
  });

  it("passes BENTO_LLAMA_SERVER_PATH and the power state file to the worker, never an inherited value", async () => {
    const dataDir = await temporaryDirectory("bento-llama-env-");
    const previous = process.env[LLAMA_SERVER_PATH_ENV];
    process.env[LLAMA_SERVER_PATH_ENV] = "/tmp/inherited-llama-server";
    try {
      const { launches, supervisor } = supervisorWith({ dataDir });
      await supervisor.start();
      const worker = launches.find((launch) => launch.command === "worker")!;
      expect(worker.env[LLAMA_SERVER_PATH_ENV]).toBe(path.join("/opt/Bento/resources", "llama-server", llamaServerExecutable() as string));
      expect(worker.env[POWER_STATE_FILE_ENV]).toBe(path.join(dataDir, "run", "power.json"));
      for (const launch of launches) expect(launch.env[LLAMA_SERVER_PATH_ENV]).not.toBe("/tmp/inherited-llama-server");
      await supervisor.stop();

      const development = supervisorWith({ dataDir, command: { executable: "uv", prefixArguments: ["run", "bento-sidecar"] } });
      await development.supervisor.start();
      // Constructed while the variable was set: development honours an explicit override.
      expect(development.launches.find((launch) => launch.command === "worker")!.env[LLAMA_SERVER_PATH_ENV]).toBe("/tmp/inherited-llama-server");
      await development.supervisor.stop();
      delete process.env[LLAMA_SERVER_PATH_ENV];
      const plain = supervisorWith({ dataDir, command: { executable: "uv", prefixArguments: ["run", "bento-sidecar"] } });
      await plain.supervisor.start();
      expect(plain.launches.find((launch) => launch.command === "worker")!.env).not.toHaveProperty(LLAMA_SERVER_PATH_ENV);
      await plain.supervisor.stop();
    } finally {
      if (previous === undefined) delete process.env[LLAMA_SERVER_PATH_ENV];
      else process.env[LLAMA_SERVER_PATH_ENV] = previous;
      await rm(dataDir, { recursive: true, force: true });
    }
  });
});

describe("power state for smart search indexing", () => {
  it("records the existing power hook's reports for the worker, low below 20 %", async () => {
    const dataDir = await temporaryDirectory("bento-power-");
    let percent: number | null = 15;
    try {
      const { fetch, supervisor } = supervisorWith({ dataDir, batteryPercent: async () => percent });
      await supervisor.start();
      const file = path.join(dataDir, "run", "power.json");
      const report = async (onBattery: boolean): Promise<Record<string, unknown>> => {
        await supervisor.apiFetch("/api/backup/power", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ on_battery: onBattery }) });
        await supervisor.setPowerState(onBattery);
        return JSON.parse(await readFile(file, "utf8")) as Record<string, unknown>;
      };
      expect(await report(true)).toMatchObject({ on_battery: true, battery_percent: 15, low_battery: true });
      if (process.platform !== "win32") expect((await stat(file)).mode & 0o777).toBe(0o600);
      percent = 55;
      expect(await report(true)).toMatchObject({ on_battery: true, battery_percent: 55, low_battery: false });
      percent = null;
      // An unknown charge on battery counts as low: CPU-safe by default.
      expect(await report(true)).toMatchObject({ on_battery: true, battery_percent: null, low_battery: true });
      expect(await report(false)).toMatchObject({ on_battery: false, battery_percent: null, low_battery: false });
      // The request itself still reaches the API unchanged.
      expect(fetch).toHaveBeenCalledWith("http://127.0.0.1:43127/api/backup/power", expect.objectContaining({ method: "POST" }));
      await supervisor.stop();
    } finally {
      await rm(dataDir, { recursive: true, force: true });
    }
  });

  it("reads the system battery from sysfs and ignores peripherals", async () => {
    const root = await temporaryDirectory("bento-sysfs-");
    try {
      for (const [name, files] of Object.entries({
        AC: { type: "Mains" },
        BAT0: { type: "Battery", capacity: "18", scope: "System" },
        hidpp_battery_0: { type: "Battery", capacity: "3", scope: "Device" },
      })) {
        await mkdir(path.join(root, name));
        for (const [file, value] of Object.entries(files)) await writeFile(path.join(root, name, file), `${value}\n`);
      }
      expect(await readBatteryPercent("linux", root)).toBe(18);
      expect(await readBatteryPercent("linux", path.join(root, "missing"))).toBeNull();
      expect(await readBatteryPercent("win32", root)).toBeNull();
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});

describe("llama-server build scripts", () => {
  it("pin one llama.cpp tag and source digest in both scripts", async () => {
    const pin = await readLlamaPin() as Pin;
    expect(pin.tag).toBe("b12777");
    expect(pin.buildNumber).toBe("12777");
    expect(pin.sourceUrl).toBe("https://github.com/ggml-org/llama.cpp/archive/refs/tags/b12777.tar.gz");
    expect(pin.sourceSha256).toMatch(/^[0-9a-f]{64}$/u);
    const powershell = await readFile(path.join(repositoryRoot, "scripts", "build-llama-server.ps1"), "utf8");
    expect(powershell).toContain(`$LlamaCppTag = "${pin.tag}"`);
    expect(powershell).toContain(`$LlamaCppSourceSha256 = "${pin.sourceSha256}"`);
    expect(powershell).toContain(`$LlamaCppCommit = "${pin.commit}"`);
    for (const component of pin.components) expect(powershell).toContain(`"${component.name} | ${component.license} | ${component.where}"`);
    expect(pin.components.map((component) => component.name)).toEqual(expect.arrayContaining(["llama.cpp (ggml-org)", "cpp-httplib (yhirose)", "nlohmann/json (Niels Lohmann)"]));
  });

  it("build CPU-dispatching, offline-only servers and verify the source before extracting it", async () => {
    const shell = await readFile(path.join(repositoryRoot, "scripts", "build-llama-server.sh"), "utf8");
    const powershell = await readFile(path.join(repositoryRoot, "scripts", "build-llama-server.ps1"), "utf8");
    for (const script of [shell, powershell]) {
      for (const flag of ["-DGGML_BACKEND_DL=ON", "-DGGML_NATIVE=OFF", "-DGGML_CPU_ALL_VARIANTS=ON", "-DLLAMA_OPENSSL=OFF", "-DLLAMA_USE_PREBUILT_UI=OFF", "-DLLAMA_BUILD_TESTS=OFF", "-DLLAMA_BUILD_EXAMPLES=OFF", "-DGGML_OPENMP=OFF"]) {
        expect(script).toContain(flag);
      }
      expect(script).toContain("--target llama-server");
      expect(script).toMatch(/source digest mismatch/u);
      expect(script).toContain("SHA256SUMS");
      expect(script).toContain("bento-llama-server.json");
    }
    // The digest check comes before tar ever sees the archive.
    expect(shell.indexOf("source digest mismatch")).toBeLessThan(shell.indexOf("tar -xzf"));
    expect(powershell.indexOf("source digest mismatch")).toBeLessThan(powershell.indexOf("tar.exe -xzf"));
    expect(shell).toContain("dist/llama-server/$TARGET");
    expect(shell).toContain("-DCMAKE_INSTALL_RPATH='$ORIGIN'");
    expect(shell).toContain("-DCMAKE_INSTALL_RPATH='@loader_path'");
    expect(shell).toContain("-DGGML_METAL=ON");
    expect(powershell).toContain('dist\\llama-server\\$Target');
    expect(powershell).toContain("-DGGML_CPU_ALL_VARIANTS=OFF");
    const { stdout } = await run("bash", [path.join(repositoryRoot, "scripts", "build-llama-server.sh"), "--print-target"]).catch(() => ({ stdout: "" }));
    if (process.platform !== "win32") expect(stdout.trim()).toBe(`${process.platform}-${process.arch}`);
  });

  it("put the output in a predictable per-platform folder", () => {
    expect(llamaBuildOutput("linux", "x64", {})).toBe(path.join(repositoryRoot, "dist", "llama-server", "linux-x64"));
    expect(llamaBuildOutput("win32", "arm64", {})).toBe(path.join(repositoryRoot, "dist", "llama-server", "win32-arm64"));
    expect(llamaBuildOutput("darwin", "arm64", { BENTO_LLAMA_SERVER_DIR: "/prebuilt" })).toBe(path.resolve("/prebuilt"));
  });
});

describe("llama-server bundle verification", () => {
  it("accepts a bundle built from the pin for this target and rejects tampering", async () => {
    const root = await temporaryDirectory("bento-llama-bundle-");
    try {
      const pin = await readLlamaPin() as Pin;
      const directory = await fakeBundle(root, pin);
      expect(await checkLlamaBundle(directory, { pin })).toEqual([]);
      const library = path.join(directory, process.platform === "win32" ? "ggml-cpu-haswell.dll" : "libggml-cpu-haswell.so");
      await writeFile(library, "tampered backend");
      expect((await checkLlamaBundle(directory, { pin })).join("\n")).toMatch(/does not match its SHA-256/u);
      // Code-signed packages rewrite binaries; presence and pin are still enforced there.
      expect(await checkLlamaBundle(directory, { pin, compareHashes: false })).toEqual([]);
      await writeFile(path.join(directory, "unlisted.so"), "extra");
      expect((await checkLlamaBundle(directory, { pin, compareHashes: false })).join("\n")).toMatch(/unlisted\.so is not listed/u);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("rejects another tag, another source digest or another target", async () => {
    const root = await temporaryDirectory("bento-llama-pin-");
    try {
      const pin = await readLlamaPin() as Pin;
      const otherTarget = process.arch === "x64" ? `${process.platform}-arm64` : `${process.platform}-x64`;
      const wrongTarget = await fakeBundle(path.join(root, "a"), pin, otherTarget);
      expect((await checkLlamaBundle(wrongTarget, { pin })).join("\n")).toContain(`built for ${otherTarget}`);
      const stale = await fakeBundle(path.join(root, "b"), { ...pin, tag: "b11454", sourceSha256: "0".repeat(64) });
      const problems = (await checkLlamaBundle(stale, { pin })).join("\n");
      expect(problems).toContain("built from b11454");
      expect(problems).toContain("another digest");
      await rm(path.join(stale, llamaServerExecutable() as string));
      expect((await checkLlamaBundle(stale, { pin })).join("\n")).toMatch(/missing or not executable/u);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("parses SHA256SUMS strictly", async () => {
    const digest = createHash("sha256").update("x").digest("hex");
    expect(parseChecksums(`${digest}  llama-server\n${digest}  licenses/LICENSE-llama.cpp\n`).get("licenses/LICENSE-llama.cpp")).toBe(digest);
    expect(() => parseChecksums(`${digest}  ../escape\n`)).toThrow(/unsafe path/u);
    expect(() => parseChecksums(`${digest}  /etc/passwd\n`)).toThrow(/unsafe path/u);
    expect(() => parseChecksums("not a checksum line\n")).toThrow();
    expect(() => parseChecksums(`${digest}  a\n${digest}  a\n`)).toThrow(/twice/u);
    const root = await temporaryDirectory("bento-sums-");
    try {
      await writeFile(path.join(root, "a"), "x");
      await writeChecksums(root);
      expect(await checkChecksums(root)).toEqual([]);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});

describe("desktop packaging includes llama-server", () => {
  it("ships llama-server as an extra resource next to bento-sidecar", async () => {
    const forgeSource = await readFile(path.join(desktopRoot, "forge.config.cjs"), "utf8");
    expect(forgeSource).toContain('path.join(sidecarBundle, "llama-server")');
    expect(forgeSource).toMatch(/trayIcons\]\.concat\(llamaServer\)/u);
    expect(forgeSource).toContain('process.env.BENTO_SKIP_LLAMA_SERVER === "1"');
    const buildSidecar = await readFile(path.join(desktopRoot, "scripts", "build-sidecar.mjs"), "utf8");
    expect(buildSidecar).toContain("build-llama-server.sh");
    expect(buildSidecar).toContain("build-llama-server.ps1");
    expect(buildSidecar).toContain("checkLlamaBundle");
  });

  it("verifies the packaged llama-server hash and signature, and smoke-runs --version", async () => {
    const verify = await readFile(path.join(desktopRoot, "scripts", "verify-artifacts.mjs"), "utf8");
    expect(verify).toContain("The platform-native llama-server is missing from the package");
    expect(verify).toContain("checkLlamaBundle(directory, { pin, compareHashes: !signed })");
    expect(verify).toContain("codesign");
    expect(verify).toContain("Get-AuthenticodeSignature");
    const smoke = await readFile(path.join(desktopRoot, "scripts", "smoke-packaged.mjs"), "utf8");
    expect(smoke).toContain('spawn(llamaServer, ["--version"]');
    expect(smoke).toContain("pin.buildNumber");
    expect(smoke).toContain('"Resources"');
  });

  it("lists llama.cpp and its vendored components in the SBOM", async () => {
    const root = await temporaryDirectory("bento-llama-sbom-");
    try {
      const output = path.join(root, "bento.cdx.json");
      await run(process.execPath, [path.join(desktopRoot, "scripts", "generate-sbom.mjs"), output]);
      const bom = JSON.parse(await readFile(output, "utf8")) as { components: Array<Record<string, unknown>> };
      const llama = bom.components.find((component) => component.name === "llama.cpp") as {
        version: string; purl: string; licenses: unknown[]; hashes: Array<{ content: string }>; components: Array<{ name: string }>;
      } | undefined;
      const pin = await readLlamaPin() as Pin;
      expect(llama?.version).toBe(pin.tag);
      expect(llama?.purl).toBe(`pkg:github/ggml-org/llama.cpp@${pin.tag}`);
      expect(llama?.licenses).toEqual([{ license: { id: "MIT" } }]);
      expect(llama?.hashes[0]?.content).toBe(pin.sourceSha256);
      expect(llama?.components.map((component) => component.name)).toContain("cpp-httplib (yhirose)");
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("bundles the sqlite-vec extension (guarded) and, for the CLI, llama-server", async () => {
    const sidecarSpec = await readFile(path.join(repositoryRoot, "apps", "api", "packaging", "bento-sidecar.spec"), "utf8");
    const cliSpec = await readFile(path.join(repositoryRoot, "apps", "api", "packaging", "bento-cli.spec"), "utf8");
    for (const spec of [sidecarSpec, cliSpec]) {
      expect(spec).toContain('collect_dynamic_libs("sqlite_vec"');
      expect(spec).toContain('importlib.util.find_spec("sqlite_vec") is not None');
    }
    expect(cliSpec).toContain('Path("llama-server")');
    expect(cliSpec).toContain("BENTO_REQUIRE_LLAMA_SERVER");
    expect(sidecarSpec).not.toContain("llama-server");
  });

  it("builds llama-server into the Docker image from the same script", async () => {
    const dockerfile = await readFile(path.join(repositoryRoot, "docker", "api.Dockerfile"), "utf8");
    expect(dockerfile).toContain("AS llama-server-build");
    expect(dockerfile).toContain("scripts/build-llama-server.sh");
    expect(dockerfile).toContain("COPY --from=llama-server /opt/llama-server /opt/llama-server");
    expect(dockerfile).toContain("BENTO_LLAMA_SERVER_PATH=/opt/llama-server/llama-server");
    const compose = await readFile(path.join(repositoryRoot, "docker-compose.yml"), "utf8");
    expect(compose.match(/LLAMA_SERVER_STAGE: \$\{LLAMA_SERVER_STAGE:-llama-server-build\}/gu)).toHaveLength(2);
  });
});
