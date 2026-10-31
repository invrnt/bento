# Telegram-First Program (Stages 14-17)

Goal: turn Bento into an end-user product that uses the user's Telegram account as unlimited encrypted storage and syncs any number of devices with a QR/code/link. Binding docs: `architecture/telegram-first.md`, `api/telegram-first-endpoints.md`, `api/pairing-relay-contract.md`, `product/telegram-first-experience.md`.

## Workflow

- Integration branch: `feature/telegram-first`. Each agent works in its own git worktree under `.worktrees/<slug>` on branch `tf/<slug>` created from the integration branch, commits there, and never touches other worktrees or the main checkout.
- Setup per worktree: `uv sync --project apps/api --extra dev`; `npm --prefix apps/web ci`; desktop needs Node 24 (`export PATH=$HOME/.local/share/mise/installs/node/24.19.0/bin:$PATH` before `npm --prefix apps/desktop ci`), because npm 12 on Node 26 refuses a git dependency.
- New dependencies were added up front (`telethon`, `spake2`, `segno`, `watchdog`, `websockets`). Adding any other dependency requires a note in the handoff and must not touch another agent's lockfile.
- The orchestrator merges stage branches in order and resolves one-line registration conflicts (router includes, worker loop registration, route config, i18n index).

## Stage 14 — Contracts, crypto, relay (parallel)

| Agent | Prompt | Owns |
|---|---|---|
| contracts-platform | `agent-prompts/20-telegram-contracts-agent.md` | new domain modules, non-security ports, ORM models + Alembic `0004`, settings registry additions, `infrastructure/runtime.py`, `adapters/fake_telegram/**`, contract tests |
| crypto | `agent-prompts/21-vault-crypto-agent.md` | `domain/security.py`, `ports/security.py`, `ports/key_store.py`, `adapters/security/**`, crypto tests |
| relay | `agent-prompts/22-pairing-relay-agent.md` | `apps/relay/**` |

Exit: backend suite green, migration upgrades/downgrades, crypto test vectors and tamper tests pass, relay vitest suite green.

## Stage 15 — Backend features + desktop + site (parallel)

| Agent | Prompt | Owns |
|---|---|---|
| mtproto | `23-telegram-mtproto-agent.md` | `infrastructure/mtproto/**`, `adapters/telegram_mtproto/**`, `adapters/storage/telegram_vault_blob_store.py`, `application/{account,vault,sharing,telegram_import,inbox}.py`, `interfaces/http/routes_{account,vault,telegram}.py` (vault includes recovery), inbox worker loop, removal of Bot API code/settings/compose service, storage factory, doctor, `domain/settings_registry.py` (legacy removals only) |
| sync | `24-sync-engine-agent.md` | `application/sync/**`, `adapters/sync/**`, change-capture wiring, OCR/embedding `asset_index` emission, `interfaces/http/routes_sync.py`, sync worker loop |
| pairing | `25-pairing-devices-agent.md` | `adapters/pairing/**`, `application/{pairing,devices}.py`, `interfaces/http/routes_{pairing,devices}.py` |
| storage-pipeline/backup | `26-backup-automation-agent.md` | `adapters/backup/**`, `adapters/storage/cache.py`, `application/{backup,trash,activity,storage_pipeline,content,upload,storage_maintenance}.py`, `application/ingestion/**`, `application/media/service.py`, `interfaces/http/routes_{backup,trash,activity,content}.py`, asset download/delete handlers, remote upload/purge/cache jobs |
| desktop | `27-desktop-experience-agent.md` | `apps/desktop/**` |
| site-docs | `30-site-docs-agent.md` | `apps/site/**`, `docs/user/**`, `docs/legal/**`, `docs/dev/**` |

Shared-file rules for Stage 15:

- `interfaces/http/routes.py`: each agent adds only its own `router.include_router(...)` line.
- `interfaces/worker/main.py` / `dispatch.py`: each agent adds only its own loop/handler registration lines.
- `domain/jobs.py` `JobType`: mtproto adds `account_reload`, `inbox_import`; sync adds `sync_snapshot`; backup adds `backup_scan`, `backup_upload`, `trash_purge`, `cache_evict`. Append only.
- `interfaces/http/routes.py` asset delete/download handlers: storage-pipeline/backup agent only.
- `infrastructure/services.py`: each owner replaces only its own factory bodies.
- `apps/desktop/**` and the site/docs run in Stage 15 too (`27`, `30`).
- `adapters/media/**`, `application/indexing/**`: sync agent only for `asset_index` emission; no other behavior changes.

Exit: full backend suite green, two-process fake-cloud sync journey passes, pairing over a local relay double passes, desktop tests green, site builds.

## Stage 16 — Web experience (starts with Stage 15; typed API clients and i18n scaffolding are pre-built)

| Agent | Prompt | Owns |
|---|---|---|
| web-core-flows | `28-web-onboarding-devices-agent.md` | `features/{onboarding,account,devices,pairing,recovery,settings}/**`, `components/QrCode.tsx`, `app/App.tsx`, `routes/{settings,join}.tsx`, `i18n/{es,en}/onboarding.ts` |
| web-everyday | `29-web-everyday-agent.md` | `features/{activity,trash,share,import,quicklook}/**`, `app/status.tsx`, `components/{AppShell,Sidebar,StatusIndicator}.tsx`, drive/photos/documents integration points, `routes/{trash,activity}.tsx`, `i18n/{es,en}/everyday.ts`, `i18n/en/base.ts` |

Shared: `routes/routeConfig.ts` one-line additions only; `src/api/**` is frozen (report gaps); the orchestrator resolves conflicts.

## Stage 17 — Integration and hardening (orchestrator)

- Merge, run `make test`, desktop tests, relay tests, site build.
- Critical journeys with the fake cloud: first run → backup → second device pairing → rename/move/delete converge → remove device rotates keys → recovery on a fresh device.
- Independent security review of crypto, key store, pairing, relay, and IPC; code review of the integrated diff; fix findings.
- Update README, `docs/telegram-setup.md` (replaced by user docs), and release notes.

## Stage 14 Results — Quick Reference For Stages 15-16

**Fake Telegram cloud** (`adapters/fake_telegram/`, `infrastructure/runtime.py`)

- Env: `STORAGE_BACKEND=fake` (rejected in production), `BENTO_FAKE_TELEGRAM_DIR` (default `<data_dir>/fake-telegram`), `BENTO_FAKE_TELEGRAM_MANUAL_LOGIN=1` (no 2 s QR auto-approve), `BENTO_FAKE_TELEGRAM_2FA=1` (password `bento-demo`, hint `demo`), `BENTO_FAKE_TELEGRAM_SESSION_TOO_NEW=1` (terminate raises `telegram_session_too_new`). Phone code `12345`.
- Runtime: `get_telegram_runtime(settings, key_store)` (cached per backend+dir), `reset_telegram_runtime()`, uncached `create_fake_telegram_runtime(directory, key_store, options=FakeTelegramOptions(...), clock=...)` for two devices in one process, `approve_fake_telegram_logins(settings)`. For `telegram` it imports `bento.infrastructure.mtproto.runtime.create_mtproto_runtime(settings, key_store) -> TelegramRuntime`.
- Test setup: `FakeTelegramCloud(dir).post_message(chat_id, text=..., document=DocumentUpload(bytes|Path, filename, mime?, kind?), pin=...)` simulates forwarding to the Inbox; `create_channel`, `read_chat`, `message`, `dialogs`, `folders`, `approve_pending_logins`. Test doubles: `tests/integration/fake_telegram/support.py` (`MemoryKeyStore`, `ManualClock`, `make_device`, `sign_in`); multi-process pattern in `fake_cloud_device.py`.
- Ids: user `777000001` "Ana Demo" (= Saved Messages), Carlos Ruiz `777000002`, group Familia `-400000001`; channels `-1001000000001…`; message ids start at 1 per chat.
- Semantics: the current authorization is listed with **hash 0** (like real Telegram); with 2FA, approved/accepted logins move to `password_required`; wrong code/password come back as `AccountStatus.error_code`; wrong-state calls raise `TelegramAccountError('telegram_login_expired')`, no session → `telegram_not_authorized`, bad accept token → `telegram_login_expired` with `details.reason`, unknown/0 hash on terminate → `telegram_authorization_not_found`; missing remote messages raise `StorageUnavailableError("telegram")`; text > 4096, caption > 1024, document > 2000 MiB raise `ValidationFailedError`; `list_chats` puts Saved Messages first and hides vault channels; `list_media` newest first with `before_message_id`; `wait_for_activity` fires for anything newer than the last listing.

**Contract additions**

- `domain/vault.py`: `channel_about()`, `parse_channel_marker()`, `VaultChannelCandidate`, `discover_vault_layouts()` (shared discovery rules; vault ids match `vlt_[0-9A-Za-z_-]+`).
- `domain/sync.py`: `SyncMessageKind.from_text()` — plaintext Sync messages must be JSON objects with a string `bento` key (`"vault-header"` → header, any other value → pairing). Fallback pairing messages therefore carry `"bento": "pair_request" | "pair_offer" | "pair_reveal" | "pair_grant"`.
- `domain/storage.py`: `StorageBackend.FAKE` names the configured backend only; blob refs written through the fake still use `TELEGRAM`. `BlobPart.from_remote(index, RemotePart)` / `BlobPart.remote()`.
- `adapters/repositories/devices.py`: `SQLiteDeviceRepository`. `adapters/media/catalog.py`: persists parts/epoch/format, `get(blob_id)`.
- Settings: new env aliases `BENTO_<KEY>`; backup policy settings apply **live** (read them live); `inbox_keep_hours`, `trash_retention_days` restart the worker.

**Device ↔ Telegram authorization matching**

A session cannot learn its own authorization hash (current = 0). Every Bento client therefore connects with `device_model = "Bento (<last 6 chars of device_id>)"`; to close another device's session, list authorizations and match `device_model` against the target device id suffix. The guest's hash is also available to the host from `AcceptedLogin.authorization_hash`. The fake cloud may be extended minimally (by the mtproto agent) to record the `device_model` each instance announces.
