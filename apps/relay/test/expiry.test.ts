import { runDurableObjectAlarm, runInDurableObject } from "cloudflare:test";
import { describe, expect, it } from "vitest";

import { ROOM_TTL_MS } from "../src/protocol";
import { type PairingRoom, ROOM_STATE_KEY, type RoomState } from "../src/room";
import { bytes, connect, expectError, freshNameplate, openHost, openPair, roomStub, type TestSocket } from "./helpers";

async function expectExpired(socket: TestSocket): Promise<void> {
  expect(await socket.nextJson()).toEqual({ type: "closed", reason: "expired" });
  const closed = await socket.waitClosed();
  expect(closed.code).toBe(4000);
  expect(closed.reason).toBe("expired");
}

interface RoomSnapshot {
  state: RoomState | undefined;
  alarm: number | null;
}

function readRoom(stub: DurableObjectStub<PairingRoom>): Promise<RoomSnapshot> {
  return runInDurableObject(stub, async (_instance, ctx) => ({
    state: ctx.storage.kv.get<RoomState>(ROOM_STATE_KEY),
    alarm: await ctx.storage.getAlarm(),
  }));
}

/** Simulates a late alarm by moving the stored expiry into the past. */
function backdateExpiry(stub: DurableObjectStub<PairingRoom>): Promise<void> {
  return runInDurableObject(stub, (_instance, ctx) => {
    const state = ctx.storage.kv.get<RoomState>(ROOM_STATE_KEY);
    if (!state) {
      throw new Error("room state missing");
    }
    ctx.storage.kv.put(ROOM_STATE_KEY, { ...state, expires_at: Date.now() - 1 });
  });
}

describe("room expiry", () => {
  it("schedules the alarm for 10 minutes after the host connects", async () => {
    const nameplate = freshNameplate();
    const host = await openHost(nameplate);
    const { state, alarm } = await readRoom(roomStub(nameplate));
    expect(state).toBeDefined();
    expect(alarm).toBe(state?.expires_at);
    expect((state?.expires_at ?? 0) - (state?.created_at ?? 0)).toBe(ROOM_TTL_MS);
    host.close();
  });

  it("closes both sockets with closed/expired and code 4000, then clears all state", async () => {
    const nameplate = freshNameplate();
    const stub = roomStub(nameplate);
    const { host, guest } = await openPair(nameplate);
    host.send(bytes(3));
    await guest.nextBinary();

    expect(await runDurableObjectAlarm(stub)).toBe(true);
    await expectExpired(host);
    await expectExpired(guest);

    expect(await readRoom(stub)).toEqual({ state: undefined, alarm: null });
    // Nothing persists: the nameplate is free again.
    const next = await openHost(nameplate);
    next.close();
  });

  it("expires a host-only room", async () => {
    const nameplate = freshNameplate();
    const stub = roomStub(nameplate);
    const host = await openHost(nameplate);
    expect(await runDurableObjectAlarm(stub)).toBe(true);
    await expectExpired(host);
    expect(await readRoom(stub)).toEqual({ state: undefined, alarm: null });
  });

  it("keeps a burned room blocked until the alarm, then frees it", async () => {
    const nameplate = freshNameplate();
    const stub = roomStub(nameplate);
    const { host, guest } = await openPair(nameplate);
    guest.send('{"type":"close"}');
    await guest.waitClosed();
    await host.waitClosed();
    await expectError(await connect(nameplate, "host"), "nameplate_taken");

    expect(await runDurableObjectAlarm(stub)).toBe(true);
    expect(await readRoom(stub)).toEqual({ state: undefined, alarm: null });
    const next = await openHost(nameplate);
    next.close();
  });

  it("rejects a guest with expired when the alarm is late", async () => {
    const nameplate = freshNameplate();
    const stub = roomStub(nameplate);
    const host = await openHost(nameplate);
    await backdateExpiry(stub);

    await expectError(await connect(nameplate, "guest"), "expired");
    await expectExpired(host);
    expect(await readRoom(stub)).toEqual({ state: undefined, alarm: null });
  });

  it("lets a new host replace a room whose alarm is late", async () => {
    const nameplate = freshNameplate();
    const stub = roomStub(nameplate);
    const stale = await openHost(nameplate);
    await backdateExpiry(stub);

    const host = await openHost(nameplate);
    await expectExpired(stale);
    const { state, alarm } = await readRoom(stub);
    expect(state).toMatchObject({ burned: false, guest_joined: false });
    expect(alarm).toBe(state?.expires_at);

    // The fresh room works normally.
    const guest = await connect(nameplate, "guest");
    expect(await guest.nextJson()).toMatchObject({ type: "welcome", role: "guest" });
    expect(await guest.nextJson()).toEqual({ type: "peer_joined" });
    expect(await host.nextJson()).toEqual({ type: "peer_joined" });
    host.close();
  });

  it("expires on the next frame when the alarm is late", async () => {
    const nameplate = freshNameplate();
    const stub = roomStub(nameplate);
    const { host, guest } = await openPair(nameplate);
    await backdateExpiry(stub);

    host.send(bytes(4));
    await expectExpired(host);
    await expectExpired(guest);
    expect(await readRoom(stub)).toEqual({ state: undefined, alarm: null });
  });
});
