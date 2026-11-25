# API Endpoint Map

All routes are under `/api`.

## Health And Settings

- `GET /api/health`: returns service health and DB reachability.
- `GET /api/version`: returns app version/build info.
- `GET /api/settings`: returns storage/OCR/embedding/job configuration status safe for UI.
- `GET /api/settings/schema`: typed editable field metadata, source, constraints, sensitivity, and restart scope.
- `GET /api/settings/values`: effective non-secret values plus revision and configured/missing markers for secrets.
- `POST /api/settings/validate`: validates a draft and returns field errors, warnings, optional probe results, and restart plan without persisting.
- `PATCH /api/settings/values`: atomically persists allowed non-secret changes using the current revision; never accepts or returns plaintext secrets.
- `POST /api/settings/import/preview`: parses a user-selected legacy `.env` payload into a redacted preview; desktop bridge performs file selection.
- `GET /api/settings/export`: exports non-secret portable configuration.

## Assets And Upload

- `POST /api/assets/upload`: multipart upload, optional `folder_id`, returns asset.
- `GET /api/assets/{asset_id}`: asset detail.
- `GET /api/assets/{asset_id}/download`: original file download.
- `GET /api/assets/{asset_id}/thumbnail`: best available thumbnail; `?size=256|512|1024` returns the nearest stored size not smaller than requested (else the largest) with `ETag` (thumbnail id), `Cache-Control: private, max-age=31536000, immutable`, and `304` on `If-None-Match`.
- `PUT /api/assets/{asset_id}/offline`: `202 {asset_id, pinned, downloading}`; keeps the original on this device, excluded from cache eviction (downloads it first when only remote). `DELETE` unpins.
- `GET /api/assets/{asset_id}/preview`: preview image/video/document render when available.
- `DELETE /api/assets/{asset_id}`: logical delete.
- `POST /api/assets/lookup`: `{sha256: [hex64]}` (<= 500) -> existing non-deleted assets and their Drive paths (CLI dedupe; see `cli-endpoints.md`).

## Drive

- `GET /api/drive/items?folder_id=`: folder children and assets.
- `POST /api/drive/folders`: create folder.
- `PATCH /api/drive/folders/{folder_id}`: rename/update folder.
- `PATCH /api/drive/items/{asset_id}`: rename/update asset.
- `POST /api/drive/items/{asset_id}/move`: move asset.
- `GET /api/drive/resolve?path=`: resolve a Drive path or `id:` ref to root/folder/asset with breadcrumbs (`404 path_not_found`, `409 path_ambiguous`).
- `POST /api/drive/folders/ensure`: `{path}` mkdir -p; reuses the oldest same-name sibling, never duplicates.
- `GET /api/drive/tree?path=&depth=&include_assets=&max_nodes=`: bounded subtree (folders first, name-sorted).
- `POST /api/drive/paths`: `{ids}` (<= 500) -> canonical paths plus `missing`.

Path semantics, limits, and the headless `BENTO_API_TOKEN` / desktop `BENTO_DESKTOP_CLI_TOKEN` authentication are specified in `cli-endpoints.md`.

## Photos

- `GET /api/photos/timeline`: grouped photo/video timeline; keyset `cursor` (`k.…`, legacy numeric offsets still accepted) and `limit`; items add `width`, `height` (largest stored thumbnail), `duration_ms`, `remote_state` (`local_only|uploading|remote|failed`), `thumbnail_etag`.
- `GET /api/photos/timeline/index`: `{months: [{month: "YYYY-MM", count, first_cursor}]}` (UTC months) for the fast scroller.
- `GET /api/photos/{asset_id}`: photo/video detail.
- `GET /api/photos/albums`: list albums.
- `POST /api/photos/albums`: create album.
- `POST /api/photos/albums/{album_id}/items`: add asset to album.

## Search

- `GET /api/search`: global or scoped search.

## Jobs And Admin

- `GET /api/jobs`: list jobs and statuses.
- `POST /api/jobs/{job_id}/retry`: retry failed job.
- `POST /api/admin/reindex`: enqueue reindex jobs.

## Storage And Backup

- `GET /api/storage/local`: `{cache_bytes, cache_files, pinned_bytes, pinned_count, cache_limit_bytes, thumbs_bytes}`.
- `GET|POST|PATCH|DELETE /api/backup/sources…`: folder sources; `POST` also takes `{kind: "media_store", bucket_id, label?}` (Android), ensuring `Del teléfono/<device>/<bucket>`. Sources report `kind` and `bucket_id`.
- `GET /api/backup/suggestions`: folders, or on Android MediaStore buckets `{id, kind: "media_store", name, count, sample_asset_hint, suggested}`.
- `GET /api/backup/status`: `{pending, waiting: {offline, thermal, battery, charging, wifi}, uploaded_today, last_backup_at, partial_access, location_access}`.
- `POST /api/backup/run-now`: `202 {accepted, pending}`; lifts the Wi-Fi rule for uploads queued so far.
- `GET /api/backup/free-up-space/preview?source_id=`: phone originals uploaded and verified (remote copy confirmed, sha256 matches): `{items: [{asset_id, media_id, size_bytes}], total_bytes, count}`.
- `POST /api/backup/free-up-space/confirm`: `{media_ids}` deleted by the system delete request -> `{freed}`; assets and thumbnails stay.

## Android

- `POST /api/android/imports`: `{items: [{fd_handle, display_name?, mime_type?, size_bytes?}], folder_id?, album_id?}` -> `202 {import_id, done, counts, items: [{client_index, asset_id, status, error}]}`.
- `GET /api/android/imports/{import_id}`: progress of one import (`pending|importing|done|duplicate|failed` per item).
- Engine entrypoints (`bento.interfaces.android.engine`), device conditions, notifier events, and the remote fake cloud: `android-endpoints.md`.
- Schema export: `uv run python -m bento.interfaces.http.export_openapi` (deterministic; Android DTOs are generated from it).

## Telegram

- `POST /api/telegram/webhook`: receive bot updates.

## Pagination

List endpoints use `limit` and `cursor` where result sets can grow.
