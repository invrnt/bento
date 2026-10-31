/** Pairing codes: `NNNN-SSSS-SSSS` in Crockford Base32 (no I, L, O, U). */

const codeLength = 12;
const aliases: Record<string, string> = { I: "1", L: "1", O: "0" };
const pattern = /^[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$/;

function normalizeChars(value: string): string {
  return value
    .toUpperCase()
    .replace(/[ILO]/g, (char) => aliases[char] ?? char)
    .replace(/[^0-9A-HJKMNP-TV-Z]/g, "");
}

/** Pulls the code out of `bento://join?v=1&c=…`, `https://…/join#v=1&c=…` or `?c=…` links. */
export function extractPairingCode(value: string): string {
  const raw = value.trim();
  if (!raw.includes("://") && !raw.includes("c=")) return raw;
  const match = raw.match(/[?#&]c=([^&#\s]+)/i) ?? raw.match(/^c=([^&#\s]+)/i);
  if (!match) return raw;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

/** Live formatting for the code field: accepts codes and pasted links, shows `XXXX-XXXX-XXXX`. */
export function formatPairingInput(value: string): string {
  const chars = normalizeChars(extractPairingCode(value)).slice(0, codeLength);
  return chars.match(/.{1,4}/g)?.join("-") ?? "";
}

export function isCompletePairingCode(value: string): boolean {
  return pattern.test(formatPairingInput(value));
}

/** Reads a prefilled code from `/join?c=…` or `/join#v=1&c=…`. */
export function pairingCodeFromLocation(search: string, hash = ""): string {
  const fromSearch = new URLSearchParams(search).get("c");
  const fromHash = new URLSearchParams(hash.replace(/^#/, "")).get("c");
  const candidate = fromSearch ?? fromHash ?? "";
  return candidate ? formatPairingInput(candidate) : "";
}
