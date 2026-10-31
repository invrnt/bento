import type { ErrorCode, Role } from "./protocol";

// Privacy rule: log only event names, room age, frame counts and error codes.
// Never frame contents, nameplates, IPs (raw or hashed) or headers.
export type RelayEvent =
  | "room_opened"
  | "peer_joined"
  | "room_burned"
  | "room_expired"
  | "connection_rejected"
  | "frame_rejected"
  | "rate_limited";

export interface RelayLogFields {
  role?: Role;
  code?: ErrorCode;
  room_age_ms?: number;
  host_frames?: number;
  guest_frames?: number;
}

export function logEvent(event: RelayEvent, fields: RelayLogFields = {}): void {
  console.log({ event, ...fields });
}
