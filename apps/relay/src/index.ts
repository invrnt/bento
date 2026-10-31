import { version } from "../package.json";
import { logEvent } from "./log";
import { NAMEPLATE_PATTERN, isRole } from "./protocol";

export { PairingRoom } from "./room";

const ROOM_PATH = /^\/v1\/rooms\/([^/]+)$/;
const RATE_LIMIT_SALT = "bento-relay/rate-limit/v1:";
const textEncoder = new TextEncoder();

export default {
  async fetch(request, env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/v1/health") {
      if (request.method !== "GET") {
        return jsonResponse(405, { type: "error", code: "method_not_allowed" }, { Allow: "GET" });
      }
      return jsonResponse(200, { ok: true, version });
    }

    const nameplate = ROOM_PATH.exec(url.pathname)?.[1];
    if (nameplate === undefined || !NAMEPLATE_PATTERN.test(nameplate)) {
      return jsonResponse(404, { type: "error", code: "not_found" });
    }

    if (request.method !== "GET" || request.headers.get("Upgrade")?.toLowerCase() !== "websocket") {
      return jsonResponse(426, { type: "error", code: "upgrade_required" }, { Upgrade: "websocket" });
    }

    const roles = url.searchParams.getAll("role");
    const role = roles.length === 1 ? (roles[0] ?? null) : null;
    if (!isRole(role)) {
      return jsonResponse(400, { type: "error", code: "invalid_role" });
    }

    const { success } = await env.ROOM_CONNECT_LIMITER.limit({ key: await clientKey(request) });
    if (!success) {
      logEvent("rate_limited");
      return jsonResponse(429, { type: "error", code: "rate_limited" }, { "Retry-After": "60" });
    }

    // Only the role crosses into the Durable Object: no client headers or IP.
    const room = env.PAIRING_ROOM.get(env.PAIRING_ROOM.idFromName(`room:${nameplate}`));
    return room.fetch(`https://pairing-room/connect?role=${role}`, {
      headers: { Upgrade: "websocket" },
    });
  },
} satisfies ExportedHandler<Env>;

/** Salted SHA-256 of the client IP. Used only as the rate-limit key; never stored or logged. */
async function clientKey(request: Request): Promise<string> {
  const ip = request.headers.get("CF-Connecting-IP") ?? "unknown";
  const digest = await crypto.subtle.digest("SHA-256", textEncoder.encode(RATE_LIMIT_SALT + ip));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return Response.json(body, {
    status,
    headers: { "Cache-Control": "no-store", ...headers },
  });
}
