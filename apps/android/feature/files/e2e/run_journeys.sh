#!/usr/bin/env bash
# Archivos, Buscar and Compartir journeys (testing/android-journeys.md 6, 8, 9) on the shared emulator,
# one cleared app per journey; every journey joins the host desktop's cloud with its recovery kit first.
#
#   flock "$HOME/.cache/bento-android-emulator.lock" feature/files/e2e/run_journeys.sh [j06_shareToBento …]
#
# Needs: debug app + androidTest APKs (`./gradlew :app:assembleDebug :app:assembleDebugAndroidTest`), the AVD,
# and uv for the host side. Starts the emulator headless, the host harness (files_host.py) on free host ports (or
# BENTO_E2E_{FAKE,DESKTOP}_PORT), maps the phone's fixed loopback ports onto them with `adb reverse`, runs the
# journeys, saves screenshots under $OUT, and stops everything it started (also on failure or Ctrl-C).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
android="$(cd "$here/../../.." && pwd)"
repo="$(cd "$android/../.." && pwd)"
# shellcheck source=../../../scripts/e2e_host.sh
source "$android/scripts/e2e_host.sh"
OUT="${OUT:-$android/build/files-journeys}"
AVD="${AVD:-bento_spike_api35}"
SDK="${ANDROID_HOME:-$HOME/Android/Sdk}"
adb="$SDK/platform-tools/adb"
mkdir -p "$OUT"
journeys=("${@:-j06_shareToBento j08_files j09_searchDesktopOcr}")
read -r -a journeys <<< "${journeys[*]}"

app_apk="$android/app/build/outputs/apk/debug/app-debug.apk"
test_apk="$android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"

# Phone-side ports: fixed (the androidTest HostDevice and dev options use them); host-side: free or given.
phone_fake=8790 phone_desktop=8791
host_fake="$(e2e_port "${BENTO_E2E_FAKE_PORT:-}")"
host_desktop="$(e2e_port "${BENTO_E2E_DESKTOP_PORT:-}")"

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
e2e_start_host "$OUT/host/pgids" uv run --quiet --project apps/api python "$here/files_host.py" --root "$OUT/host" \
  --fake-port "$host_fake" --desktop-port "$host_desktop" >"$OUT/host.out" 2>&1
cd "$android"
until grep -q FILES_HOST_READY "$OUT/host.out"; do sleep 1; kill -0 "$e2e_host_pid" 2>/dev/null || { cat "$OUT/host.out"; exit 1; }; done
e2e_reverse "$phone_fake" "$host_fake"
e2e_reverse "$phone_desktop" "$host_desktop"
echo "host ports: fake cloud $host_fake, desktop $host_desktop"

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
  options="{\"fake_telegram_url\":\"http://127.0.0.1:$phone_fake\",\"manual_login\":\"true\"}"
  "$adb" shell "run-as dev.bento.app sh -c 'mkdir -p files && echo '\''$options'\'' > files/dev-options.json'"
  echo "== $j"
  if ! "$adb" shell am instrument -w -r -e class "dev.bento.app.FilesJourneysTest#$j" dev.bento.app.test/androidx.test.runner.AndroidJUnitRunner | tee "$OUT/$j.txt" | grep -E "OK \(|FAILURES|Tests run|AssertionError|Exception" ; then status=1; fi
  grep -q "OK (1 test)" "$OUT/$j.txt" || status=1
  mkdir -p "$OUT/screens-${APP_LOCALE:-es-ES}"
  "$adb" logcat -d -s BentoJourney:I > "$OUT/$j.logcat" 2>/dev/null || true
  "$adb" logcat -d > "$OUT/$j.full.logcat" 2>/dev/null || true
  "$adb" pull /sdcard/Android/data/dev.bento.app/files/journeys/. "$OUT/screens-${APP_LOCALE:-es-ES}" >/dev/null 2>&1 || true
done
exit $status
