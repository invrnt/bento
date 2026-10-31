// Wire contract: orchestration/api/pairing-relay-contract.md

export const NAMEPLATE_PATTERN = /^[0-9A-HJKMNP-TV-Z]{4}$/;

export const ROOM_TTL_MS = 10 * 60 * 1000;
export const MAX_FRAME_BYTES = 64 * 1024;
export const MAX_FRAMES_PER_SIDE = 128;

export const CLOSE_EXPIRED = 4000;
export const CLOSE_ERROR = 4001;
export const CLOSE_NORMAL = 1000;

export const ROLES = ["host", "guest"] as const;
export type Role = (typeof ROLES)[number];

export type ErrorCode =
  | "nameplate_taken"
  | "room_not_found"
  | "room_full"
  | "expired"
  | "rate_limited"
  | "message_too_large"
  | "protocol";

export type ClosedReason = "expired" | "burned";

export type ServerFrame =
  | { type: "welcome"; role: Role; expires_at: string }
  | { type: "peer_joined" }
  | { type: "peer_left" }
  | { type: "error"; code: ErrorCode }
  | { type: "closed"; reason: ClosedReason };

export function isRole(value: string | null): value is Role {
  return value === "host" || value === "guest";
}

export function peerOf(role: Role): Role {
  return role === "host" ? "guest" : "host";
}

export function encodeFrame(frame: ServerFrame): string {
  return JSON.stringify(frame);
}

const textEncoder = new TextEncoder();

export function utf8Length(text: string): number {
  return textEncoder.encode(text).byteLength;
}

/** The only client text frame is exactly `{"type":"close"}` (whitespace allowed). */
export function isCloseCommand(text: string): boolean {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return false;
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return false;
  }
  const keys = Object.keys(parsed);
  return keys.length === 1 && keys[0] === "type" && (parsed as { type: unknown }).type === "close";
}
