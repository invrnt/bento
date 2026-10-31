import { describe, expect, it } from "vitest";

import { freshNameplate, randomIp, roomRequest, sleep } from "./helpers";

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
});
