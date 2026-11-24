#!/usr/bin/env bash
# Baseline Profile generation and §13 Macrobenchmarks on the shared emulator (or a physical device with DEVICE=serial).
#
#   flock "$HOME/.cache/bento-android-emulator.lock" benchmark/run.sh profile [Class#method…]  # regenerate the profiles
#   flock "$HOME/.cache/bento-android-emulator.lock" benchmark/run.sh bench [Class…]   # StartupBenchmarks FotosBenchmarks …
#
# Build first (see docs/dev/android-performance.md):
#   profile: ./gradlew :app:assembleNonMinifiedRelease :baselineprofile:assembleNonMinifiedRelease
#   bench:   ./gradlew :app:assembleBenchmarkRelease :benchmark:assembleBenchmarkRelease
# Env: DEVICE (adb serial; no emulator is started when set), AVD, SEED (photos, default 10000), COMPILATION
# (none|profile, default both), OUT. The app is always reinstalled clean: other agents' runs on the shared AVD leave
# debug options and data behind.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
android="$(cd "$here/.." && pwd)"
OUT="${OUT:-$android/build/benchmark-results}"
AVD="${AVD:-bento_spike_api35}"
SDK="${ANDROID_HOME:-$HOME/Android/Sdk}"
export ANDROID_AVD_HOME="${ANDROID_AVD_HOME:-$HOME/.config/.android/avd}"
adb=("$SDK/platform-tools/adb")
mode="${1:-bench}"
shift || true
mkdir -p "$OUT"

case "$mode" in
  profile)
    app_apk="$android/app/build/outputs/apk/nonMinifiedRelease/app-nonMinifiedRelease.apk"
    test_apk="$android/baselineprofile/build/outputs/apk/nonMinifiedRelease/baselineprofile-nonMinifiedRelease.apk"
    test_pkg="dev.bento.baselineprofile"
    if [[ $# -gt 0 ]]; then classes=("${@/#/dev.bento.baselineprofile.}"); else
      classes=("dev.bento.baselineprofile.BaselineProfileGenerator"); fi
    ;;
  bench)
    app_apk="$android/app/build/outputs/apk/benchmarkRelease/app-benchmarkRelease.apk"
    test_apk="$android/benchmark/build/outputs/apk/benchmarkRelease/benchmark-benchmarkRelease.apk"
    test_pkg="dev.bento.benchmark"
    if [[ $# -gt 0 ]]; then classes=("${@/#/dev.bento.benchmark.}"); else
      classes=(dev.bento.benchmark.StartupBenchmarks dev.bento.benchmark.FotosBenchmarks
        dev.bento.benchmark.FilesSearchShareBenchmarks dev.bento.benchmark.MemoryBenchmark); fi
    ;;
  *) echo "usage: run.sh profile|bench [Class…]" >&2; exit 2 ;;
esac
for apk in "$app_apk" "$test_apk"; do [[ -f "$apk" ]] || { echo "missing $apk (build it first)" >&2; exit 1; }; done

restore=()
cleanup() {
  for setting in "${restore[@]}"; do "${adb[@]}" shell settings put global $setting >/dev/null 2>&1 || true; done
  [[ -n "${emu_pid:-}" ]] && { "${adb[@]}" emu kill >/dev/null 2>&1 || kill "$emu_pid" 2>/dev/null || true; }
}
trap cleanup EXIT

if [[ -n "${DEVICE:-}" ]]; then
  adb+=(-s "$DEVICE")
else
  "$SDK/emulator/emulator" -avd "$AVD" -no-window -no-audio -no-snapshot-save -no-boot-anim -gpu swiftshader_indirect \
    -memory "${EMU_MEMORY:-2048}" >"$OUT/emulator.log" 2>&1 &
  emu_pid=$!
  adb+=(-e)
fi
"${adb[@]}" wait-for-device
until [[ "$("${adb[@]}" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]]; do sleep 2; done
# Real animations (journey scripts on the shared AVD set them to 0; Compose flings would end instantly). Restored on exit.
for key in window_animation_scale transition_animation_scale animator_duration_scale; do
  restore+=("$key $("${adb[@]}" shell settings get global $key | tr -d '\r')")
  "${adb[@]}" shell settings put global $key 1
done
"${adb[@]}" shell input keyevent KEYCODE_WAKEUP
"${adb[@]}" shell wm dismiss-keyguard >/dev/null 2>&1 || true

# Stale data (debug options, another variant's catalog) can crash-loop the engine: always start clean.
"${adb[@]}" uninstall dev.bento.app >/dev/null 2>&1 || true
"${adb[@]}" install -r -t "$app_apk" >/dev/null
"${adb[@]}" install -r -t "$test_apk" >/dev/null
"${adb[@]}" shell pm grant dev.bento.app android.permission.POST_NOTIFICATIONS >/dev/null 2>&1 || true

args=(-e bento.seed "${SEED:-10000}" -e androidx.benchmark.suppressErrors EMULATOR,LOW-BATTERY)
[[ -n "${COMPILATION:-}" ]] && args+=(-e bento.compilation "$COMPILATION")
status=0
for class in "${classes[@]}"; do
  name="${class##*.}"
  echo "== $name"
  "${adb[@]}" logcat -c || true
  "${adb[@]}" shell am instrument -w -r "${args[@]}" -e class "$class" "$test_pkg/androidx.test.runner.AndroidJUnitRunner" \
    | tee "$OUT/$name.txt" | grep -E "^(  |\w).*(ms|_kb|frame|P50|P90|P99|median|OK \(|FAILURES|Tests run|Error|Exception)" || true
  grep -q "^OK (" "$OUT/$name.txt" || status=1
  "${adb[@]}" logcat -d -s BentoBenchmark:I BentoJank:I TestRunner:E > "$OUT/$name.logcat" 2>/dev/null || true
done
"${adb[@]}" pull "/sdcard/Android/media/$test_pkg/." "$OUT/device" >/dev/null 2>&1 || true

if [[ "$mode" == profile && $status == 0 ]]; then
  dest="$android/app/src/main/generated/baselineProfiles"
  mkdir -p "$dest"
  shopt -s nullglob
  baseline=("$OUT"/device/*-baseline-prof*.txt)
  startup=("$OUT"/device/*-startup-prof*.txt)
  [[ ${#baseline[@]} -gt 0 ]] || { echo "no baseline profile pulled" >&2; exit 1; }
  # Like the plugin's merge: startup rules belong to the baseline profile too.
  sort -u "${baseline[@]}" "${startup[@]}" > "$dest/baseline-prof.txt"
  [[ ${#startup[@]} -gt 0 ]] && sort -u "${startup[@]}" > "$dest/startup-prof.txt"
  wc -l "$dest"/*.txt
fi
exit $status
