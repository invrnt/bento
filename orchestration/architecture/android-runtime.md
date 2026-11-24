# Android Runtime Architecture

Status: binding for Stages 19-22. Product contract: `product/android.md`. Protocol: `architecture/telegram-first.md` (unchanged; Android is one more device).

## 1. Decision

**Native Kotlin + Jetpack Compose UI on top of the existing Python backend, embedded in the app process with Chaquopy.** The phone runs the same `apps/api/src/bento` package as the desktop sidecars: the same domain, sync engine, crypto, pairing, Telethon transport, SQLite schema, and migrations. Kotlin owns everything the user touches and everything that is an Android system API; Python owns everything that is Bento.

Why:

- The Telegram-first protocol (epochs, floors, edited-message rules, grant authentication, HLC bounds, snapshot digests) is a security contract with hundreds of hardened rules and 800+ tests. A second implementation would drift; `repo-structure.md` already forbids a second backend.
- Kotlin + Compose (not React Native, Capacitor, or a WebView of `apps/web`) is the only way to hit the product bar: 120 Hz grids of 100k items, shared-element viewer transitions, predictive back, system photo picker, share targets, WorkManager/user-initiated jobs, MediaStore, Keystore, TalkBack-grade semantics.
- The UI talks to the backend through the **existing HTTP contract** on loopback, so `api/*.md` stays the single API and the desktop's request guard and token model are reused.

Rejected: React Native/Capacitor (the deferred note in `product/telegram-first-experience.md`; UX ceiling, still needs a native core), WebView of `apps/web` (desktop-shaped UI), Kotlin rewrite of the core with TDLib (drift, duplicate security surface) — kept only as Plan B (§13).

## 2. Process topology

```txt
Android app process (single process, com.<org>.bento)
├─ Kotlin UI — MainActivity (Compose), ShareActivity (translucent), QS tile, shortcuts
│   └─ core/data repositories ──HTTP/SSE──┐
├─ BentoEngine (Kotlin) — owns the embedded interpreter lifecycle
│   └─ Chaquopy Python runtime            │
│       ├─ API: FastAPI on uvicorn ◄───────┘  127.0.0.1:<ephemeral>, bearer token
│       ├─ Worker: job loop (same process, own asyncio loop/thread)
│       └─ Telethon clients (API + worker copies of one StringSession)
├─ Host bridges (Kotlin objects called from Python adapters via Chaquopy)
│   KeyWrapping · MediaTools · Ocr · MediaStoreSource · DeviceConditions · Notifier
└─ Background: WorkManager workers, user-initiated data transfer jobs (14+), dataSync FGS (≤ 13)
```

- One process. No `:remote` processes (the interpreter and SQLite must be single-owner).
- API and worker run on separate Python threads with separate asyncio loops, exactly mirroring the desktop's two sidecars, so backend code paths are identical. Each opens its own Telethon client from the shared `StringSession` (`telegram-first.md` § Process Topology).
- The API binds `127.0.0.1` on an ephemeral port (`bento.interfaces.android.engine` reuses `bind_loopback_listener`). Every request needs `Authorization: Bearer <token>` where the token is 32 random bytes generated per engine start by Kotlin and passed in-memory; the request guard also checks `Host`. Other apps on the phone can reach loopback ports; without the token they get `401` and the port changes every start. Unix domain sockets are a spike stretch goal (§12), not a requirement.

## 3. Engine lifecycle

`BentoEngine` is an application-scoped singleton with reference-counted **holders**:

| Holder | Acquired by | Engine mode |
|---|---|---|
| `ui` | `MainActivity`/`ShareActivity` started | API + worker (full) |
| `work:<name>` | a WorkManager worker or UIDT job running | worker; API started lazily only if a bridge-facing endpoint is needed |
| `transfer` | an active user-initiated transfer | worker |

- `Application.onCreate` starts the interpreter on a background thread immediately (warm-up imports in a fixed order measured by the spike); the first frame never waits for it.
- `start()` sequence: interpreter ready → `engine.configure(paths, platform="android", wrapping_key, api_token, build_config)` → migrations (`alembic upgrade head`, fast path when already at head) → worker start → API start → emits `Ready(port)`.
- When the last holder is released, the engine waits 60 s, then asks the worker to finish the current job step, disconnects Telethon, and stops the loops. The interpreter itself stays loaded until the OS kills the process.
- Crash isolation: an uncaught Python exception in a loop restarts that loop with backoff (1, 5, 30 s) and records a redacted diagnostic; three crashes in 5 min surface an attention item. Python stdout/stderr go to a redacted rotating log in `noBackupFilesDir/logs`, never to logcat in release builds.
- Kotlin reads engine state through a `StateFlow<EngineState>` (`Starting`, `Ready(port, token)`, `Degraded(reason)`, `Stopped`). UI repositories suspend on `Ready` only for network calls; cached UI state renders before (§8).

## 4. Python package on Android

- Chaquopy Gradle plugin builds the interpreter and pip dependencies per ABI. The Python source set points at `apps/api/src` (no copy); a Gradle task excludes tests, `__pycache__`, desktop-only modules (`interfaces/desktop/updater*`, `adapters/media/ffmpeg*`, watchdog watcher) via an explicit include list kept next to the build file.
- Dependency profile `android` in `apps/api/pyproject.toml` (optional extra): `fastapi`, `pydantic`, `pydantic-settings`, `sqlalchemy`, `alembic`, `cryptography`, `spake2`, `segno`, `telethon`, `uvicorn` (**without** `[standard]`: no uvloop/httptools/watchfiles), `websockets`, `python-multipart`, `pillow`. Not on Android: `watchdog`, `onnxruntime`, `rapidocr`, `pypdfium2`, `pyinstaller`, ffmpeg.
- Native wheels needed for Android ABIs: `cryptography`, `pydantic-core`, `pillow` (and optionally `cryptg` for Telethon AES speed). Source of wheels, in order: Chaquopy package repository → `cibuildwheel` Android builds published to an internal index in CI. The spike records which path each wheel took.
- Python version = the newest Chaquopy-supported version satisfying `requires-python >= 3.12`, pinned in the spike report.
- SQLite: Python's `sqlite3` with FTS5 (verified in the spike). `sqlite-vec` is not loaded on Android v1.

## 5. Platform adapters (Python) and host bridges (Kotlin)

Every Android capability enters the backend through an existing or new **port**, implemented by a Python adapter under `adapters/android/` that calls a Kotlin bridge through Chaquopy's `java` module. Only `adapters/android/*` and `interfaces/android/*` may import `java`/Chaquopy; they are wired only when `BENTO_PLATFORM=android` (`infrastructure/services.py`). Python tests replace bridges with fakes; nothing else in the backend knows it runs on Android.

| Port (Python) | Adapter `adapters/android/…` | Kotlin bridge `core/engine/bridge/…` | Behavior |
|---|---|---|---|
| Device wrapping key (configure arg) | — | `KeyWrapping` | AndroidKeystore AES-256-GCM key `bento.wrapping.v1` (StrongBox when present, else TEE; not user-auth-bound) wraps a random 32-byte `BENTO_DEVICE_WRAPPING_KEY` stored in `noBackupFilesDir/secure/wrapping.bin`. Unwrapped bytes are passed to `engine.configure` in memory, never in env vars or files. Backend `WrappedFileKeyStore` is unchanged. |
| `ThumbnailerPort` / media metadata ports (`ports/media.py`) | `media_tools.py` | `MediaTools` | Image thumbnails and previews via `ImageDecoder` (HEIC/AVIF/DNG/animated), video poster frames and duration via `MediaMetadataRetriever`, PDF page thumbnails and page count via `PdfRenderer`, EXIF via `ExifInterface`. Returns JPEG/WebP bytes at requested sizes. Pillow remains the fallback for formats the system cannot decode. |
| `OcrPort` (`ports/providers.py`) | `ocr_mlkit.py` | `Ocr` | ML Kit Text Recognition v2, **bundled** Latin model (on-device, no network, no Play services dependency). Same result shape as RapidOCR (text, lines, language). Only `origin=device` assets (enforced by the existing service). |
| Embeddings | disabled provider | — | v1 off; peers' `asset_index.embedding` is stored, not indexed. |
| `FolderWatcherPort`, scanner, `BackupSuggestionsPort` (`ports/backup.py`) | `media_store.py` | `MediaStoreSource` | Backup sources of kind `media_store` (bucket id). Scans with `MediaStore` queries (id, generation, size, date taken, mime, relative path, `IS_PENDING`/`IS_TRASHED` excluded), observes with `ContentObserver` while the engine runs, and opens content via `ContentResolver.openFileDescriptor(uri, "r")` → detached fd → `os.fdopen` for streaming hash/copy (no temp copy). `setRequireOriginal` when location permission is granted. Suggestions = buckets with counts. |
| `DeviceConditionsPort` (new, `ports/device.py`) | `conditions.py` | `DeviceConditions` | `{online, metered, unmetered_wifi, charging, battery_pct, power_save, data_saver, storage_free_bytes, thermal}` as a snapshot + change callbacks. The storage pipeline and indexing scheduler read it to apply Wi-Fi/charging/battery/thermal rules (§6). |
| `NotifierPort` (new, `ports/device.py`) | `notifier.py` | `Notifier` | The backend raises semantic events (`transfer_progress`, `attention`, `pairing_request`, `new_device`); Kotlin owns channels, text (Android strings), coalescing, and the ongoing progress notification. No user strings cross the bridge. |
| `ContentImportsPort` (new, `ports/device.py`) | `content_imports.py` | `ContentImports` | Kotlin opens a content URI, detaches the fd, and registers it under a one-time handle; Python adopts and closes it (`api/android-endpoints.md` §4). |
| Content import from share/SAF (small items) | — (HTTP) | — | Kotlin streams the content URI to `POST /api/assets/upload` (multipart, chunked) or, for large items, uses `POST /api/android/imports` with an fd handle (§`api/android-endpoints.md`). |

Bridge rules: calls are coarse (one call per file, never per byte); bridges never hold Python objects; exceptions map to typed Python errors; every bridge has a Kotlin interface + fake for JVM tests.

## 6. Background execution

| Trigger | Mechanism | Budget | Work |
|---|---|---|---|
| App visible | engine `ui` holder | unlimited | everything, real-time Telethon updates |
| New media in enabled buckets | WorkManager `OneTimeWorkRequest` with content-URI triggers (re-armed after each run), expedited when quota allows | ~10 min per run | scan → ingest (local-first) → upload by policy |
| Periodic | WorkManager periodic 1 h (flex 15 min), constraints: network connected, battery not low | ~10 min | sync pull/flush, inbox import, small uploads, reconcile (every 12 h) |
| Initial backup, share-to-Bento copies, user-started downloads/uploads > 50 MB, "Respaldar ahora" | **User-initiated data transfer job** (`JobInfo.Builder.setUserInitiated`, Android 14+) with its required notification; `dataSync` foreground service on Android ≤ 13 | system-managed, survives app close | bulk transfer |
| OCR backlog | WorkManager with `requiresCharging` + `requiresDeviceIdle` (default), batch of 20 | ~10 min | `ocr_index` jobs |
| Network regained | WorkManager network constraint on the periodic and pending work | — | resume |

- A run = acquire `work:<name>` holder → `engine.run_worker_until(deadline, kinds)` (§api) → release. The worker drains eligible jobs, stops at the deadline at a safe step boundary (uploads resume at part granularity via `upload_sessions`), and returns `{remaining, next_eligible_at}`; Kotlin re-enqueues accordingly.
- Never request battery-optimization exemption. OEM killers are handled by the stall card (`product/android.md` §11).
- Foreground service types declared: `dataSync` (≤ 13 path) and `shortService` is not used. Android 15's `dataSync` time limit is handled by preferring UIDT on 14+.
- Realtime sync freshness: foreground realtime; background ≤ 1 h; after a local change made in the UI, an expedited flush within seconds. No push notifications in v1 (Telegram pushes need an FCM project and do not fire for muted channels).

## 7. Capability profile on Android

| Capability | v1 on Android |
|---|---|
| Storage backends | `telegram`, `local`; `fake` only in debug builds |
| Pairing | relay (host and guest) and Sync-channel fallback |
| OCR | ML Kit bundled Latin; default on, charging + idle only |
| Search by meaning | off (no model on phone); FTS/name/metadata/OCR text work, including OCR text synced from desktops |
| Inbox import, Telegram import, share via Telegram | yes |
| Folder backup | MediaStore buckets only (no arbitrary filesystem paths); SAF folder upload as a one-shot import |
| Updates | signed manifest → verified APK → system installer (`PackageInstaller`); Play later |

## 8. UI data layer

- `core/api`: OkHttp client bound to the engine port + token; DTOs **generated** from the backend OpenAPI schema (`kotlinx.serialization`), never hand-written (no DTO duplication). A Gradle check fails when the checked-in OpenAPI snapshot is stale versus `create_app().openapi()` (exported by a backend script).
- `core/data`: repositories expose `Flow`/`PagingData`. Paging 3 with keyset cursors for timeline, drive items, search. Mutations are optimistic with rollback and `Deshacer`.
- **UI cache (instant start):** each top-level destination persists its first screen (≤ 300 items of DTOs) as a small file in `filesDir/ui-cache/` after every successful load; on cold start it renders immediately and is replaced by the live page (stable keys, no flicker). This is a view cache, not a second catalog; it is invalidated on vault change, sign-out, or schema version change.
- **Events:** one SSE/streaming connection to the existing jobs/events stream drives invalidation (`api/jobs-events-contract.md`); no polling while connected.
- **Images:** Coil 3 with a custom fetcher hitting `/assets/{id}/thumbnail?size=` and `/preview`, memory cache sized to 20 % of the app heap, disk cache in `cacheDir`. Viewer uses subsampling (Telephoto) for originals.
- **Video:** Media3 ExoPlayer with an `OkHttpDataSource` over the loopback API (Range).
- DI: Hilt. Navigation: Navigation 3 (adaptive list-detail scenes) — if the spike finds it unsuitable, Navigation Compose type-safe routes. Settings UI state that is purely local (theme, last sort, recent searches) lives in DataStore; everything else comes from the backend.

## 9. Links and intents

- `bento://join?v=1&c=…` custom scheme and **verified App Links** for `https://<site>/join` (fragment `#v=1&c=…`). `apps/site` publishes `/.well-known/assetlinks.json` with the release and upload signing certificate fingerprints. The backend's pairing `link`/QR payload switches to the https form when `site_url` is configured (desktop deep link handling already accepts both; the web `pairingCode.ts` parser already does).
- `bento-recovery:<code>` scanned in-app only.
- Share targets (`ACTION_SEND`/`SEND_MULTIPLE`, `*/*`), Direct Share via `ShortcutManagerCompat` sharing shortcuts, launcher shortcuts, `ACTION_VIEW` for opening a file "with Bento" (imports it).
- `tg://login?token=` (opening the Telegram app for login-token confirmation) — feasibility checked in the spike (§12); fallback is phone-number login.

## 10. Storage layout and data safety

```txt
noBackupFilesDir/bento/
  db/bento.sqlite (+wal)        catalog, jobs, sync state
  secure/*.bin                  WrappedFileKeyStore + wrapping.bin (Keystore-wrapped)
  logs/                         redacted rotating logs
filesDir/bento/
  blobs/                        local originals (until uploaded) and cached originals (LRU, pinnable)
  thumbs/                       thumbnails/previews (kept)
  ui-cache/
cacheDir/                       Coil disk cache, decrypted temporary share/open copies (deleted after 1 h or on next start)
```

- `android:allowBackup="false"` and `dataExtractionRules` excluding everything from cloud backup **and** device-to-device transfer: a restored copy would clone the device identity and Telegram session. A new phone joins by pairing.
- Decrypted temporary files for share/"Abrir con" are exposed only through a `FileProvider` with per-URI read grants and deleted after use.
- Release builds: no `debuggable`, R8 full mode, logs redacted, `fake` backend and dev endpoints compiled out (`BENTO_ENVIRONMENT=production`).
- Network security config: cleartext allowed only for `127.0.0.1`; relay over `wss`.

## 11. Build, modules, CI

```txt
apps/android/
  settings.gradle.kts, gradle/libs.versions.toml (version catalog, all versions pinned)
  app/                      Application, MainActivity, ShareActivity, navigation, DI, manifest
  core/engine/              Chaquopy config, BentoEngine, bridges, python include list
  core/api/                 OkHttp client, generated DTOs, SSE, Coil fetcher, Media3 data source
  core/data/                repositories, paging sources, UI cache
  core/designsystem/        theme (generated tokens), typography, icons (generated), primitives
  core/strings/             string resources es/en (the Android dictionary)
  core/background/          WorkManager workers, UIDT/FGS, notifications, QS tile
  core/testing/             fakes for engine/bridges/api
  feature/{onboarding,pairing,recovery,photos,viewer,files,search,collections,share,activity,settings,devices}/
  baselineprofile/, benchmark/   Baseline Profile generator, Macrobenchmark
```

- Gradle Kotlin DSL, AGP/Kotlin/Compose BOM at the latest stable versions at Stage 19 start, recorded in the spike report.
- CI (`.github/workflows/android.yml`): lint, detekt/ktlint, unit (JVM), Roborazzi screenshot tests, OpenAPI drift check, assemble release (unsigned in PRs), instrumented tests on an emulator (API 29 and latest), Macrobenchmark smoke on emulator. Release workflow signs with the upload key from secrets and publishes to Play internal testing.
- Backend CI adds `tests/unit/android` (adapters with fake bridges, run everywhere) and an `android` dependency-profile import smoke.

## 12. Stage 19 spike — go/no-go gate

Agent 34 builds a throwaway-quality but real APK that embeds the backend and measures. **Go** requires all of:

1. Backend imports and `alembic upgrade head` succeed on arm64 and x86_64 with the `android` profile; FTS5 available.
2. API answers `/api/health` from Kotlin with the token guard; worker runs a `thumbnail` job through the `MediaTools` bridge.
3. Telethon connects to the fake cloud (debug) and to real Telegram with a test account: QR login, phone login, upload/download of a 200 MB v2-encrypted file with resume after process kill.
4. Relay pairing: phone as guest joins a desktop host (including login-token forwarding) and bootstraps a 5,000-asset snapshot.
5. Measurements on the floor device and a reference device: interpreter warm-up, engine ready (≤ 4 s p90 floor), resident memory with engine idle (≤ 120 MB PSS for Python), APK size per ABI (≤ 60 MB arm64 download), encrypted upload throughput (≥ 8 MB/s on Wi-Fi on the reference device, with or without `cryptg`).
6. `tg://login?token=` confirmation from the same phone works with the Telegram app (if not: phone-number login is the primary path and §4.1 copy changes; not a no-go).

The spike report (`docs/dev/android-spike.md`) lists versions, wheel sources, numbers, and deviations. A miss on 1-4 or a budget miss > 50 % triggers Plan B review with the owner before Stage 20.

## 13. Plan B (only if the gate fails)

Kotlin core with TDLib for MTProto and the protocol reimplemented from `telegram-first.md`, validated by conformance vectors exported from the Python implementation (envelope, blob v2 with range reads, sealed boxes, grant auth, header MAC, HLC/LWW merge sequences, snapshot round trips) and by the multi-process e2e suite with a desktop peer. Estimated at 3-4× the effort of Plan A; it requires an owner decision and an update to this document first.
