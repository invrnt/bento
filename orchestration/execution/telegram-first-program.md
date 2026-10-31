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
| mtproto | `23-telegram-mtproto-agent.md` | `infrastructure/mtproto/**`, `adapters/telegram_mtproto/**`, `application/{account,vault,sharing,telegram_import,inbox}.py`, `interfaces/http/routes_{account,vault,telegram}.py`, inbox worker loop, removal of Bot API code/settings/compose service, storage factory, `domain/settings_registry.py` (legacy removals only) |
| sync | `24-sync-engine-agent.md` | `application/sync/**`, `adapters/sync/**`, change-capture wiring, OCR/embedding `asset_index` emission, `interfaces/http/routes_sync.py`, sync worker loop |
| pairing | `25-pairing-devices-agent.md` | `adapters/pairing/**`, `application/{pairing,devices,recovery}.py`, `interfaces/http/routes_{pairing,devices,recovery}.py` |
| backup | `26-backup-automation-agent.md` | `adapters/backup/**`, `application/{backup,trash,activity,content}.py`, `interfaces/http/routes_{backup,trash,activity,content}.py`, purge/cache jobs, fix of remote blob deletion |
| desktop | `27-desktop-experience-agent.md` | `apps/desktop/**` |
| site-docs | `30-site-docs-agent.md` | `apps/site/**`, `docs/user/**`, `docs/legal/**`, `docs/dev/**` |

Shared-file rules for Stage 15:

- `interfaces/http/routes.py`: each agent adds only its own `router.include_router(...)` line.
- `interfaces/worker/main.py` / `dispatch.py`: each agent adds only its own loop/handler registration lines.
- `domain/jobs.py` `JobType`: mtproto adds `account_reload`, `inbox_import`; sync adds `sync_snapshot`; backup adds `backup_scan`, `backup_upload`, `trash_purge`, `cache_evict`. Append only.
- `interfaces/http/routes.py` asset delete/download handlers: backup agent only.
- `adapters/media/**`, `application/indexing/**`: sync agent only for `asset_index` emission; no other behavior changes.

Exit: full backend suite green, two-process fake-cloud sync journey passes, pairing over a local relay double passes, desktop tests green, site builds.

## Stage 16 — Web experience (after the design/branding pass is merged)

| Agent | Prompt | Owns |
|---|---|---|
| web-onboarding | `28-web-onboarding-devices-agent.md` | `features/{onboarding,account,devices,pairing,recovery}/**`, `api/{account,vault,pairing,devices}.ts`, `components/QrCode.tsx`, `i18n/es/onboarding.ts` + `i18n/en/onboarding.ts`, app shell status footer |
| web-experience | `29-web-everyday-agent.md` | `features/{backup,activity,trash,share,import,quicklook}/**`, `api/{backup,activity,trash,telegram}.ts`, settings IA simplification, `i18n/{es,en}/everyday.ts`, English base dictionary |

Shared: `routes/routeConfig.ts`, `components/Sidebar.tsx`, `app/App.tsx` — one-line additions only; the orchestrator resolves conflicts.

## Stage 17 — Integration and hardening (orchestrator)

- Merge, run `make test`, desktop tests, relay tests, site build.
- Critical journeys with the fake cloud: first run → backup → second device pairing → rename/move/delete converge → remove device rotates keys → recovery on a fresh device.
- Independent security review of crypto, key store, pairing, relay, and IPC; code review of the integrated diff; fix findings.
- Update README, `docs/telegram-setup.md` (replaced by user docs), and release notes.
