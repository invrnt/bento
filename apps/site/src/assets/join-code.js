// Pairing-code parsing for the /join page. Pure functions, no DOM and no network.
// Format (orchestration/architecture/telegram-first.md § Pairing Protocol):
// three groups of four Crockford Base32 characters, e.g. K7Q2-MXR9-T4WA.
// Accepted input mirrors the app: case-insensitive, spaces/dashes ignored, O→0 and I/L→1.

export const CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
export const CANONICAL_CODE = /^[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$/u;
export const SUPPORTED_VERSION = "1";

const MAX_FRAGMENT_LENGTH = 256;
const MAX_CODE_INPUT_LENGTH = 40;
const RAW_CODE = /^[0-9A-Za-z \t-]+$/u;
const ALIASES = { O: "0", I: "1", L: "1" };

/** Returns the canonical `XXXX-XXXX-XXXX` code, or null when the value is not a valid code. */
export function normalizeCode(value) {
  if (typeof value !== "string" || value.length > MAX_CODE_INPUT_LENGTH || !RAW_CODE.test(value)) return null;
  const compact = value
    .toUpperCase()
    .replace(/[\s-]/gu, "")
    .replace(/[OIL]/gu, (character) => ALIASES[character]);
  if (compact.length !== 12) return null;
  for (const character of compact) {
    if (!CROCKFORD_ALPHABET.includes(character)) return null;
  }
  return `${compact.slice(0, 4)}-${compact.slice(4, 8)}-${compact.slice(8)}`;
}

/** The deep link the desktop app accepts (it re-validates the canonical code strictly). */
export function appLinkFor(code) {
  if (typeof code !== "string" || !CANONICAL_CODE.test(code)) throw new TypeError("appLinkFor expects a canonical code");
  return `bento://join?v=${SUPPORTED_VERSION}&c=${code}`;
}

/**
 * Parses `location.hash` (`#v=1&c=K7Q2-MXR9-T4WA`; a bare `#K7Q2-MXR9-T4WA` is also accepted).
 * Result status: "ok" | "missing" | "invalid" | "unsupported".
 */
export function parseJoinFragment(hash) {
  const raw = typeof hash === "string" ? hash.replace(/^#/u, "") : "";
  if (raw.trim() === "") return { status: "missing" };
  if (raw.length > MAX_FRAGMENT_LENGTH) return { status: "invalid" };

  if (!raw.includes("=")) {
    let bare;
    try {
      bare = decodeURIComponent(raw);
    } catch {
      return { status: "invalid" };
    }
    return result(normalizeCode(bare));
  }

  const params = new URLSearchParams(raw);
  const versions = params.getAll("v");
  const codes = params.getAll("c");
  if (versions.length > 1 || codes.length > 1) return { status: "invalid" };
  if (versions.length === 1 && versions[0] !== SUPPORTED_VERSION) {
    return /^\d{1,4}$/u.test(versions[0]) ? { status: "unsupported" } : { status: "invalid" };
  }
  if (codes.length === 0 || codes[0].trim() === "") return { status: "missing" };
  return result(normalizeCode(codes[0]));
}

function result(code) {
  return code ? { status: "ok", code, appLink: appLinkFor(code) } : { status: "invalid" };
}
