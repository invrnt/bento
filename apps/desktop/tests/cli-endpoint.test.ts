import { mkdtemp, readdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CLI_ENDPOINT_FILE, CliEndpointFile, cliEndpointDocument } from "../src/main/cli-endpoint";

const TOKEN = "cli-token-abcdefghijklmnopqrstuvwxyz-0123456789";
let root: string;

beforeEach(async () => {
  root = await mkdtemp(path.join(os.tmpdir(), "bento-cli-endpoint-"));
});

afterEach(async () => {
  await rm(root, { recursive: true, force: true });
});

function endpointFile(warn = vi.fn()) {
  const directory = path.join(root, "bento-desktop");
  const file = new CliEndpointFile({
    directory,
    pid: 4242,
    appVersion: "0.3.0",
    now: () => new Date("2026-11-23T10:00:00.000Z"),
    warn,
  });
  return { directory, file, warn };
}

describe("desktop CLI endpoint file", () => {
  it("matches the documented schema", () => {
    expect(cliEndpointDocument({ port: 53211, cliToken: TOKEN }, { pid: 4242, appVersion: "0.3.0", startedAt: new Date("2026-11-23T10:00:00.000Z") }))
      .toEqual({
        version: 1,
        kind: "desktop",
        url: "http://127.0.0.1:53211",
        token: TOKEN,
        pid: 4242,
        app_version: "0.3.0",
        started_at: "2026-11-23T10:00:00.000Z",
      });
  });

  it("writes atomically with owner-only permissions and leaves no temporary files", async () => {
    const { directory, file } = endpointFile();
    await file.update({ port: 53211, cliToken: TOKEN });
    expect(file.filePath).toBe(path.join(directory, CLI_ENDPOINT_FILE));
    const document = JSON.parse(await readFile(file.filePath, "utf8")) as Record<string, unknown>;
    expect(document).toMatchObject({ version: 1, kind: "desktop", url: "http://127.0.0.1:53211", token: TOKEN, pid: 4242 });
    if (process.platform !== "win32") {
      expect((await stat(file.filePath)).mode & 0o777).toBe(0o600);
      expect((await stat(directory)).mode & 0o077).toBe(0);
    }
    expect(await readdir(directory)).toEqual([CLI_ENDPOINT_FILE]);
  });

  it("replaces the previous endpoint and removes it when the API goes away", async () => {
    const { file } = endpointFile();
    await file.publish({ port: 53211, cliToken: TOKEN });
    void file.update({ port: 53212, cliToken: `${TOKEN}-next` });
    void file.update(null);
    void file.update({ port: 53213, cliToken: `${TOKEN}-last` });
    await file.flush();
    expect(JSON.parse(await readFile(file.filePath, "utf8"))).toMatchObject({ url: "http://127.0.0.1:53213", token: `${TOKEN}-last` });
    await file.update(null);
    await expect(stat(file.filePath)).rejects.toMatchObject({ code: "ENOENT" });
    // Removing an absent file is not an error.
    await expect(file.remove()).resolves.toBeUndefined();
  });

  it("reports failures without the token and keeps working afterwards", async () => {
    const warn = vi.fn();
    const blocker = path.join(root, "not-a-directory");
    await writeFile(blocker, "x");
    const file = new CliEndpointFile({ directory: path.join(blocker, "bento-desktop"), pid: 1, appVersion: "0.3.0", warn });
    await file.publish({ port: 53211, cliToken: TOKEN });
    expect(warn).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(warn.mock.calls)).not.toContain(TOKEN);
    // The queue survives the failure.
    await expect(file.flush()).resolves.toBeUndefined();
    const { file: healthy } = endpointFile();
    await expect(healthy.publish({ port: 1, cliToken: TOKEN })).resolves.toBeUndefined();
  });
});
