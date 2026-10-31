# Sync Engine Agent (Stage 15)

## Mission

Make every device converge: capture local changes, publish encrypted batches to the Sync channel, apply peers' batches with field-level last-writer-wins, snapshot for fast bootstrap, apply key grants, and expose sync status.

## First Read

- `AGENTS.md`, `orchestration/execution/telegram-first-program.md`
- `orchestration/architecture/telegram-first.md` § Sync Protocol, § Keys messages, § Integration Rules (binding)
- `orchestration/api/telegram-first-endpoints.md` § Sync
- Contracts: `domain/sync.py`, `domain/vault.py`, `ports/{sync,vault,telegram,security}.py`, `infrastructure/{runtime,services}.py`
- Stage 14 results: ORM models + migration `0004`, `adapters/fake_telegram/**`, `adapters/security/vault_crypto.py`
- Existing repositories, `adapters/media/catalog.py`, search adapters (`adapters/search/**`), indexing services (`application/indexing/**`), worker (`interfaces/worker/**`)

## Own These Paths

- `application/sync/**`, `adapters/sync/**`
- Change-capture hook: `infrastructure/db/engine.py` (optional listener installation only) and the composition points that create session factories for API and worker (one-line wiring)
- `application/indexing/{ocr,embedding}.py`: emit `asset_index` ops after successful indexing (optional recorder dependency; no other behavior change)
- `interfaces/http/routes_sync.py` (+ include line), worker sync loop module (+ registration), `domain/jobs.py` append `sync_snapshot`
- `infrastructure/services.py`: implement `get_sync_status_provider` and its part of `reset_services`
- Tests under `apps/api/tests/{unit,integration}/sync/**`

## Deliver

1. **HLC source** persisted in `sync_state` (`last_hlc`), using the domain `hlc_tick`/`hlc_receive`.
2. **Change capture** (`before_flush`) for the tracked models with the column→field mapping, JSON-safe values (ISO datetimes, `parts` as list of dicts with `index, channel_id, message_id, size_bytes`), skip in `sync_apply` sessions, skip when the vault is not ready, `purge` op on deletes, local-only blob refs ignored.
3. **Outbox flush** with batching thresholds, the hold rule, `seal_json(purpose=SYNC)`, `post_sync_document(BATCH)`, deletion of outbox rows only after confirmation; resilient to crashes (re-sent ops are idempotent by HLC).
4. **Pull/apply**: list Sync messages after the cursor, route by kind (`batch` → apply; `snapshot` → ignore unless bootstrapping; `keys` → apply grant addressed to this device via `VaultSessionPort.update_keyring`; `pairing`/`header` → skip), skip own batches, `sync_applied_batches` idempotency, LWW per field with clocks, purge tombstones, folder-cycle repair, unknown-reference tolerance, `asset_index` application through the search adapters (FTS text, OCR blocks/pdf pages, vectors), advance cursor and HLC.
5. **Snapshots**: create per thresholds when caught up (entity states with clocks + purge list, `seal_json(purpose=SNAPSHOT)`, `.bsnap`), then `VaultSessionPort.update_header` with the new pointer; **bootstrap** a device without cursor from the header's snapshot, then pull the tail; progress in `sync_state` for `/sync/status` and `VaultStatus.bootstrapping`.
6. **Initial publish** when a vault becomes ready on a device with existing local data: full-state upserts for every entity (respecting the hold rule), once per vault.
7. **Worker loop**: flush → pull → snapshot check → `wait_for_activity` (30 s) with backoff on errors, `TelegramFloodWaitError` → `waiting` state, offline detection; cross-process `request_sync` (API writes a `sync_requested_at` marker the loop checks every second).
8. **Status provider + endpoints** `/sync/status`, `/sync/now`.

## Required Tests

- Unit: capture diffs (insert/update/delete, untracked columns, local blob refs, apply-session skip), hold rule ordering, LWW with concurrent edits, delete-vs-rename, restore after delete, purge terminality, folder cycles, idempotent re-application, HLC monotonicity across restarts.
- Integration with the fake cloud and two SQLite databases (two devices of one account): create/rename/move/favorite/album/delete/restore/purge converge in both directions with interleaved concurrent edits; snapshot bootstrap of a third device equals the others' state; keys grant updates the keyring; large batch splitting; crash between post and outbox delete.
- HTTP tests for the sync endpoints. Full backend suite green.

## Constraints

- Application code depends on ports only; adapters may use SQLAlchemy.
- Never send plaintext metadata to Telegram; every Sync document is sealed.
- Do not implement Telegram adapters, pairing, backup, or remote uploads.

## Handoff

Commit on your branch. Report wiring points, sync_state keys, status semantics, test counts, and anything other agents must call.
