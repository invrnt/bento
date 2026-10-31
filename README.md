![Bento minimalist banner](docs/assets/readme-banner.png)

# Bento

Bento is a local-first private cloud MVP Lite. It stores metadata, jobs, search indexes, manifests, thumbnails, and settings in local SQLite and uses local filesystem storage by default. Telegram storage is optional and only used when `STORAGE_BACKEND=telegram` is configured.

The packaged Electron app is the recommended path for desktop users: it includes the web UI plus native API/worker sidecars, requires no Docker, Python, Node, or manual `.env`, and keeps data on the device by default. Docker Compose remains supported for development and headless deployments.

## Desktop installation

Download the artifact for your architecture from a signed GitHub release:

- Windows x64: Squirrel `Setup.exe`.
- macOS 13+ on Intel or Apple silicon: the matching notarized `.dmg`.
- Ubuntu 22.04 x64 and compatible Debian-based systems: `.deb`; a portable `.zip` is also published.

Verify the matching `SHA256SUMS-*` file before installing. Release tags are blocked unless the Windows installer is signed and both macOS architectures are signed and notarized. Pull requests publish short-lived artifacts whose names include `unsigned`; those are for testing, not general distribution.

Stable desktop releases follow GitHub Flow from short-lived `feature/*` or `fix/*` branches into `main`. Maintainers use the manual **Desktop version bump PR** workflow for a stable SemVer `patch`, `minor`, or `major`; after the version PR and four-platform native validation pass, an immutable matching `vX.Y.Z` tag builds the signed release. Per-target update manifests contain exact GitHub asset URLs, hashes and sizes; update checks are metadata-only and installation remains an explicit, fail-closed desktop action.

See [Desktop installation and first run](docs/desktop/install-first-run.md), [Settings, backup, and recovery](docs/desktop/settings-recovery.md), and [Release and signing](docs/desktop/releasing.md).

## Runtime Processes

- `web`: Vite React TypeScript app on `127.0.0.1:5173`.
- `api`: FastAPI app on `127.0.0.1:8000`.
- `worker`: background worker using the same `bento` backend package.
- `telegram-bot-api`: optional local Telegram Bot API profile.

Local mode is the safe default. `STORAGE_BACKEND=local` does not require Telegram credentials.

## Quick Start

```sh
copy .env.example .env
make setup
make doctor
make seed
make up
```

Open the app at `http://127.0.0.1:5173`. The API is available at `http://127.0.0.1:8000/api`.

Backend dependency management uses `uv >=0.11,<0.13`; install or update it before running `make setup`.

```sh
uv self update
```

If `uv` is not installed yet, use the official standalone installer or your package manager.

## Commands

```sh
make setup          # install local deps, create data dirs, run Alembic migrations
make doctor         # validate local mode, DB, writable volumes, compose config, tools
make seed           # add deterministic demo Drive and Photos assets
make test           # backend pytest and frontend Vitest
make pre-commit     # run commit-time hooks against all files
make pre-push       # run push-time project checks against all files
make smoke          # backend release smoke journey
make desktop-make   # native installer/archive makers for the current OS
make desktop-release-artifacts # makers, packaged smoke, SBOM, checksums
make up             # build and start Docker Compose local mode
make watch          # start Docker Compose in watch mode for development
make down
make logs
```

`make watch` syncs source changes into running containers, restarts API/worker on backend changes, and rebuilds services when dependency or Docker build files change.

Backend-only:

```sh
cd apps/api && uv run pytest
```

Frontend-only:

```sh
npm --prefix apps/web test
```

Install Git hooks locally:

```sh
make pre-commit-install
```

Validate Compose without starting services:

```sh
docker compose config --quiet
```

## Environment

`.env.example` is safe for local mode:

- `STORAGE_BACKEND=local`
- `WORKER_CONCURRENCY=1`
- `OCR_PROVIDER=disabled`
- `EMBEDDINGS_PROVIDER=disabled`
- `VITE_API_BASE_URL=http://127.0.0.1:8000/api`

Telegram mode requires all Telegram fields:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_RAW_CHAT_ID`
- `TELEGRAM_THUMBS_CHAT_ID`
- `TELEGRAM_JOURNAL_CHAT_ID`
- `TELEGRAM_WEBHOOK_SECRET`
- `ENCRYPTION_MODE=aes_gcm`
- `BENTO_ENCRYPTION_KEY`
- `BENTO_ENCRYPTION_KEY_ID`

See the complete [Telegram Configuration Guide](docs/telegram-setup.md) for step-by-step setup instructions.

Do not commit real Telegram tokens, API hashes, chat IDs, or local secrets.

## Implemented MVP Surface

- Upload to local storage with sha256 dedupe.
- Drive listing, folders, rename, move, logical delete, download, and search.
- Photos timeline, upload, detail, and favorite toggle.
- Search by filename, metadata, OCR text when indexed, and optional vector records.
- Jobs list, retry for failed jobs, and reindex enqueue.
- Settings/status endpoint for storage, providers, model availability, worker concurrency, and data paths.
- Manifest events persisted in SQLite and exported to `data/journal/manifest-events.jsonl`.
- Telegram webhook and Telegram blob adapter wiring when Telegram mode is configured.

## Brand And Design Language

Bento's identity ("Todo en su lugar"), palette, typography, shapes, motion, voice and per-screen patterns are defined in the [brand book](orchestration/design-system/brand.md). The UI supports light, dark and system themes; tokens live in `apps/web/src/styles/tokens.css`.

## Known Limitations

- OCR and embeddings are disabled by default; real providers require local runtime setup and model files.
- The worker is conservative by default (`WORKER_CONCURRENCY=1`).
- Telegram mode requires a local Telegram Bot API server and private channels; automated tests use fakes, not real Telegram.
- The desktop package does not currently bundle or supervise `telegram-bot-api`; Telegram storage therefore requires a separately operated loopback service. Local storage is fully supported without it.
- Thumbnails/previews depend on worker/media tooling and may be pending until jobs run.
- No public sharing, mobile app, multi-PC sync, cloud AI, PostgreSQL, or external vector database is included in MVP Lite.

## Release Checks

- `make test`
- `make doctor`
- `make smoke`
- `docker compose config --quiet`
- Docker Compose local smoke: `make up`, open `http://127.0.0.1:5173`, upload, browse Drive/Photos, search, view Jobs/Settings, then `make down`.

## MVP Definition Of Done

- [x] Clean local setup creates data directories and migrates SQLite.
- [x] Local mode works without Telegram configuration.
- [x] Upload, Drive listing, download, Photos timeline, filename search, Jobs, Settings, and manifest export have smoke coverage.
- [x] Docker Compose binds app ports to localhost and waits for API health before starting dependents.
- [x] Defaults avoid cloud AI and keep worker concurrency CPU-safe.
- [x] Known limitations are documented.

## Version Assumptions

- Python 3.12+.
- uv `>=0.11,<0.13` for backend dependency locking and local commands.
- FastAPI `0.115.x`, SQLAlchemy `2.x`, Alembic `1.x`, Uvicorn `0.34.x`, pytest `8.x`.
- cryptography `46.x` for streaming AES-256-GCM blob encryption.
- Node 22, Vite `6.x`, React `19.x`, TypeScript `5.7.x`, Tailwind CSS `4.x`, Vitest `3.x`.
- Desktop CI/release: Node 24, Python 3.12, Electron `43.4.1`, Electron Forge `7.11.2`, and PyInstaller `6.22.2`, built natively rather than cross-compiled.
- Docker Compose V2 with healthcheck-aware `depends_on` and `develop.watch` support.

Docs consulted during release hardening: project orchestration docs and current official Docker Compose documentation for healthchecks and `depends_on` conditions.
