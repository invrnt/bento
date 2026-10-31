# Storage Pipeline And Backup Automation Agent (Stage 15)

## Mission

Make storage automatic and invisible: local-first ingestion with background encrypted upload, on-demand downloads with a bounded cache and video streaming, automatic folder backup, trash with real remote deletion, and one activity summary that powers the status bar and tray.

## First Read

- `AGENTS.md`, `orchestration/execution/telegram-first-program.md`
- `orchestration/architecture/telegram-first.md` § Integration Rules (Storage pipeline), § Rate and size policy
- `orchestration/api/telegram-first-endpoints.md` § Backup, activity, power; § Trash and cache; § Content streaming
- `orchestration/product/telegram-first-experience.md` § Everyday use
- Contracts: `domain/{backup,trash,activity,storage}.py`, `ports/{backup,trash,content,blob_store,vault,sync}.py`, `infrastructure/services.py`
- Existing: `application/{upload,storage_maintenance,drive,photos,jobs}.py`, `application/ingestion/**`, `application/media/**`, `adapters/storage/{local_blob_store,maintenance}.py`, `interfaces/http/routes.py` (asset download/thumbnail/preview/delete), `interfaces/worker/**`, Stage 14 models/migration

## Own These Paths

- `adapters/backup/**` (watchdog watcher, OS folder suggestions for Windows/macOS/Linux, SQLite repositories for sources/files/policy), `adapters/storage/cache.py`
- `application/{backup,trash,activity,storage_pipeline,content}.py`
- `application/upload.py`, `application/ingestion/**`, `application/media/service.py`, `application/storage_maintenance.py` (local-first + remote enqueue + cache integration only)
- `interfaces/http/routes_{backup,trash,activity,content}.py` (+ include lines) and the asset download/thumbnail/preview/delete and folder delete handlers in `interfaces/http/routes.py`
- Worker handlers for `remote_upload`, `backup_scan`, `backup_upload`, `trash_purge`, `cache_evict` (own module + registration); `domain/jobs.py` append those types
- `infrastructure/services.py`: implement `get_asset_content` and its part of `reset_services`
- Tests under `apps/api/tests/{unit,integration,api}/{backup,storage_pipeline,trash,activity,content}/**`

## Deliver

1. **Local-first pipeline**: ingestion stores locally and returns immediately; when `get_remote_blob_store` is available, enqueue `remote_upload` (originals first, then thumbnails/previews, priority-ordered); on success replace the blob ref with the remote one (sync capture publishes it), register the local file as a cache entry; when the vault becomes ready, enqueue uploads for every local-only blob. Retries with backoff; flood waits reschedule instead of failing.
2. **Content service** (`AssetContentPort`): cache hit → serve; for backup-sourced assets prefer the user's source file when size+mtime match; otherwise fetch from the remote store (full or by range), record `cache_entries` access; `GET /assets/{id}/content` with Range/206/`Accept-Ranges`; `/download` and thumbnail/preview handlers use it so other devices can open remote files and thumbnails lazily.
3. **Cache**: `cache_max_gb` LRU eviction job of originals (never thumbnails, never blobs not yet uploaded, never files being read); integrate the existing "Liberar espacio" reclaim with the cache; backup-sourced originals drop Bento's local copy right after upload.
4. **Folder backup**: sources CRUD with validation (exists, readable dir, not root, not inside data dir, no overlap), suggestions (Pictures/Documents/Desktop/Downloads that exist), incremental scan by size+mtime (hidden/system/temp files skipped; symlinks not followed), watcher events debounced (2 s) into scans, `backup_upload` through ingestion with sha256 dedupe, mode selection (images/videos → Photos, others → Drive under `Respaldo/<label>/<relative dirs>` folders created as needed), one-way semantics (source deletions never delete from Bento), per-source counts/state; policy (paused, pause on battery with `POST /backup/power`, bandwidth limit persisted to `backup_bandwidth_limit_kbps`).
5. **Trash**: asset and folder deletes move to trash; list/restore/purge/empty; purge deletes remote parts (`delete_ref`), local cache, catalog rows (sync emits `purge`); retention job by `trash_retention_days`.
6. **Activity**: aggregate jobs, transfer progress (bytes and ETA from upload sessions/jobs), backup state, sync status (`get_sync_status_provider`), flood waits, recovery-kit reminder (`VaultStatus.recovery_kit_saved == False`), inbox failures → `GET /activity` per contract with i18n title keys `activity.attention.<kind>`.

## Required Tests

Local-first upload returns before remote upload; remote upload success/failure/retry/flood wait; vault-ready backfill; content range requests (206, boundaries, invalid ranges 416) against the fake cloud; cache LRU respecting pinned/pending blobs; backup-sourced cache drop and source-file preference with mtime change fallback; source validation hostile paths; scan incremental behavior and debounced watcher (watcher mocked); policy and power; trash lifecycle including remote deletion; activity aggregation snapshots. Existing upload/drive/photos/storage-maintenance tests stay green (update only where behavior intentionally changed). Full backend suite green.

## Constraints

- Thumbnails/previews for grids; never load originals for lists.
- Worker defaults CPU-safe (concurrency 1).
- Do not implement Telegram adapters, sync, pairing, or UI.

## Handoff

Commit on your branch. Report behavior changes to existing endpoints, job types, settings used, test counts, and what the web agent should render.
