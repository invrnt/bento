import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { SecretMutation } from "../shared/contracts";

interface SafeStorageLike {
  isAsyncEncryptionAvailable(): Promise<boolean>;
  encryptStringAsync(value: string): Promise<Buffer>;
  decryptStringAsync(value: Buffer): Promise<{ result: string; shouldReEncrypt: boolean }>;
  getSelectedStorageBackend?(): string;
}

interface StoredSecret {
  reference: string;
  encrypted: string;
}

interface StoredInternalSecret {
  encrypted: string;
}

interface SecretDocument {
  version: 1;
  secrets: Record<string, StoredSecret>;
  /** Desktop-owned material (never settings keys, never sent to the renderer or HTTP API). */
  internal?: Record<string, StoredInternalSecret>;
}

/** Bot API era secrets removed by the Telegram-first startup migration. */
export const LEGACY_SECRET_SETTING_KEYS = [
  "telegram_bot_token",
  "telegram_api_id",
  "telegram_api_hash",
  "telegram_raw_chat_id",
  "telegram_thumbs_chat_id",
  "telegram_journal_chat_id",
  "telegram_webhook_secret",
  "bento_encryption_key",
] as const;

const INTERNAL_NAME = /^[a-z][a-z0-9-]{0,63}$/u;

export interface PreparedSecretMutation {
  references: Record<string, { reference: string | null; configured: boolean }>;
  values: Record<string, string>;
  commit(): Promise<void>;
  rollback(): Promise<void>;
}

const EMPTY: SecretDocument = { version: 1, secrets: {} };

export class SecureSecretStore {
  constructor(
    private readonly filePath: string,
    private readonly storage: SafeStorageLike,
    private readonly platform: NodeJS.Platform = process.platform,
  ) {}

  async available(): Promise<boolean> {
    if (!(await this.storage.isAsyncEncryptionAvailable())) return false;
    return !(this.platform === "linux" && this.storage.getSelectedStorageBackend?.() === "basic_text");
  }

  async references(): Promise<Record<string, string>> {
    const document = await this.readDocument();
    return Object.fromEntries(Object.entries(document.secrets).map(([key, item]) => [key, item.reference]));
  }

  async values(): Promise<Record<string, string>> {
    const document = await this.readDocument();
    if (Object.keys(document.secrets).length === 0) return {};
    await this.assertAvailable();
    const values: Record<string, string> = {};
    for (const [key, item] of Object.entries(document.secrets)) {
      const decrypted = await this.storage.decryptStringAsync(Buffer.from(item.encrypted, "base64"));
      values[key] = decrypted.result;
      if (decrypted.shouldReEncrypt) {
        const encrypted = await this.storage.encryptStringAsync(decrypted.result);
        item.encrypted = encrypted.toString("base64");
      }
    }
    return values;
  }

  async prepare(mutations: Record<string, SecretMutation>): Promise<PreparedSecretMutation> {
    await this.assertAvailable();
    const before = await this.readDocument();
    const after: SecretDocument = structuredClone(before);
    for (const [key, mutation] of Object.entries(mutations)) {
      if (mutation.operation === "unchanged") continue;
      if (mutation.operation === "clear") {
        delete after.secrets[key];
        continue;
      }
      after.secrets[key] = {
        reference: before.secrets[key]?.reference ?? `desktop-secret:${randomUUID()}`,
        encrypted: (await this.storage.encryptStringAsync(mutation.value)).toString("base64"),
      };
    }
    const references = Object.fromEntries(Object.keys(mutations).map((key) => {
      const item = after.secrets[key];
      return [key, { reference: item?.reference ?? null, configured: Boolean(item) }];
    }));
    const decode = async (): Promise<Record<string, string>> => {
      const result: Record<string, string> = {};
      for (const [key, item] of Object.entries(after.secrets)) {
        result[key] = (await this.storage.decryptStringAsync(Buffer.from(item.encrypted, "base64"))).result;
      }
      return result;
    };
    return {
      references,
      values: await decode(),
      commit: () => this.writeSettingsSecrets(after),
      rollback: () => this.writeSettingsSecrets(before),
    };
  }

  async hasInternal(name: string): Promise<boolean> {
    assertInternalName(name);
    const document = await this.readDocument();
    return Boolean(document.internal?.[name]);
  }

  async readInternal(name: string): Promise<string | null> {
    assertInternalName(name);
    const document = await this.readDocument();
    const item = document.internal?.[name];
    if (!item) return null;
    await this.assertAvailable();
    return (await this.storage.decryptStringAsync(Buffer.from(item.encrypted, "base64"))).result;
  }

  async writeInternal(name: string, value: string): Promise<void> {
    assertInternalName(name);
    await this.assertAvailable();
    const document = await this.readDocument();
    const encrypted = (await this.storage.encryptStringAsync(value)).toString("base64");
    document.internal = { ...document.internal, [name]: { encrypted } };
    await this.writeDocument(document);
  }

  /** Deletes stored settings secrets without decrypting them; returns how many were removed. */
  async removeSecrets(keys: readonly string[]): Promise<number> {
    const document = await this.readDocument();
    const present = keys.filter((key) => Object.hasOwn(document.secrets, key));
    if (!present.length) return 0;
    for (const key of present) delete document.secrets[key];
    await this.writeDocument(document);
    return present.length;
  }

  private async assertAvailable(): Promise<void> {
    if (!(await this.available())) throw new Error("Secure OS storage is unavailable; secret changes were not saved");
  }

  private async readDocument(): Promise<SecretDocument> {
    try {
      const raw = JSON.parse(await readFile(this.filePath, "utf8")) as unknown;
      if (!validDocument(raw)) throw new Error("Secure secret metadata is invalid");
      return raw;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return structuredClone(EMPTY);
      throw error;
    }
  }

  /** Settings transactions replace only settings secrets and keep current internal entries. */
  private async writeSettingsSecrets(document: SecretDocument): Promise<void> {
    const current = await this.readDocument();
    const next: SecretDocument = { version: 1, secrets: document.secrets };
    if (current.internal) next.internal = current.internal;
    await this.writeDocument(next);
  }

  private async writeDocument(document: SecretDocument): Promise<void> {
    await mkdir(path.dirname(this.filePath), { recursive: true, mode: 0o700 });
    const temporary = `${this.filePath}.tmp`;
    await writeFile(temporary, `${JSON.stringify(document)}\n`, { encoding: "utf8", mode: 0o600 });
    await rename(temporary, this.filePath);
  }
}

function validDocument(value: unknown): value is SecretDocument {
  if (!value || typeof value !== "object") return false;
  const document = value as Partial<SecretDocument>;
  if (document.version !== 1 || !document.secrets || typeof document.secrets !== "object") return false;
  if (document.internal !== undefined) {
    if (!document.internal || typeof document.internal !== "object" || Array.isArray(document.internal)) return false;
    const validInternal = Object.entries(document.internal).every(([name, item]) =>
      INTERNAL_NAME.test(name) && item && typeof item.encrypted === "string" && item.encrypted.length > 0,
    );
    if (!validInternal) return false;
  }
  return Object.values(document.secrets).every((item) =>
    item && typeof item.reference === "string" && item.reference.startsWith("desktop-secret:") &&
    typeof item.encrypted === "string" && item.encrypted.length > 0,
  );
}

function assertInternalName(name: string): void {
  if (!INTERNAL_NAME.test(name)) throw new TypeError("Internal secret name is invalid");
}
