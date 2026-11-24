# Android Backend Contract

Additions needed by the Android app (`product/android.md`, `architecture/android-runtime.md`). All additive; existing routes and the error model (`api/error-model.md`) are unchanged. Business rules live in `application/` and `domain/`; routers only translate.

## 1. Engine entrypoints (`bento.interfaces.android.engine`)

Called from Kotlin through Chaquopy. Plain Python functions with JSON-serializable arguments; no FastAPI types cross the boundary.

| Function | Arguments | Returns / behavior |
|---|---|---|
| `configure(config: dict)` | `{data_dir, no_backup_dir, cache_dir, platform: "android", environment, wrapping_key: bytes, api_token: str, telegram_api_id, telegram_api_hash, relay_url, site_url, app_version, device_name_default, bridges: {…Java objects}}` | Builds `Settings` without reading env for secrets (the token and wrapping key are passed in memory), installs bridge adapters. Idempotent for identical config; raises `EngineConfigError` otherwise. |
| `migrate() -> dict` | — | `alembic upgrade head`; `{from, to, ran: bool, ms}`. Fast no-op at head (≤ 50 ms). |
| `start_api() -> int` | — | Starts uvicorn on a loopback ephemeral port in its own thread/loop; returns the port once accepting. Request guard requires the bearer token (`BENTO_API_TOKEN` semantics from `cli-endpoints.md`). |
| `start_worker(mode: "full" \| "drain")` | — | `full`: normal job loop with Telethon update handlers. `drain`: no update handlers; used by background runs. |
| `run_worker_until(deadline_epoch_ms: int, kinds: list[str] \| None) -> dict` | job kinds filter (`None` = all eligible) | Runs eligible jobs until the deadline or no eligible job; stops at the next safe step boundary. Returns `{ran, remaining, next_eligible_at, stopped_reason: "idle\|deadline\|conditions\|error"}`. |
| `stop(timeout_ms: int)` | — | Graceful stop of API, worker, Telethon clients. |
| `status() -> dict` | — | `{api_port, worker: "stopped\|full\|drain", telegram: "disconnected\|connected\|signed_out", last_error}` (no secrets). |

## 2. Device conditions

`ports/device.py` adds `DeviceConditionsPort.snapshot() -> DeviceConditions` and `subscribe(callback)`. `DeviceConditions = {online, metered, unmetered, charging, battery_pct, power_save, data_saver, storage_free_bytes, thermal: "none|light|moderate|severe"}`. Desktop/headless adapters return permissive defaults (`online=True, metered=False, charging=True`), so existing behavior is unchanged.

Policy (application layer, `application/storage_pipeline.py` + job scheduler):

- `remote_upload`/`backup_upload` of originals: require `unmetered` when `backup_wifi_only` (new setting, default `true` on Android, `false` elsewhere); videos require `unmetered` unless `backup_videos_on_metered`. Thumbnails/previews and sync batches may use metered networks.
- `backup_only_charging` (default `false`): backup uploads wait for `charging`.
- Always defer bulk uploads and OCR when `battery_pct < 15` and not charging, when `power_save`, or `thermal >= moderate`.
- `ocr_requires_charging` (default `true` on Android): OCR jobs wait for `charging`.
- A one-shot override `POST /api/backup/run-now` lifts the Wi-Fi rule for the current backlog (not the battery/thermal rules).
- Deferred jobs carry `wait_reason` (`wifi|charging|battery|thermal|offline`) exposed in Activity and `/sync/status` summaries so the UI can say "esperando Wi-Fi".

## 3. Media sources (camera roll)

Backup sources gain `kind: "folder" | "media_store"` (migration adds `backup_sources.kind`, default `folder`, and `backup_files.source_key` for MediaStore ids). `media_store` sources store `{bucket_id, bucket_name, relative_path}`; files are keyed by `(source_id, media_id)` with `generation`/`size`/`date_modified` as the change token.

| Method | Path | Body / Query | Response |
|---|---|---|---|
| GET | `/backup/suggestions` | (existing) | On Android lists MediaStore buckets: `{id, kind: "media_store", name, count, sample_asset_hint, suggested: bool}` |
| POST | `/backup/sources` | (existing) `{kind: "media_store", bucket_id}` | Source; target Drive folder `Del teléfono/<device name>/<bucket name>` is ensured (reusing `ensure` semantics) |
| GET | `/backup/status` | — | adds `{pending, waiting: {wifi, charging, battery}, uploaded_today, last_backup_at, partial_access: bool, location_access: bool}` |
| POST | `/backup/run-now` | — | `202 {accepted, pending}` |
| GET | `/backup/free-up-space/preview` | `?source_id=` optional | `{items: [{asset_id, media_id, size_bytes}], total_bytes, count}` — only phone originals whose remote blob is confirmed and whose sha256 matches the local hash |
| POST | `/backup/free-up-space/confirm` | `{media_ids}` | Records that the system deleted them (Kotlin performs `MediaStore.createDeleteRequest` and reports the granted ids); assets stay, thumbnails stay |

Ingestion of a MediaStore item: hash while streaming from the fd → `assets/lookup` semantics (existing sha256 in vault → link the backup file to that asset, no upload) → otherwise local-first ingest with `origin=device`, `taken_at` from `DATE_TAKEN`/EXIF, and enqueue thumbnail → remote upload → OCR by policy.

## 4. Imports from content URIs

`POST /api/android/imports` `{items: [{fd_handle, display_name, mime_type, size_bytes?}], folder_id?, album_id?}` → `202 {import_id, items: [{client_index, asset_id?, status}]}`. `fd_handle` is an integer registered by Kotlin through the `ContentImports` bridge (Kotlin opens the URI, detaches the fd, registers it with a one-time handle; Python adopts and closes it). Used for share-to-Bento and SAF uploads above 50 MB so bytes are not copied through HTTP. Small items may use the existing multipart upload. `GET /api/android/imports/{id}` reports progress; events are published on the jobs stream. Display names are sanitized with the existing upload rules (path traversal, control chars, length).

## 5. Thumbnails and previews

- `GET /assets/{id}/thumbnail?size=256|512|1024` (new optional `size`, default current behavior): returns the nearest stored size not smaller than requested (or the largest), with `ETag` and `Cache-Control: private, max-age=31536000, immutable` keyed by thumbnail id. Thumbnail generation produces 256 and 1024 (512 derived on demand and cached locally only).
- `GET /photos/timeline` adds `?cursor&limit` keyset paging (if not already), plus per-item `{width, height, duration_ms?, favorite, remote_state: "local_only|uploading|remote|failed", thumbnail_etag}` so the grid can render overlays without extra calls.
- `GET /photos/timeline/index` → `{months: [{month: "2024-03", count, first_cursor}]}` for the fast scroller (O(months), cached).

## 6. Offline pins (cache)

`cache_entries.pinned` (migration). `PUT /assets/{id}/offline` → `202`, enqueues a download of the original and marks it pinned (excluded from LRU). `DELETE /assets/{id}/offline` unpins. `GET /storage/local` adds `{pinned_bytes, pinned_count, cache_limit_bytes, thumbs_bytes}`. Eviction also runs when `storage_free_bytes` drops under 10 % of the volume (from device conditions), never evicting pinned or not-yet-uploaded originals.

## 7. Notifier events

The application layer emits semantic events to `NotifierPort` (no strings): `transfer_progress {kind: "backup|upload|download|import", done, total, bytes_done, bytes_total, paused}`, `transfer_finished {kind, count, failed}`, `attention {code, count}` (codes = Activity item codes), `pairing_request {request_id, device_name, platform}`, `new_device {device_id, name}`. Rate-limited to 1 Hz for progress. Desktop/headless use a no-op adapter.

## 8. Pairing link

When `site_url` is configured, pairing sessions return `link = "<site_url>/join#v=1&c=<code>"` and the QR encodes it; otherwise `bento://join?v=1&c=<code>` as today. All parsers already accept both.

## 9. Debug-only: remote fake cloud

`bento-sidecar fake-telegram-serve --dir <dir> --port <p>` (non-production only) exposes the fake Telegram directory over a tiny HTTP API, and `BENTO_FAKE_TELEGRAM_URL` makes the fake adapters use it instead of a local directory. Lets an emulator (`http://10.0.2.2:<p>`) and host processes act as devices of one account in e2e tests. Compiled out of release APKs.

## 10. OpenAPI export

`uv run python -m bento.interfaces.http.export_openapi > apps/android/core/api/openapi.json` (deterministic ordering). The Android build generates DTOs from it; CI fails when the snapshot is stale.
