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
| `on_event(kind: str, payload_json: str)` | `media_changed`, `conditions`, `access_changed`, `low_memory` | Thread-safe hand-off from Kotlin into the worker loop; never blocks the caller. |
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

## 11. Stage 21b backend additions

All additive: new fields are optional/defaulted and old routes keep their shapes.

### OCR and embeddings on upload

Uploads (`POST /assets/upload`, Android imports, folder/MediaStore backup) queue OCR and embedding jobs from the configured providers (`IndexingPolicy.from_providers`: a provider other than `disabled` turns its jobs on), like `POST /admin/reindex`. Job order and conditions stay with the scheduler: thumbnails run first (priority), OCR waits for `charging` when `ocr_requires_charging` (Android default) and for the battery/thermal rules. Files obtained from Telegram are never indexed.

### Telegram sign-in and vault creation

- `GET/POST /account…` (`AccountStatusResponse`) add `code_length: int | null` and `code_delivery: "app"|"sms"|"call"|"flash_call"|"missed_call"|"email"|"fragment_sms"|"firebase_sms"|null` on `code_required` (from Telethon's `auth.SentCode.type`).
- `GET /vault` (`VaultStatusResponse`) adds `creation: {state: "running"|"done"|"failed", steps: [{step: "files"|"sync"|"inbox"|"header"|"device", state: "pending"|"running"|"done"|"failed"}], error_code}` for the last `POST /vault` of this process. While it runs, `GET /vault` answers from memory with `state: "no_vault"` and `creation.state: "running"`; poll it during the (blocking) `POST /vault`. A second concurrent `POST /vault` fails `409 vault_creation_in_progress`.

### Pairing while signing in

While a guest pairing is `needs_telegram_login`, the guest keeps one login in flight: once the person starts a phone login (`POST /account/login/phone` → `code_required`, then `password_required`), the session stops showing a Telegram QR (`telegram_qr: null`, `needs_telegram_qr: false`) and never restarts QR login; the app drives the code/password through `/account`. When `/account` reaches `authorized` the pairing continues by itself.

### Removed devices

- While signed out of a vault it belongs to, `/vault` reports `reason: "device_removed"` (instead of `session_closed`) whenever this device already holds removal evidence: the sync `device_removed` flag, its own registry row with `removed_at` (a peer's removal op), or its id in `removed_device_ids`.
- After signing in again following a lost session, `/vault` reports `bootstrapping` until the sync engine completed one pull newer than the loss (the backend requests it), so a removal keys message posted while the session was closed is found before `ready` is ever reported; `/vault` then turns `locked` with `reason: "device_removed"`.
- Not done (protocol): the desktop closes the phone's Telegram session (step 2) before it posts the rotation keys message (step 3), so a removed phone cannot learn of the removal before re-signing in. Rotating before revoking would let an online phone read the keys message first; it changes the binding step order of `architecture/telegram-first.md` § Devices, Removal, Key Rotation and widens the window in which a removed session can delete or edit the rotation, so it needs a protocol decision first.

### Android imports

Import state is persisted (`content_imports`, `content_import_items`, migration `0008`), so `GET /android/imports/{id}` answers after a restart. The fds die with the process, so unfinished items of an earlier process end `failed` with `error: "import_interrupted"` (share them again); other item errors are `content_unreadable`, `album_unavailable`, or an upload error code. Imports with failed items show an Activity item `{id: "import_failed:<import_id>", kind: "import_failed", action: "dismiss", params: {import_id, count, code}}` until `POST /android/imports/{id}/dismiss` (`204`; `404` while unknown or running).

### Search

See `api/search-contract.md`: `match_reasons`, `snippet`, `folder_id`, `folder_name`, `mime_type`, `origin` per item and the `origin` filter.

### Drive, assets, albums

- `GET /drive/items?sort=name|modified|size|kind&order=asc|desc`: with `sort`, folders come first and both groups follow the key (`order` defaults to `asc`, `desc` for `modified`; folders sort by `item_count` for `size`, by name for `kind`); without it the listing stays newest first, mixed. Keep `sort`/`order` across a cursor's pages. Folder items carry `item_count` (live direct children).
- `AssetResponse` adds `offline_pinned` (the original is pinned in the cache), `locally_available` (the original opens offline: never uploaded, cached, or still in its backup source) and `exif: {camera_make, camera_model, lens_model, exposure_time_s, exposure_display, f_number, iso, focal_length_mm, latitude, longitude} | null` (parsed at read time from the stored EXIF; GPS is read from the GPS IFD for new uploads). `offline_pinned`/`locally_available` are filled on asset detail, photo detail, favorite, upload, Drive listings, and the timeline.
- `PATCH /photos/albums/{id}` `{title?, cover_asset_id?}` and `DELETE /photos/albums/{id}` (the album only; photos stay). Rename and delete sync through the album's `title`/`deleted_at` (LWW). `cover_asset_id` must be a member (`400 validation_failed` otherwise), `null` clears it, and it is **device-local**: the Sync `album` entity has no cover field and peers reject ops with unknown fields (`SyncOperation` validation), so syncing covers needs a protocol revision. `AlbumResponse` adds `cover_asset_id`.

### Events

`GET /events` (Server-Sent Events, bearer-guarded like every route) replaces polling: `?topics=library,jobs,imports,sync` (default all), `?max_seconds=` (≤ 3600, the server then closes; reconnect). Stream: `retry: 3000`, one `event: ready` (`data: {"topics": [...]}`), then `event: change` (`data: {"topics": ["library", ...]}`) whenever a watched topic changed, `: ping` comments every 15 s while idle. Events name what changed, never data; refetch: `library` → Drive/Photos/albums/search, `jobs` → `/jobs`, `/activity`, `/backup/status`, `imports` → `/android/imports/{id}`, `sync` → `/sync/status`, `/vault`, `/devices`, `/activity`. Changes are detected once per second from SQLite, so they include the worker's and sync's writes; nothing is replayed after a reconnect.

### Notifier

- `attention {code, count}`: the worker (every 30 s while running, and at the end of each bounded run) emits one event per Activity kind with items not announced before (`count` = new items of that kind). Announced ids live in `sync_state` (`activity.announced`), so background runs do not notify again. `new_device` items use their own event.
- `new_device {device_id, name}`: the sync engine, after a pull that introduced devices needing review.
- `pairing_request {request_id, device_name, platform}`: when the host indexes a new, unanswered fallback request (on `GET /pairing/requests` and reviews; there is no background scan of pairing requests yet).

### Stage 22h status (Android adoption)

What the Android app now uses from the 21b additions above, and what is left.

| 21b addition | Android (Stage 22h) | Where |
|---|---|---|
| DTOs | Regenerated from `core/api/openapi.json` at build time (no hand-merge); `libraryEvents` (`GET /events`) is excluded from the generated client like the binary routes and lives in `EventsClient` | `core/api/build.gradle.kts` |
| `code_length`, `code_delivery` | The code field auto-submits at `code_length` digits (5 when absent), caps its length, and the clipboard chip only offers a code of that length. The body names where the code went (Telegram app, SMS, call, email) | `feature/onboarding` `TelegramSignIn*.kt` |
| `creation.steps` | `GET /vault` is polled every 400 ms while the blocking `POST /vault` runs. "Creando tu nube" shows three rows: channels (`files`/`sync`/`inbox`, with "n de 3"), keys (`header`) and this phone (`device`), each pending, running, done or failed, and each a polite live region. The unused "Carpeta de Bento" row and its string were removed | `OnboardingViewModel.kt`, `OnboardingScreens.kt` |
| Phone login while pairing | `Usar mi número de teléfono` on `needs_telegram_login` keeps the pairing open and shows the phone, code and 2FA flow inside the pairing step (its own view model key). Back or authorization returns to the pairing, which continues by itself. A phone login already at `code_required` resumes there | `feature/pairing` `JoinViewModel.kt`, `JoinScreen.kt` |
| `bootstrapping` / `device_removed` | Reconnect shows "Comprobando tu nube…" and waits while `/vault` is `bootstrapping` (up to 30 s), then opens the existing DeviceRemoved route on `reason: device_removed`. Creation checks for a removal before `POST /vault`. The app gate keeps re-reading `/vault` every 2 s while `bootstrapping` (up to 60 s), so a removal found by the first pull routes to `Route.DeviceRemoved` | `OnboardingViewModel.kt`, `AppGate.kt` (`updates()`), `MainActivity.kt` |
| Search `match_reasons`, `snippet`, `origin` | Reasons come from the codes (`exif_date` becomes "Fecha de la foto"; unknown codes are skipped; `semantic` is never shown). The Spanish `reason` parsing stays as the fallback for answers without codes. The snippet line shows the server's `highlights` in bold; file-name snippets are left out because the title already carries the name. The Origen chip follows the 22g pattern ("Origen: Este teléfono" description, `Role.DropdownList`, "Quitar el filtro «Origen»" action, sheet, side-pane section) with `device`/`peer`/`telegram` | `feature/search` |
| Drive `sort`/`order`, `item_count` | The sort sheet sends `sort`/`order` on every page of the listing, and the backend order is shown as it comes. A sort change re-sorts locally right away, then reloads. The local comparator now matches the backend (folders by `item_count` for size). Folders show "1240 elementos" through `BentoFormat` plurals | `feature/files` `FilesRepository.kt`, `FilesSort.kt`, `FilesComponents.kt` |
| `exif` | The info sheet uses the backend summary (camera, lens, exposure, GPS). The on-device EXIF reader only runs when `exif` is null and the original is `locally_available`, so the sheet no longer downloads originals over the network. The date row stays `taken_at` | `feature/viewer` `ViewerState.kt`, `ViewerViewModel.kt` |
| `offline_pinned`, `locally_available` | Files: "Disponible sin conexión" (pin) or "En este teléfono" badges, and offline opening no longer refuses a locally available file. Pin and unpin update the row at once and invalidate Drive and Photos. Viewer: a "Uso sin conexión" info row (pinned, opens offline, or needs a connection), and the menu toggle starts from `offline_pinned`. Photo tiles show a pin badge and TalkBack reads "disponible sin conexión" | `feature/files`, `feature/viewer`, `feature/photos` `MediaTile.kt` |
| Albums `PATCH`/`DELETE`, `cover_asset_id` | Album detail overflow: `Cambiar nombre` (sheet, empty name refused) and `Eliminar álbum`, confirmed with a `BentoDialog` that says the photos stay. "Usar como portada en este teléfono" appears in the selection bar with one photo selected, and its snackbar says "en este teléfono" (the cover never claims to sync). Album cards use `cover_asset_id` | `core/data` `AlbumsRepository`, `feature/collections` `AlbumManage.kt`, `feature/photos` |
| `GET /events` | `EventsClient` streams it through the loopback client (bearer and server-proof interceptors from 22f), with a 45 s read timeout (pings every 15 s). It reconnects after the server's `retry:` hint and backs off on failure (doubling, 30 s cap). After 3 attempts in a row that never reached `ready`, it falls back to the old jobs/sync fingerprint polling for 60 s and then retries the stream. A stream that comes back emits one change for every topic, because nothing is replayed. `Invalidations` maps topics: `library` → timeline, drive, search, albums, trash; `jobs` → activity, settings; `imports` → activity; `sync` → activity, devices, account. An unknown topic invalidates everything | `core/api` `EventsClient.kt`, `BentoHttp.open`, `core/data` `Invalidation.kt` |

Left for later:

- **SEC-06 live-code redaction (gap).** `bento.interfaces.android.redaction.register/unregister` exists in Python, but nothing on the Android side can reach it: `engine.py` has no entrypoint for it, and there is no HTTP route either. The codes are typed on the phone and only travel to the backend over loopback. The right fix is backend-side: `application/pairing.py` should register the pairing code from `POST /pairing/join` (and the host code it creates) for the session's lifetime, and the Telegram login adapter should register the login code and 2FA password while `code_required`/`password_required` is live. The Kotlin code never logs these values.
- Activity items `import_interrupted` and `import_failed`, and the notifier events `attention`, `new_device` and `pairing_request`: owned by agent 41 (`feature/activity`, `feature/settings`, backup and notifications). The `jobs`/`imports`/`sync` event topics already invalidate `Topic.ACTIVITY`, `Topic.SETTINGS` and `Topic.DEVICES`, so their screens only need to follow `Invalidations` instead of polling.
- `DevicesViewModel` still polls pairing requests every 5 s (`feature/devices` was out of this stage's scope), and the import progress in `feature/files/Uploads.kt` still polls `GET /android/imports/{id}` (400 ms, only while an import runs). Both could follow the `sync`/`imports` topics.
- Clearing an album cover (`cover_asset_id: null`) is not offered. The generated client omits nulls (`explicitNulls = false`), so it would need a raw request like `FilesRepository.moveFolder`.
- `locally_available` is not shown on photo tiles, because nearly every camera-roll photo is still in its backup source and the badge would be noise. It is shown in Files and in the viewer.
- Protocol: a removed phone still learns of its removal only after signing in again (see "Removed devices" above).
