import { describe, expect, it } from "vitest";

import { MAX_FRAME_BYTES, MAX_FRAMES_PER_SIDE } from "../src/protocol";
import { bytes, connect, expectError, expectPeerLeft, freshNameplate, openHost, openPair } from "./helpers";

describe("binary relay", () => {
  it("forwards frames verbatim in both directions", async () => {
    const { host, guest } = await openPair(freshNameplate());

    const spake = Uint8Array.of(0x01, ...bytes(33, 3));
    host.send(spake);
    expect(await guest.nextBinary()).toEqual(spake);

    const reply = Uint8Array.of(0x01, ...bytes(33, 9));
    guest.send(reply);
    expect(await host.nextBinary()).toEqual(reply);

    const confirm = Uint8Array.of(0x02, ...bytes(32, 5));
    guest.send(confirm);
    expect(await host.nextBinary()).toEqual(confirm);

    // Ordering is preserved for a burst.
    for (let i = 0; i < 10; i += 1) {
      host.send(Uint8Array.of(0x03, i));
    }
    for (let i = 0; i < 10; i += 1) {
      expect(await guest.nextBinary()).toEqual(Uint8Array.of(0x03, i));
    }
    expect(host.pending()).toEqual([]);
    expect(guest.pending()).toEqual([]);
    host.close();
  });

  it("accepts a frame of exactly 64 KiB", async () => {
    const { host, guest } = await openPair(freshNameplate());
    const frame = bytes(MAX_FRAME_BYTES, 11);
    guest.send(frame);
    expect(await host.nextBinary()).toEqual(frame);
    host.close();
  });

  it("rejects binary frames before the peer joined with protocol and burns the room", async () => {
    const nameplate = freshNameplate();
    const host = await openHost(nameplate);
    host.send(bytes(4));
    await expectError(host, "protocol");

    await expectError(await connect(nameplate, "guest"), "room_not_found");
    await expectError(await connect(nameplate, "host"), "nameplate_taken");
  });

  it("rejects an oversize binary frame with message_too_large and notifies the peer", async () => {
    const { host, guest } = await openPair(freshNameplate());
    host.send(bytes(MAX_FRAME_BYTES + 1));
    await expectError(host, "message_too_large");
    await expectPeerLeft(guest);
  });

  it("rejects an oversize text frame with message_too_large", async () => {
    const { host, guest } = await openPair(freshNameplate());
    guest.send(`{"type":"close","pad":"${"x".repeat(MAX_FRAME_BYTES)}"}`);
    await expectError(guest, "message_too_large");
    await expectPeerLeft(host);
  });

  it("allows 128 frames per side and rejects the 129th with protocol", async () => {
    const { host, guest } = await openPair(freshNameplate());

    for (let i = 0; i < MAX_FRAMES_PER_SIDE; i += 1) {
      host.send(Uint8Array.of(i));
      guest.send(Uint8Array.of(255 - i));
    }
    for (let i = 0; i < MAX_FRAMES_PER_SIDE; i += 1) {
      expect(await guest.nextBinary()).toEqual(Uint8Array.of(i));
      expect(await host.nextBinary()).toEqual(Uint8Array.of(255 - i));
    }

    guest.send(Uint8Array.of(0));
    await expectError(guest, "protocol");
    await expectPeerLeft(host);
  });
});

describe("text frames", () => {
  it.each([
    ["plain text", "hello"],
    ["empty string", ""],
    ["empty object", "{}"],
    ["unknown type", '{"type":"ping"}'],
    ["close with extra keys", '{"type":"close","reason":"done"}'],
    ["close in an array", '["close"]'],
    ["JSON string", '"close"'],
    ["JSON null", "null"],
    ["upper-case type", '{"type":"CLOSE"}'],
    ["truncated JSON", '{"type":"close"'],
  ])("rejects %s with protocol and notifies the peer", async (_label, text) => {
    const { host, guest } = await openPair(freshNameplate());
    host.send(text);
    await expectError(host, "protocol");
    await expectPeerLeft(guest);
  });

  it("rejects a non-close text frame before the peer joined", async () => {
    const host = await openHost(freshNameplate());
    host.send('{"type":"hello"}');
    await expectError(host, "protocol");
  });
});
