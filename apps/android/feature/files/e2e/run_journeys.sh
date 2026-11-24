#!/usr/bin/env bash
# Archivos, Buscar and Compartir journeys (testing/android-journeys.md 6, 8, 9) on the shared emulator,
# one cleared app per journey; every journey joins the host desktop's cloud with its recovery kit first.
#
#   flock "$HOME/.cache/bento-android-emulator.lock" feature/files/e2e/run_journeys.sh [j06_shareToBento …]
#
# Needs: debug app + androidTest APKs (`./gradlew :app:assembleDebug :app:assembleDebugAndroidTest`), the AVD,
# and uv for the host side. Starts the emulator headless, the host harness (files_host.py), wires everything with
# `adb reverse`, runs the journeys, saves screenshots under $OUT, and stops everything it started.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
android="$(cd "$here/../../.." && pwd)"
repo="$(cd "$android/../.." && pwd)"
OUT="${OUT:-$android/build/files-journeys}"
AVD="${AVD:-bento_spike_api35}"
SDK="${ANDROID_HOME:-$HOME/Android/Sdk}"
adb="$SDK/platform-tools/adb"
mkdir -p "$OUT"
journeys=("${@:-j06_shareToBento j08_files j09_searchDesktopOcr}")
read -r -a journeys <<< "${journeys[*]}"

app_apk="$android/app/build/outputs/apk/debug/app-debug.apk"
test_apk="$android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"

cleanup() {
  [[ -n "${host_pid:-}" ]] && kill "$host_pid" 2>/dev/null || true
  [[ -n "${emu_pid:-}" ]] && { "$adb" emu kill >/dev/null 2>&1 || kill "$emu_pid" 2>/dev/null || true; }
}
trap cleanup EXIT

"$SDK/emulator/emulator" -avd "$AVD" -no-window -no-audio -no-snapshot-save -no-boot-anim -gpu swiftshader_indirect -memory "${EMU_MEMORY:-2048}" >"$OUT/emulator.log" 2>&1 &
emu_pid=$!
"$adb" wait-for-device
until [[ "$("$adb" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]]; do sleep 2; done
"$adb" shell settings put global window_animation_scale 0
"$adb" shell settings put global transition_animation_scale 0
"$adb" shell settings put global animator_duration_scale 0

(cd "$repo" && uv run --quiet --project apps/api python "$here/files_host.py" --root "$OUT/host") >"$OUT/host.out" 2>&1 &
host_pid=$!
until grep -q FILES_HOST_READY "$OUT/host.out"; do sleep 1; kill -0 "$host_pid" || { cat "$OUT/host.out"; exit 1; }; done
for port in 8790 8791; do "$adb" reverse "tcp:$port" "tcp:$port" >/dev/null; done

"$adb" install -r -t "$app_apk" >/dev/null
"$adb" install -r -t "$test_apk" >/dev/null

status=0
for j in "${journeys[@]}"; do
  "$adb" shell pm clear dev.bento.app >/dev/null
  "$adb" shell cmd locale set-app-locales dev.bento.app --locales "${APP_LOCALE:-es-ES}" >/dev/null 2>&1 || true
  options='{"fake_telegram_url":"http://127.0.0.1:8790","manual_login":"true"}'
  "$adb" shell "run-as dev.bento.app sh -c 'mkdir -p files && echo '\''$options'\'' > files/dev-options.json'"
  echo "== $j"
  if ! "$adb" shell am instrument -w -r -e class "dev.bento.app.FilesJourneysTest#$j" dev.bento.app.test/androidx.test.runner.AndroidJUnitRunner | tee "$OUT/$j.txt" | grep -E "OK \(|FAILURES|Tests run|AssertionError|Exception" ; then status=1; fi
  grep -q "OK (1 test)" "$OUT/$j.txt" || status=1
  "$adb" pull /sdcard/Android/data/dev.bento.app/files/journeys "$OUT/screens-${APP_LOCALE:-es-ES}" >/dev/null 2>&1 || true
done
exit $status
