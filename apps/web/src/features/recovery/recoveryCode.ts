import type { QrMatrix } from "../../api/qr";
import type { MessageKey } from "../../i18n/dictionary";

/** Recovery codes: 36 Crockford Base32 characters shown as 9 groups of 4. */

export const recoveryCodeLength = 36;
const groupSize = 4;
const aliases: Record<string, string> = { I: "1", L: "1", O: "0" };

export function normalizeRecoveryInput(value: string): string {
  return value
    .toUpperCase()
    .replace(/[ILO]/g, (char) => aliases[char] ?? char)
    .replace(/[^0-9A-HJKMNP-TV-Z]/g, "");
}

/** Splits a code into its display groups. */
export function recoveryGroups(code: string): string[] {
  const normalized = normalizeRecoveryInput(code);
  const groups: string[] = [];
  for (let index = 0; index < normalized.length; index += groupSize) groups.push(normalized.slice(index, index + groupSize));
  return groups;
}

export function formatRecoveryCode(code: string): string {
  return recoveryGroups(code).join("-");
}

/** Live formatting for a code field: `XXXX-XXXX-…`, capped at 36 characters. */
export function formatRecoveryInput(value: string): string {
  return formatRecoveryCode(normalizeRecoveryInput(value).slice(0, recoveryCodeLength));
}

export function isCompleteRecoveryCode(value: string): boolean {
  return normalizeRecoveryInput(value).length === recoveryCodeLength;
}

export function lastRecoveryGroup(code: string): string {
  return recoveryGroups(code).at(-1) ?? "";
}

export function matchesLastGroup(code: string, typed: string): boolean {
  const expected = lastRecoveryGroup(code);
  return expected.length > 0 && normalizeRecoveryInput(typed) === expected;
}

/**
 * Optional `recovery_qr` matrix next to a freshly returned recovery code
 * (requested from the API; absent today, so the printed kit shows no QR).
 */
export function recoveryQrFrom(response: unknown): QrMatrix | null {
  const qr = (response as { recovery_qr?: unknown } | null)?.recovery_qr as QrMatrix | undefined;
  return qr && typeof qr.size === "number" && Array.isArray(qr.rows) ? qr : null;
}

/** "Revisa el código" for typos caught by the checksum; "no abre esta nube" for a valid code of another vault. */
export function recoveryErrorKey(code: string | null, fallback: MessageKey): MessageKey {
  const value = code ?? "";
  if (/checksum|format|malformed|validation_failed/.test(value)) return "recovery.error.checksum";
  if (value === "recovery_code_invalid") return "join.recovery.invalid";
  return fallback;
}
