import path from "node:path";
import {
  DesktopPreferencesPatch,
  DirectoryPickerRequest,
  FilePickerRequest,
  ProbeRequest,
  SavePdfRequest,
  SecretMutation,
  SettingsApplyRequest,
} from "../shared/contracts";
import { SECRET_SETTING_KEYS } from "./sidecars";

const KEY = /^[a-z][a-z0-9_]{0,79}$/;
const MAX_SECRET_LENGTH = 16_384;
const MAX_DRAFT_BYTES = 1_048_576;

function record(value: unknown, label: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function onlyKeys(value: Record<string, unknown>, allowed: readonly string[], label: string): void {
  const unexpected = Object.keys(value).filter((key) => !allowed.includes(key));
  if (unexpected.length) throw new TypeError(`${label} contains unsupported fields`);
}

function optionalTitle(value: unknown): string | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "string" || value.length < 1 || value.length > 160 || /[\u0000-\u001f]/u.test(value)) {
    throw new TypeError("title is invalid");
  }
  return value;
}

export function validateDirectoryPicker(value: unknown): DirectoryPickerRequest {
  const input = record(value ?? {}, "directory picker request");
  onlyKeys(input, ["title"], "directory picker request");
  return { title: optionalTitle(input.title) };
}

export function validateFilePicker(value: unknown): FilePickerRequest {
  const input = record(value ?? {}, "file picker request");
  onlyKeys(input, ["title", "filters"], "file picker request");
  let filters: FilePickerRequest["filters"];
  if (input.filters !== undefined) {
    if (!Array.isArray(input.filters) || input.filters.length > 12) throw new TypeError("filters are invalid");
    filters = input.filters.map((candidate) => {
      const filter = record(candidate, "file filter");
      onlyKeys(filter, ["name", "extensions"], "file filter");
      if (typeof filter.name !== "string" || !filter.name || filter.name.length > 80) {
        throw new TypeError("filter name is invalid");
      }
      if (!Array.isArray(filter.extensions) || filter.extensions.length > 20) {
        throw new TypeError("filter extensions are invalid");
      }
      const extensions = filter.extensions.map((extension) => {
        if (typeof extension !== "string" || !/^[a-z0-9]{1,12}$/iu.test(extension)) {
          throw new TypeError("filter extension is invalid");
        }
        return extension.toLowerCase();
      });
      return { name: filter.name, extensions };
    });
  }
  return { title: optionalTitle(input.title), filters };
}

function validateJson(value: unknown, depth = 0): void {
  if (depth > 8) throw new TypeError("settings draft is too deeply nested");
  if (value === null || ["string", "boolean"].includes(typeof value)) return;
  if (typeof value === "number" && Number.isFinite(value)) return;
  if (Array.isArray(value)) return value.forEach((item) => validateJson(item, depth + 1));
  if (typeof value === "object") {
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      if (!KEY.test(key)) throw new TypeError("settings key is invalid");
      validateJson(item, depth + 1);
    }
    return;
  }
  throw new TypeError("settings draft contains unsupported data");
}

function validateSecretMutation(value: unknown): SecretMutation {
  const mutation = record(value, "secret mutation");
  if (mutation.operation === "set") {
    onlyKeys(mutation, ["operation", "value"], "secret mutation");
    if (typeof mutation.value !== "string" || mutation.value.length < 1 || mutation.value.length > MAX_SECRET_LENGTH) {
      throw new TypeError("secret value is invalid");
    }
    return { operation: "set", value: mutation.value };
  }
  if (mutation.operation === "clear" || mutation.operation === "unchanged") {
    onlyKeys(mutation, ["operation"], "secret mutation");
    return { operation: mutation.operation };
  }
  throw new TypeError("secret operation is invalid");
}

export function validateSettingsApply(value: unknown): SettingsApplyRequest {
  const input = record(value, "settings apply request");
  onlyKeys(input, ["revision", "values", "secrets", "runProbes", "dataMigration"], "settings apply request");
  if (!Number.isSafeInteger(input.revision) || (input.revision as number) < 0) throw new TypeError("revision is invalid");
  const values = record(input.values, "settings values");
  const secretsInput = record(input.secrets, "settings secrets");
  for (const key of Object.keys(values)) if (!KEY.test(key)) throw new TypeError("settings key is invalid");
  validateJson(values);
  if (Buffer.byteLength(JSON.stringify(values), "utf8") > MAX_DRAFT_BYTES) throw new TypeError("settings draft is too large");
  const secrets: Record<string, SecretMutation> = {};
  for (const [key, mutation] of Object.entries(secretsInput)) {
    if (!KEY.test(key) || !SECRET_SETTING_KEYS.includes(key)) throw new TypeError("secret key is invalid");
    secrets[key] = validateSecretMutation(mutation);
  }
  if (input.runProbes !== undefined && typeof input.runProbes !== "boolean") throw new TypeError("runProbes is invalid");
  if (input.dataMigration !== undefined && input.dataMigration !== "copy" && input.dataMigration !== "use-empty") {
    throw new TypeError("dataMigration is invalid");
  }
  return {
    revision: input.revision as number,
    values,
    secrets,
    runProbes: input.runProbes as boolean | undefined,
    dataMigration: input.dataMigration as SettingsApplyRequest["dataMigration"],
  };
}

export function validateProbe(value: unknown): ProbeRequest {
  const input = record(value, "probe request");
  onlyKeys(input, ["kind", "path"], "probe request");
  const kinds = ["writable-directory", "model-file", "ffmpeg", "ocr"];
  if (typeof input.kind !== "string" || !kinds.includes(input.kind)) throw new TypeError("probe kind is invalid");
  const result: ProbeRequest = { kind: input.kind as ProbeRequest["kind"] };
  if (input.path !== undefined) result.path = validateSafePath(input.path);
  return result;
}

const PREFERENCE_KEYS = ["keepRunningInBackground", "launchAtLogin", "autoDownloadUpdates"] as const;

export function validatePreferencesPatch(value: unknown): DesktopPreferencesPatch {
  const input = record(value, "preferences patch");
  onlyKeys(input, PREFERENCE_KEYS, "preferences patch");
  const patch: DesktopPreferencesPatch = {};
  for (const key of PREFERENCE_KEYS) {
    if (!Object.hasOwn(input, key)) continue;
    if (typeof input[key] !== "boolean") throw new TypeError(`${key} must be a boolean`);
    patch[key] = input[key] as boolean;
  }
  if (Object.keys(patch).length === 0) throw new TypeError("preferences patch is empty");
  return patch;
}

const WINDOWS_RESERVED_NAME = /^(?:con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?$/iu;

export function validateSavePdfRequest(value: unknown): SavePdfRequest {
  const input = record(value ?? {}, "PDF request");
  onlyKeys(input, ["suggestedName"], "PDF request");
  if (input.suggestedName === undefined) return {};
  const name = input.suggestedName;
  if (typeof name !== "string" || name.trim().length < 1 || name.length > 120 ||
    /[\u0000-\u001f\u007f/\\:*?"<>|]/u.test(name) || name.trim().startsWith(".") ||
    WINDOWS_RESERVED_NAME.test(name.trim())) {
    throw new TypeError("suggestedName is invalid");
  }
  return { suggestedName: name.trim() };
}

export function validateSafePath(value: unknown): string {
  if (typeof value !== "string" || !path.isAbsolute(value) || value.includes("\0")) throw new TypeError("path is invalid");
  const resolved = path.resolve(value);
  if (resolved === path.parse(resolved).root) throw new TypeError("filesystem root is not allowed");
  return resolved;
}
