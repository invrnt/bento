# Android release (local, signed APK + signed update manifest)

Distribution v1 (`orchestration/product/android.md` §2): signed APKs (arm64-v8a and universal) attached to a GitHub
release `android-vX.Y.Z`, plus one Ed25519-signed update-manifest entry per APK. The app's updater (`core/update`)
reads that manifest. **Everything builds, signs and verifies locally**: there is no Android release workflow, and
`scripts/release.sh` never pushes, tags or publishes; it prints the `gh` command for the owner.

## Versions

- Tag `android-vX.Y.Z` (each part below 1000). `versionName = X.Y.Z`, `versionCode = X·10⁶ + Y·10³ + Z`
  (e.g. 1.2.3 → 1002003). Both APKs of a release share the versionCode.
- `app/build.gradle.kts` takes `-PbentoVersion=X.Y.Z`, else the exact `android-v*` tag at HEAD, else `0.1.0`.
- Android releases are separate from desktop `vX.Y.Z` releases and are created with `--latest=false`, because the
  desktop updater reads `releases/latest`.

## One-time owner setup

1. **Upload/signing keystore** (never committed; `*.jks`/`*.keystore` are git-ignored). Keep it and its passwords in a
   password manager plus an offline backup: losing it means users must uninstall to update, and Google Play's
   later channel must use the same key.

   ```sh
   keytool -genkeypair -keystore ~/secure/bento-android-release.p12 -storetype PKCS12 \
     -alias bento -keyalg RSA -keysize 4096 -validity 10000 -dname "CN=Bento"
   chmod 600 ~/secure/bento-android-release.p12
   keytool -list -v -keystore ~/secure/bento-android-release.p12 -alias bento | grep SHA256   # pin this
   ```

2. **Update-manifest key**: the same Ed25519 key as the desktop updater (`BENTO_UPDATE_SIGNING_KEY`, see
   `docs/desktop/releasing.md`). If it does not exist yet:
   `node apps/desktop/scripts/sign-update-manifest.mjs --generate-key ~/secure/bento-update-signing-key.pem`
   (prints `BENTO_UPDATE_PUBLIC_KEY=…`, the public half that builds embed).

3. Shell environment for a release (e.g. a `release.env` outside the repo, mode 600, sourced by hand):

   ```sh
   export BENTO_ANDROID_KEYSTORE=~/secure/bento-android-release.p12
   export BENTO_ANDROID_KEYSTORE_PASSWORD=…   BENTO_ANDROID_KEY_ALIAS=bento   BENTO_ANDROID_KEY_PASSWORD=…
   export BENTO_UPDATE_SIGNING_KEY_FILE=~/secure/bento-update-signing-key.pem
   export BENTO_UPDATE_PUBLIC_KEY=<base64 raw key>
   export BENTO_ANDROID_CERT_SHA256=<keystore SHA-256, optional pin checked against every APK>
   ```

   The keystore values can instead live in `~/.gradle/gradle.properties` as `bentoReleaseStoreFile`,
   `bentoReleaseStorePassword`, `bentoReleaseKeyAlias`, `bentoReleaseKeyPassword`. Passwords travel to Gradle through
   the environment or that file, never on the command line.

4. The App Links certificate fingerprint for `/.well-known/assetlinks.json` is the keystore SHA-256 above.

## Releasing

```sh
git tag -s android-v1.2.3 -m "Bento para Android 1.2.3"     # on the reviewed main commit
cd apps/android && source ~/secure/release.env
scripts/release.sh                                          # version from the tag; or --version 1.2.3
git push origin android-v1.2.3
# then run the printed `gh release create … --latest=false` command
```

`release.sh` (JDK 17, `--max-workers=2`, `-Xmx2g`):

1. builds `:app:assembleRelease` twice: `-PbentoAbis=arm64-v8a` → `bento-android-X.Y.Z-arm64-v8a.apk` and
   `-PbentoAbis=arm64-v8a,x86_64` → `bento-android-X.Y.Z-universal.apk` (Chaquopy needs `ndk.abiFilters` and
   refuses AGP ABI splits, so each APK is its own build), embedding `BENTO_UPDATE_PUBLIC_KEY`;
2. verifies each APK: `apksigner verify --print-certs` (v2/v3, one signer, optional pinned cert), `aapt2 dump badging`
   (package, versionCode/Name, native code, not debuggable) and the absence of debug-only code (kitchen sink,
   specimens, media samples, debug shortcuts, Compose test/tooling activities); it also reports the runtime-gated
   debug paths that remain (see below);
3. writes `SHA256SUMS-android-X.Y.Z.txt` and archives the R8 `mapping.txt` per APK under `mapping/` (keep it privately
   to deobfuscate crash traces; it is not a release asset);
4. writes `bento-update-android-{arm64,universal}.json` with `scripts/update_manifest.mjs` and signs each into a
   detached `.sig` with the desktop's format code (`apps/desktop/src/main/update-signature.ts`), then verifies them
   against `BENTO_UPDATE_PUBLIC_KEY`. The signing key path is read from the environment and never printed.

Output: `apps/android/build/release/android-vX.Y.Z/`.

### Dry run

`scripts/release.sh --dry-run [--version 0.1.0]` runs the whole pipeline with a throwaway PKCS12 keystore and a
throwaway Ed25519 key generated once into `build/release-dry-run/keys/` (random passwords in a 0600 file). Dry-run
APKs read a local feed at `http://127.0.0.1:8799` instead of GitHub, so an update can be tested end to end on an
emulator:

```sh
scripts/release.sh --dry-run --abi universal --version 0.1.0
scripts/release.sh --dry-run --abi universal --version 0.1.1
python3 -m http.server 8799 --bind 127.0.0.1 --directory build/release-dry-run/feed &
adb install build/release-dry-run/feed/download/android-v0.1.0/bento-android-0.1.0-universal.apk
adb reverse tcp:8799 tcp:8799      # the app's 127.0.0.1:8799 reaches the host feed
# open Ajustes › Acerca de › Actualizaciones (or the card) → Descargar → Instalar → system confirmation
```

Never publish dry-run artifacts: they are signed by a test key.

## Update manifest (Android entry)

Same schema as the desktop's per-target manifests plus an `android` block; detached `<manifest>.sig` in the
desktop format (`{"schemaVersion":1,"algorithm":"ed25519","signatures":[{keyId,signature}]}` over
`"bento-update-manifest:v1\0" + bytes`, `keyId` = first 16 hex of SHA-256 of the raw public key; up to four
signatures during a key rotation).

```json
{
  "schemaVersion": 1, "version": "1.2.3", "releaseName": "Bento 1.2.3", "notes": "…",
  "publishedAt": "…", "commit": "<40 hex>", "repository": "invrnt/bento", "target": "android-arm64",
  "assets": [{ "platform": "android", "arch": "arm64", "kind": "apk",
               "filename": "bento-android-1.2.3-arm64-v8a.apk",
               "url": "https://github.com/invrnt/bento/releases/download/android-v1.2.3/bento-android-1.2.3-arm64-v8a.apk",
               "sha256": "<64 hex>", "size": 123 }],
  "android": { "packageName": "dev.bento.app", "versionCode": 1002003, "minSdk": 29,
               "signingCertificateSha256": ["<64 hex>"] }
}
```

## In-app updater (`core/update`)

- Feed: GitHub releases API (`api.github.com/repos/invrnt/bento/releases`), highest non-draft, non-prerelease
  `android-vX.Y.Z` release; downloads `bento-update-android-<arch>.json` + `.sig` (arm64 on arm64 phones, universal
  otherwise). This is the only network call besides Telegram and the relay. Builds without
  `-PbentoUpdatePublicKey` (debug by default) are `Unavailable` and never contact it.
- Verification order: Ed25519 signature by an embedded key → manifest content (repository, target, package, tag ==
  version, versionCode derived from version, HTTPS URL ending in the file name, `minSdk`) → versionCode greater than
  the installed one (else "up to date") → download to `noBackupFilesDir/bento-update/` with HTTP Range resume →
  size + SHA-256 → `PackageManager.getPackageArchiveInfo`: same package, signed versionCode, signer equals the
  installed app's current certificate (or its v3 rotation lineage contains it) and is listed in the manifest →
  `PackageInstaller` session with `USER_ACTION_REQUIRED` (never silent). "Instalar apps desconocidas" is checked first
  and opened from the card when off; the user cancelling the system dialog returns to "Lista para instalar".
- Daily background check: WorkManager, unmetered network, battery not low; it only checks.
- UI: `UpdateCard()` (calm card, hidden after "Ahora no" for that version) and `UpdateRow()` for Ajustes › Acerca de;
  strings in `core/strings/.../strings_update.xml`. Goldens: `core/update/screenshots/`.

## Debug code in release

Compiled out (checked by `release.sh`): debug source sets (kitchen sink, specimens, media samples, debug launcher
shortcuts), Compose test/tooling manifests, `debuggable`. Still present but runtime-gated: `DebugOptions` (dev endpoint
file, only written when `EngineBuildInfo.debugTools`, which is `BuildConfig.DEBUG`) and the Python `fake_telegram`
adapter (imported by `infrastructure/runtime.py`; `interfaces/android/engine.py` refuses the fake backend in
production). Removing those needs changes in `core/engine` / `apps/api`.
