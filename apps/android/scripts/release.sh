#!/usr/bin/env bash
# Local Android release (no CI): builds signed release APKs (arm64-v8a + universal) with JDK 17, verifies them with
# apksigner/aapt2, checks that debug-only code is absent, computes SHA-256, writes and signs the Ed25519 update
# manifest entries with the desktop's format and key, and prints the `gh release create` command for the owner.
# It never pushes, tags or publishes anything. Docs: docs/dev/android-release.md.
#
#   scripts/release.sh --version 1.2.3            real release (keystore + update key from the environment)
#   scripts/release.sh --dry-run [--version 0.1.0] throwaway keystore + update key in build/release-dry-run
#   options: --abi all|arm64|universal (default all)   --out <dir>   --feed-port 8799 (dry run)
#            --skip-build (re-verify and re-sign the APKs already in --out)
#
# Real release environment (or the equivalent Gradle properties in ~/.gradle/gradle.properties for the keystore):
#   BENTO_ANDROID_KEYSTORE, BENTO_ANDROID_KEYSTORE_PASSWORD, BENTO_ANDROID_KEY_ALIAS, BENTO_ANDROID_KEY_PASSWORD
#   BENTO_UPDATE_SIGNING_KEY_FILE (PKCS#8 PEM path) or BENTO_UPDATE_SIGNING_KEY (PEM text), BENTO_UPDATE_PUBLIC_KEY
#   BENTO_ANDROID_CERT_SHA256 (optional pin: the expected APK signing certificate SHA-256)
set -euo pipefail
umask 077

ANDROID_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$ANDROID_DIR/../.." && pwd)"
REPOSITORY="invrnt/bento"
VERSION=""
ABI="all"
DRY_RUN=0
SKIP_BUILD=0
OUT=""
FEED_PORT=8799

die() { echo "release: $*" >&2; exit 1; }
step() { printf '\n==> %s\n' "$*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --version) VERSION="${2:-}"; shift 2 ;;
    --abi) ABI="${2:-}"; shift 2 ;;
    --out) OUT="$(realpath -m "${2:-}")"; shift 2 ;;
    --feed-port) FEED_PORT="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
case "$ABI" in all) LABELS=(arm64 universal) ;; arm64|universal) LABELS=("$ABI") ;; *) die "--abi must be all, arm64 or universal" ;; esac

# --- Toolchain -------------------------------------------------------------------------------------------------------
export JAVA_HOME="${JAVA_HOME:-$HOME/.local/share/mise/installs/java/temurin-17}"
grep -q 'version "17' <<<"$("$JAVA_HOME/bin/java" -version 2>&1)" || die "JAVA_HOME must point to JDK 17 (got $JAVA_HOME)"
export PATH="$JAVA_HOME/bin:$PATH"
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
if [ -z "$SDK" ] && [ -f "$ANDROID_DIR/local.properties" ]; then SDK="$(sed -n 's/^sdk\.dir=//p' "$ANDROID_DIR/local.properties")"; fi
SDK="${SDK:-$HOME/Android/Sdk}"
BUILD_TOOLS="$(find "$SDK/build-tools" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort -V | tail -1)"
[ -n "$BUILD_TOOLS" ] || die "no Android build-tools under $SDK"
APKSIGNER="$BUILD_TOOLS/apksigner"
AAPT2="$BUILD_TOOLS/aapt2"
BUILD_PYTHON="${BENTO_BUILD_PYTHON:-$HOME/.local/share/uv/python/cpython-3.13-linux-x86_64-gnu/bin/python3.13}"
[ -x "$BUILD_PYTHON" ] || BUILD_PYTHON="$(command -v python3.13 || true)"
[ -n "$BUILD_PYTHON" ] || die "Python 3.13 not found (set BENTO_BUILD_PYTHON)"
command -v node >/dev/null || die "node is required (manifest signing reuses apps/desktop's format code)"
MANIFEST_TOOL="$ANDROID_DIR/scripts/update_manifest.mjs"
node_quiet() { node --no-warnings "$@"; }

COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
if [ -z "$VERSION" ]; then
  TAG="$(git -C "$REPO_ROOT" describe --tags --exact-match --match 'android-v*' HEAD 2>/dev/null || true)"
  VERSION="${TAG#android-v}"
fi
if [ -z "$VERSION" ] && [ "$DRY_RUN" = 1 ]; then VERSION="0.1.0"; fi
[[ "$VERSION" =~ ^(0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2})$ ]] || die "version must be X.Y.Z (pass --version or tag android-vX.Y.Z), got '$VERSION'"
VERSION_CODE=$(( BASH_REMATCH[1] * 1000000 + BASH_REMATCH[2] * 1000 + BASH_REMATCH[3] ))
TAG="android-v$VERSION"

# --- Keys ------------------------------------------------------------------------------------------------------------
FEED_URL=""
BASE_URL=""
if [ "$DRY_RUN" = 1 ]; then
  OUT="${OUT:-$ANDROID_DIR/build/release-dry-run}"
  KEYS="$OUT/keys"
  mkdir -p "$KEYS"
  chmod 700 "$KEYS"
  if [ ! -f "$KEYS/dry-run.p12" ]; then
    step "Generating a throwaway keystore (dry run only) in $KEYS"
    {
      echo "export BENTO_ANDROID_KEYSTORE_PASSWORD='$(head -c 24 /dev/urandom | base64 | tr -d '/+=')'"
      echo "export BENTO_ANDROID_KEY_PASSWORD=\"\$BENTO_ANDROID_KEYSTORE_PASSWORD\""
    } > "$KEYS/passwords.env"
    # shellcheck source=/dev/null
    . "$KEYS/passwords.env"
    keytool -genkeypair -keystore "$KEYS/dry-run.p12" -storetype PKCS12 -alias bento-dry-run -keyalg RSA -keysize 4096 \
      -validity 10000 -dname "CN=Bento release dry run" -storepass:env BENTO_ANDROID_KEYSTORE_PASSWORD \
      -keypass:env BENTO_ANDROID_KEY_PASSWORD >/dev/null 2>&1
  fi
  # shellcheck source=/dev/null
  . "$KEYS/passwords.env"
  export BENTO_ANDROID_KEYSTORE="$KEYS/dry-run.p12" BENTO_ANDROID_KEY_ALIAS="bento-dry-run"
  if [ ! -f "$KEYS/update-signing-key.pem" ]; then
    step "Generating a throwaway Ed25519 update-manifest key (dry run only)"
    node_quiet "$REPO_ROOT/apps/desktop/scripts/sign-update-manifest.mjs" --generate-key "$KEYS/update-signing-key.pem" \
      | sed -n 's/^BENTO_UPDATE_PUBLIC_KEY=//p' > "$KEYS/update-public-key.txt"
  fi
  export BENTO_UPDATE_SIGNING_KEY_FILE="$KEYS/update-signing-key.pem"
  BENTO_UPDATE_PUBLIC_KEY="$(cat "$KEYS/update-public-key.txt")"
  export BENTO_UPDATE_PUBLIC_KEY
  unset BENTO_UPDATE_SIGNING_KEY BENTO_ANDROID_CERT_SHA256
  FEED_ORIGIN="http://127.0.0.1:$FEED_PORT"
  FEED_URL="$FEED_ORIGIN/repos/$REPOSITORY/releases"
  BASE_URL="$FEED_ORIGIN/download/$TAG"
else
  OUT="${OUT:-$ANDROID_DIR/build/release/$TAG}"
  GRADLE_PROPS="${GRADLE_USER_HOME:-$HOME/.gradle}/gradle.properties"
  if [ -z "${BENTO_ANDROID_KEYSTORE:-}" ] && ! grep -q '^bentoReleaseStoreFile=' "$GRADLE_PROPS" 2>/dev/null; then
    die "no release keystore: set BENTO_ANDROID_KEYSTORE (+ _PASSWORD, _KEY_ALIAS, _KEY_PASSWORD) or bentoRelease* in $GRADLE_PROPS"
  fi
  [ -n "${BENTO_UPDATE_PUBLIC_KEY:-}" ] || die "BENTO_UPDATE_PUBLIC_KEY is required (it is embedded in the app and must match the signing key)"
  [ -n "${BENTO_UPDATE_SIGNING_KEY_FILE:-}${BENTO_UPDATE_SIGNING_KEY:-}" ] || die "set BENTO_UPDATE_SIGNING_KEY_FILE (or BENTO_UPDATE_SIGNING_KEY)"
  [ -z "$(git -C "$REPO_ROOT" status --porcelain)" ] || die "working tree is not clean"
  [ "$(git -C "$REPO_ROOT" rev-parse -q --verify "refs/tags/$TAG^{commit}" || true)" = "$COMMIT" ] || die "tag $TAG must exist and point at HEAD"
fi
mkdir -p "$OUT/mapping" "$OUT/verify"
[ "$SKIP_BUILD" = 1 ] || rm -f "$OUT"/bento-android-*.apk
rm -f "$OUT"/bento-update-android-*.json* "$OUT"/SHA256SUMS-android-*.txt

# --- Build -----------------------------------------------------------------------------------------------------------
abis_for() { case "$1" in arm64) echo "arm64-v8a" ;; universal) echo "arm64-v8a,x86_64" ;; esac; }
abi_suffix() { case "$1" in arm64) echo "arm64-v8a" ;; universal) echo "universal" ;; esac; }

build() {
  local label="$1" name
  name="bento-android-$VERSION-$(abi_suffix "$label").apk"
  if [ "$SKIP_BUILD" = 1 ]; then
    [ -f "$OUT/$name" ] && [ -f "$OUT/mapping/${name%.apk}-mapping.txt" ] || die "--skip-build: $OUT/$name or its mapping is missing"
    return
  fi
  step "Building $name (ABIs $(abis_for "$label"), versionCode $VERSION_CODE)"
  local args=(":app:assembleRelease" "-PbentoAbis=$(abis_for "$label")" "-PbentoVersion=$VERSION"
    "-PbentoBuildPython=$BUILD_PYTHON" "-PbentoUpdatePublicKey=$BENTO_UPDATE_PUBLIC_KEY")
  [ -n "$FEED_URL" ] && args+=("-PbentoUpdateFeedUrl=$FEED_URL")
  (cd "$ANDROID_DIR" && ./gradlew -Dorg.gradle.jvmargs=-Xmx2g --max-workers=2 --quiet "${args[@]}")
  cp "$ANDROID_DIR/app/build/outputs/apk/release/app-release.apk" "$OUT/$name"
  chmod 644 "$OUT/$name"
  cp "$ANDROID_DIR/app/build/outputs/mapping/release/mapping.txt" "$OUT/mapping/${name%.apk}-mapping.txt"
}

# --- Verify ----------------------------------------------------------------------------------------------------------
CERT=""
verify() {
  local label="$1" name apk report badging manifest_xml mapping cert signers
  name="bento-android-$VERSION-$(abi_suffix "$label").apk"
  apk="$OUT/$name"
  mapping="$OUT/mapping/${name%.apk}-mapping.txt"
  report="$OUT/verify/${name%.apk}.txt"
  step "Verifying $name"
  "$APKSIGNER" verify --print-certs --verbose "$apk" > "$OUT/verify/${name%.apk}-apksigner.txt" || die "apksigner rejected $name"
  # minSdk 29: apksigner reports the v3 block (v2 is still present for older verifiers); JAR signing must be off.
  grep -Eq "Verified using v(2|3) scheme \(APK Signature Scheme v(2|3)\): true" "$OUT/verify/${name%.apk}-apksigner.txt" || die "$name is not v2/v3-signed"
  grep -q "Verified using v1 scheme (JAR signing): false" "$OUT/verify/${name%.apk}-apksigner.txt" || die "$name is JAR-signed"
  signers="$(grep -c '^Signer #[0-9]* certificate DN' "$OUT/verify/${name%.apk}-apksigner.txt")"
  [ "$signers" = 1 ] || die "$name has $signers signers (expected 1)"
  cert="$(sed -n 's/^Signer #1 certificate SHA-256 digest: //p' "$OUT/verify/${name%.apk}-apksigner.txt" | tr 'A-F' 'a-f')"
  [ -n "${BENTO_ANDROID_CERT_SHA256:-}" ] && [ "$cert" != "$(echo "$BENTO_ANDROID_CERT_SHA256" | tr 'A-F:' 'a-f\0' | tr -d '\0')" ] &&
    die "$name is signed by $cert, not the pinned BENTO_ANDROID_CERT_SHA256"
  [ -z "$CERT" ] || [ "$CERT" = "$cert" ] || die "APKs are signed by different certificates"
  CERT="$cert"

  badging="$("$AAPT2" dump badging "$apk")"
  grep -q "^package: name='dev.bento.app' versionCode='$VERSION_CODE' versionName='$VERSION'" <<<"$badging" || die "$name: wrong package/version"
  ! grep -q "application-debuggable" <<<"$badging" || die "$name is debuggable"
  local native expected
  native="$(sed -n "s/^native-code: //p" <<<"$badging" | tr -d "'")"
  expected="$(abis_for "$label" | tr ',' ' ')"
  [ "$native" = "$expected" ] || die "$name: native code for '$native', expected '$expected'"

  manifest_xml="$("$AAPT2" dump xmltree --file AndroidManifest.xml "$apk")"
  # Debug-only code (debug source sets of app/core/designsystem/feature/photos) must not reach the release APK.
  local leaks=()
  grep -qi "kitchensink" <<<"$manifest_xml" && leaks+=("KitchenSinkActivity in the manifest")
  grep -q "debug_shortcuts" <<<"$manifest_xml" && leaks+=("debug launcher shortcuts")
  grep -q 'android:debuggable.*=true\|0x0101000f.*=true' <<<"$manifest_xml" && leaks+=("android:debuggable")
  # Listings are captured first: with pipefail, `unzip -l | grep -q` fails on SIGPIPE and would hide a match.
  local entries
  entries="$(unzip -Z1 "$apk")"
  grep -q "res/xml/debug_shortcuts" <<<"$entries" && leaks+=("res/xml/debug_shortcuts.xml")
  grep -Eq '^dev\.bento\.designsystem\.(kitchensink|specimen)\.|^dev\.bento\.feature\.photos\.MediaSamples' "$mapping" && leaks+=("kitchen sink/specimens/media samples in dex")
  grep -q 'ui-test-manifest\|androidx\.compose\.ui\.tooling\.PreviewActivity' <<<"$manifest_xml" && leaks+=("compose test/tooling activities")
  [ ${#leaks[@]} -eq 0 ] || die "$name contains debug-only code: ${leaks[*]}"

  # Informational: runtime-gated (not compiled-out) debug paths, for the security pass.
  local dev_options python_fake tmp
  dev_options="absent"
  grep -q '^dev\.bento\.engine\.DebugOptions ->' "$mapping" && dev_options="present (gated by EngineBuildInfo.debugTools=false)"
  tmp="$(mktemp -d)"
  python_fake="absent"
  if unzip -q -o "$apk" 'assets/chaquopy/app.imy' -d "$tmp" 2>/dev/null &&
    grep -q '^bento/adapters/fake_telegram/' <<<"$(unzip -Z1 "$tmp/assets/chaquopy/app.imy")"; then
    python_fake="present (refused when BENTO_ENVIRONMENT=production, interfaces/android/engine.py)"
  fi
  rm -rf "$tmp"

  local sha size
  sha="$(sha256sum "$apk" | cut -d' ' -f1)"
  size="$(stat -c %s "$apk")"
  echo "$sha  $name" >> "$OUT/SHA256SUMS-android-$VERSION.txt"
  {
    echo "apk: $name"
    echo "size: $size"
    echo "sha256: $sha"
    echo "package: dev.bento.app versionCode=$VERSION_CODE versionName=$VERSION"
    echo "native-code: $native"
    echo "signer certificate sha256: $cert"
    grep -E "^Verified using v[0-9]" "$OUT/verify/${name%.apk}-apksigner.txt" | sed 's/^/apksigner: /'
    echo "r8 mapping: mapping/${name%.apk}-mapping.txt ($(wc -l < "$mapping") lines)"
    echo "debug-only code (kitchen sink, specimens, media samples, debug shortcuts, debuggable): absent"
    echo "dev.bento.engine.DebugOptions (dev endpoint file): $dev_options"
    echo "python fake_telegram adapter: $python_fake"
  } > "$report"
  sed 's/^/    /' "$report"
}

# --- Manifest --------------------------------------------------------------------------------------------------------
manifest() {
  local label="$1" name
  name="bento-android-$VERSION-$(abi_suffix "$label").apk"
  step "Update manifest for android-$label"
  local args=(generate --apk "$OUT/$name" --arch "$label" --version "$VERSION" --commit "$COMMIT" --cert-sha256 "$CERT" --out "$OUT")
  [ -n "$BASE_URL" ] && args+=(--base-url "$BASE_URL")
  node_quiet "$MANIFEST_TOOL" "${args[@]}" | sed 's/^/    /'
}

for label in "${LABELS[@]}"; do build "$label"; verify "$label"; done
for label in "${LABELS[@]}"; do manifest "$label"; done
step "Checking manifest signatures against BENTO_UPDATE_PUBLIC_KEY"
node_quiet "$MANIFEST_TOOL" verify "$OUT"/bento-update-android-*.json | sed 's/^/    /'

ASSETS=()
for label in "${LABELS[@]}"; do
  ASSETS+=("$OUT/bento-android-$VERSION-$(abi_suffix "$label").apk" "$OUT/bento-update-android-$label.json" "$OUT/bento-update-android-$label.json.sig")
done
ASSETS+=("$OUT/SHA256SUMS-android-$VERSION.txt")
chmod 644 "${ASSETS[@]}"   # public artifacts; umask 077 only protects the keys and logs

if [ "$DRY_RUN" = 1 ]; then
  FEED="$OUT/feed"
  mkdir -p "$FEED/download/$TAG"
  cp "${ASSETS[@]}" "$FEED/download/$TAG/"
  node_quiet "$MANIFEST_TOOL" feed --root "$FEED" --origin "$FEED_ORIGIN" >/dev/null
  step "Dry run complete: $OUT"
  echo "    Local feed (every dry-run version built so far): $FEED"
  echo "    Serve it:  python3 -m http.server $FEED_PORT --bind 127.0.0.1 --directory '$FEED'"
  echo "    Device:    adb reverse tcp:$FEED_PORT tcp:$FEED_PORT   (the dry-run APKs read $FEED_URL)"
  echo "    The keystore and update key in $KEYS are throwaway test keys; never publish dry-run APKs."
else
  step "Release artifacts ready: $OUT"
fi

echo
echo "Owner action (not run by this script). Push the tag, then:"
printf '  gh release create %q --repo %q --verify-tag --latest=false \\\n' "$TAG" "$REPOSITORY"
printf '    --title %q --notes %q \\\n' "Bento para Android $VERSION" "Actualización estable de Bento $VERSION para Android."
for asset in "${ASSETS[@]}"; do printf '    %q \\\n' "${asset/#$REPO_ROOT\//}"; done | sed '$ s/ \\$//'
echo "  (--latest=false keeps the desktop updater, which reads releases/latest, on the desktop release.)"
echo "  Archive the R8 mappings in $OUT/mapping privately; they are not release assets."
