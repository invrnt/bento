# Pairing And Devices Agent (Stage 15)

## Mission

Let a person add a device by typing or scanning one short code, approve it with matching emojis, and have the new device signed in to Telegram and unlocked without touching their phone; provide the Sync-channel fallback; and manage devices including removal with key rotation.

## First Read

- `AGENTS.md`, `orchestration/execution/telegram-first-program.md`
- `orchestration/architecture/telegram-first.md` § Pairing Protocol, § Devices, Removal, Key Rotation, § Keys messages, § Device registration
- `orchestration/api/pairing-relay-contract.md` (whole; you implement the client side)
- `orchestration/api/telegram-first-endpoints.md` § Devices, § Pairing
- Contracts: `domain/{pairing,devices,account,vault,security}.py`, `ports/{pairing,telegram,vault,security,key_store}.py`, `infrastructure/services.py`, `interfaces/http/qr.py`
- Stage 14 results: `adapters/security/pairing_crypto.py`, `adapters/security/vault_crypto.py`, `adapters/repositories/devices.py`, `adapters/fake_telegram/**`, `apps/relay` (behavior reference)

## Own These Paths

- `adapters/pairing/**` (relay client with `websockets`, frame codec, test relay server double under tests)
- `application/{pairing,devices}.py`
- `interfaces/http/routes_{pairing,devices}.py` (+ include lines)
- Tests under `apps/api/tests/{unit,integration,api}/pairing/**` and `.../devices/**`

## Deliver

1. **Relay client** implementing `PairingRelayPort`/`PairingChannelPort` against `settings.relay_url` (`wss://…`; empty → unavailable), handling `welcome`, `peer_joined`, `peer_left`, error codes, close codes, frame limits, timeouts, and clean shutdown.
2. **Host flow** (`POST /pairing/host` → code/link/web_link/QR/expiry): random nameplate + secret (regenerate on `nameplate_taken`), SPAKE2 + confirmations, encrypted application messages, `join_request` handling, SAS exposure, approval → optional `accept_login_token` (refresh on expiry, `telegram_login_failed` fallback), `vault_grant` with `seal_for_device`, record the guest `device` row (synced), completion; reject/cancel/expiry paths; 10-minute TTL.
3. **Guest flow** (`POST /pairing/join` with code or link): connect, SPAKE2, send `join_request` including device identity and (when not signed in) a QR login token from `TelegramAccountPort.start_qr_login`, refresh tokens on request, wait for Telegram authorization (`poll_login`), on `telegram_login_failed` expose `telegram_qr` and `needs_telegram_login`, receive `vault_grant`, `VaultSessionPort.install`, report `bootstrapping` then `completed`.
4. **Fallback via Sync channel**: guest `POST /pairing/request` posts `pair_request`; hosts list `GET /pairing/requests` (own cursor over `.bpair` messages, 15-minute expiry), `review` posts `pair_offer` and shows SAS, `approve` posts `pair_grant` sealed to the guest; guest polls for its offer/grant, shows SAS, installs; guest deletes its pairing messages after completion.
5. **Devices**: list (current flag, last seen), rename, remove (`removed_at` op, terminate Telegram authorization with the "too new" fallback, key rotation: new epoch, `.bkeys` grants for remaining active devices, new recovery code wrapped into a new header via `update_header`, local `update_keyring`), returning the new recovery code once.
6. Pairing sessions live in API memory with a background task per session; terminal sessions are dropped after 10 minutes.

## Required Tests

- Unit: state machine transitions, code generation (alphabet, no ambiguous chars), message validation (hostile/oversized/unknown types), timeouts.
- Integration: two in-process "devices" (separate data dirs/key stores) over a local relay test double (real `websockets` server implementing the contract) and the fake cloud: guest not signed in gets signed in via accepted token and receives the vault; wrong code fails on both sides and burns the room; rejection; token expiry refresh; `telegram_login_failed` path; fallback via Sync channel end to end; device removal rotates keys, other devices receive the grant, removed device cannot open new batches, old recovery code no longer unwraps the new header.
- HTTP tests for every owned endpoint, including that secrets never appear in responses. Full backend suite green.

## Constraints

- Use the crypto adapters through the ports; no new crypto.
- Never log codes, SAS, tokens, or keys.
- Do not implement Telegram adapters, vault creation, sync engine, or UI.

## Handoff

Commit on your branch. Report the endpoints' exact behavior, timeouts, test counts, and anything the web agent must know (polling intervals, states to render).

## Stage 14 Handoff Notes

- `PairingCryptoFactory` sessions produce/consume complete frames including the type byte (`0x01` start = 1+33 bytes, `0x02` confirmation = 1+32, `0x03` messages); counters are implicit; any failure poisons the session; messages require the peer confirmation to be verified first; frames ≤ 64 KiB.
- Fallback pairing uses commit-then-reveal (`FallbackPairingKeysPort.commitment`, `pair_reveal` message, transcript-bound `sas_with`); see the updated architecture section.
- Relay specifics (see `apps/relay/README.md`): nameplates must be upper-case; error frames are followed by close code `4001` with the error code as reason; on burn the peer gets `peer_left` then `{"type":"closed","reason":"burned"}` then close `1000`; `room_full` vs `room_not_found` semantics for burned rooms; `429` with `Retry-After: 60` before upgrade. Health: swap the scheme to `https://` and GET `/v1/health`.
- For integration tests you may run the real relay with `cd apps/relay && npm run dev` only if it works offline in CI; otherwise use the Python relay double.
