# Pairing Relay Agent (Stage 14)

## Mission

Build the tiny, stateless pairing relay as a Cloudflare Worker + SQLite-backed Durable Object exactly per `orchestration/api/pairing-relay-contract.md`, fully tested locally and ready to deploy with one command.

## First Read

- `AGENTS.md`, `orchestration/execution/telegram-first-program.md`
- `orchestration/api/pairing-relay-contract.md` (binding)
- `orchestration/architecture/telegram-first.md` § Pairing Protocol (context only)

## Retrieve First

Current official Cloudflare docs: Durable Objects (SQLite storage backend, Free plan), WebSocket Hibernation API (`ctx.acceptWebSocket`, `webSocketMessage`, `webSocketClose`, `serializeAttachment`, `getWebSockets`, alarms), Workers rate limiting binding, `wrangler.jsonc` configuration and migrations (`new_sqlite_classes`), and `@cloudflare/vitest-pool-workers`. Use the `cloudflare`, `durable-objects`, `workers-best-practices`, and `wrangler` skills if available. Pin exact package versions.

## Own These Paths

- `apps/relay/**` (new): `package.json`, `package-lock.json`, `wrangler.jsonc`, `tsconfig.json`, `vitest.config.ts`, `src/**`, `test/**`, `README.md`.

## Deliver

- Worker router: `/v1/health`, `/v1/rooms/:nameplate` (strict nameplate regex, role validation, `426` for non-upgrade, `404` otherwise), rate limiting before upgrade, routing to `PAIRING_ROOM.idFromName("room:" + nameplate)`.
- `PairingRoom` Durable Object using hibernatable WebSockets with role stored via `serializeAttachment`; host-first rule; guest join; `room_full`; burn on close/peer leave; 10-minute alarm expiry with `closed` frame and close code `4000`; error frames then close `4001`; binary forwarding with 64 KiB and 128-frames-per-side limits; text frames only `{"type":"close"}`; persisted minimal room state (`created_at`, `burned`, frame counters) so hibernation does not lose it; state cleared on expiry.
- Logging of event names and counts only; never frame contents or raw IPs.
- `README.md`: what the relay sees, local dev (`npm run dev`), tests, deploy (`npm run deploy`), and how to set `BENTO_RELAY_URL` in Bento builds.
- Scripts: `dev`, `test`, `typecheck`, `deploy`, `cf-typegen`.

## Required Tests (vitest-pool-workers)

Health; invalid nameplate/role/path; host-first; guest without host; third connection; binary relay both directions; binary before peer; oversize frame; frame count limit; text protocol errors; close burns room and blocks reuse; peer disconnect notifies other side; alarm expiry closes both with `4000`; rate limit returns `429`.

## Constraints

- TypeScript strict. No database bindings (no D1/KV). No secrets required to run tests.
- Do not deploy to any Cloudflare account; deployment is a documented manual step for the owner.
- Do not touch any path outside `apps/relay`.

## Handoff

Commit on your branch. Report versions, test results, and the exact deploy steps.
