import { afterEach, describe, expect, it, vi } from "vitest";

import { connect, expectError, expectPeerLeft, freshNameplate, openPair, roomRequest } from "./helpers";

const ALLOWED_KEYS = new Set(["event", "role", "code", "room_age_ms", "host_frames", "guest_frames"]);

describe("logging", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("emits only event names, roles, ages, frame counts and error codes", async () => {
    const lines: unknown[][] = [];
    for (const method of ["log", "info", "warn", "error", "debug"] as const) {
      vi.spyOn(console, method).mockImplementation((...args: unknown[]) => {
        lines.push(args);
      });
    }

    const nameplate = freshNameplate();
    const ip = "203.0.113.77";
    const secret = "PAYLOAD-MARKER-7f3a";
    const { host, guest } = await openPair(nameplate);
    host.send(new TextEncoder().encode(secret));
    await guest.nextBinary();
    guest.send(`{"type":"${secret}"}`);
    await expectError(guest, "protocol");
    await expectPeerLeft(host);
    await expectError(await connect(nameplate, "guest", ip), "room_full");
    const limited = await roomRequest(nameplate, "admin", { "CF-Connecting-IP": ip });
    expect(limited.status).toBe(400);

    expect(lines.length).toBeGreaterThan(0);
    const events = new Set<string>();
    for (const args of lines) {
      expect(args).toHaveLength(1);
      const entry = args[0] as Record<string, unknown>;
      expect(typeof entry).toBe("object");
      for (const key of Object.keys(entry)) {
        expect(ALLOWED_KEYS.has(key), `unexpected log key ${key}`).toBe(true);
      }
      events.add(String(entry.event));
      const serialized = JSON.stringify(entry);
      expect(serialized).not.toContain(nameplate);
      expect(serialized).not.toContain(ip);
      expect(serialized).not.toContain(secret);
    }
    expect([...events].sort()).toEqual(
      ["connection_rejected", "frame_rejected", "peer_joined", "room_burned", "room_opened"].sort(),
    );
  });
});
