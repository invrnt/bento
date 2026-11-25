#!/usr/bin/env bash
# Trust journeys (testing/android-journeys.md 1-4, 13-15) on the shared emulator, one cleared app per journey.
#
#   flock "$HOME/.cache/bento-android-emulator.lock" feature/pairing/e2e/run_journeys.sh [j01 j03 …]
#
# Needs: any debug app + androidTest APKs, the AVD, and uv for the host side. Starts the emulator headless, the host
# harness (trust_host.py) on free host ports (or BENTO_E2E_{RELAY,FAKE,DESKTOP,DESKTOP2}_PORT), maps the phone's fixed
# loopback ports onto them with `adb reverse`, points the app at the relay double through dev-options.json, runs the
# journeys, saves screenshots under $OUT, and stops everything it started (also on failure or Ctrl-C).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
android="$(cd "$here/../../.." && pwd)"
repo="$(cd "$android/../.." && pwd)"
# shellcheck source=../../../scripts/e2e_host.sh
source "$android/scripts/e2e_host.sh"
OUT="${OUT:-$android/build/trust-journeys}"
AVD="${AVD:-bento_spike_api35}"
SDK="${ANDROID_HOME:-$HOME/Android/Sdk}"
adb="$SDK/platform-tools/adb"
mkdir -p "$OUT"
journeys=("${@:-j01_firstRunNewVault j03_joinByAppLink j15_sessionRevoked j02_joinFromDesktopByCode j04_recoveryWithoutOtherDevice j13_phoneAsHost j14_removedFromDesktop}")
read -r -a journeys <<< "${journeys[*]}"

app_apk="$android/app/build/outputs/apk/debug/app-debug.apk"
test_apk="$android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"

# Phone-side ports: fixed (the androidTest HostDevice and dev options use them); host-side: free or given.
phone_relay=8788 phone_fake=8790 phone_desktop=8791 phone_desktop2=8792
host_relay="$(e2e_port "${BENTO_E2E_RELAY_PORT:-}")"
host_fake="$(e2e_port "${BENTO_E2E_FAKE_PORT:-}")"
host_desktop="$(e2e_port "${BENTO_E2E_DESKTOP_PORT:-}")"
host_desktop2="$(e2e_port "${BENTO_E2E_DESKTOP2_PORT:-}")"

cleanup() {
  e2e_stop_host
  [[ -n "${emu_pid:-}" ]] && { "$adb" emu kill >/dev/null 2>&1 || kill "$emu_pid" 2>/dev/null || true; }
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP

"$SDK/emulator/emulator" -avd "$AVD" -no-window -no-audio -no-snapshot-save -no-boot-anim -gpu swiftshader_indirect -memory "${EMU_MEMORY:-2048}" >"$OUT/emulator.log" 2>&1 &
emu_pid=$!
# Fail fast when the emulator cannot start (never hold the shared lock on a dead `wait-for-device`).
until "$adb" get-state >/dev/null 2>&1; do sleep 2; kill -0 "$emu_pid" 2>/dev/null || { tail -5 "$OUT/emulator.log"; exit 1; }; done
until [[ "$("$adb" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]]; do sleep 2; done
"$adb" shell settings put global window_animation_scale 0
"$adb" shell settings put global transition_animation_scale 0
"$adb" shell settings put global animator_duration_scale 0

# A fresh cloud and fresh desktops every run: leftovers from earlier runs change what the journeys see.
rm -rf "$OUT/host"
cd "$repo"
e2e_start_host "$OUT/host/pgids" uv run --quiet --project apps/api python "$here/trust_host.py" --root "$OUT/host" \
  --relay-port "$host_relay" --fake-port "$host_fake" --desktop-port "$host_desktop" --desktop2-port "$host_desktop2" >"$OUT/host.out" 2>&1
cd "$android"
until grep -q TRUST_HOST_READY "$OUT/host.out"; do sleep 1; kill -0 "$e2e_host_pid" 2>/dev/null || { cat "$OUT/host.out"; exit 1; }; done
e2e_reverse "$phone_relay" "$host_relay"
e2e_reverse "$phone_fake" "$host_fake"
e2e_reverse "$phone_desktop" "$host_desktop"
e2e_reverse "$phone_desktop2" "$host_desktop2"
echo "host ports: relay $host_relay, fake cloud $host_fake, desktop $host_desktop, desktop2 $host_desktop2"

"$adb" install -r -t "$app_apk" >/dev/null
"$adb" install -r -t "$test_apk" >/dev/null

status=0
for j in "${journeys[@]}"; do
  "$adb" shell pm clear dev.bento.app >/dev/null
  # Connectivity persists in the AVD: a journey that toggled airplane mode must not leave the next one off Wi-Fi.
  "$adb" shell cmd connectivity airplane-mode disable >/dev/null 2>&1 || true
  "$adb" shell svc wifi enable >/dev/null 2>&1 || true
  "$adb" logcat -c || true
  "$adb" shell cmd locale set-app-locales dev.bento.app --locales "${APP_LOCALE:-es-ES}" >/dev/null 2>&1 || true
  # The multi-device journeys share the host's fake cloud; the others use the phone's own fake directory.
  relay="\"relay_url\":\"ws://127.0.0.1:$phone_relay\""
  if [[ "$j" == j01* || "$j" == j03* || "$j" == j15* || "$j" == j90* ]]; then
    options="{$relay,\"manual_login\":\"true\"}"
  else
    options="{$relay,\"fake_telegram_url\":\"http://127.0.0.1:$phone_fake\",\"manual_login\":\"true\"}"
  fi
  "$adb" shell "run-as dev.bento.app sh -c 'mkdir -p files && echo '\''$options'\'' > files/dev-options.json'"
  echo "== $j"
  if ! "$adb" shell am instrument -w -r -e class "dev.bento.app.TrustJourneysTest#$j" dev.bento.app.test/androidx.test.runner.AndroidJUnitRunner | tee "$OUT/$j.txt" | grep -E "OK \(|FAILURES|Tests run|AssertionError|Exception" ; then status=1; fi
  grep -q "OK (1 test)" "$OUT/$j.txt" || status=1
  "$adb" logcat -d > "$OUT/$j.logcat" 2>/dev/null || true
  "$adb" pull /sdcard/Android/data/dev.bento.app/files/journeys "$OUT/screens-${APP_LOCALE:-es-ES}" >/dev/null 2>&1 || true
done
exit $status
