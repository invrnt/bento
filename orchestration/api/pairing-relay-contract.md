# Pairing Relay Contract

`apps/relay` is a Cloudflare Worker with one Durable Object class (`PairingRoom`, SQLite-backed so it runs on the Workers Free plan). It relays opaque binary frames between exactly two Bento devices for a short time. It never stores, parses, or logs frame contents.

## Endpoints

- `GET /v1/health` → `200 {"ok": true, "version": "<semver>"}`.
- `GET /v1/rooms/{nameplate}?role=host|guest` with `Upgrade: websocket` → WebSocket. Any other path → `404`. Non-upgrade request to a room → `426`.

`nameplate` matches `^[0-9A-HJKMNP-TV-Z]{4}$` (Crockford Base32, upper case). The Worker routes to the Durable Object `idFromName("room:" + nameplate)`.

## Room lifecycle

1. The host must connect first. If a host is already present, the room was used in the last 10 minutes, or the nameplate's connection budget is spent (§ Limits and abuse) → `nameplate_taken`.
2. A guest connecting to a room without a host → `room_not_found`. A third connection → `room_full`.
3. The room expires 10 minutes after the host connects (Durable Object alarm). Expiry sends `{"type":"closed","reason":"expired"}` and closes both sockets with code `4000`.
4. When either side sends `{"type":"close"}` or disconnects after the peer joined, the other side receives `{"type":"peer_left"}` and the room is burned (cannot be reused until expiry).
5. Room state is cleared after expiry/burn. The nameplate's attempt counter (`{started_at, count}`, no client data) stays until its 10-minute window ends, when the alarm deletes it and nothing persists.

## Frames

Server → client (text, JSON):

- `{"type":"welcome","role":"host|guest","expires_at":"ISO"}`
- `{"type":"peer_joined"}` sent to the host when the guest connects, and to the guest immediately after `welcome` if the host is present.
- `{"type":"peer_left"}`
- `{"type":"error","code":"nameplate_taken|room_not_found|room_full|expired|rate_limited|message_too_large|protocol"}` followed by close `4001`.
- `{"type":"closed","reason":"expired|burned"}`

Client → server:

- Binary frames are forwarded verbatim to the peer. Max 64 KiB per frame, max 128 frames per side per room. Binary frames before the peer joined are rejected with `protocol`.
- Text frame `{"type":"close"}` burns the room.
- Any other text frame → `protocol`.

## Limits and abuse

- Use the WebSocket Hibernation API (`ctx.acceptWebSocket`, `serializeAttachment`) so idle rooms are not billed for duration.
- Rate limit per client (hashed, never stored raw): 20 room connections per minute using the Workers rate limiting binding; excess returns `429` before upgrade. The key is the IPv4 address, or the IPv6 `/64` prefix (one subscriber usually controls a whole `/64`); IPv4-mapped IPv6 counts as IPv4, malformed values share one bucket.
- Per-nameplate budget, tracked in the room's Durable Object: at most 10 connection attempts (host or guest, any client, accepted or rejected) per nameplate in a fixed 10-minute window starting at the first attempt. It survives room expiry and burning, so squatting or burning cannot simply be repeated and spreading attempts over many IPs does not help. Over budget (not counted further): hosts get `nameplate_taken` (clients retry with a fresh nameplate), guests get `rate_limited`, both as an error frame followed by close `4001`.
- No authentication: security comes from SPAKE2 at the endpoints. The relay cannot decrypt or forge frames.
- Logs contain only event names, room age, frame counts, and error codes.

## Inner protocol (implemented by Bento, opaque to the relay)

Binary frame = `type u8 || payload`:

- `0x01` SPAKE2 message (raw bytes from `spake2`).
- `0x02` key confirmation (32-byte HMAC).
- `0x03` application message: `AES-256-GCM(session_key_dir, nonce = 4 zero bytes || u64 BE counter, json)`; counters start at 0 per direction and must strictly increase.

Application message types are defined in `architecture/telegram-first.md` § Pairing Protocol.

## Deployment

- `wrangler.jsonc` with `compatibility_date` pinned, `durable_objects.bindings` (`PAIRING_ROOM`), `migrations` with `new_sqlite_classes`, and the rate limit binding.
- `npm run deploy` deploys; the resulting URL is configured in Bento builds as `BENTO_RELAY_URL` (e.g. `wss://bento-relay.<account>.workers.dev`).
- Tests use `@cloudflare/vitest-pool-workers`.
