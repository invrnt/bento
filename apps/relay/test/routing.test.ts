import { runInDurableObject } from "cloudflare:test";
import { env } from "cloudflare:workers";
import { describe, expect, it } from "vitest";

import { version } from "../package.json";
import worker from "../src/index";
import { ROOM_STATE_KEY, type RoomState } from "../src/room";
import { freshNameplate, openHost, relayFetch, roomRequest, roomStub } from "./helpers";

// Typed like a request arriving at the Worker (docs: "Write your first test").
const IncomingRequest = Request<unknown, IncomingRequestCfProperties>;

describe("GET /v1/health", () => {
  it("returns ok and the package version", async () => {
    const response = await relayFetch("/v1/health");
    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toContain("application/json");
    expect(await response.json()).toEqual({ ok: true, version });
    expect(version).toMatch(/^\d+\.\d+\.\d+$/);
  });

  it("rejects other methods", async () => {
    const response = await relayFetch("/v1/health", { method: "POST" });
    expect(response.status).toBe(405);
    expect(response.headers.get("Allow")).toBe("GET");
  });
});

describe("routing", () => {
  it.each([
    "/",
    "/v1",
    "/v1/",
    "/v1/health/",
    "/v1/rooms",
    "/v1/rooms/",
    "/v1/rooms/K7Q2/",
    "/v1/rooms/K7Q2/extra",
    "/v2/rooms/K7Q2",
    "/rooms/K7Q2",
  ])("returns 404 for unknown path %s", async (path) => {
    const response = await relayFetch(path, { headers: { Upgrade: "websocket" } });
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ type: "error", code: "not_found" });
  });

  it.each([
    ["lower case", "k7q2"],
    ["too short", "K7Q"],
    ["too long", "K7Q2M"],
    ["excluded letter I", "K7QI"],
    ["excluded letter L", "K7QL"],
    ["excluded letter O", "K7QO"],
    ["excluded letter U", "K7QU"],
    ["punctuation", "K7Q-"],
    ["percent-encoded", "K7Q%32"],
  ])("returns 404 for an invalid nameplate (%s)", async (_label, nameplate) => {
    const response = await roomRequest(nameplate, "host");
    expect(response.status).toBe(404);
    expect(response.webSocket).toBeNull();
  });

  it("returns 426 for a non-upgrade request to a room", async () => {
    const response = await relayFetch(`/v1/rooms/${freshNameplate()}?role=host`);
    expect(response.status).toBe(426);
    expect(response.headers.get("Upgrade")).toBe("websocket");
    expect(await response.json()).toEqual({ type: "error", code: "upgrade_required" });
  });

  it("returns 426 for a non-GET upgrade request", async () => {
    // exports.default.fetch() turns WebSocket upgrades into GETs, so call the handler directly.
    const request = new IncomingRequest(`https://relay.test/v1/rooms/${freshNameplate()}?role=host`, {
      method: "POST",
      headers: { Upgrade: "websocket" },
    });
    const response = await worker.fetch(request, env);
    expect(response.status).toBe(426);
  });

  it.each([
    ["missing", null],
    ["unknown", "admin"],
    ["upper case", "HOST"],
    ["empty", ""],
    ["duplicated", "host&role=guest"],
  ])("returns 400 for an invalid role (%s)", async (_label, role) => {
    const response = await roomRequest(freshNameplate(), role);
    expect(response.status).toBe(400);
    expect(response.webSocket).toBeNull();
    expect(await response.json()).toEqual({ type: "error", code: "invalid_role" });
  });

  it("routes a nameplate to the Durable Object named room:<nameplate>", async () => {
    const nameplate = freshNameplate();
    const host = await openHost(nameplate);
    const state = await runInDurableObject(roomStub(nameplate), (_instance, ctx) =>
      ctx.storage.kv.get<RoomState>(ROOM_STATE_KEY),
    );
    expect(state).toMatchObject({ burned: false, guest_joined: false, host_frames: 0, guest_frames: 0 });
    host.close();
  });
});
