# Telegram Contracts And Platform Agent (Stage 14)

## Mission

Turn the frozen domain types and ports into a working persistence and runtime platform that every Stage 15 agent builds on: ORM models, Alembic migration, settings registry additions, blob part persistence, the Telegram runtime factory, and a filesystem-backed fake Telegram cloud good enough to run two Bento devices against one simulated account.

## First Read

- `AGENTS.md`, `orchestration/execution/telegram-first-program.md`
- `orchestration/architecture/telegram-first.md` (whole document)
- `orchestration/api/telegram-first-endpoints.md` (Account, Vault, Development sections)
- Frozen contracts (read, do not redesign; you may add small helpers and fix defects, and must list every change in your handoff): `apps/api/src/bento/domain/{account,telegram,vault,sync,pairing,devices,backup,trash,activity,security,storage}.py`, `apps/api/src/bento/ports/{telegram,key_store,security,sync,pairing,backup,trash,blob_store}.py`

## Own These Paths

- `apps/api/src/bento/infrastructure/db/models.py` (additions only)
- `apps/api/migrations/versions/0004_telegram_first.py`
- `apps/api/src/bento/adapters/repositories/mappers.py`, `apps/api/src/bento/adapters/media/catalog.py` (BlobRef parts/epoch/format persistence only)
- `apps/api/src/bento/domain/settings_registry.py`, `apps/api/src/bento/infrastructure/settings.py` (additions only; legacy Bot API fields stay until Stage 15)
- `apps/api/src/bento/infrastructure/runtime.py`
- `apps/api/src/bento/adapters/fake_telegram/**`
- `apps/api/src/bento/interfaces/http/routes_dev.py` + its single include line in `interfaces/http/routes.py`
- `apps/api/tests/unit/contracts/**`, `apps/api/tests/integration/fake_telegram/**`, `apps/api/tests/integration/db/test_migration_0004.py`

## Deliver

1. **ORM models + migration `0004`** (upgrade and downgrade):
   - `blob_parts(blob_ref_id FK blob_refs.id ON DELETE CASCADE, part_index, channel_id, message_id, size_bytes, PK(blob_ref_id, part_index))`.
   - `blob_refs` new columns: `key_epoch INTEGER NULL`, `format_version INTEGER NOT NULL DEFAULT 1`, `remote_deleted_at DATETIME NULL`.
   - `sync_outbox(seq INTEGER PK AUTOINCREMENT, op_id UNIQUE, hlc, entity, entity_id, kind, fields JSON, size_bytes, created_at)`.
   - `sync_field_clocks(entity, entity_id, field, hlc, PK(entity, entity_id, field))`.
   - `sync_purged(entity, entity_id, hlc, purged_at, PK(entity, entity_id))`.
   - `sync_applied_batches(batch_id PK, message_id, applied_at)`.
   - `sync_state(key PK, value TEXT, updated_at)`.
   - `devices(id PK, name, platform, public_key, telegram_auth_hash BIGINT NULL, added_at, last_seen_at NULL, removed_at NULL, is_current BOOL)`.
   - `backup_sources(id PK, path UNIQUE, label, enabled, created_at, updated_at, last_scan_at NULL, error_code NULL)`.
   - `backup_files(source_id FK CASCADE, relative_path, size_bytes, mtime_ns BIGINT, sha256 NULL, asset_id NULL, state, error_code NULL, updated_at, PK(source_id, relative_path))` + index on `state`.
   - `upload_sessions(id PK, asset_id NULL, blob_ref_id NULL, source_path, blob_kind, epoch, file_salt, nonce_prefix, segment_size, plaintext_size, ciphertext_size, completed_parts JSON, state, error_code NULL, created_at, updated_at)`.
   - `cache_entries(blob_ref_id PK, path, size_bytes, last_accessed_at)` + index on `last_accessed_at`.
   - `inbox_items(message_id PK, state, asset_id NULL, error_code NULL, created_at, updated_at)`.
2. **BlobRef persistence**: mappers/catalog read and write `parts`, `encryption.key_epoch`, `encryption.format_version`; existing local and legacy Telegram refs keep working (parts empty).
3. **Settings registry additions** (with matching `Settings` fields, defaults, constraints; label/help keys follow `settings.<key>.label`):
   - `storage_backend` choices become `local|telegram|fake`; validation rejects `fake` when `environment == "production"`.
   - `telegram_parallel_transfers` int 1..4 default 1 (`performance`), `telegram_part_size_mb` int 64..1950 default 512 (`advanced`), `relay_url` string default `""` (`advanced`, alias `BENTO_RELAY_URL`), `public_site_url` string default `""` (`advanced`, alias `BENTO_PUBLIC_SITE_URL`), `inbox_keep_hours` int 0..720 default 24 (`telegram`), `trash_retention_days` int 1..365 default 30 (`storage`), `cache_max_gb` number 1..2048 default 10 (`storage`), `backup_pause_on_battery` bool default true (`backup`), `backup_bandwidth_limit_kbps` int 0..1000000 default 0 (`backup`), `fake_telegram_dir` path default `""` (`advanced`, alias `BENTO_FAKE_TELEGRAM_DIR`, empty means `<data_dir>/fake-telegram`).
   - Keep every existing test green; update settings tests only where the registry snapshot is asserted.
4. **`infrastructure/runtime.py`**: `TelegramRuntime` dataclass `{account: TelegramAccountPort, transport: VaultTransportPort, parts: RemotePartStorePort, chats: TelegramChatsPort}` and `get_telegram_runtime(settings, key_store) -> TelegramRuntime | None` (process-wide cache, `None` for `local`, the fake for `fake`, and for `telegram` a call into `bento.infrastructure.mtproto.runtime.create_mtproto_runtime` if that module exists, otherwise raise `TelegramNotAvailableError`). Also `reset_telegram_runtime()` for tests and account reloads.
5. **Fake Telegram cloud** (`adapters/fake_telegram/`), implementing `TelegramAccountPort`, `VaultTransportPort`, `RemotePartStorePort`, `TelegramChatsPort` over a directory:
   - Multi-process safe: atomic writes (`os.replace`), an exclusive lock file per mutation (POSIX `fcntl.flock`, Windows `msvcrt.locking`), monotonically increasing message ids per channel.
   - Account: one simulated user (`user_id 777000001`, "Ana Demo"). Each Bento instance is a separate authorization whose id is stored in the key store under `telegram.session`. `start_qr_login` returns `tg://login?token=<b64url>` with a 30 s expiry and auto-approves after 2 s unless `BENTO_FAKE_TELEGRAM_MANUAL_LOGIN=1`; `approve_pending_login()` exists for the dev route and tests; phone login accepts code `12345`; password `bento-demo` when the simulated account has 2FA enabled (`BENTO_FAKE_TELEGRAM_2FA=1`). `accept_login_token` authorizes another instance's pending token (shared via the directory). `terminate_authorization` signs that instance out. `list_authorizations` returns all instances.
   - Channels with `about`, title, creator flag, pinned message id, text and document messages, reactions, deletion; chat folder and mute/archive recorded as metadata. `find_vaults` follows the real discovery rules (title prefix + about markers).
   - `wait_for_activity` polls the channel log mtime every 200 ms.
   - Chats: Saved Messages plus two seeded chats with a few generated media items (small PNG/JPEG/MP4 placeholders produced at runtime, no binary fixtures committed) so import and share can be demoed.
6. **Dev route** `POST /api/dev/fake-telegram/approve-login`, registered only when `storage_backend == "fake"` and `environment != "production"`.
7. **Tests**: domain contract tests (HLC tick/receive ordering and string order, `fields_to_apply`, `SyncOperation` validation, `PairingCode.parse` for codes/links/aliases/invalid input, `VaultHeader` JSON round-trip and canonical bytes), migration upgrade/downgrade on a temp DB, BlobRef parts round-trip through the catalog, fake cloud: two "devices" in two processes (use `multiprocessing`) see each other's Sync messages, QR approval, accept-login-token, authorization termination, chat media listing/download.

## Constraints

- Domain stays stdlib-only; the import-boundary test must pass.
- No real network calls anywhere in tests.
- Do not implement sync, pairing, backup, crypto, or MTProto behavior—only contracts, persistence, runtime selection, and the fake.
- Keep the full backend suite green (`cd apps/api && uv run pytest`).

## Handoff

Commit on your branch. Report: files changed, any contract adjustments (with reasons), tests run with counts, and anything Stage 15 agents must know (fake cloud env vars, helper APIs).
