# Android development

How to build, test and release `apps/android` locally: Kotlin + Jetpack Compose over the same `bento` Python backend embedded with Chaquopy. Binding contracts: [product](../../orchestration/product/android.md), [runtime](../../orchestration/architecture/android-runtime.md), [endpoints](../../orchestration/api/android-endpoints.md), [journeys](../../orchestration/testing/android-journeys.md). Module map: [apps/android/README.md](../../apps/android/README.md). Background on the embedding: [Android spike](android-spike.md).

Everything here runs on a developer machine; no step needs GitHub Actions.

## Setup

| Tool | Version / where | Notes |
|---|---|---|
| JDK | **17** (Temurin) | AGP does not run on newer JDKs. With mise: `export JAVA_HOME=$HOME/.local/share/mise/installs/java/temurin-17`. |
| Build Python | **CPython 3.13** | Chaquopy needs a host Python of the same minor version as the embedded one. It does not have to be on `PATH`: pass it with `-PbentoBuildPython=$(uv python find 3.13)` (for example `~/.local/share/uv/python/cpython-3.13-linux-x86_64-gnu/bin/python3.13`). Install with `uv python install 3.13`. |
| Android SDK | `ANDROID_HOME` (default `~/Android/Sdk`) | Platform 37 (compileSdk), build-tools, platform-tools, emulator, NDK (for the wheels). |
| Emulator image | API 35 `google_apis` x86_64 | AVD `bento_spike_api35` (Pixel 7 profile) is what the e2e scripts expect (`AVD=…` to override). |
| `uv` | latest | Runs the backend on the host side of the e2e harnesses and the OpenAPI drift check. |
| Node 22+ | | Only for `apps/android/scripts` (token and icon generators) and the site. |

Create the AVD once:

```sh
sdkmanager "system-images;android-35;google_apis;x86_64" "platforms;android-37" "emulator" "platform-tools"
avdmanager create avd -n bento_spike_api35 -k "system-images;android-35;google_apis;x86_64" -d pixel_7
```

If your AVDs live outside `~/.android/avd` (for example a shared one in `~/.config/.android/avd`), export `ANDROID_AVD_HOME` to that directory before starting the emulator or the e2e scripts.

Build the Android wheels for the embedded backend once (and again when the backend's `android` extra changes):

```sh
apps/android/python-wheels/build_all.sh      # → apps/android/python-wheels/dist
```

### Build properties

Passed with `-P<name>=<value>` or in `~/.gradle/gradle.properties`:

| Property | Default | What |
|---|---|---|
| `bentoBuildPython` | — (required) | Host CPython 3.13 for Chaquopy. |
| `bentoAbis` | `x86_64` (`gradle.properties`) | `arm64-v8a,x86_64` to build both (releases). |
| `bentoSiteUrl` / `bentoSiteHost` | empty / `bento.example` | Public site origin (`https://<domain>`) for pairing links, and its host for the verified App Link intent filter. Release builds must use the production domain that serves `/.well-known/assetlinks.json` (see [site](site.md#android-app-links-and-downloads)). |
| `bentoRelayUrl` | unset | Pairing relay (`ws://127.0.0.1:8788` for the e2e harness). |
| `bentoTelegramApiId` / `bentoTelegramApiHash` | unset | Telegram credentials ([how to get them](telegram-credentials.md)); never commit them. |

## Build and check

```sh
cd apps/android
export JAVA_HOME=$HOME/.local/share/mise/installs/java/temurin-17
PY=$(uv python find 3.13)

./gradlew :app:assembleDebug -PbentoBuildPython=$PY
./gradlew check -PbentoBuildPython=$PY                 # unit tests, ktlint, detekt, lint
./gradlew :core:api:checkOpenApiDrift                  # generated DTOs vs the backend's OpenAPI
```

Gradle and the emulator are memory-hungry: on a machine with little free RAM, run one build at a time and keep `org.gradle.jvmargs` modest. Do not run `gradle --stop` while someone else's build shares the daemon.

When the backend's HTTP API changes, regenerate the snapshot with `uv run python -m bento.interfaces.http.export_openapi > apps/android/core/api/openapi.json` (or `./gradlew :core:api:updateOpenApiSnapshot`).

## Screenshot tests (Roborazzi)

Every feature module keeps its goldens in `feature/<name>/screenshots/<state>/` with `light.png`, `dark.png`, `font-200.png`, `compact.png` and `expanded.png` (JVM, no emulator).

```sh
./gradlew :feature:photos:verifyRoborazziDebug -PbentoBuildPython=$PY     # compare against the goldens
./gradlew :feature:photos:recordRoborazziDebug -PbentoBuildPython=$PY     # rewrite goldens after an intended change
```

Review the PNG diffs before committing recorded goldens. The public site's Android page uses some light goldens: after they change, run `node apps/site/scripts/import-android-screenshots.mjs` (needs ImageMagick) and commit the WebP files it writes.

## Instrumented journeys and e2e harnesses

The journeys of [testing/android-journeys.md](../../orchestration/testing/android-journeys.md) run on the emulator against the embedded engine and a **remote fake Telegram cloud**: `bento-sidecar fake-telegram-serve --dir <dir> --port <p>` serves the fake Telegram directory over HTTP, and the app's debug build reads `fake_telegram_url` from `files/dev-options.json` (host processes use `BENTO_FAKE_TELEGRAM_URL`). The phone (`http://127.0.0.1:<p>` through `adb reverse`) and headless desktops on the host then act as devices of one account. This is debug-only and compiled out of release builds ([endpoints §9](../../orchestration/api/android-endpoints.md)).

| Harness | Journeys | Host side |
|---|---|---|
| [feature/pairing/e2e](../../apps/android/feature/pairing/e2e/README.md) | 1-4, 13-15 (first run, join by code and by App Link, recovery, phone as host, removal, session revoked) | `trust_host.py`: fake cloud :8790, relay double :8788, two headless desktops :8791/:8792 |
| [feature/files/e2e](../../apps/android/feature/files/e2e/README.md) | 6, 8, 9 (share to Bento, Archivos, search of desktop OCR) | `files_host.py`: fake cloud :8790, one headless desktop :8791 |

```sh
cd apps/android
./gradlew :app:assembleDebug :app:assembleDebugAndroidTest -PbentoRelayUrl=ws://127.0.0.1:8788 \
  -PbentoSiteUrl=https://bento.example -PbentoBuildPython=$PY
flock "$HOME/.cache/bento-android-emulator.lock" feature/pairing/e2e/run_journeys.sh             # all, es-ES
flock "$HOME/.cache/bento-android-emulator.lock" feature/pairing/e2e/run_journeys.sh j03_joinByAppLink
APP_LOCALE=en-US flock "$HOME/.cache/bento-android-emulator.lock" feature/files/e2e/run_journeys.sh j90_englishFiles
```

Each script boots the AVD headless, starts its host harness with `uv`, maps the ports with `adb reverse`, clears the app before every journey and pulls in-app screenshots under `apps/android/build/<harness>-journeys/`. Use the `flock` so only one run owns the emulator at a time. Other suites: `./gradlew :app:connectedDebugAndroidTest :smoke:connectedCheck` (process-death and cold-start smoke) and the Fotos journeys and Macrobenchmarks in [feature/photos/README.md](../../apps/android/feature/photos/README.md).

To try the App Link by hand on the emulator:

```sh
adb shell am start -a android.intent.action.VIEW -d "https://bento.example/join#v=1&c=K7Q2-MXR9-T4WA"
adb shell pm get-app-links dev.bento.app        # verification state of the https host
```

A debug build is only *verified* for a real domain whose `assetlinks.json` lists the debug certificate; otherwise Android shows a chooser or opens the browser, which is the "not installed" path of the site's `/join` page.

## Release (local, signed)

v1 ships as signed APKs attached to GitHub releases and linked from the site ([product §2](../../orchestration/product/android.md)): one `arm64-v8a` APK (recommended) and one universal APK. The local signed-release path is `apps/android/scripts/release.sh`; read its header for the exact arguments. In outline it:

1. builds the release variant with R8 for both outputs, with `BENTO_ENVIRONMENT=production` (no fake backend, no dev endpoints);
2. signs them with the release keystore, which lives outside the repository and is passed through the environment (never commit it or its passwords);
3. writes the SHA-256 of each APK (`SHA256SUMS-android`) and the signed update-manifest entry that the in-app updater checks.

Then, by hand:

1. Create the GitHub release (or add to it) and upload both APKs, `SHA256SUMS-android` and the manifest files.
2. Point the site at the exact files: fill `android.release` in [apps/site/site.config.json](../../apps/site/site.config.json) with the tag, the two file names and their SHA-256 ([how](site.md#android-app-links-and-downloads)), run `npm --prefix apps/site test` and deploy the site.
3. Install the arm64 APK on a real phone over the previous release and check that the in-app update and the App Link both work.

### Signing certificate fingerprint

App Links are verified against the SHA-256 fingerprint of the signing certificate. Get it from the keystore or from a signed APK:

```sh
keytool -list -v -keystore <release.keystore> -alias <alias> | grep 'SHA256:'
apksigner verify --print-certs <app-release.apk> | grep 'SHA-256'   # hex without colons: add them
```

Put it, upper-case with colons, in `android.sha256CertFingerprints` of `apps/site/site.config.json`. The site's production build (`npm run deploy`) refuses to run while that list still holds the placeholder. If Google Play is added later with Play App Signing, add Play's app-signing fingerprint to the same list.

The certificate must never change for the life of the app: Android only installs updates signed with the same certificate, and the in-app updater checks it too.

## Troubleshooting

- **`Could not determine Java version` / AGP errors at configuration:** `JAVA_HOME` points at a JDK newer than 17.
- **Chaquopy: `buildPython` not found or wrong version:** pass `-PbentoBuildPython` with an absolute path to CPython 3.13.
- **Wheels missing (`No matching distribution` while Chaquopy installs requirements):** run `python-wheels/build_all.sh`.
- **Emulator `PANIC: Unknown AVD name`:** set `ANDROID_AVD_HOME` to where the AVD lives, or pass `AVD=<name>` to the e2e scripts.
- **e2e host never prints `…_READY`:** read `build/<harness>-journeys/host.out`; usually `uv` cannot resolve the backend or a port (8788-8792) is taken.
