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
