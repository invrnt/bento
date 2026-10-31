# Bento pairing relay

A small, stateless Cloudflare Worker plus one SQLite-backed Durable Object (`PairingRoom`). It forwards opaque binary frames between exactly two Bento devices for at most 10 minutes while they pair. It runs on the Workers Free plan.

The binding contract is [`orchestration/api/pairing-relay-contract.md`](../../orchestration/api/pairing-relay-contract.md). The pairing protocol that runs inside the relay is described in [`orchestration/architecture/telegram-first.md` § Pairing Protocol](../../orchestration/architecture/telegram-first.md).

## What the relay sees

| Sees | Does not see |
| --- | --- |
| The **nameplate** (the first 4-character group of the pairing code). It only picks the room; it is not the SPAKE2 password. | The two secret groups of the pairing code. |
| Each connection's role (`host`/`guest`), connect and disconnect times. | Any plaintext. SPAKE2, key confirmation and AES-256-GCM all run end to end between the devices. |
| How many binary frames each side sends and how big they are. | Keys, keyrings, Telegram login tokens and device names. All of them travel inside encrypted `0x03` frames. |
| The client IP while a request is being handled. Its rate-limit subject (the IPv4 address, or the IPv6 `/64` prefix) is hashed (salted SHA-256) and used only as the rate-limit key. | |

- The relay cannot decrypt or forge frames. If it dropped, reordered or replayed a frame, the devices would notice: key confirmation would fail or the GCM counters would not match, and the pairing would abort.
- **Persisted:** only the minimal room state (`created_at`, `expires_at`, `burned`, `guest_joined`, frame counters) and the nameplate's attempt counter (`started_at`, `count`) in the room's private Durable Object storage. The expiry alarm deletes the room state 10 minutes after the host connected; the counter, and the alarm itself, are deleted 10 minutes after the counter's window started.
- **Logged:** only structured events, such as `{event, role, code, room_age_ms, host_frames, guest_frames}`. The relay never logs frame contents, nameplates, IPs (raw or hashed) or headers.
- **Invocation logs and traces are disabled** in `wrangler.jsonc`, because Cloudflare would otherwise record request URLs (which contain the nameplate), user agents and geo data.

## Behaviour

- `GET /v1/health` returns `200 {"ok": true, "version": "<package.json version>"}`.
- `GET /v1/rooms/{nameplate}?role=host|guest` with `Upgrade: websocket` opens the WebSocket. The nameplate must match `^[0-9A-HJKMNP-TV-Z]{4}$`. The request is routed to `PAIRING_ROOM.idFromName("room:" + nameplate)`.
- HTTP errors are returned before any upgrade, with a JSON body `{"type":"error","code":...}`:

  | Status | Code | When |
  | --- | --- | --- |
  | `404` | `not_found` | Any other path, or an invalid nameplate. |
  | `426` | `upgrade_required` | A room request without a WebSocket upgrade. |
  | `400` | `invalid_role` | `role` is missing, unknown or repeated. |
  | `405` | `method_not_allowed` | Any method other than `GET` on `/v1/health`. |
  | `429` | `rate_limited` | More than 20 room connections per minute from one client (per Cloudflare location). IPv4 clients are counted per address and IPv6 clients per `/64` prefix, since one subscriber usually holds a whole `/64`. IPv4-mapped IPv6 addresses count as IPv4. Includes `Retry-After: 60`. |

- **Room errors** are sent as an `{"type":"error","code":...}` frame, followed by close code `4001` (the close reason is the error code):

  | Code | When |
  | --- | --- |
  | `nameplate_taken` | A host connects to a room that already exists (live or burned), or to a nameplate that has used up its connection budget (see below). |
  | `room_not_found` | A guest connects to a room that does not exist, or that burned before any guest joined. |
  | `room_full` | A guest connects after a guest has already joined, even if the room has since burned. |
  | `expired` | A guest connects after the expiry time but before the alarm ran. |
  | `message_too_large` | A frame larger than 64 KiB. |
  | `protocol` | Binary before the peer joined, the 129th binary frame from one side, or any text frame other than `{"type":"close"}`. |
  | `rate_limited` | A guest connects to a nameplate that has used up its connection budget. |

- **Per-nameplate budget:** each nameplate accepts at most 10 connection attempts (host or guest, from any clients, accepted or rejected) in a 10-minute window that starts with its first attempt. The counter lives in the room's Durable Object and survives room expiry and burning, so squatting a nameplate or burning a room cannot simply be repeated at once, and spreading attempts across many IPs does not help. Further attempts are not counted: hosts get `nameplate_taken` (Bento then picks a fresh nameplate) and guests `rate_limited`.

- **Burning:** a room burns when either side sends `{"type":"close"}`, disconnects, or is closed for an error. Every remaining side receives `peer_left` (unless it sent the close itself), then `{"type":"closed","reason":"burned"}`, and is closed with code `1000`. The nameplate stays blocked until the expiry alarm.
- **Expiry:** 10 minutes after the host connects, both sockets receive `{"type":"closed","reason":"expired"}` and are closed with code `4000`. The room state is then deleted; the attempt counter follows when its window ends. If the alarm fires late, expiry is applied the next time the room is touched.
- **Hibernation:** sockets are accepted through the WebSocket Hibernation API. Each socket's role and room session are stored with `serializeAttachment`, and all other room state lives in Durable Object storage, so an evicted room resumes correctly. Idle rooms are not billed for duration.

## Requirements

Node.js 22 or later (the repository uses Node 24: `export PATH=$HOME/.local/share/mise/installs/node/24.19.0/bin:$PATH`).

```sh
cd apps/relay
npm ci
```

## Local development

```sh
npm run dev          # wrangler dev, serves on http://localhost:8787
curl http://localhost:8787/v1/health
```

To point a local Bento instance at it, set `BENTO_RELAY_URL=ws://localhost:8787`. Everything runs locally in workerd: the Durable Object, the alarms and the rate limiter. No Cloudflare account is needed.

After you edit `wrangler.jsonc`, regenerate the binding and runtime types with `npm run cf-typegen`. `npm run typecheck` fails if `src/worker-configuration.d.ts` is stale.

## Tests

```sh
npm test             # vitest + @cloudflare/vitest-plugin, inside workerd
npm run typecheck    # generated types are current + tsc (src and tests)
```

The suites cover:

- Health, routing and validation.
- Host-first, guest join, third connection, burning and peer disconnect.
- Binary relay in both directions, the size limit and the frame-count limit.
- Text protocol errors.
- Alarm expiry with code `4000`, state cleanup, and late-alarm handling.
- Rate limiting (`429`, IPv4 per address, IPv6 per `/64`) and the per-nameplate connection budget.
- Hibernation (eviction keeps roles, peers and counters).
- Log privacy.

## Deploy (manual, by the owner)

1. Log in once with `npx wrangler login`. For CI, export `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` instead; the token needs *Workers Scripts: Edit* on the account. A Workers Free account is enough.
2. Optional: change `ratelimits[0].namespace_id` in `wrangler.jsonc` if `4271` is already used by another rate-limit binding in the account. Any positive integer that is unique within the account works.
3. Deploy:

   ```sh
   cd apps/relay
   npm ci
   npm test
   npm run deploy     # wrangler deploy; creates the PairingRoom namespace (migration v1)
   ```

   Wrangler prints the URL, for example `https://bento-relay.<your-subdomain>.workers.dev`.
4. Verify with `curl https://bento-relay.<your-subdomain>.workers.dev/v1/health`.
5. Watch live events with `npx wrangler tail bento-relay`. Tail is a live stream shown only to you; it includes Cloudflare request metadata such as the client IP and is not stored. Roll back with `npx wrangler rollback`.

Bump `version` in `package.json` for each release; `/v1/health` reports it.

## Configuring Bento builds (`BENTO_RELAY_URL`)

Bento reads the relay origin from the `relay_url` setting (environment alias `BENTO_RELAY_URL`). Set it to the WebSocket origin, with no path and no trailing slash:

```sh
BENTO_RELAY_URL=wss://bento-relay.<your-subdomain>.workers.dev
```

- Bento appends `/v1/rooms/<nameplate>?role=host|guest` itself.
- For health checks, Bento swaps the scheme to `https://` and appends `/v1/health`.
- Leaving the setting empty disables the relay, and Bento falls back to pairing through the Sync channel.
- To use a custom domain, add a Workers route or custom domain to `wrangler.jsonc` and use `wss://<that-domain>` instead.
