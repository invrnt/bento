import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LEGACY_SECRET_SETTING_KEYS, SecureSecretStore } from "../src/main/secrets";

const temporaryDirectories: string[] = [];

async function secretPath(): Promise<string> {
  const directory = await mkdtemp(path.join(os.tmpdir(), "bento-secret-test-"));
  temporaryDirectories.push(directory);
  return path.join(directory, "secrets.json");
}

function fakeSafeStorage(available = true, backend = "kwallet") {
  return {
    isAsyncEncryptionAvailable: vi.fn(async () => available),
    encryptStringAsync: vi.fn(async (value: string) => Buffer.from(`cipher:${value}`, "utf8")),
    decryptStringAsync: vi.fn(async (value: Buffer) => ({
      result: value.toString("utf8").replace(/^cipher:/u, ""),
      shouldReEncrypt: false,
    })),
    getSelectedStorageBackend: vi.fn(() => backend),
  };
}

afterEach(async () => {
  await Promise.all(temporaryDirectories.splice(0).map((directory) => rm(directory, { recursive: true, force: true })));
});

describe("OS-backed secure secret storage", () => {
  it("fails closed when encryption is unavailable without writing plaintext", async () => {
    const file = await secretPath();
    const storage = fakeSafeStorage(false);
    const store = new SecureSecretStore(file, storage, "darwin");

    await expect(store.prepare({ sample_token: { operation: "set", value: "plaintext-token" } })).rejects.toThrow(
      /unavailable/i,
    );
    await expect(readFile(file, "utf8")).rejects.toMatchObject({ code: "ENOENT" });
    expect(storage.encryptStringAsync).not.toHaveBeenCalled();
  });

  it("rejects Linux basic_text as an insecure fallback", async () => {
    const file = await secretPath();
    const storage = fakeSafeStorage(true, "basic_text");
    const store = new SecureSecretStore(file, storage, "linux");
    await expect(store.available()).resolves.toBe(false);
    await expect(store.prepare({ token: { operation: "set", value: "secret" } })).rejects.toThrow(/unavailable/i);
  });

  it("persists only encrypted payloads and opaque references", async () => {
    const file = await secretPath();
    const storage = fakeSafeStorage();
    const store = new SecureSecretStore(file, storage, "linux");
    const prepared = await store.prepare({ sample_token: { operation: "set", value: "plaintext-token" } });

    expect(prepared.references.sample_token).toMatchObject({ configured: true });
    expect(prepared.references.sample_token?.reference).toMatch(/^desktop-secret:/u);
    expect(prepared.values).toEqual({ sample_token: "plaintext-token" });
    await prepared.commit();

    const raw = await readFile(file, "utf8");
    expect(raw).not.toContain("plaintext-token");
    expect(raw).toContain(Buffer.from("cipher:plaintext-token").toString("base64"));
    await expect(store.values()).resolves.toEqual({ sample_token: "plaintext-token" });
    await expect(store.references()).resolves.toEqual({
      sample_token: prepared.references.sample_token?.reference,
    });
  });

  it("supports transactional rollback for rotation and clear mutations", async () => {
    const file = await secretPath();
    const store = new SecureSecretStore(file, fakeSafeStorage(), "darwin");
    const initial = await store.prepare({ token: { operation: "set", value: "first-value" } });
    await initial.commit();

    const changed = await store.prepare({
      token: { operation: "set", value: "second-value" },
      absent: { operation: "clear" },
    });
    expect(changed.references.token?.reference).toBe(initial.references.token?.reference);
    expect(changed.references.absent).toEqual({ reference: null, configured: false });
    await changed.commit();
    await expect(store.values()).resolves.toEqual({ token: "second-value" });
    await changed.rollback();
    await expect(store.values()).resolves.toEqual({ token: "first-value" });
  });

  it("rejects malformed secret metadata rather than treating it as empty", async () => {
    const file = await secretPath();
    const { writeFile } = await import("node:fs/promises");
    await writeFile(file, JSON.stringify({ version: 1, secrets: { token: { reference: "raw", encrypted: "" } } }));
    const store = new SecureSecretStore(file, fakeSafeStorage(), "darwin");
    await expect(store.references()).rejects.toThrow(/invalid/i);
  });

  it("keeps internal desktop material separate from settings secrets and their references", async () => {
    const file = await secretPath();
    const storage = fakeSafeStorage();
    const store = new SecureSecretStore(file, storage, "darwin");
    await store.writeInternal("device-wrapping-key", "internal-key-material");
    const prepared = await store.prepare({ sample_token: { operation: "set", value: "setting-secret" } });
    await prepared.commit();

    expect(await store.hasInternal("device-wrapping-key")).toBe(true);
    await expect(store.readInternal("device-wrapping-key")).resolves.toBe("internal-key-material");
    await expect(store.values()).resolves.toEqual({ sample_token: "setting-secret" });
    expect(Object.keys(await store.references())).toEqual(["sample_token"]);
    expect(await readFile(file, "utf8")).not.toContain("internal-key-material");

    // Rolling back a settings transaction never drops internal entries.
    await prepared.rollback();
    await expect(store.readInternal("device-wrapping-key")).resolves.toBe("internal-key-material");
    await expect(store.values()).resolves.toEqual({});
  });

  it("rejects internal names that could collide with settings keys or paths", async () => {
    const store = new SecureSecretStore(await secretPath(), fakeSafeStorage(), "darwin");
    for (const name of ["device_wrapping_key", "../key", "Device-Key", ""]) {
      await expect(store.writeInternal(name, "value")).rejects.toThrow(TypeError);
    }
  });

  it("deletes legacy Bot API secrets on startup without decrypting or needing the OS store", async () => {
    const file = await secretPath();
    const writer = new SecureSecretStore(file, fakeSafeStorage(), "darwin");
    const mutations = Object.fromEntries([...LEGACY_SECRET_SETTING_KEYS, "kept_secret"].map((key) => [key, { operation: "set" as const, value: `value-${key}` }]));
    await (await writer.prepare(mutations)).commit();
    await writer.writeInternal("device-wrapping-key", "internal");

    const lockedStorage = fakeSafeStorage(false);
    const store = new SecureSecretStore(file, lockedStorage, "darwin");
    await expect(store.removeSecrets(LEGACY_SECRET_SETTING_KEYS)).resolves.toBe(LEGACY_SECRET_SETTING_KEYS.length);
    expect(lockedStorage.decryptStringAsync).not.toHaveBeenCalled();
    expect(Object.keys(await store.references())).toEqual(["kept_secret"]);
    expect(await store.hasInternal("device-wrapping-key")).toBe(true);
    await expect(store.removeSecrets(LEGACY_SECRET_SETTING_KEYS)).resolves.toBe(0);
    const raw = await readFile(file, "utf8");
    for (const key of LEGACY_SECRET_SETTING_KEYS) expect(raw).not.toContain(key);
  });
});
