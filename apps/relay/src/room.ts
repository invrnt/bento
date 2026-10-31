import { DurableObject } from "cloudflare:workers";

import { logEvent } from "./log";
import {
  CLOSE_ERROR,
  CLOSE_EXPIRED,
  CLOSE_NORMAL,
  type ErrorCode,
  MAX_FRAME_BYTES,
  MAX_FRAMES_PER_SIDE,
  NAMEPLATE_ATTEMPT_LIMIT,
  NAMEPLATE_ATTEMPT_WINDOW_MS,
  ROLES,
  ROOM_TTL_MS,
  type Role,
  type ServerFrame,
  encodeFrame,
  isCloseCommand,
  isRole,
  peerOf,
  utf8Length,
} from "./protocol";

/**
 * Minimal persisted room state. It lives until the expiry alarm, so a burned
 * room keeps blocking reuse of its nameplate, and survives hibernation.
 */
export interface RoomState {
  /** Random id tying accepted sockets to this room generation. */
  session: string;
  created_at: number;
  expires_at: number;
  burned: boolean;
  guest_joined: boolean;
  host_frames: number;
  guest_frames: number;
}

/**
 * Connection attempts against this nameplate in a fixed window that starts with the first attempt.
 * Kept apart from the room so squatting or burning cannot be repeated by simply waiting for expiry;
 * it is deleted once the window is over.
 */
export interface AttemptWindow {
  started_at: number;
  count: number;
}

/** Per-socket state kept with `serializeAttachment` (survives hibernation). */
export interface SocketAttachment {
  session: string;
  role: Role;
}

export const ROOM_STATE_KEY = "room";
export const ATTEMPTS_KEY = "attempts";

const FRAME_COUNTER: Record<Role, "host_frames" | "guest_frames"> = {
  host: "host_frames",
  guest: "guest_frames",
};

/**
 * One pairing room per nameplate. Relays opaque binary frames between exactly
 * one host and one guest; never inspects or stores frame contents.
 */
export class PairingRoom extends DurableObject<Env> {
  override async fetch(request: Request): Promise<Response> {
    if (request.headers.get("Upgrade")?.toLowerCase() !== "websocket") {
      return new Response(null, { status: 426, headers: { Upgrade: "websocket" } });
    }
    const role = new URL(request.url).searchParams.get("role");
    if (!isRole(role)) {
      return new Response(null, { status: 400 });
    }

    const { 0: client, 1: server } = new WebSocketPair();
    let rejection: ErrorCode | null;
    if (!this.countAttempt(Date.now())) {
      // A host simply picks another nameplate; a guest has to wait.
      rejection = role === "host" ? "nameplate_taken" : "rate_limited";
    } else {
      rejection = role === "host" ? await this.admitHost(server) : await this.admitGuest(server);
    }
    if (this.readState() === undefined) {
      // No room alarm is pending; make sure the attempt counter is still cleaned up.
      await this.releaseStorage();
    }
    if (rejection !== null) {
      // Rejected sockets are not hibernatable participants: send the error and close.
      server.accept();
      sendFrame(server, { type: "error", code: rejection });
      closeSocket(server, CLOSE_ERROR, rejection);
      logEvent("connection_rejected", { role, code: rejection });
    }
    return new Response(null, { status: 101, webSocket: client });
  }

  override async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer): Promise<void> {
    const attachment = readAttachment(ws);
    const state = this.readState();
    if (attachment === null || state === undefined || state.session !== attachment.session) {
      // Socket from a room generation that no longer exists.
      sendFrame(ws, { type: "error", code: "protocol" });
      closeSocket(ws, CLOSE_ERROR, "protocol");
      return;
    }
    if (state.burned) {
      return;
    }
    if (Date.now() >= state.expires_at) {
      await this.expire(state);
      return;
    }

    const role = attachment.role;
    const size = typeof message === "string" ? utf8Length(message) : message.byteLength;
    if (size > MAX_FRAME_BYTES) {
      this.fail(state, ws, role, "message_too_large");
      return;
    }
    if (typeof message === "string") {
      if (isCloseCommand(message)) {
        this.burn(state, role);
      } else {
        this.fail(state, ws, role, "protocol");
      }
      return;
    }

    const peer = this.socketFor(state, peerOf(role));
    const counter = FRAME_COUNTER[role];
    if (peer === null || state[counter] >= MAX_FRAMES_PER_SIDE) {
      this.fail(state, ws, role, "protocol");
      return;
    }
    state[counter] += 1;
    this.writeState(state);
    try {
      peer.send(message);
    } catch {
      // The peer went away between the readyState check and the send.
      this.burn(state, null);
    }
  }

  override async webSocketClose(ws: WebSocket, code: number, reason: string): Promise<void> {
    // Complete the close handshake; ignored when the runtime already replied.
    if (isSendableCloseCode(code)) {
      closeSocket(ws, code, reason);
    } else {
      closeSocket(ws, CLOSE_NORMAL, "");
    }
    await this.handleDisconnect(ws);
  }

  override async webSocketError(ws: WebSocket): Promise<void> {
    await this.handleDisconnect(ws);
  }

  override async alarm(): Promise<void> {
    const state = this.readState();
    if (state === undefined) {
      await this.releaseStorage();
      return;
    }
    await this.expire(state);
  }

  private async admitHost(server: WebSocket): Promise<ErrorCode | null> {
    const now = Date.now();
    const existing = this.readState();
    if (existing !== undefined) {
      if (now < existing.expires_at) {
        return "nameplate_taken";
      }
      // The alarm is late; finish the old room before reusing the nameplate.
      await this.expire(existing);
    }

    const state: RoomState = {
      session: crypto.randomUUID(),
      created_at: now,
      expires_at: now + ROOM_TTL_MS,
      burned: false,
      guest_joined: false,
      host_frames: 0,
      guest_frames: 0,
    };
    this.writeState(state);
    await this.ctx.storage.setAlarm(state.expires_at);

    this.accept(server, state, "host");
    sendFrame(server, welcome("host", state));
    logEvent("room_opened", { role: "host" });
    return null;
  }

  private async admitGuest(server: WebSocket): Promise<ErrorCode | null> {
    const state = this.readState();
    if (state === undefined) {
      return "room_not_found";
    }
    if (Date.now() >= state.expires_at) {
      await this.expire(state);
      return "expired";
    }
    if (state.burned) {
      return state.guest_joined ? "room_full" : "room_not_found";
    }
    if (state.guest_joined) {
      return "room_full";
    }
    const host = this.socketFor(state, "host");
    if (host === null) {
      // Host vanished without a close event reaching us; treat as burned.
      this.burn(state, null);
      return "room_not_found";
    }

    state.guest_joined = true;
    this.writeState(state);

    this.accept(server, state, "guest");
    sendFrame(server, welcome("guest", state));
    sendFrame(server, { type: "peer_joined" });
    sendFrame(host, { type: "peer_joined" });
    logEvent("peer_joined", { role: "guest", room_age_ms: Date.now() - state.created_at });
    return null;
  }

  private async handleDisconnect(ws: WebSocket): Promise<void> {
    const attachment = readAttachment(ws);
    const state = this.readState();
    if (attachment === null || state === undefined || state.session !== attachment.session) {
      return;
    }
    if (state.burned) {
      return;
    }
    if (Date.now() >= state.expires_at) {
      await this.expire(state);
      return;
    }
    this.burn(state, null);
  }

  /** Reject a participant's frame: error + close 4001 to it, then burn the room. */
  private fail(state: RoomState, ws: WebSocket, role: Role, code: ErrorCode): void {
    sendFrame(ws, { type: "error", code });
    closeSocket(ws, CLOSE_ERROR, code);
    logEvent("frame_rejected", { role, code, ...frameStats(state) });
    this.burn(state, role);
  }

  /**
   * Mark the room burned and close every remaining participant. `initiator`
   * is the side that ended the room (close command or error); every other
   * open side is told its peer left. State stays until the alarm so the
   * nameplate cannot be reused before expiry.
   */
  private burn(state: RoomState, initiator: Role | null): void {
    state.burned = true;
    this.writeState(state);
    for (const role of ROLES) {
      const ws = this.socketFor(state, role);
      if (ws === null) {
        continue;
      }
      if (role !== initiator) {
        sendFrame(ws, { type: "peer_left" });
      }
      sendFrame(ws, { type: "closed", reason: "burned" });
      closeSocket(ws, CLOSE_NORMAL, "burned");
    }
    logEvent("room_burned", frameStats(state));
  }

  /** Expiry: notify and close every open socket with 4000, then drop the room state. */
  private async expire(state: RoomState): Promise<void> {
    for (const ws of this.ctx.getWebSockets()) {
      if (ws.readyState !== WebSocket.READY_STATE_OPEN) {
        continue;
      }
      sendFrame(ws, { type: "closed", reason: "expired" });
      closeSocket(ws, CLOSE_EXPIRED, "expired");
    }
    logEvent("room_expired", frameStats(state));
    this.ctx.storage.kv.delete(ROOM_STATE_KEY);
    await this.releaseStorage();
  }

  /**
   * With no room left: delete everything (and the alarm) once the attempt window is over, otherwise
   * keep only the counter and wake up when its window ends.
   */
  private async releaseStorage(): Promise<void> {
    const attempts = this.readAttempts();
    if (attempts === undefined || Date.now() >= attempts.started_at + NAMEPLATE_ATTEMPT_WINDOW_MS) {
      await this.ctx.storage.deleteAll();
      return;
    }
    await this.ctx.storage.setAlarm(attempts.started_at + NAMEPLATE_ATTEMPT_WINDOW_MS);
  }

  /** Counts one connection attempt; false once this window's budget is spent (not counted then). */
  private countAttempt(now: number): boolean {
    const current = this.readAttempts();
    const window = current !== undefined && now < current.started_at + NAMEPLATE_ATTEMPT_WINDOW_MS
      ? current
      : { started_at: now, count: 0 };
    if (window.count >= NAMEPLATE_ATTEMPT_LIMIT) {
      return false;
    }
    const next: AttemptWindow = { started_at: window.started_at, count: window.count + 1 };
    this.ctx.storage.kv.put(ATTEMPTS_KEY, next);
    return true;
  }

  private accept(server: WebSocket, state: RoomState, role: Role): void {
    this.ctx.acceptWebSocket(server, [role]);
    const attachment: SocketAttachment = { session: state.session, role };
    server.serializeAttachment(attachment);
  }

  /** The open socket for `role` in the current room generation, if any. */
  private socketFor(state: RoomState, role: Role): WebSocket | null {
    for (const ws of this.ctx.getWebSockets(role)) {
      if (ws.readyState !== WebSocket.READY_STATE_OPEN) {
        continue;
      }
      if (readAttachment(ws)?.session === state.session) {
        return ws;
      }
    }
    return null;
  }

  private readState(): RoomState | undefined {
    return this.ctx.storage.kv.get<RoomState>(ROOM_STATE_KEY);
  }

  private readAttempts(): AttemptWindow | undefined {
    const value = this.ctx.storage.kv.get<AttemptWindow>(ATTEMPTS_KEY);
    return typeof value?.started_at === "number" && typeof value.count === "number" ? value : undefined;
  }

  private writeState(state: RoomState): void {
    this.ctx.storage.kv.put(ROOM_STATE_KEY, state);
  }
}

function welcome(role: Role, state: RoomState): ServerFrame {
  return { type: "welcome", role, expires_at: new Date(state.expires_at).toISOString() };
}

function frameStats(state: RoomState): { room_age_ms: number; host_frames: number; guest_frames: number } {
  return {
    room_age_ms: Date.now() - state.created_at,
    host_frames: state.host_frames,
    guest_frames: state.guest_frames,
  };
}

function readAttachment(ws: WebSocket): SocketAttachment | null {
  const value: unknown = ws.deserializeAttachment();
  if (typeof value !== "object" || value === null) {
    return null;
  }
  const { session, role } = value as Partial<SocketAttachment>;
  if (typeof session !== "string" || !isRole(role ?? null)) {
    return null;
  }
  return value as SocketAttachment;
}

/** Codes an endpoint may put in a Close frame (RFC 6455 section 7.4). */
function isSendableCloseCode(code: number): boolean {
  return (
    code === CLOSE_NORMAL ||
    (code >= 1001 && code <= 1003) ||
    (code >= 1007 && code <= 1014) ||
    (code >= 3000 && code <= 4999)
  );
}

function sendFrame(ws: WebSocket, frame: ServerFrame): void {
  try {
    ws.send(encodeFrame(frame));
  } catch {
    // Socket already closing; nothing to deliver.
  }
}

function closeSocket(ws: WebSocket, code: number, reason: string): void {
  try {
    ws.close(code, reason);
  } catch {
    // Already closed.
  }
}
