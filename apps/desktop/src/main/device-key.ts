import { randomBytes } from "node:crypto";
import { access } from "node:fs/promises";
import path from "node:path";
import { SecureStorageMode } from "../shared/contracts";

/** Reserved internal name in the secure store; it can never collide with a settings key. */
export const DEVICE_WRAPPING_KEY_NAME = "device-wrapping-key";
export const DEVICE_WRAPPING_KEY_ENV = "BENTO_DEVICE_WRAPPING_KEY";
const KEY_BYTES = 32;
const BASE64URL_KEY = /^[A-Za-z0-9_-]{43}$/u;

export interface InternalSecretStore {
  available(): Promise<boolean>;
  hasInternal(name: string): Promise<boolean>;
  readInternal(name: string): Promise<string | null>;
  writeInternal(name: string, value: string): Promise<void>;
}

export interface DeviceKeyProvision {
  /** base64url (no padding) 32-byte key; absent in file mode. */
  key?: string;
  secureStorage: SecureStorageMode;
  generated: boolean;
}

export class DeviceKeyUnavailableError extends Error {
  constructor(readonly code: "device_key_store_unavailable" | "device_key_invalid") {
    super(code === "device_key_store_unavailable"
      ? "The operating system secure store is unavailable, so Bento cannot unlock this device's keys"
      : "The stored device key is invalid");
  }
}

export interface ProvisionOptions {
  store: InternalSecretStore;
  dataDir: string;
  random?: (size: number) => Buffer;
  exists?: (filePath: string) => Promise<boolean>;
}

/**
 * Returns the device wrapping key for the API/worker environment.
 *
 * - A stored OS-protected key is always reused; if the OS store is unavailable startup fails closed
 *   instead of letting the backend silently switch keys.
 * - A data directory already using the backend's 0600 key file stays in file mode.
 * - Otherwise a new random key is generated when the OS store is available.
 */
export async function provisionDeviceWrappingKey(options: ProvisionOptions): Promise<DeviceKeyProvision> {
  const exists = options.exists ?? fileExists;
  if (await options.store.hasInternal(DEVICE_WRAPPING_KEY_NAME)) {
    if (!(await options.store.available())) throw new DeviceKeyUnavailableError("device_key_store_unavailable");
    let stored: string | null;
    try {
      stored = await options.store.readInternal(DEVICE_WRAPPING_KEY_NAME);
    } catch {
      throw new DeviceKeyUnavailableError("device_key_store_unavailable");
    }
    if (!stored || !validWrappingKey(stored)) throw new DeviceKeyUnavailableError("device_key_invalid");
    return { key: stored, secureStorage: "os", generated: false };
  }
  if (await exists(fileWrappingKeyPath(options.dataDir))) return { secureStorage: "file", generated: false };
  if (!(await options.store.available())) return { secureStorage: "file", generated: false };
  const bytes = (options.random ?? randomBytes)(KEY_BYTES);
  if (bytes.length !== KEY_BYTES) throw new Error("Device key generation returned an unexpected length");
  const key = bytes.toString("base64url");
  bytes.fill(0);
  await options.store.writeInternal(DEVICE_WRAPPING_KEY_NAME, key);
  return { key, secureStorage: "os", generated: true };
}

export function fileWrappingKeyPath(dataDir: string): string {
  return path.join(dataDir, "secure", "wrapping.key");
}

export function validWrappingKey(value: string): boolean {
  return BASE64URL_KEY.test(value) && Buffer.from(value, "base64url").length === KEY_BYTES;
}

async function fileExists(filePath: string): Promise<boolean> {
  try {
    await access(filePath);
    return true;
  } catch {
    return false;
  }
}
