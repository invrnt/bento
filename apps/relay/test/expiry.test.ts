import { runDurableObjectAlarm, runInDurableObject } from "cloudflare:test";
import { describe, expect, it } from "vitest";

import { NAMEPLATE_ATTEMPT_WINDOW_MS, ROOM_TTL_MS } from "../src/protocol";
import { ATTEMPTS_KEY, type AttemptWindow, type PairingRoom, ROOM_STATE_KEY, type RoomState } from "../src/room";
import { bytes, connect, expectError, freshNameplate, openHost, openPair, roomStub, type TestSocket } from "./helpers";

async function expectExpired(socket: TestSocket): Promise<void> {
  expect(await socket.nextJson()).toEqual({ type: "closed", reason: "expired" });
  const closed = await socket.waitClosed();
  expect(closed.code).toBe(4000);
  expect(closed.reason).toBe("expired");
}

interface RoomSnapshot {
  state: RoomState | undefined;
  attempts: AttemptWindow | undefined;
  alarm: number | null;
}

function readRoom(stub: DurableObjectStub<PairingRoom>): Promise<RoomSnapshot> {
  return runInDurableObject(stub, async (_instance, ctx) => ({
    state: ctx.storage.kv.get<RoomState>(ROOM_STATE_KEY),
    attempts: ctx.storage.kv.get<AttemptWindow>(ATTEMPTS_KEY),
    alarm: await ctx.storage.getAlarm(),
  }));
}

/** The room is gone; only the nameplate's attempt counter remains, with an alarm to delete it. */
async function expectRoomCleared(stub: DurableObjectStub<PairingRoom>): Promise<void> {
  const { state, attempts, alarm } = await readRoom(stub);
  expect(state).toBeUndefined();
  expect(attempts).toBeDefined();
  expect(alarm).toBe((attempts?.started_at ?? 0) + NAMEPLATE_ATTEMPT_WINDOW_MS);
}

/** Simulates the attempt window having ended. */
function backdateAttempts(stub: DurableObjectStub<PairingRoom>): Promise<void> {
  return runInDurableObject(stub, (_instance, ctx) => {
    const attempts = ctx.storage.kv.get<AttemptWindow>(ATTEMPTS_KEY);
    if (!attempts) {
      throw new Error("attempt counter missing");
    }
    ctx.storage.kv.put(ATTEMPTS_KEY, { ...attempts, started_at: Date.now() - NAMEPLATE_ATTEMPT_WINDOW_MS - 1 });
  });
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

  it("closes both sockets with closed/expired and code 4000, then clears the room", async () => {
    const nameplate = freshNameplate();
    const stub = roomStub(nameplate);
    const { host, guest } = await openPair(nameplate);
    host.send(bytes(3));
    await guest.nextBinary();

    expect(await runDurableObjectAlarm(stub)).toBe(true);
    await expectExpired(host);
    await expectExpired(guest);

    await expectRoomCleared(stub);
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
    await expectRoomCleared(stub);
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
    await expectRoomCleared(stub);
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
    await expectRoomCleared(stub);
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
    await expectRoomCleared(stub);
  });

  it("deletes the attempt counter and the alarm once the attempt window is over", async () => {
    const nameplate = freshNameplate();
    const stub = roomStub(nameplate);
    const host = await openHost(nameplate);
    expect(await runDurableObjectAlarm(stub)).toBe(true);
    await expectExpired(host);
    await expectRoomCleared(stub);

    await backdateAttempts(stub);
    expect(await runDurableObjectAlarm(stub)).toBe(true);
    expect(await readRoom(stub)).toEqual({ state: undefined, attempts: undefined, alarm: null });
  });

  it("cleans up the counter of a nameplate that never had a room", async () => {
    const nameplate = freshNameplate();
    const stub = roomStub(nameplate);
    await expectError(await connect(nameplate, "guest"), "room_not_found");
    await expectRoomCleared(stub);
    expect((await readRoom(stub)).attempts?.count).toBe(1);

    // An early wake-up keeps the counter; the end of the window removes it.
    expect(await runDurableObjectAlarm(stub)).toBe(true);
    await expectRoomCleared(stub);
    await backdateAttempts(stub);
    expect(await runDurableObjectAlarm(stub)).toBe(true);
    expect(await readRoom(stub)).toEqual({ state: undefined, attempts: undefined, alarm: null });
  });
});
