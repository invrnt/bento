import { cp, mkdir, rm } from "node:fs/promises";
import { spawn } from "node:child_process";
import { resolve } from "node:path";
import {
  checkLlamaBundle,
  LLAMA_RESOURCE_DIR,
  LLAMA_SERVER_DIR_ENV,
  llamaBuildOutput,
  readLlamaPin,
  repositoryRoot,
  SKIP_LLAMA_SERVER_ENV,
  skipLlamaServer,
} from "./llama-server.mjs";

const output = resolve(import.meta.dirname, `../resources/sidecars/${process.platform}-${process.arch}`);
await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });

await run("uv", [
  "run", "--project", resolve(import.meta.dirname, "../../api"), "--extra", "desktop",
  "python", resolve(import.meta.dirname, "../../api/scripts/build_desktop_sidecar.py"), "--output", output,
]);
await rm(resolve(output, ".pyinstaller-work"), { recursive: true, force: true });

// llama-server ships next to bento-sidecar (forge extraResource); Bento never downloads executables.
if (skipLlamaServer()) {
  console.warn(`${SKIP_LLAMA_SERVER_ENV}=1: packaging without llama-server (smart search will report a runtime error)`);
} else {
  const source = llamaBuildOutput();
  if (!process.env[LLAMA_SERVER_DIR_ENV]) {
    // The build script is a no-op when its cached output already matches the pin and flags.
    if (process.platform === "win32") {
      await run("powershell", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", resolve(repositoryRoot, "scripts", "build-llama-server.ps1"), "-Out", source]);
    } else {
      await run("bash", [resolve(repositoryRoot, "scripts", "build-llama-server.sh"), "--out", source]);
    }
  }
  const pin = await readLlamaPin();
  const problems = await checkLlamaBundle(source, { pin });
  if (problems.length) throw new Error(`llama-server build output is not usable:\n  - ${problems.join("\n  - ")}`);
  const destination = resolve(output, LLAMA_RESOURCE_DIR);
  await cp(source, destination, { recursive: true, verbatimSymlinks: false });
  const copied = await checkLlamaBundle(destination, { pin });
  if (copied.length) throw new Error(`llama-server copy is corrupt:\n  - ${copied.join("\n  - ")}`);
}

async function run(command, args) {
  const child = spawn(command, args, { stdio: "inherit" });
  const exitCode = await new Promise((resolveExit, reject) => {
    child.once("error", reject);
    child.once("exit", (code) => resolveExit(code ?? 1));
  });
  if (exitCode !== 0) process.exit(exitCode);
}
