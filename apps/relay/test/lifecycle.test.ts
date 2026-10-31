import { evictDurableObject, runInDurableObject } from "cloudflare:test";
import { describe, expect, it } from "vitest";

import { ROOM_TTL_MS } from "../src/protocol";
import { ROOM_STATE_KEY, type RoomState } from "../src/room";
import {
  bytes,
  connect,
  expectError,
  expectPeerLeft,
  freshNameplate,
  openHost,
  openPair,
  roomStub,
} from "./helpers";

describe("host first", () => {
  it("welcomes the host with an ISO expiry 10 minutes ahead", async () => {
    const before = Date.now();
    const host = await connect(freshNameplate(), "host");
    const welcome = await host.nextJson();
    expect(welcome).toEqual({ type: "welcome", role: "host", expires_at: expect.any(String) });
    const expiresAt = Date.parse(welcome.expires_at as string);
    expect(new Date(expiresAt).toISOString()).toBe(welcome.expires_at);
    expect(expiresAt).toBeGreaterThanOrEqual(before + ROOM_TTL_MS);
    expect(expiresAt).toBeLessThanOrEqual(Date.now() + ROOM_TTL_MS);
    host.close();
  });

  it("rejects a second host with nameplate_taken and keeps the first", async () => {
    const nameplate = freshNameplate();
    const host = await openHost(nameplate);
    const intruder = await connect(nameplate, "host");
    await expectError(intruder, "nameplate_taken");

    const guest = await connect(nameplate, "guest");
    expect(await guest.nextJson()).toMatchObject({ type: "welcome", role: "guest" });
    expect(await host.nextJson()).toEqual({ type: "peer_joined" });
    host.close();
  });

  it("rejects a guest when no host is present with room_not_found", async () => {
    const guest = await connect(freshNameplate(), "guest");
    await expectError(guest, "room_not_found");
  });
});

describe("guest join", () => {
  it("sends welcome then peer_joined to the guest and peer_joined to the host", async () => {
    const nameplate = freshNameplate();
    const host = await connect(nameplate, "host");
    const hostWelcome = await host.nextJson();

    const guest = await connect(nameplate, "guest");
    const guestWelcome = await guest.nextJson();
    expect(guestWelcome).toEqual({ type: "welcome", role: "guest", expires_at: hostWelcome.expires_at });
    expect(await guest.nextJson()).toEqual({ type: "peer_joined" });
    expect(await host.nextJson()).toEqual({ type: "peer_joined" });
    host.close();
  });

  it("rejects a third connection with room_full (guest) or nameplate_taken (host)", async () => {
    const nameplate = freshNameplate();
    const { host, guest } = await openPair(nameplate);

    await expectError(await connect(nameplate, "guest"), "room_full");
    await expectError(await connect(nameplate, "host"), "nameplate_taken");

    // The existing pair is untouched.
    host.send(bytes(8));
    expect(await guest.nextBinary()).toEqual(bytes(8));
    expect(host.pending()).toEqual([]);
    host.close();
  });
});

describe("burning", () => {
  it("close command burns the room for both sides and blocks reuse", async () => {
    const nameplate = freshNameplate();
    const { host, guest } = await openPair(nameplate);

    guest.send(JSON.stringify({ type: "close" }));
    expect(await guest.nextJson()).toEqual({ type: "closed", reason: "burned" });
    expect((await guest.waitClosed()).code).toBe(1000);
    await expectPeerLeft(host);

    await expectError(await connect(nameplate, "host"), "nameplate_taken");
    await expectError(await connect(nameplate, "guest"), "room_full");

    const state = await runInDurableObject(roomStub(nameplate), (_instance, ctx) =>
      ctx.storage.kv.get<RoomState>(ROOM_STATE_KEY),
    );
    expect(state?.burned).toBe(true);
  });

  it("host close before a guest joined burns the room", async () => {
    const nameplate = freshNameplate();
    const host = await openHost(nameplate);

    host.send('{ "type" : "close" }');
    expect(await host.nextJson()).toEqual({ type: "closed", reason: "burned" });
    expect((await host.waitClosed()).code).toBe(1000);

    await expectError(await connect(nameplate, "guest"), "room_not_found");
    await expectError(await connect(nameplate, "host"), "nameplate_taken");
  });

  it("guest disconnect notifies the host with peer_left", async () => {
    const nameplate = freshNameplate();
    const { host, guest } = await openPair(nameplate);
    guest.close(1000, "done");
    await expectPeerLeft(host);
    await expectError(await connect(nameplate, "guest"), "room_full");
  });

  it("host disconnect notifies the guest with peer_left", async () => {
    const nameplate = freshNameplate();
    const { host, guest } = await openPair(nameplate);
    host.close(1001, "going away");
    await expectPeerLeft(guest);
    await expectError(await connect(nameplate, "host"), "nameplate_taken");
  });

  it("host disconnect before a guest joined burns the room", async () => {
    const nameplate = freshNameplate();
    const host = await openHost(nameplate);
    host.close();
    await host.waitClosed();

    // The close event is delivered to the Durable Object asynchronously.
    const isBurned = (): Promise<boolean | undefined> =>
      runInDurableObject(roomStub(nameplate), (_instance, ctx) => ctx.storage.kv.get<RoomState>(ROOM_STATE_KEY)?.burned);
    await expect.poll(isBurned).toBe(true);
    await expectError(await connect(nameplate, "guest"), "room_not_found");
  });
});

describe("hibernation", () => {
  it("keeps roles, peers and frame counters across eviction", async () => {
    const nameplate = freshNameplate();
    const stub = roomStub(nameplate);
    const { host, guest } = await openPair(nameplate);

    for (let i = 0; i < 100; i += 1) {
      host.send(bytes(4, i));
      expect(await guest.nextBinary()).toEqual(bytes(4, i));
    }

    await evictDurableObject(stub);

    guest.send(bytes(16, 7));
    expect(await host.nextBinary()).toEqual(bytes(16, 7));
    for (let i = 100; i < 128; i += 1) {
      host.send(bytes(4, i));
      expect(await guest.nextBinary()).toEqual(bytes(4, i));
    }

    // The persisted counter survived eviction: the 129th host frame is refused.
    host.send(bytes(4));
    await expectError(host, "protocol");
    await expectPeerLeft(guest);

    const state = await runInDurableObject(stub, (_instance, ctx) => ctx.storage.kv.get<RoomState>(ROOM_STATE_KEY));
    expect(state).toMatchObject({ burned: true, host_frames: 128, guest_frames: 1 });
  });
});
