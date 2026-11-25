# Agent 35 — Android Backend Support

Read first: `AGENTS.md`, `orchestration/README.md`, `architecture/system-overview.md`, `architecture/boundaries-layers.md`, `architecture/telegram-first.md`, then `api/android-endpoints.md` (binding), `architecture/android-runtime.md` (binding §3-§7, §10), `product/android.md` §5 (phone backup), and `docs/dev/android-spike.md` (required backend changes found by the spike). Read the actual code in `application/storage_pipeline.py`, `application/backup.py`, `adapters/backup/`, `ports/backup.py`, `ports/media.py`, `ports/providers.py`, and `interfaces/desktop/launcher.py` before changing anything — the code is the source of truth where docs are vague.

## Goal

Make the backend a first-class Android citizen without changing desktop behavior:

1. `interfaces/android/engine.py`: `configure`, `migrate`, `start_api`, `start_worker(full|drain)`, `run_worker_until`, `stop`, `status` exactly as in `api/android-endpoints.md` §1. Reuse `bind_loopback_listener`, the request guard token path, and the worker dispatch loop; add a cooperative deadline/safe-boundary mechanism to the worker loop (also unit-testable on desktop).
2. `ports/device.py`: `DeviceConditionsPort`, `NotifierPort`, `ContentImportsPort`; permissive/no-op adapters for desktop/headless; Android adapters in `adapters/android/` calling bridges by the method names in `architecture/android-runtime.md` §5 (imports of `java` only inside `adapters/android/`, lazily).
3. Android adapters: `media_tools.py` (thumbnailer/metadata), `ocr_mlkit.py` (OCR provider returning the existing OCR result shape), `media_store.py` (backup source kind `media_store`: scan, observe, open fd, suggestions), `conditions.py`, `notifier.py`, `content_imports.py`. Each with a fake bridge for tests.
4. Policy: device-condition rules and new settings (`backup_wifi_only`, `backup_videos_on_metered`, `backup_only_charging`, `ocr_requires_charging`) with platform defaults; `wait_reason` on deferred jobs surfaced in Activity/status; `POST /backup/run-now`.
5. Media sources: migration (`backup_sources.kind`, `backup_files.source_key`, `cache_entries.pinned`), dedupe by sha256 before upload, target folder `Del teléfono/<device name>/<bucket>` via the existing ensure use case, free-up-space preview/confirm.
6. HTTP: `routes_android.py` (imports), thumbnail `size`, timeline keyset paging + per-item fields + month index, offline pins, `/storage/local` additions, pairing `link` with `site_url`.
7. `interfaces/http/export_openapi.py` (deterministic) and the remote fake cloud (`fake-telegram-serve`, `BENTO_FAKE_TELEGRAM_URL`, non-production only).
8. `pyproject.toml` `android` extra (§4 of the runtime doc), `uv lock`; update `api/endpoint-map.md`.

Constraints: no Android-specific branching outside `adapters/android/`, `interfaces/android/`, and the `infrastructure/services.py` android wiring; desktop/headless defaults keep every existing test green; Telegram compliance origin rule unchanged (MediaStore and share imports are `origin=device`).

## Tests

Unit: worker deadline/drain semantics, policy decisions for every condition combination, media_store scan/change detection/dedupe with a fake bridge, fd adoption and closing, notifier rate limiting, settings defaults per platform. API: imports, thumbnails `size`, timeline paging/index, pins, backup status/run-now/free-up-space, pairing link form, OpenAPI export determinism. Integration: an engine smoke that calls `configure → migrate → start_api → health → stop` in-process with fakes; two backend processes sharing the remote fake cloud converge. Full backend suite green: `cd apps/api && uv run --extra dev pytest -q`.

## Handoff

Commit on your branch. Report: endpoints and settings added, migration id, bridge method signatures as implemented (the platform agent codes against them), test counts, deviations.
