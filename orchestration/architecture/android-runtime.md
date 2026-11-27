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
- The API binds `127.0.0.1` on an ephemeral port (`bento.interfaces.android.engine` reuses `bind_loopback_listener`). Every request needs `Authorization: Bearer <token>`; the request guard also checks `Host`. Other apps on the phone can reach loopback ports; without the token they get `401`. uvicorn caps connections (`limit_concurrency=64`, backlog 64, 5 s keep-alive) so they cannot flood it. Unix domain sockets are a spike stretch goal (§12), not a requirement.

### 2.1 Per-start credentials and server proof (SEC-01)

Another app can bind a loopback port the moment Bento's listener frees it (idle stop, API crash, stall restart) and receive whatever the client sends there. So the client never trusts a port by itself:

- **Credentials per API start.** Kotlin generates a fresh `ApiCredentials(token, serverKey)` (two independent 32-byte `SecureRandom` values, base64url) for every `start_api(api_token, server_key)` call: engine start, restart after the idle stop, and stall or identity-failure restarts. `configure` no longer takes a token. New credentials replace a running server (new port); the same ones return its port. A token therefore dies with the server that accepted it: one captured by a squatter is useless against the next start. Both values are registered for redaction on both sides and never leave memory.
- **One snapshot.** `EngineState.Ready(port, token, serverKey, mode)` changes as a whole. `LoopbackAuthInterceptor` reads one snapshot per request and attaches the token only when the request URL is `http://127.0.0.1:<that port>`; a request built for an older port goes out without it.
- **Leave Ready first.** `stopNow` sets `Stopped` before `runtime.stop()` closes the listener; `reportStall` sets `Degraded(STALLED)` before probing. No request is sent to a port that is closing or being checked.
- **Server proof.** Each request carries `X-Bento-Nonce` (16 random bytes); the engine's `ServerProofMiddleware` (outermost ASGI layer, so 401s are signed too) answers `X-Bento-Proof = base64url(HMAC-SHA256(serverKey, "bento-server-proof-v1|<port>|<nonce>"))`. The key never crosses the socket and the port is bound into the MAC, so neither a squatter nor a relay to the real API's new port can forge it. A missing or wrong proof: the interceptor closes the response unread, throws `UnverifiedServerException`, and `BentoEngine.reportUnverifiedServer(port)` leaves Ready at once and restarts the API with new credentials. Both implementations share a test vector (`BentoHttpTest`, `test_security_review_findings.py`).
- Residual: the first request to a squatted port still carries the (by then dead) token and its body; the proof check stops everything after it. The listener is only freed by a stop or a crash, and the client leaves Ready before a stop.

## 3. Engine lifecycle

`BentoEngine` is an application-scoped singleton with reference-counted **holders**:

| Holder | Acquired by | Engine mode |
|---|---|---|
| `ui` | `MainActivity`/`ShareActivity` started | API + worker (full) |
| `work:<name>` | a WorkManager worker or UIDT job running | worker; API started lazily only if a bridge-facing endpoint is needed |
| `transfer` | an active user-initiated transfer | worker |

- `Application.onCreate` starts the interpreter on a background thread immediately (warm-up imports in a fixed order measured by the spike); the first frame never waits for it.
- `start()` sequence: interpreter ready → `engine.configure(paths, platform="android", wrapping_key, build_config)` → migrations (`alembic upgrade head`, fast path when already at head) → worker start → API start with fresh credentials (§2.1) → emits `Ready(port, token, serverKey)`.
- Device key lost (SEC-11): if `wrapping.bin` exists but the AndroidKeystore key is gone, replaced, or the file is corrupt, `KeystoreKeyWrapping` throws `DeviceKeyLostException` (it never generates a new key next to an existing `wrapping.bin`). The engine enters `Degraded(KEY_LOST)` without retrying, and the shell shows "Restablecer este teléfono": `DeviceReset` deletes the wrapped key, the Keystore key, `noBackupFilesDir/bento`, `filesDir/bento` and the caches, then the app restarts into onboarding (link again or use the recovery kit). `wrapping.bin` is `fsync`ed before the rename that publishes it.
- When the last holder is released, the engine waits 60 s, then asks the worker to finish the current job step, disconnects Telethon, and stops the loops. The interpreter itself stays loaded until the OS kills the process.
- Crash isolation: an uncaught Python exception in a loop restarts that loop with backoff (1, 5, 30 s) and records a redacted diagnostic; three crashes in 5 min surface an attention item. Python stdout/stderr go to a redacted rotating log in `noBackupFilesDir/logs`, never to logcat in release builds.
- Kotlin reads engine state through a `StateFlow<EngineState>` (`Starting`, `Ready(port, token)`, `Degraded(reason)`, `Stopped`). UI repositories suspend on `Ready` only for network calls; cached UI state renders before (§8).

## 4. Python package on Android

- Chaquopy Gradle plugin builds the interpreter and pip dependencies per ABI. The Python source set points at `apps/api/src` (no copy); a Gradle task excludes tests, `__pycache__`, desktop-only modules (`interfaces/desktop/updater*`, `adapters/media/ffmpeg*`, watchdog watcher) via an explicit include list kept next to the build file.
- Dependency profile `android` in `apps/api/pyproject.toml` (optional extra): `fastapi`, `pydantic`, `pydantic-settings`, `sqlalchemy`, `alembic`, `cryptography`, `spake2`, `segno`, `telethon`, `uvicorn` (**without** `[standard]`: no uvloop/httptools/watchfiles), `websockets`, `python-multipart`, `pillow`. Not on Android: `watchdog`, `onnxruntime`, `rapidocr`, `pypdfium2`, `pyinstaller`, ffmpeg.
- Native wheels needed for Android ABIs: `cryptography`, `pydantic-core`, `pillow` (and optionally `cryptg` for Telethon AES speed). Source of wheels, in order: Chaquopy package repository → `cibuildwheel` Android builds published to an internal index in CI. The spike records which path each wheel took.
- Python version = the newest Chaquopy-supported version satisfying `requires-python >= 3.12`, pinned in the spike report.
- SQLite: Python's `sqlite3` with FTS5 (verified in the spike). `sqlite-vec` is not loaded on Android v1.

### 4.1 Spike findings (Stage 19, binding)

From `docs/dev/android-spike.md`:

- Pins: AGP 9.5.2, Kotlin 2.4.21, Gradle 9.9.2, Chaquopy 17.2.0, JDK 17, NDK r27b, **Python 3.13** (Chaquopy has no 3.14 builds of cryptography/pillow/cffi/greenlet). Stage 20 raised compileSdk to **37** (minor 2; Compose BOM 2026.11.01 / Material 3 1.5 need it); targetSdk stays 36, minSdk 29.
- `cryptg` is **mandatory** on Android (pure-Python AES runs at ~0.4 MB/s; with `cryptg` 293-432 MB/s). Telethon's libssl fallback does not find Chaquopy's renamed `libssl_python.so`.
- `cryptography` is 42.0.8 on Android (Chaquopy repository); the backend's `>=46` floor becomes `>=42` for the `android` extra only; every API Bento uses exists in 42. Building 46 for Android in CI is the follow-up.
- `pydantic-core` and `cryptg` are cross-compiled with maturin for both ABIs (`apps/android/python-wheels/build_all.sh`, ext-suffix fix); pure-Python sdists (`pyaes`, `hkdf`) are prebuilt as wheels because Chaquopy 17 refuses sdists. CI builds these wheels (cached artifact) and Gradle passes `python-wheels/dist` to Chaquopy pip with `--find-links`. `python-wheels/requirements-android.txt` is generated from the backend's `android` extra (`uv export --extra android --no-dev --no-emit-project`, Android markers, a short list of Chaquopy-build overrides) and checked by `:core:engine:checkPythonRequirements`.
- The process that runs the engine must be kept un-frozen while it works: the engine runs inside a **bound/started service** (`EngineService`) whenever any holder is active, not just as an application singleton; Android's cached-app freezer otherwise stalls background requests.
- Measured on the emulator: engine ready p50 2.9 s / p90 3.1 s; Python PSS ~152 MB idle (budget raised to **160 MB**, reduction work tracked: lazy Telethon, no OpenAPI build at start, alembic-free head check, launcher split); APK arm64 ~29 MB download.
- Chaquopy refuses AGP ABI splits; per-ABI APKs are produced as separate flavors (`abi` dimension) in Stage 22.

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

### 5.1 Bridge signatures (binding for agents 35 and 36)

- Application id `dev.bento.app`; Kotlin root package `dev.bento`; bridges live in `dev.bento.engine.bridge`.
- Kotlin passes bridge **instances** in `configure(config)["bridges"]` (keys below); Python never looks classes up by name, so tests inject plain Python fakes with the same methods.
- Arguments are primitives/strings; structured results are **JSON strings** (snake_case keys). Failures throw `dev.bento.engine.bridge.BridgeException(code: String, message: String)`; adapters map `code` to typed Python errors (`unsupported`, `not_found`, `permission_denied`, `io`, `cancelled`).
- `source` arguments are an absolute path or `fd:<n>` (a file descriptor owned by the caller).
- Kotlin → Python notifications go through `bento.interfaces.android.engine.on_event(kind: str, payload_json: str)` (thread-safe, non-blocking; kinds `media_changed`, `conditions`, `access_changed`, `low_memory`).

| Key | Kotlin interface | Methods |
|---|---|---|
| `media_tools` | `MediaTools` | `thumbnail(source, output, maxSide: Int, quality: Int, format: String /* jpeg\|webp */): String` → `{width,height}`; `videoFrame(source, output, maxSide: Int, quality: Int, atMs: Long): String` → `{width,height,duration_ms}`; `pdfPage(source, output, page: Int, maxSide: Int): String` → `{width,height,page_count}`; `metadata(source, mime: String): String` → `{width,height,duration_ms,taken_at,orientation,exif:{make,model,lens,f_number,exposure_time,iso,focal_length,gps:{lat,lon}?}}` |
| `ocr` | `Ocr` | `available(): Boolean`; `recognize(source, maxSide: Int): String` → `{text, language, lines:[{text, box:[x,y,w,h], confidence}]}` |
| `media_store` | `MediaStoreSource` | `access(): String` → `{full, partial, location}`; `buckets(): String` → `[{bucket_id, name, relative_path, count, video_count}]`; `scan(bucketId: String, afterMediaId: Long, limit: Int): String` → `{items:[MediaItem], next_after: Long?}`; `changes(sinceGeneration: Long, limit: Int): String` → `{items:[MediaItem], max_generation}`; `exists(mediaIds: String /* JSON list */): String` → JSON list of ids still present; `openFd(uri: String, requireOriginal: Boolean): Int` (detached; Python closes). `MediaItem = {media_id, uri, bucket_id, display_name, mime_type, size_bytes, date_taken_ms, date_modified_s, generation, width, height, duration_ms, relative_path}` |
| `conditions` | `DeviceConditions` | `snapshot(): String` → `DeviceConditions` JSON (`api/android-endpoints.md` §2) |
| `notifier` | `Notifier` | `emit(event: String, payloadJson: String)` (events of `api/android-endpoints.md` §7) |
| `content_imports` | `ContentImports` | `describe(handle: Long): String` → `{display_name, mime_type, size_bytes?}`; `adopt(handle: Long): Int` (one-time detached fd) |

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
| Document text without OCR (`text_extract`) | plain text files only (≤ 4 MiB read, stops at `check_safe_boundary()` like other bounded work; not in the deferred `indexing` class because it is cheap and renders nothing). PDF text layers are not read on Android (no pypdfium2): PDFs there are indexed by OCR as before, or by the text a desktop publishes |
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
- Links are untrusted input (SEC-05/SEC-10): any app can claim `bento://` and any page can fire it. `DeepLinks` never throws (malformed `%` escapes drop the parameter, links over 2048 characters are ignored), accepts `/join` and `/join/`, and a code only prefills the join screen (the person confirms, and the host confirms the SAS). Release builds fail (`:app:verifyReleaseSiteHost`, wired to `packageRelease`/`bundleRelease`) unless `-PbentoSiteHost=<production host>` and `-PbentoSiteUrl=https://<that host>` are set; debug keeps the `bento.example` default.
- `MainActivity` is `singleTask` with `taskAffinity=""` (and `ShareActivity` keeps `taskAffinity=""`), so no other app can declare Bento's affinity to inject activities into its task (SEC-13).
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
  build-logic/              convention plugins (android application/library/compose, hilt, openapi), OpenAPI → Kotlin generator
  python-wheels/            locally built Android wheels (build_all.sh) and the generated requirements-android.txt
  scripts/                  design-system generators (tokens, Lucide icons) and their drift check
  app/                      Application, MainActivity, ShareActivity, navigation, DI, manifest
  core/engine/              Chaquopy config, BentoEngine, bridges, python include list
  core/api/                 OkHttp client, generated DTOs, SSE, Coil fetcher, Media3 data source
  core/data/                repositories, paging sources, UI cache
  core/designsystem/        theme (generated tokens), typography, icons (generated), primitives
  core/strings/             string resources es/en (the Android dictionary)
  core/background/          WorkManager workers, UIDT/FGS, notifications, QS tile
  core/testing/             fakes for engine/bridges/api
  feature/{onboarding,pairing,recovery,photos,viewer,files,search,collections,share,activity,settings,devices}/
  smoke/                    separate-process instrumentation: SIGKILL during upload, Macrobenchmark cold-start smoke
  baselineprofile/, benchmark/   Baseline Profile generator, Macrobenchmark (Stage 22; smoke/ hosts the startup smoke until then)
```

- Gradle Kotlin DSL, AGP/Kotlin/Compose BOM at the latest stable versions at Stage 19 start, recorded in the spike report; compileSdk 37 (minor 2), targetSdk 36, minSdk 29 since Stage 20.
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
