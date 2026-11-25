# Android security review (Stage 22 release gate)

Scope: the Android-specific surface of `feature/android` at `0b611cf`: the embedded engine and loopback API, the
Keystore wrapping key, data at rest, FileProvider, exported components and intents, pairing links, FLAG_SECURE,
logging and redaction, release-build exclusions, the Kotlin↔Python bridges, and pinned dependencies. The review was
read-only on product code. No Gradle run (RAM), so no merged manifest exists under `build/`. Manifests were read from
sources: `app`, `app/src/debug`, `core/{engine,background,designsystem(debug)}`, `feature/onboarding`.

Release gate (`orchestration/testing/android-journeys.md`): every **high** and **medium** finding must be fixed.
This review found **no high** findings and **3 medium** findings (SEC-01, SEC-02, SEC-03).

## Findings

| ID | Sev | Title | Owner path | Evidence | Status |
| --- | --- | --- | --- | --- | --- |
| SEC-01 | medium | Bearer token lives for the whole process; it is reused across API restarts and sent to whatever listens on the old port | `apps/android/core/engine`, `apps/api/src/bento/interfaces/android/engine.py` | `BentoEngine.kt:51,111-117,175-190,234-241`; `engine.py:171-177`; `BentoHttp.kt:61-68` | fixed (`bfb2aad`, `0604475`) |
| SEC-02 | medium | Pillow 11.0.0 in the APK (PSD out-of-bounds writes) parses untrusted shared files with every format plugin enabled | `apps/android/python-wheels`, `apps/api/src/bento/adapters/media` | `requirements-android.txt` (`pillow==11.0.0`); `adapters/media/metadata.py:80-87`; `generator.py:54` | fixed (`c3a03ba`) |
| SEC-03 | medium | App lock and the recents-preview hiding (`setRecentsScreenshotEnabled(false)`) are not implemented | `apps/android/feature/settings` (in progress), `app` | `product/android.md:195,208`; no `BiometricPrompt`/`setRecentsScreenshotEnabled` in the tree | open: agent 41 (`feature/settings`) |
| SEC-04 | low | Decrypted copies in `cacheDir/share` can outlive the 1 h TTL, and URI grants are never revoked | `feature/files`, `feature/photos` | `ContentFiles.kt:79-82`; `FilesModule.kt:69`; `MediaExporter.kt:32-44,97-100` | fixed (`4e2a2fd`) |
| SEC-05 | low | A malformed `%` escape in a `bento://join` or App Link crashes `MainActivity` | `app` | `DeepLinks.kt:27-30`; `MainActivity.kt:44,61,64-68` | fixed (`da2c21d`) |
| SEC-06 | low | Redaction patterns miss pairing codes, phone numbers without `+`, login codes and 2FA passwords; warm-up logs reach logcat before redaction is installed | `apps/api/src/bento/interfaces/android` | `redaction.py:23-47`; `engine.py:122-140` vs `203-211` | fixed (`bfb2aad`) |
| SEC-07 | low | starlette 0.46.2 (CVE-2025-62727 Range DoS, CVE-2025-54121), reachable only after bearer auth | `apps/api` (`uv.lock`), `python-wheels` | `requirements-android.txt` (`starlette==0.46.2`) | fixed (`c3a03ba`) |
| SEC-08 | low | FLAG_SECURE missing on the guest pairing-code entry and on the Telegram login-code step | `feature/pairing`, `feature/onboarding` | `JoinScreen.kt:249`; `TelegramSignIn.kt:332` | fixed (`7f3f522`) |
| SEC-09 | low | No tapjacking protection on high-value confirmations (approve a pairing device, recovery) | `feature/pairing`, `feature/recovery` | `HostPairingScreen.kt:138`; no `filterTouchesWhenObscured`/`setHideOverlayWindows` in the tree | fixed (`7f3f522`) |
| SEC-10 | low | The App Links host silently defaults to `bento.example`, and the `bento://` scheme can be claimed by any app | `app`, backend pairing link | `app/build.gradle.kts:20`; `AndroidManifest.xml:64-83` | fixed (`da2c21d`) |
| SEC-11 | low | When the Keystore key is lost, the app regenerates it next to an unreadable `wrapping.bin`, then fails to start in a permanent loop with no recovery UX | `core/engine` | `KeystoreKeyWrapping.kt:32-39,80` | fixed (`0604475`) |
| SEC-12 | low | Other apps can open unlimited connections to the loopback API (no `limit_concurrency`) | `interfaces/android/engine.py` | `engine.py:331-336` | fixed (`bfb2aad`) |
| SEC-13 | low | `MainActivity` keeps the default `taskAffinity` with `singleTask` (task-hijacking class) | `app` | `AndroidManifest.xml:54-60` | fixed (`da2c21d`) |
| I-1..I-10 | info | Verified controls and notes (see below) | — | — | — |

### SEC-01 (medium): the API token is per process, not per engine start

**Evidence.**
- `BentoEngine.kt:51`: `private val apiToken by lazy(tokenFactory)` creates one token per `BentoEngine`, which is
  an `@Singleton`. That makes it one token per process.
- `BentoEngine.kt:175-182`: `configure` runs only once (`configured = true`).
- `engine.py:171-177`: `configure` with a different token raises `EngineConfigError` ("restart the process").
- `BentoEngine.kt:111-117`: `reportStall()` restarts a dead API on a new port and publishes `ready.copy(port = port)`,
  which carries the same token.
- `BentoEngine.kt:234-241`: `stopNow()` calls `runtime.stop()` (up to 10 s, and it closes the listener) while
  `state` is still `Ready(port, token)`. The state flips to `Stopped` only afterwards.
- `BentoHttp.kt:61-68`: the interceptor attaches `Authorization: Bearer` to any server answering on
  `127.0.0.1:<port>`. The client never authenticates the server.
- `android-runtime.md:35` promises a token "generated per engine start" and a port that "changes every start".

**Exploit.**
1. A malicious app with only `INTERNET` scans loopback ports. Bento's 401 JSON (`api_token_required`) fingerprints
   it, and `/proc/net` is not needed.
2. The app polls the port. When Bento's listener closes (the idle stop after 60 s in the background, an API crash,
   or a stall restart), the app binds the same port.
3. Requests that are in flight or arrive in that window (Coil, ExoPlayer, workers, repository refreshes) go to the
   attacker with the bearer token.
4. The token stays valid for the next API start on its new port. The attacker can then call the real API: download
   every decrypted original (`/api/assets/{id}/content`), create pairing sessions, and so on.

The attack needs a race but no permission beyond `INTERNET`.

**Fix.**
1. Rotate the token on every API start. Add a Python entry point (`start_api(token)` or `rotate_api_token`) that
   swaps `process_secrets[API_TOKEN_ENV]` and the guard's token. Have Kotlin generate a fresh token in `startNow()`
   and on the stall restart, and register each one with `Redaction`.
2. Leave `Ready` (set `Stopping`/`Degraded`) before calling `runtime.stop()` and before probing a stalled API, so
   that no request is sent to a closing port.
3. Optional: have the server prove its identity before the token goes out, for example a response header with an
   HMAC of a client nonce under a second per-start secret. Alternatively, move to the abstract Unix socket with a
   peer-UID check (§12 stretch).

**Test.** `apps/android/core/testing/src/test/kotlin/dev/bento/testing/security/SecurityReviewFindingsTest.kt`
(`SEC-01 …` ×2) fails today. It was not run (no Gradle).

### SEC-02 (medium): Pillow 11.0.0 decodes untrusted files with every plugin

**Evidence.**
- `python-wheels/requirements-android.txt` pins `pillow==11.0.0` (Chaquopy repository build). Desktop `uv.lock` has
  11.3.0.
- Pillow 10.3.0 up to (not including) 12.1.1 has an out-of-bounds write when loading crafted PSD images
  (CVE-2026-25990, GHSA-cfh3-3jmp-rvhc, CVSS 8.9).
- Pillow before 12.2.0 has a second PSD tile-extent integer overflow that leads to an OOB write
  (CVE-2026-42311, GHSA-pwv6-vv43-88gr).
- `adapters/media/metadata.py:80-87` runs `Image.open(source_path)` with no `formats=` on every upload whose MIME is
  `image/*`. That covers share-sheet imports from any app, where the declared MIME and name are attacker-chosen. It
  then calls `getexif()`, and `generator.py:54` does the same for desktop thumbnails.

**Exploit.** The person receives a crafted file in a messenger and taps "Compartir → Bento", or another app sends
`ACTION_SEND` with a crafted `image/vnd.adobe.photoshop`. Native memory corruption happens in the process that holds
the unwrapped device key, the Telegram session, and the vault keyring.

**Fix.**
- Build or ship Pillow ≥ 12.2.0 for Chaquopy (as `pydantic-core` is built in `python-wheels/build_all.sh`).
- Independently, pass `formats=("JPEG", "PNG", "WEBP", "TIFF", "GIF", "MPO", "HEIF")` (or whatever the product
  supports) to every `Image.open`.

**Test.** `apps/api/tests/unit/android/test_security_review_findings.py::test_sec02_android_pillow_has_the_psd_fixes`
is `xfail(strict)`.

Related low/info: `cryptography==42.0.8` is a Chaquopy deviation (uv.lock 46.0.7). Bento uses AES-GCM, X25519,
HKDF and SPAKE2, and I found no advisory that affects that usage. The advisories against 42.x concern the OpenSSL
bundled in PyPI wheels and binary-curve ECDH. Track it with the Pillow rebuild.

### SEC-03 (medium, gate): app lock and recents hiding are absent

`product/android.md:195,208` requires "Bloqueo de la app" (biometric/PIN, timeout) and "Ocultar contenido en apps
recientes", with `setRecentsScreenshotEnabled(false)` while locked.

Nothing on `feature/android` implements them. `feature/settings` is still being written. Until then, the recents
thumbnail shows photos and file names, and anyone holding the unlocked phone has the vault.

Fix (owner: `feature/settings` + `app`):
- Lock state in `MainActivity` and `ShareActivity`.
- `setRecentsScreenshotEnabled(!lockEnabled)` on API 33+.
- FLAG_SECURE fallback while locked on API 29-32.
- Re-check after the configured timeout.
- Add a journey test.

### SEC-04 (low): decrypted copies outlive their TTL

**Evidence.**
- `ContentFiles.prune(everything = true)` runs once, when the Hilt singleton is created (`FilesModule.kt:69`).
- Afterwards, copies are pruned only when another copy is made (`ContentFiles.kt:34`, `MediaExporter.kt:33`).
- `MediaExporter` reuses `cacheDir/share/<assetId>/<name>` when the length matches, without refreshing its mtime
  (`MediaExporter.kt:36`). A reused copy can therefore be deleted while the receiver is reading it.
- Grants are never revoked.
- The process often lives for days, so a plaintext original can stay in `cacheDir/share` indefinitely, and a
  receiving app keeps its grant while its task lives.

**Fix.**
- Schedule a cleanup on `ON_STOP` or as a periodic WorkManager task.
- Call `revokeUriPermission` when the copy is pruned.
- Touch the mtime on reuse.
- Delete PDF reader copies on dispose. This is already documented; verify that the reader calls `discard`.

### SEC-05 (low): malformed deep link crashes the app

`DeepLinks.parseParams` calls `URLDecoder.decode` (`DeepLinks.kt:29`), which throws `IllegalArgumentException` on
`%zz`. `handleLink` runs in `onCreate` and `onNewIntent` without a catch (`MainActivity.kt:44,61`). Any web page or
app can therefore crash Bento with `bento://join?v=1&c=%zz`.

Fix: decode each parameter in `runCatching`, and add the case to `app/src/test` (the test could not live in
`core/testing` because `DeepLinks` is in `:app`).

### SEC-06 (low): redaction is pattern-based and misses short secrets

`redaction.py:23-47` removes registered secrets, `Bearer …`, `[A-Za-z0-9_-]{40,}` and `+digits`. It does not catch:
- pairing codes (`NNNN-SSSS-SSSS`, 14 characters)
- phone numbers without `+`
- the SMS login code
- the 2FA password (when it shows up in an exception message)

Today no logger call passes these. I checked every `logger.*` call in `application/pairing.py`,
`adapters/pairing/relay.py` and `adapters/telegram_mtproto/*`: they log session ids, states and error codes only. The
pattern layer is the only backstop, though.

Also, `warm_up()` (`engine.py:122-140`) runs before `configure` installs the redacting handler (`engine.py:203-211`).
Its warnings go through `logging.lastResort` to `sys.stderr`, which Chaquopy routes to logcat in release. Today only
module and exception class names are printed.

Fix:
- Have the pairing and login services register their codes with `redaction` while they are live (a
  `redaction.register(secret)` API).
- Add a bare-digits phone pattern for 7–15 digits in a `phone=` context.
- Install the file-only redacting handler at the start of `warm_up`.

Tests: `test_sec06_*` (xfail strict).

### SEC-07 (low): starlette 0.46.2

starlette 0.46.2 has CVE-2025-62727 (quadratic Range merging in `FileResponse`, fixed in 0.49.1) and CVE-2025-54121.
On Android, `LocalRequestGuard` rejects unauthenticated requests before routing, so only a token holder could
trigger it. The desktop shares the pin.

Fix: bump FastAPI/starlette in `uv.lock` and regenerate `requirements-android.txt`. Test: `test_sec07_*` (xfail
strict).

### SEC-08 (low): FLAG_SECURE gaps

Covered: recovery kit (`RecoveryKitScreen.kt:110`), recovery entry (`RecoveryEntry.kt:103`), host pairing code/QR
(`HostPairingScreen.kt:134`), 2FA in onboarding (`TelegramSignIn.kt:417`), and guest pairing
(`GuestPairing.kt:216`).

Missing:
- The guest code entry (`JoinScreen.kt:249`, `EntryStep`) shows the prefilled or typed pairing code.
- The login-code step (`TelegramSignIn.kt:332`).

The SAS approval on the host limits the impact. Fix: call `SecureWindow()` in both.

### SEC-09 (low): tapjacking

There is no `filterTouchesWhenObscured` and no `setHideOverlayWindows`. `minSdk = 29`: Android 10/11 do not block
touches through untrusted overlays. An overlay app could trick the host into tapping "Añadir" (pairing approval,
`HostPairingScreen.kt:138`) while it hides the SAS emojis.

Fix:
- On API 31+, call `window.setHideOverlayWindows(true)` (permission `HIDE_OVERLAY_WINDOWS`) while the approval,
  recovery and remove-device screens are shown.
- On API 29-30, reject touches with `MotionEvent.FLAG_WINDOW_IS_OBSCURED` on those buttons.

### SEC-10 (low): link claimability

`app/build.gradle.kts:20` defaults `bentoSiteHost` to `bento.example`. A release built without the property ships
an unverifiable `autoVerify` filter: links open in a chooser, and the `#c=` fragment goes to whichever app the person
picks. `bento://join` can be registered by any app.

Fix:
- Fail release assembly when `bentoSiteHost`/`bentoSiteUrl` are unset.
- Have the backend emit the https form whenever `site_url` is configured. This is already planned in
  `android-runtime.md` §9. Verify it on the Android host's "Compartir enlace" and QR.

Mitigation already in place: links prefill and never auto-join (`JoinViewModel.kt:88-96`), and the SAS is confirmed
on the host.

### SEC-11 (low): Keystore key loss is unrecoverable

If the AndroidKeystore alias disappears (OEM keystore reset, restore of app data without keys), `key()` generates a
new key (`KeystoreKeyWrapping.kt:80`). `unwrap` then fails with `AEADBadTagException`, which surfaces as
`BridgeException(IO)`. Every start fails and the app ends in `CRASH_LOOP` with no way out.

The tmp file is also renamed without `fsync` (`:37-39`).

Fix:
- When `wrapping.bin` exists but the alias does not, raise a typed "device key lost" error.
- Show "Este teléfono debe volver a vincularse / usar el kit": wipe `secure/` and catalog state, then go to Join or
  Recovery.
- `fsync` before the rename.

Biometric enrolment changes and removing the device credential do not affect this key. It is not auth-bound, by
design.

### SEC-12 (low): loopback connection flood

`uvicorn.Config` (`engine.py:334-336`) sets no `limit_concurrency` or `timeout_keep_alive` cap, and the backlog is
2048. Any app can hold thousands of idle connections and exhaust the engine's file descriptors or memory, a local DoS
of sync.

Fix: `limit_concurrency≈64` and a short `timeout_keep_alive`. The guard already answers 401 cheaply.

### SEC-13 (low): task affinity

`MainActivity` is `singleTask` with the package's default affinity (`AndroidManifest.xml:54-60`). A malicious app
declaring `taskAffinity="dev.bento.app"` can try StrandHogg-style task injection on unpatched OS versions.
`ShareActivity` already uses `taskAffinity=""`.

Fix: `android:taskAffinity=""` on `MainActivity`. Check that predictive back and the share hand-off still work.

## Fixes (Stage 22f)

| ID | Fix | Regression tests |
| --- | --- | --- |
| SEC-01 | Fresh `ApiCredentials(token, serverKey)` on every `start_api`; `configure` takes no token; Ready leaves before stop/probe; `X-Bento-Nonce`/`X-Bento-Proof` HMAC server proof, unverified answers dropped and the API restarted with new credentials (`android-runtime.md` §2.1) | `SecurityReviewFindingsTest` (5), `BentoHttpTest` `SEC-01 …` (3, shared vector), `test_start_api_rotates_credentials_and_proves_the_server`, `test_sec01_server_proof_*` |
| SEC-02 | Pillow 13.0.0 cross-built for both ABIs (`python-wheels/build_pillow.sh`, libjpeg-turbo 3.2.1 static, system zlib); desktop `pillow>=13,<14`; `Image.open(formats=open_formats())` (JPEG, MPO, PNG, WEBP, GIF, TIFF, HEIF, AVIF) in metadata and thumbnails | `test_sec02_android_pillow_has_the_psd_fixes`, `test_sec02_psd_is_never_parsed_by_metadata_or_thumbnails` |
| SEC-04 | Prune revokes FileProvider grants before deleting; `ShareCacheJanitor` every 10 min and on app stop; reused exporter copies refresh their TTL; PDF reader copies already discarded (verified) | `ContentFilesPruneTest` |
| SEC-05 | `DeepLinks` never throws (malformed escapes, >2048 chars, 16-param cap), `/join/` accepted; `handleLink` guarded | `DeepLinksTest` (`SEC-05 …`, trailing slash) |
| SEC-06 | `redaction.register/unregister`; pairing codes (all formats), join-link `c=`, phones with/without `+`, login codes, 2FA passwords; `install_early` in `warm_up` buffers redacted records (nothing reaches `lastResort`). Registering live codes from `application/pairing.py` and the Telegram login adapter is left to their owners (API ready) | `test_sec06_*` (5) |
| SEC-07 | FastAPI 0.165.0, Starlette 1.10.0 (floor `>=1.3.1`: all 0.x/1.0 have open advisories) | `test_sec07_starlette_has_the_range_fix` + full backend suite |
| SEC-08 | `SecureWindow()` in the join code entry and the Telegram login-code step | covered by existing `SecureWindow` tests |
| SEC-09 | `ObscuredTouchGuard`: `filterTouchesWhenObscured` (sheet-aware) + `setHideOverlayWindows` on API 31+ on pairing approval, device removal sheet, recovery kit and recovery entry | `RecoveryUiTest.sec09GuardFiltersObscuredTouchesUntilTheLastGuardLeaves` |
| SEC-10 | `:app:verifyReleaseSiteHost` fails `packageRelease`/`bundleRelease` without a real host and matching https URL; host share uses `webLink` when the backend has `site_url` (verified, `HostPairingScreen.kt:271`); links only prefill (verified) | build check (manual: `assembleRelease` without the properties fails) |
| SEC-11 | `DeviceKeyLostException`, `Degraded(KEY_LOST)` with no retry, "Restablecer este teléfono" (`DeviceReset`), `fsync` before rename | `KeystoreKeyWrappingTest` `SEC-11 …` (3), `BentoEngineTest` `SEC-11 …` |
| SEC-12 | uvicorn `limit_concurrency=64`, backlog 64, `timeout_keep_alive=5` | `test_sec12_loopback_uvicorn_limits_connections` |
| SEC-13 | `MainActivity` `taskAffinity=""` | emulator check below |

Not fixed here: SEC-03 (agent 41, `feature/settings`). `cryptography==42.0.8` on Android remains a Chaquopy deviation with OSV advisories (bundled-OpenSSL and binary-curve issues; Bento's AES-GCM/X25519/HKDF use is not affected as far as reviewed) — rebuild it like Pillow in a follow-up.

## Verified controls (info)

- **I-1 Loopback API.**
  - Binds `127.0.0.1` on an OS-assigned port (`engine.py:332`, `loopback.py:14-29`).
  - The token is 32 `SecureRandom` bytes in base64url (`ApiTokens.kt`) and is passed in memory only, never in env
    or files.
  - `hmac.compare_digest` is used, and exactly one `Authorization` header is required (`request_guard.py:68-108`).
  - The `Host` allow-list is loopback only, so DNS rebinding fails.
  - WebSocket handshakes go through the same guard (`:87,132`).
  - OpenAPI/docs are off in production (`engine.py:220`).
  - The token is attached only to `http://127.0.0.1:<engine port>` (`BentoHttp.kt:66`).
  - `Ready.toString()` redacts the token.
  - CORS preflights (`main.py:46-52`) are answered before the guard, but they only expose CORS headers.
- **I-2 Keystore.**
  - AES-256-GCM, StrongBox with TEE fallback (`KeystoreKeyWrapping.kt:76-106`), randomized IV, versioned blob.
  - Not user-auth-bound and no `setUnlockedDeviceRequired`, intentionally, for background sync (`android-runtime.md`
    §5).
  - The unwrapped key is zeroed in Kotlin after `configure` (`BentoEngine.kt:180`). Python keeps an immutable
    base64 copy in `process_secrets`; that is unavoidable, and it is registered for redaction.
- **I-3 Backup.** `allowBackup="false"`, `fullBackupContent="false"`, and `data_extraction_rules.xml` excludes every
  domain for both cloud backup and device transfer. The catalog, key store and logs live in `noBackupFilesDir` (CE
  storage).
- **I-4 FileProvider.** Not exported. It exposes only `cache-path share/`. Grants are per URI
  (`FLAG_GRANT_READ_URI_PERMISSION` plus `ClipData`) and go through the system chooser.
- **I-5 Exported components.**
  - Only `MainActivity` (launcher, `bento://join`, App Link) and `ShareActivity` (`SEND`/`SEND_MULTIPLE`/`VIEW
    content:`, `excludeFromRecents`, `taskAffinity=""`).
  - `EngineService`, the transfer services and `TransferActionReceiver` are `exported="false"`.
    `TransferJobService` requires `BIND_JOB_SERVICE`.
  - PendingIntents are explicit and `FLAG_IMMUTABLE` (`Transfers.kt:176-180`, `Notifications.kt:144-145`).
  - The kitchen sink (`exported="true"`) and its shortcut exist only in debug source sets.
  - Library components (WorkManager, ProfileInstaller with `DUMP`) are standard.
- **I-6 Share and content imports.**
  - Only `content:` URIs are accepted (`ShareIntents.kt:59`).
  - Kotlin `DisplayNames.file` and Python `sanitize_filename` strip separators, control characters and reserved
    names. Staging uses `mkstemp` (`media.py:36-48`).
  - fds are adopted exactly once, with a 10-minute TTL and close on stop (`ContentImportRegistry.kt`).
  - MediaStore `openFd` refuses non-MediaStore authorities (`AndroidMediaStoreSource.kt:200-207`).
  - A third app can make Bento import something Bento can read (MediaStore, its own `cacheDir/share`), but the
    result lands in the person's own vault, so there is no exfiltration path.
  - No archive extraction exists on this surface.
- **I-7 Release exclusions.**
  - Debug tools are keyed on `BuildConfig.DEBUG` (`AppModule.kt:18`) and `ENGINE_DEBUG_TOOLS` (`EngineModule.kt:58`).
    These are two flags; keep them in lockstep if a new build type is added.
  - Production refuses `storage_backend=fake` and `BENTO_FAKE_TELEGRAM_URL` (`engine.py:254-257`), and overrides
    are allow-listed (`:80-82,249-252`). Guard tests are in `test_security_review_findings.py`.
  - `routes_dev.py:20` is gated. `fake-telegram-serve` runs only on the e2e host.
  - `dev-endpoint.json` with the token is written in debug only.
  - Release has `isDebuggable=false` and R8. Release logcat is `EngineLog.None`, and Python mirrors to stderr only
    when not in production.
  - The network security config allows cleartext to `127.0.0.1` only. It does not govern Python sockets; the relay
    enforces `wss` except for loopback (`adapters/pairing/frames.py:108-123`), and Telethon is MTProto.
  - There is no WebView.
- **I-8** `REQUEST_INSTALL_PACKAGES` is declared but no installer code is on `feature/android`. The local-release
  updater branch must verify the APK signature and version before handing it to `PackageInstaller`, and should be
  reviewed when it merges.
- **I-9** The Telegram `api_id`/`api_hash` sit in `BuildConfig`. These are public client credentials, which is
  expected.
- **I-10 At rest.** Coil thumbnails (`cacheDir/images`), the UI cache (`filesDir/bento/ui-cache`, file names) and
  the catalog are plaintext under file-based encryption (CE). This is consistent with the local-first model, and all
  of it is excluded from backup. The Telegram session, keyring and device identity live in the Keystore-wrapped
  `WrappedFileKeyStore`.

## Tests added

| File | Status |
| --- | --- |
| `apps/android/core/testing/src/test/kotlin/dev/bento/testing/security/SecurityReviewFindingsTest.kt` | 5 SEC-01 regression tests, passing (`./gradlew check`). |
| `apps/api/tests/unit/android/test_security_review_findings.py` | xfails removed: SEC-02 ×2, SEC-06 ×5, SEC-07, SEC-01 proof ×2, SEC-12 and the 2 guards, all passing. |
