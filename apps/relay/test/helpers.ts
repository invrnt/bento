import { env, exports } from "cloudflare:workers";
import { expect } from "vitest";

import type { Role } from "../src/protocol";

const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
const BASE_URL = "https://relay.test";
const DEFAULT_TIMEOUT_MS = 2_000;

/** workerd delivers binary frames to a client socket as Blob by default. */
export type Received = string | ArrayBuffer | Blob;

export interface CloseInfo {
  code: number;
  reason: string;
}

/** Client side of a relay WebSocket with an ordered message queue. */
export class TestSocket {
  readonly closed: Promise<CloseInfo>;
  private readonly queue: Received[] = [];
  private readonly waiters: Array<(message: Received) => void> = [];

  constructor(readonly ws: WebSocket) {
    ws.accept();
    ws.addEventListener("message", (event) => {
      const data = event.data as Received;
      const waiter = this.waiters.shift();
      if (waiter) {
        waiter(data);
      } else {
        this.queue.push(data);
      }
    });
    this.closed = new Promise((resolve) => {
      ws.addEventListener("close", (event) => resolve({ code: event.code, reason: event.reason }));
    });
  }

  next(timeoutMs = DEFAULT_TIMEOUT_MS): Promise<Received> {
    const queued = this.queue.shift();
    if (queued !== undefined) {
      return Promise.resolve(queued);
    }
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        const index = this.waiters.indexOf(waiter);
        if (index >= 0) {
          this.waiters.splice(index, 1);
        }
        reject(new Error(`no message within ${timeoutMs} ms`));
      }, timeoutMs);
      const waiter = (message: Received): void => {
        clearTimeout(timer);
        resolve(message);
      };
      this.waiters.push(waiter);
    });
  }

  async nextJson(): Promise<Record<string, unknown>> {
    const message = await this.next();
    if (typeof message !== "string") {
      throw new Error("expected a text frame, got binary");
    }
    return JSON.parse(message) as Record<string, unknown>;
  }

  async nextBinary(): Promise<Uint8Array> {
    const message = await this.next();
    if (typeof message === "string") {
      throw new Error(`expected a binary frame, got text ${message}`);
    }
    return new Uint8Array(message instanceof Blob ? await message.arrayBuffer() : message);
  }

  /** Resolves with the close info, failing if it does not arrive in time. */
  async waitClosed(timeoutMs = DEFAULT_TIMEOUT_MS): Promise<CloseInfo> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error(`socket not closed within ${timeoutMs} ms`)), timeoutMs);
    });
    try {
      return await Promise.race([this.closed, timeout]);
    } finally {
      if (timer !== undefined) {
        clearTimeout(timer);
      }
    }
  }

  /** Messages received but not consumed yet. */
  pending(): Received[] {
    return [...this.queue];
  }

  send(data: string | ArrayBuffer | ArrayBufferView): void {
    this.ws.send(data);
  }

  close(code = 1000, reason = "bye"): void {
    this.ws.close(code, reason);
  }
}

const usedNameplates = new Set<string>();

/** A random nameplate not used before in this test file (storage is isolated per file). */
export function freshNameplate(): string {
  for (;;) {
    const nameplate = Array.from(crypto.getRandomValues(new Uint8Array(4)), (b) => CROCKFORD[b % 32]).join("");
    if (!usedNameplates.has(nameplate)) {
      usedNameplates.add(nameplate);
      return nameplate;
    }
  }
}

/** Random private address so tests do not share a rate-limit bucket. */
export function randomIp(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(3));
  return `10.${bytes[0]}.${bytes[1]}.${bytes[2]}`;
}

export function roomRequest(
  nameplate: string,
  role: string | null,
  headers: Record<string, string> = {},
): Promise<Response> {
  const query = role === null ? "" : `?role=${role}`;
  return exports.default.fetch(`${BASE_URL}/v1/rooms/${nameplate}${query}`, {
    headers: { Upgrade: "websocket", "CF-Connecting-IP": randomIp(), ...headers },
  });
}

export function relayFetch(path: string, init?: RequestInit): Promise<Response> {
  return exports.default.fetch(`${BASE_URL}${path}`, init);
}

/** Opens a room WebSocket through the Worker router. */
export async function connect(nameplate: string, role: Role, ip?: string): Promise<TestSocket> {
  const response = await roomRequest(nameplate, role, ip === undefined ? {} : { "CF-Connecting-IP": ip });
  expect(response.status).toBe(101);
  const ws = response.webSocket;
  if (!ws) {
    throw new Error("expected a WebSocket upgrade");
  }
  return new TestSocket(ws);
}

/** Connects a host and checks its welcome frame. */
export async function openHost(nameplate: string): Promise<TestSocket> {
  const host = await connect(nameplate, "host");
  expect(await host.nextJson()).toMatchObject({ type: "welcome", role: "host" });
  return host;
}

/** Host + guest with all join frames consumed. */
export async function openPair(nameplate: string): Promise<{ host: TestSocket; guest: TestSocket }> {
  const host = await openHost(nameplate);
  const guest = await connect(nameplate, "guest");
  expect(await guest.nextJson()).toMatchObject({ type: "welcome", role: "guest" });
  expect(await guest.nextJson()).toEqual({ type: "peer_joined" });
  expect(await host.nextJson()).toEqual({ type: "peer_joined" });
  return { host, guest };
}

/** Expects `{"type":"error","code":code}` followed by close 4001. */
export async function expectError(socket: TestSocket, code: string): Promise<void> {
  expect(await socket.nextJson()).toEqual({ type: "error", code });
  const closed = await socket.waitClosed();
  expect(closed.code).toBe(4001);
  expect(closed.reason).toBe(code);
}

/** Expects `peer_left`, `closed: burned` and a normal close. */
export async function expectPeerLeft(socket: TestSocket): Promise<void> {
  expect(await socket.nextJson()).toEqual({ type: "peer_left" });
  expect(await socket.nextJson()).toEqual({ type: "closed", reason: "burned" });
  expect((await socket.waitClosed()).code).toBe(1000);
}

export function roomStub(nameplate: string): DurableObjectStub<import("../src/room").PairingRoom> {
  return env.PAIRING_ROOM.get(env.PAIRING_ROOM.idFromName(`room:${nameplate}`));
}

export function bytes(length: number, seed = 1): Uint8Array {
  const out = new Uint8Array(length);
  for (let i = 0; i < length; i += 1) {
    out[i] = (i * 31 + seed) & 0xff;
  }
  return out;
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
