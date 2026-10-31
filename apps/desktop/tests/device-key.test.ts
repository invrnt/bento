import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  DEVICE_WRAPPING_KEY_NAME,
  DeviceKeyUnavailableError,
  fileWrappingKeyPath,
  provisionDeviceWrappingKey,
  validWrappingKey,
} from "../src/main/device-key";
import { SecureSecretStore } from "../src/main/secrets";

const roots: string[] = [];

async function fixture(available = true, backend = "gnome_libsecret") {
  const root = await mkdtemp(path.join(os.tmpdir(), "bento-device-key-"));
  roots.push(root);
  const storage = {
    available,
    isAsyncEncryptionAvailable: vi.fn(async () => storage.available),
    encryptStringAsync: vi.fn(async (value: string) => Buffer.from(`sealed:${Buffer.from(value).toString("hex")}`)),
    decryptStringAsync: vi.fn(async (value: Buffer) => ({
      result: Buffer.from(value.toString().replace(/^sealed:/u, ""), "hex").toString(),
      shouldReEncrypt: false,
    })),
    getSelectedStorageBackend: vi.fn(() => backend),
  };
  const secretsFile = path.join(root, "desktop", "secrets.json");
  const dataDir = path.join(root, "data");
  return { root, storage, secretsFile, dataDir, store: new SecureSecretStore(secretsFile, storage, "linux") };
}

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

describe("device wrapping key provisioning", () => {
  it("generates 32 random bytes once, stores them OS-encrypted, and reuses them", async () => {
    const { store, secretsFile, dataDir } = await fixture();
    const random = vi.fn((size: number) => Buffer.alloc(size, 0xab));
    const first = await provisionDeviceWrappingKey({ store, dataDir, random });
    expect(first.secureStorage).toBe("os");
    expect(first.generated).toBe(true);
    expect(random).toHaveBeenCalledWith(32);
    expect(first.key).toBe(Buffer.alloc(32, 0xab).toString("base64url"));
    expect(first.key).toMatch(/^[A-Za-z0-9_-]{43}$/u);
    expect(first.key).not.toContain("=");
    expect(await readFile(secretsFile, "utf8")).not.toContain(first.key!);

    const second = await provisionDeviceWrappingKey({ store, dataDir, random });
    expect(second).toEqual({ key: first.key, secureStorage: "os", generated: false });
    expect(random).toHaveBeenCalledTimes(1);
  });

  it("uses the backend key file when secure storage is unavailable", async () => {
    for (const [available, backend] of [[false, "gnome_libsecret"], [true, "basic_text"]] as const) {
      const { store, dataDir, storage } = await fixture(available, backend);
      const random = vi.fn((size: number) => Buffer.alloc(size, 1));
      await expect(provisionDeviceWrappingKey({ store, dataDir, random })).resolves.toEqual({ secureStorage: "file", generated: false });
      expect(random).not.toHaveBeenCalled();
      expect(storage.encryptStringAsync).not.toHaveBeenCalled();
    }
  });

  it("keeps a data directory that already uses the backend key file in file mode", async () => {
    const { store, dataDir } = await fixture();
    await mkdir(path.dirname(fileWrappingKeyPath(dataDir)), { recursive: true });
    await writeFile(fileWrappingKeyPath(dataDir), "existing file key");
    const random = vi.fn((size: number) => Buffer.alloc(size, 1));
    await expect(provisionDeviceWrappingKey({ store, dataDir, random })).resolves.toEqual({ secureStorage: "file", generated: false });
    expect(random).not.toHaveBeenCalled();
    expect(await store.hasInternal(DEVICE_WRAPPING_KEY_NAME)).toBe(false);
  });

  it("fails closed instead of switching keys when a stored key cannot be unlocked", async () => {
    const { store, dataDir, storage } = await fixture();
    await provisionDeviceWrappingKey({ store, dataDir });
    storage.available = false;
    await expect(provisionDeviceWrappingKey({ store, dataDir })).rejects.toMatchObject({ code: "device_key_store_unavailable" });
    storage.available = true;
    storage.decryptStringAsync.mockRejectedValueOnce(new Error("keychain reset"));
    await expect(provisionDeviceWrappingKey({ store, dataDir })).rejects.toBeInstanceOf(DeviceKeyUnavailableError);
  });

  it("rejects a corrupted stored key", async () => {
    const { store, dataDir } = await fixture();
    await store.writeInternal(DEVICE_WRAPPING_KEY_NAME, "too-short");
    await expect(provisionDeviceWrappingKey({ store, dataDir })).rejects.toMatchObject({ code: "device_key_invalid" });
    expect(validWrappingKey(Buffer.alloc(32).toString("base64url"))).toBe(true);
    expect(validWrappingKey(Buffer.alloc(31).toString("base64url"))).toBe(false);
    expect(validWrappingKey(`${Buffer.alloc(32).toString("base64")}`)).toBe(false);
  });
});
