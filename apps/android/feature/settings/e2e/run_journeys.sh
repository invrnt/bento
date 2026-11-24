#!/usr/bin/env bash
# Backup, background, free-up-space and app-lock journeys (testing/android-journeys.md 1 camera-roll part, 10, 11,
# 12, 16) on the shared emulator: a cleared app and a fresh remote fake cloud (:8790) per journey.
#
#   flock "$HOME/.cache/bento-android-emulator.lock" feature/settings/e2e/run_journeys.sh [j01_firstRunBackupOn …]
#
# Needs the debug app + androidTest APKs, the AVD, and uv for the fake cloud. Starts the emulator headless, wires
# :8790 with `adb reverse`, runs the journeys, saves in-app/system screenshots under $OUT, stops what it started.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
android="$(cd "$here/../../.." && pwd)"
repo="$(cd "$android/../.." && pwd)"
OUT="${OUT:-$android/build/backup-journeys}"
AVD="${AVD:-bento_spike_api35}"
SDK="${ANDROID_HOME:-$HOME/Android/Sdk}"
adb="$SDK/platform-tools/adb"
mkdir -p "$OUT"
journeys=("${@:-j01_firstRunBackupOn j10_backgroundBackup j11_initialBackup j12_freeUpSpace j16_appLock}")
read -r -a journeys <<< "${journeys[*]}"

app_apk="$android/app/build/outputs/apk/debug/app-debug.apk"
test_apk="$android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"

cleanup() {
  [[ -n "${cloud_pid:-}" ]] && kill "$cloud_pid" 2>/dev/null || true
  [[ -n "${emu_pid:-}" ]] && { "$adb" emu kill >/dev/null 2>&1 || kill "$emu_pid" 2>/dev/null || true; }
}
trap cleanup EXIT

"$SDK/emulator/emulator" -avd "$AVD" -no-window -no-audio -no-snapshot-save -no-boot-anim -gpu swiftshader_indirect -memory "${EMU_MEMORY:-2048}" >"$OUT/emulator.log" 2>&1 &
emu_pid=$!
# Fail fast when the emulator cannot start (never hold the shared lock on a dead `wait-for-device`).
until "$adb" get-state >/dev/null 2>&1; do sleep 2; kill -0 "$emu_pid" 2>/dev/null || { tail -5 "$OUT/emulator.log"; exit 1; }; done
until [[ "$("$adb" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]]; do sleep 2; done
for scale in window_animation_scale transition_animation_scale animator_duration_scale; do "$adb" shell settings put global "$scale" 0; done
"$adb" install -r -t "$app_apk" >/dev/null
"$adb" install -r -t "$test_apk" >/dev/null

status=0
for j in "${journeys[@]}"; do
  rm -rf "$OUT/cloud-$j"
  (cd "$repo" && BENTO_FAKE_TELEGRAM_MANUAL_LOGIN=1 uv run --quiet --project apps/api bento-sidecar fake-telegram-serve --dir "$OUT/cloud-$j" --port 8790) >"$OUT/cloud-$j.log" 2>&1 &
  cloud_pid=$!
  until curl -s -o /dev/null "http://127.0.0.1:8790/" ; do sleep 0.5; kill -0 "$cloud_pid" || { cat "$OUT/cloud-$j.log"; exit 1; }; done
  "$adb" reverse tcp:8790 tcp:8790 >/dev/null
  "$adb" shell pm clear dev.bento.app >/dev/null
  "$adb" shell svc wifi enable || true
  "$adb" logcat -c || true
  "$adb" shell cmd locale set-app-locales dev.bento.app --locales "${APP_LOCALE:-es-ES}" >/dev/null 2>&1 || true
  options='{"fake_telegram_url":"http://127.0.0.1:8790","manual_login":"true"}'
  "$adb" shell "run-as dev.bento.app sh -c 'mkdir -p files && echo '\''$options'\'' > files/dev-options.json'"
  echo "== $j"
  if ! "$adb" shell am instrument -w -r -e class "dev.bento.app.${CLASS:-BackupJourneysTest}#$j" dev.bento.app.test/androidx.test.runner.AndroidJUnitRunner | tee "$OUT/$j.txt" | grep -E "OK \(|FAILURES|Tests run|AssertionError|Exception" ; then status=1; fi
  grep -q "OK (1 test)" "$OUT/$j.txt" || status=1
  "$adb" logcat -d -s BentoJourney:I > "$OUT/$j.logcat" 2>/dev/null || true
  "$adb" logcat -d -b crash,main "*:E" > "$OUT/$j.errors.logcat" 2>/dev/null || true
  mkdir -p "$OUT/screens-${APP_LOCALE:-es-ES}"
  "$adb" pull /sdcard/Android/data/dev.bento.app/files/journeys/. "$OUT/screens-${APP_LOCALE:-es-ES}" >/dev/null 2>&1 || true
  kill "$cloud_pid" 2>/dev/null || true; wait "$cloud_pid" 2>/dev/null || true; cloud_pid=""
done
exit $status
