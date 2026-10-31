import { runInDurableObject } from "cloudflare:test";
import { describe, expect, it } from "vitest";

import { rateLimitSubject } from "../src/client-address";
import { NAMEPLATE_ATTEMPT_LIMIT, NAMEPLATE_ATTEMPT_WINDOW_MS } from "../src/protocol";
import { ATTEMPTS_KEY, type AttemptWindow } from "../src/room";
import { connect, expectError, freshNameplate, openHost, randomIp, roomRequest, roomStub, sleep } from "./helpers";

const LIMIT = 20;
const WINDOW_MS = 60_000;

/** The local limiter uses wall-clock aligned windows; avoid straddling a boundary. */
async function waitForRoomInWindow(neededMs: number): Promise<void> {
  const remaining = WINDOW_MS - (Date.now() % WINDOW_MS);
  if (remaining < neededMs) {
    await sleep(remaining + 50);
  }
}

describe("rate limiting", () => {
  it(`allows ${LIMIT} room connections per minute per client IP, then returns 429 before upgrading`, async () => {
    await waitForRoomInWindow(10_000);
    const ip = randomIp();

    for (let i = 0; i < LIMIT; i += 1) {
      const response = await roomRequest(freshNameplate(), "guest", { "CF-Connecting-IP": ip });
      expect(response.status).toBe(101);
      response.webSocket?.accept();
      response.webSocket?.close(1000, "done");
    }

    const limited = await roomRequest(freshNameplate(), "host", { "CF-Connecting-IP": ip });
    expect(limited.status).toBe(429);
    expect(limited.webSocket).toBeNull();
    expect(limited.headers.get("Retry-After")).toBe("60");
    expect(await limited.json()).toEqual({ type: "error", code: "rate_limited" });

    // Other clients are unaffected.
    const other = await roomRequest(freshNameplate(), "guest", { "CF-Connecting-IP": randomIp() });
    expect(other.status).toBe(101);
    other.webSocket?.accept();
    other.webSocket?.close(1000, "done");
  }, 30_000);

  it("does not count requests rejected before the limiter", async () => {
    await waitForRoomInWindow(10_000);
    const ip = randomIp();
    for (let i = 0; i < LIMIT + 5; i += 1) {
      const response = await roomRequest(freshNameplate(), "admin", { "CF-Connecting-IP": ip });
      expect(response.status).toBe(400);
    }
    const response = await roomRequest(freshNameplate(), "guest", { "CF-Connecting-IP": ip });
    expect(response.status).toBe(101);
    response.webSocket?.accept();
    response.webSocket?.close(1000, "done");
  }, 30_000);

  it("limits IPv6 clients by /64 prefix", async () => {
    await waitForRoomInWindow(10_000);
    const hex = () => Array.from(crypto.getRandomValues(new Uint16Array(1)), (word) => word.toString(16))[0];
    const prefix = `2001:db8:${hex()}:${hex()}`;

    for (let i = 0; i < LIMIT; i += 1) {
      // Every request comes from a different address inside the same /64.
      const response = await roomRequest(freshNameplate(), "guest", { "CF-Connecting-IP": `${prefix}:${hex()}:${hex()}::${i + 1}` });
      expect(response.status).toBe(101);
      response.webSocket?.accept();
      response.webSocket?.close(1000, "done");
    }
    const limited = await roomRequest(freshNameplate(), "guest", { "CF-Connecting-IP": `${prefix}:ffff:ffff:ffff:ffff` });
    expect(limited.status).toBe(429);

    const neighbour = await roomRequest(freshNameplate(), "guest", { "CF-Connecting-IP": `2001:db8:${hex()}:${hex()}::1` });
    expect(neighbour.status).toBe(101);
    neighbour.webSocket?.accept();
    neighbour.webSocket?.close(1000, "done");
  }, 30_000);
});

describe("rate-limit subjects", () => {
  it("uses the IPv4 address and the IPv6 /64 prefix", () => {
    expect(rateLimitSubject("203.0.113.7")).toBe("v4:203.0.113.7");
    expect(rateLimitSubject("2001:db8:1:2::1")).toBe("v6:2001:0db8:0001:0002::/64");
    expect(rateLimitSubject("2001:DB8:1:2:aaaa:bbbb:cccc:dddd")).toBe("v6:2001:0db8:0001:0002::/64");
    expect(rateLimitSubject("2001:db8:1::")).toBe("v6:2001:0db8:0001:0000::/64");
    expect(rateLimitSubject("::1")).toBe("v6:0000:0000:0000:0000::/64");
    expect(rateLimitSubject("::ffff:203.0.113.7")).toBe("v4:203.0.113.7");
    expect(rateLimitSubject("::ffff:cb00:7107")).toBe("v4:203.0.113.7");
    expect(rateLimitSubject("64:ff9b::203.0.113.7")).toBe("v6:0064:ff9b:0000:0000::/64");
    expect(rateLimitSubject("fe80::1%eth0")).toBe("v6:fe80:0000:0000:0000::/64");
  });

  it("puts anything malformed into one shared bucket", () => {
    for (const value of [null, "", "unknown", "256.0.0.1", "01.2.3.4", "1.2.3", "2001:db8::1::2", "2001:db8:1:2:3:4:5:6:7", "12345::1", "2001:db8:g::1", "1:2:3:4:5:6:7:8::"]) {
      expect(rateLimitSubject(value)).toBe("unknown");
    }
  });
});

describe("per-nameplate connection limit", () => {
  it(`accepts ${NAMEPLATE_ATTEMPT_LIMIT} attempts per nameplate per window from any clients, then refuses more`, async () => {
    const nameplate = freshNameplate();
    for (let i = 0; i < NAMEPLATE_ATTEMPT_LIMIT; i += 1) {
      // A different client each time: only the nameplate budget applies.
      await expectError(await connect(nameplate, "guest", randomIp()), "room_not_found");
    }
    await expectError(await connect(nameplate, "guest", randomIp()), "rate_limited");
    // Hosts are told the nameplate is taken, so Bento retries with a fresh nameplate.
    await expectError(await connect(nameplate, "host", randomIp()), "nameplate_taken");

    const stub = roomStub(nameplate);
    const attempts = await runInDurableObject(stub, (_instance, ctx) => ctx.storage.kv.get<AttemptWindow>(ATTEMPTS_KEY));
    expect(attempts?.count).toBe(NAMEPLATE_ATTEMPT_LIMIT);

    // Once the window has passed, the nameplate works again.
    await runInDurableObject(stub, (_instance, ctx) => {
      ctx.storage.kv.put(ATTEMPTS_KEY, { started_at: Date.now() - NAMEPLATE_ATTEMPT_WINDOW_MS - 1, count: NAMEPLATE_ATTEMPT_LIMIT });
    });
    const host = await openHost(nameplate);
    host.close();
  });

  it("keeps counting across room expiry so a nameplate cannot be squatted again at once", async () => {
    const nameplate = freshNameplate();
    const stub = roomStub(nameplate);
    for (let i = 0; i < NAMEPLATE_ATTEMPT_LIMIT - 1; i += 1) {
      await expectError(await connect(nameplate, "guest", randomIp()), "room_not_found");
    }
    const host = await openHost(nameplate);
    await runInDurableObject(stub, async (instance) => {
      await instance.alarm();
    });
    expect(await host.nextJson()).toEqual({ type: "closed", reason: "expired" });
    await expectError(await connect(nameplate, "host", randomIp()), "nameplate_taken");
  });
});
