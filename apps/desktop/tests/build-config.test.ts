import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  buildConfigRedactions,
  loadBuildConfig,
  parseBuildConfig,
  sidecarRuntimeEnvironment,
} from "../src/main/build-config";

const roots: string[] = [];
const VALID = {
  BENTO_TELEGRAM_API_ID: "1234567",
  BENTO_TELEGRAM_API_HASH: "0123456789abcdef0123456789abcdef",
  BENTO_RELAY_URL: "wss://bento-relay.example.workers.dev",
  BENTO_PUBLIC_SITE_URL: "https://bento.example",
};

async function resources(contents?: string): Promise<string> {
  const root = await mkdtemp(path.join(os.tmpdir(), "bento-build-config-"));
  roots.push(root);
  if (contents !== undefined) await writeFile(path.join(root, "build-config.json"), contents);
  return root;
}

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

describe("desktop build configuration", () => {
  it("parses the four known keys and omits absent values", () => {
    expect(parseBuildConfig(VALID, { allowLoopbackInsecure: false })).toEqual({ config: VALID, rejected: [] });
    expect(parseBuildConfig({ BENTO_RELAY_URL: VALID.BENTO_RELAY_URL }, { allowLoopbackInsecure: false })).toEqual({
      config: { BENTO_RELAY_URL: VALID.BENTO_RELAY_URL },
      rejected: [],
    });
    expect(parseBuildConfig({ BENTO_TELEGRAM_API_ID: "" }, { allowLoopbackInsecure: false })).toEqual({ config: {}, rejected: [] });
  });

  it.each([
    ["BENTO_TELEGRAM_API_ID", "abc"],
    ["BENTO_TELEGRAM_API_ID", "0123"],
    ["BENTO_TELEGRAM_API_HASH", "short"],
    ["BENTO_TELEGRAM_API_HASH", "zz23456789abcdef0123456789abcdef"],
    ["BENTO_RELAY_URL", "ws://relay.example"],
    ["BENTO_RELAY_URL", "wss://user:pass@relay.example"],
    ["BENTO_RELAY_URL", "javascript:alert(1)"],
    ["BENTO_PUBLIC_SITE_URL", "http://bento.example"],
    ["BENTO_PUBLIC_SITE_URL", "https://bento.example/?next=evil"],
    ["BENTO_PUBLIC_SITE_URL", "https://bento.example\nInjected: 1"],
  ])("rejects invalid %s values without echoing them", (key, value) => {
    const result = parseBuildConfig({ [key]: value }, { allowLoopbackInsecure: false });
    expect(result.config).toEqual({});
    expect(result.rejected).toEqual([key]);
    expect(JSON.stringify(result)).not.toContain(value);
  });

  it("ignores unknown keys and non-object documents", () => {
    expect(parseBuildConfig({ STORAGE_BACKEND: "fake", ...VALID }, { allowLoopbackInsecure: false })).toEqual({
      config: VALID,
      rejected: ["STORAGE_BACKEND"],
    });
    expect(parseBuildConfig(["x"], { allowLoopbackInsecure: false })).toEqual({ config: {}, rejected: ["_document"] });
  });

  it("allows loopback ws/http only for unpackaged development runs", () => {
    const local = { BENTO_RELAY_URL: "ws://127.0.0.1:8787", BENTO_PUBLIC_SITE_URL: "http://localhost:4321" };
    expect(parseBuildConfig(local, { allowLoopbackInsecure: true }).config).toEqual(local);
    expect(parseBuildConfig(local, { allowLoopbackInsecure: false }).config).toEqual({});
    expect(parseBuildConfig({ BENTO_RELAY_URL: "ws://relay.example" }, { allowLoopbackInsecure: true }).config).toEqual({});
  });

  it("reads only the packaged resource file in packaged builds", async () => {
    const root = await resources(JSON.stringify(VALID));
    const result = await loadBuildConfig({ packaged: true, resourcesPath: root, environment: { BENTO_RELAY_URL: "wss://other.example" } });
    expect(result).toEqual({ config: VALID, rejected: [], source: "packaged" });
  });

  it("treats a missing, malformed, or oversized packaged file as empty configuration", async () => {
    await expect(loadBuildConfig({ packaged: true, resourcesPath: await resources(), environment: {} })).resolves.toEqual({ config: {}, rejected: [], source: "packaged" });
    await expect(loadBuildConfig({ packaged: true, resourcesPath: await resources("{not json"), environment: {} })).resolves.toMatchObject({ config: {}, rejected: ["_document"] });
    const huge = JSON.stringify({ BENTO_RELAY_URL: `wss://relay.example/${"a".repeat(70_000)}` });
    await expect(loadBuildConfig({ packaged: true, resourcesPath: await resources(huge), environment: {} })).resolves.toMatchObject({ config: {}, rejected: ["_document"] });
  });

  it("reads the same variables from the parent environment in development", async () => {
    const result = await loadBuildConfig({
      packaged: false,
      resourcesPath: "/nonexistent",
      environment: { ...VALID, BENTO_RELAY_URL: "ws://localhost:8787", UNRELATED: "x" },
    });
    expect(result).toEqual({ config: { ...VALID, BENTO_RELAY_URL: "ws://localhost:8787" }, rejected: [], source: "environment" });
  });

  it("forwards build values to sidecars and strips inherited or invalid overrides", () => {
    const packaged = sidecarRuntimeEnvironment({
      packaged: true,
      buildConfig: { BENTO_TELEGRAM_API_ID: VALID.BENTO_TELEGRAM_API_ID },
      environment: { BENTO_TELEGRAM_API_HASH: "inherited", STORAGE_BACKEND: "fake", BENTO_DEV_STORAGE_BACKEND: "fake" },
    });
    expect(packaged.set).toEqual({ BENTO_TELEGRAM_API_ID: VALID.BENTO_TELEGRAM_API_ID, ENVIRONMENT: "production" });
    expect(packaged.strip).toEqual(expect.arrayContaining([
      "BENTO_DEVICE_WRAPPING_KEY",
      "BENTO_DEV_STORAGE_BACKEND",
      "BENTO_TELEGRAM_API_HASH",
      "BENTO_RELAY_URL",
      "BENTO_PUBLIC_SITE_URL",
      "STORAGE_BACKEND",
    ]));
    expect(packaged.strip).not.toContain("BENTO_TELEGRAM_API_ID");
  });

  it("runs packaged builds as production so the simulated Telegram cloud can never be selected", () => {
    const packaged = sidecarRuntimeEnvironment({ packaged: true, buildConfig: VALID, environment: { ENVIRONMENT: "local", BENTO_DEV_STORAGE_BACKEND: "fake" } });
    expect(packaged.set.ENVIRONMENT).toBe("production");
    expect(packaged.set).not.toHaveProperty("STORAGE_BACKEND");
    expect(packaged.strip).toContain("BENTO_DEV_STORAGE_BACKEND");
  });

  it("forwards STORAGE_BACKEND=fake only for unpackaged runs and keeps their environment", () => {
    const development = sidecarRuntimeEnvironment({ packaged: false, buildConfig: {}, environment: { BENTO_DEV_STORAGE_BACKEND: "fake", ENVIRONMENT: "local" } });
    expect(development.set).toEqual({ STORAGE_BACKEND: "fake" });
    expect(development.strip).not.toContain("ENVIRONMENT");
    expect(sidecarRuntimeEnvironment({ packaged: false, buildConfig: {}, environment: { BENTO_DEV_STORAGE_BACKEND: "telegram" } }).set).toEqual({});
    expect(sidecarRuntimeEnvironment({ packaged: false, buildConfig: {}, environment: { STORAGE_BACKEND: "fake" } }).strip).not.toContain("STORAGE_BACKEND");
  });

  it("redacts the API hash from desktop logs", () => {
    expect(buildConfigRedactions(VALID)).toEqual([VALID.BENTO_TELEGRAM_API_HASH]);
    expect(buildConfigRedactions({})).toEqual([]);
  });
});
