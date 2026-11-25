#!/usr/bin/env bash
# Local CI gate for Bento (GitHub Actions is unavailable). See orchestration/execution/local-integration.md.
#
# Checks out <ref> in a throwaway detached worktree, runs the selected components with per-step memory
# limits, writes one log per step and a markdown summary ready to paste into a PR or append to the
# versioned evidence log.
#
#   scripts/local-ci.sh [--ref <sha|branch>] [components...] [options]
#
# Components (mirror .github/workflows/*.yml and the pre-push hooks):
#   --backend         uv sync --frozen --extra dev --extra desktop; pytest (whole suite)
#   --backend-smoke   pytest tests/smoke + tests/api/android (minutes, not the whole suite)
#   --web             npm ci; vitest; tsc -b && vite build
#   --desktop         npm ci (web + desktop); vitest; tsc main process
#   --desktop-native  linux-x64 "unsigned package": make, smoke:packaged, verify:artifacts (heavy)
#   --site            node build + node --test (includes the docs link checker)
#   --relay           npm ci; wrangler types --check + tsc; vitest (workers pool)
#   --release         release tool: unittest suite, version/CHANGELOG checks (scripts/release, seconds)
#   --android-fast    generators, drift (tokens/icons/OpenAPI), ktlint, detekt, unit + Roborazzi, assembleDebug
#   --android-full    CI "checks" job: build-logic tests, check (incl. lint), assembleDebug/Release both ABIs,
#                     assembleDebugAndroidTest
#   --journeys        instrumented app + smoke on the shared AVD, under the emulator flock
#   --benchmarks      Macrobenchmark StartupBenchmark + photos journeys/benchmarks (emulator, slow)
# Presets:
#   --light           backend web desktop site relay release
#   --merge           light + android-fast
#   --full            light + android-full + journeys
#   --auto <base>     pick components from the paths changed in <base>...<ref>
# Options:
#   --dry-run         print the plan and commands; create nothing, run nothing
#   --parallel        run the backend lane, the TS lane and the Android lane concurrently (RAM-gated)
#   --record <file>   append the summary to <file> (e.g. orchestration/execution/evidence/local-ci.md)
#   --log-dir <dir>   default: ~/.cache/bento-local-ci/runs/<short-sha>-<timestamp>
#   --keep            keep the temporary worktree (default: removed at exit)
#   --min-free-mb <n> wait for this much MemAvailable before each heavy lane (default 1500)
#   --mem-wait <s>    how long to wait for memory before proceeding with a warning (default 600)
#   --step-timeout <s> kill a step after this long (default 2700; Android/emulator/desktop-native 7200)
#
# Environment overrides: BENTO_JAVA17, BENTO_BUILD_PYTHON, BENTO_ANDROID_WHEELS, BENTO_CI_NODE_DIR,
# ANDROID_HOME, ANDROID_AVD_HOME, BENTO_AVD, BENTO_EMULATOR_LOCK, BENTO_EMULATOR_LOCK_WAIT, BENTO_CI_ROOT,
# BENTO_CI_MEM_{BACKEND,TS,GRADLE,EMULATOR,DESKTOP_NATIVE} (systemd MemoryMax values, e.g. 3G).
set -uo pipefail

SELF="$(readlink -f "${BASH_SOURCE[0]}")"
COMPONENT_ORDER=(backend backend-smoke release web desktop desktop-native site relay android-fast android-full journeys benchmarks)

die() { printf 'local-ci: %s\n' "$*" >&2; exit 2; }
log() { printf '[local-ci %s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }

# ---------------------------------------------------------------- toolchain defaults
JAVA17="${BENTO_JAVA17:-$HOME/.local/share/mise/installs/java/temurin-17}"
BUILD_PY="${BENTO_BUILD_PYTHON:-$HOME/.local/share/uv/python/cpython-3.13-linux-x86_64-gnu/bin/python3.13}"
SDK="${ANDROID_HOME:-$HOME/Android/Sdk}"
export ANDROID_AVD_HOME="${ANDROID_AVD_HOME:-$HOME/.config/.android/avd}"
AVD="${BENTO_AVD:-bento_spike_api35}"
EMU_LOCK="${BENTO_EMULATOR_LOCK:-$HOME/.cache/bento-android-emulator.lock}"
EMU_LOCK_WAIT="${BENTO_EMULATOR_LOCK_WAIT:-3600}"
CI_ROOT="${BENTO_CI_ROOT:-$HOME/.cache/bento-local-ci}"
GRADLE_FLAGS=(--no-daemon --console=plain --max-workers=3 "-Dorg.gradle.jvmargs=-Xmx2g -Dfile.encoding=UTF-8"
  -Pkotlin.compiler.execution.strategy=in-process)

# Memory ceilings per step (systemd user scope). Gradle: 2 GB heap + Kotlin in-process + workers + lint.
MEM_BACKEND="${BENTO_CI_MEM_BACKEND:-3G}" MEM_TS="${BENTO_CI_MEM_TS:-2G}" MEM_GRADLE="${BENTO_CI_MEM_GRADLE:-5G}"
MEM_EMULATOR="${BENTO_CI_MEM_EMULATOR:-7G}" MEM_DESKTOP_NATIVE="${BENTO_CI_MEM_DESKTOP_NATIVE:-4G}"

node_dir() {
  if [[ -n "${BENTO_CI_NODE_DIR:-}" ]]; then echo "$BENTO_CI_NODE_DIR"; return; fi
  local d="$HOME/.local/share/mise/installs/node/24/bin"
  if [[ -x "$d/node" ]]; then echo "$d"; return; fi
  if command -v mise >/dev/null && d="$(mise where node@24 2>/dev/null)/bin" && [[ -x "$d/node" ]]; then echo "$d"; return; fi
  echo ""
}

# ---------------------------------------------------------------- internal: run a command holding the emulator
# local-ci.sh __emulator-run <cmd...>: take the shared AVD lock, boot the AVD if no emulator is attached,
# run <cmd>, and shut the emulator down only if this invocation booted it.
emulator_run() {
  local adb="$SDK/platform-tools/adb" emu="$SDK/emulator/emulator"
  mkdir -p "$(dirname "$EMU_LOCK")"
  exec 9>"$EMU_LOCK"
  log "waiting for emulator lock $EMU_LOCK (max ${EMU_LOCK_WAIT}s)"
  flock -w "$EMU_LOCK_WAIT" 9 || { echo "emulator lock not acquired within ${EMU_LOCK_WAIT}s"; return 75; }
  local serial started=0
  serial="$("$adb" devices | awk '/^emulator-[0-9]+\tdevice$/ {print $1; exit}')"
  if [[ -z "$serial" ]]; then
    log "booting AVD $AVD"
    "$emu" -avd "$AVD" -no-window -no-audio -no-snapshot-save -no-boot-anim -gpu swiftshader_indirect \
      >"${LOCAL_CI_STEP_LOG:-${TMPDIR:-/tmp}/bento-local-ci-emulator}.emulator" 2>&1 &
    started=1
    local t=0
    until [[ "$("$adb" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]]; do
      sleep 3; t=$((t + 3))
      (( t > 420 )) && { echo "AVD did not boot in 420s"; kill %1 2>/dev/null; return 1; }
    done
    serial="$("$adb" devices | awk '/^emulator-[0-9]+\tdevice$/ {print $1; exit}')"
  fi
  log "using $serial"
  export ANDROID_SERIAL="$serial"
  "$adb" shell settings put global window_animation_scale 0 >/dev/null 2>&1
  "$adb" shell settings put global transition_animation_scale 0 >/dev/null 2>&1
  "$adb" shell settings put global animator_duration_scale 0 >/dev/null 2>&1
  "$@"
  local rc=$?
  if (( started )); then "$adb" -s "$serial" emu kill >/dev/null 2>&1; wait 2>/dev/null; fi
  return "$rc"
}
if [[ "${1:-}" == "__emulator-run" ]]; then shift; emulator_run "$@"; exit $?; fi

# ---------------------------------------------------------------- arguments
STEP_TIMEOUT="${BENTO_CI_STEP_TIMEOUT:-2700}" STEP_TIMEOUT_LONG="${BENTO_CI_STEP_TIMEOUT_LONG:-7200}"
REF=HEAD DRY_RUN=0 PARALLEL=0 KEEP=0 RECORD="" LOG_DIR="" AUTO_BASE="" MIN_FREE_MB=1500 MEM_WAIT=600
declare -A WANT=()
want() { local c; for c in "$@"; do WANT[$c]=1; done; }
while (( $# )); do
  case "$1" in
    --ref) REF="${2:?}"; shift ;;
    --backend|--backend-smoke|--release|--web|--desktop|--desktop-native|--site|--relay|--android-fast|--android-full|--journeys|--benchmarks)
      want "${1#--}" ;;
    --light) want backend web desktop site relay release ;;
    --merge) want backend web desktop site relay release android-fast ;;
    --full) want backend web desktop site relay release android-full journeys ;;
    --auto) AUTO_BASE="${2:?}"; shift ;;
    --dry-run) DRY_RUN=1 ;;
    --parallel) PARALLEL=1 ;;
    --keep) KEEP=1 ;;
    --record) RECORD="$(readlink -m "${2:?}")"; shift ;;
    --log-dir) LOG_DIR="$(readlink -m "${2:?}")"; shift ;;
    --min-free-mb) MIN_FREE_MB="${2:?}"; shift ;;
    --mem-wait) MEM_WAIT="${2:?}"; shift ;;
    --step-timeout) STEP_TIMEOUT="${2:?}"; STEP_TIMEOUT_LONG="${2:?}"; shift ;;
    -h|--help) sed -n '2,/^set -uo/p' "$SELF" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown argument: $1 (see --help)" ;;
  esac
  shift
done

REPO="$(git rev-parse --show-toplevel 2>/dev/null)" || die "run inside the Bento repository"
SHA="$(git -C "$REPO" rev-parse --verify "$REF^{commit}" 2>/dev/null)" || die "cannot resolve ref '$REF'"
SHORT="${SHA:0:10}"
TREE="$(git -C "$REPO" rev-parse "$SHA^{tree}")"
SUBJECT="$(git -C "$REPO" log -1 --format=%s "$SHA")"

if [[ -n "$AUTO_BASE" ]]; then
  BASE_SHA="$(git -C "$REPO" merge-base "$AUTO_BASE" "$SHA")" || die "cannot resolve --auto base '$AUTO_BASE'"
  while IFS= read -r p; do
    case "$p" in
      apps/api/src/*|apps/api/migrations/*|apps/api/uv.lock) want backend android-fast release ;;
      apps/api/pyproject.toml) want backend release ;;
      apps/api/*) want backend ;;
      apps/web/src/styles/tokens.css) want web desktop android-fast ;;
      apps/web/package.json|apps/web/package-lock.json) want web desktop release ;;
      apps/web/*) want web desktop ;;
      apps/desktop/package.json|apps/desktop/package-lock.json) want desktop release ;;
      apps/desktop/*) want desktop ;;
      apps/site/*|docs/*|README.md|*/README.md) want site ;;
      apps/relay/*) want relay ;;
      apps/android/app/build.gradle.kts) want android-fast release ;;
      apps/android/*) want android-fast ;;
      scripts/release/*|VERSION|CHANGELOG.md) want release ;;
      scripts/local-ci.sh|.github/*|Makefile|.pre-commit-config.yaml) want backend web desktop site relay release ;;
      scripts/*) want backend ;;
    esac
  done < <(git -C "$REPO" diff --name-only "$BASE_SHA" "$SHA")
fi
(( ${#WANT[@]} )) || die "no component selected (try --light, --merge or --auto <base>)"

SELECTED=()
for c in "${COMPONENT_ORDER[@]}"; do [[ -n "${WANT[$c]:-}" ]] && SELECTED+=("$c"); done

STAMP="$(date +%Y%m%d-%H%M%S)"
DRY_TMP=""
if (( DRY_RUN )) && [[ -z "$LOG_DIR" ]]; then DRY_TMP="$(mktemp -d)"; LOG_DIR="$DRY_TMP"; fi
LOG_DIR="${LOG_DIR:-$CI_ROOT/runs/$SHORT-$STAMP}"
WT="$CI_ROOT/wt/$SHORT-$STAMP"
RESULTS="$LOG_DIR/results.tsv"
NOTES="$LOG_DIR/notes.txt"

NODE_DIR="$(node_dir)"
needs_node=0
for c in "${SELECTED[@]}"; do case "$c" in web|desktop|desktop-native|site|relay|android-*) needs_node=1 ;; esac; done
if (( needs_node )) && [[ -z "$NODE_DIR" ]]; then
  die "Node 24 not found (CI uses 24; desktop refuses 26). Run: mise install node@24, or set BENTO_CI_NODE_DIR"
fi

# ---------------------------------------------------------------- helpers
record() { printf '%s\t%s\t%s\t%s\t%s\n' "$@" >>"$RESULTS"; }   # component step status seconds detail
note() { printf '%s\n' "$*" >>"$NOTES"; log "$*"; }

mem_available_mb() { awk '/^MemAvailable:/ {print int($2/1024)}' /proc/meminfo; }
wait_for_memory() {   # wait_for_memory <lane>
  (( DRY_RUN )) && return 0
  local need=$MIN_FREE_MB t=0
  while (( $(mem_available_mb) < need )); do
    (( t == 0 )) && log "$1: waiting for ${need} MB MemAvailable (now $(mem_available_mb) MB)"
    if (( t >= MEM_WAIT )); then
      note "WARN $1: started with only $(mem_available_mb) MB MemAvailable after waiting ${MEM_WAIT}s"
      return 0
    fi
    sleep 10; t=$((t + 10))
  done
}

HAVE_SCOPE=0
systemd-run --user --scope -q --collect true >/dev/null 2>&1 && HAVE_SCOPE=1
limited() {   # limited <mem> <cmd...>
  local mem=$1; shift
  if (( HAVE_SCOPE )); then
    systemd-run --user --scope -q --collect -p "MemoryMax=$mem" -p MemorySwapMax=1G -p CPUWeight=50 -- nice -n 10 "$@"
  else
    nice -n 10 "$@"
  fi
}

detail_from_log() {
  local f=$1 d=""
  d="$(grep -aE '^=+ .*([0-9]+ (passed|failed)).* in [0-9.]+s' "$f" | tail -1 | sed -E 's/^=+ //; s/ =+$//')"
  [[ -z "$d" ]] && d="$(grep -aE '^[0-9]+ (passed|failed)' "$f" | tail -1)"
  [[ -z "$d" ]] && d="$(grep -aE '^ +Tests +[0-9]' "$f" | tail -1 | sed -E 's/\x1b\[[0-9;]*m//g; s/^ +//; s/ +/ /g')"
  if [[ -z "$d" ]] && grep -aqE '^(#|ℹ) (pass|fail) ' "$f"; then
    d="node --test: $(grep -aE '^(#|ℹ) pass ' "$f" | awk '{s+=$3} END {print s+0}') pass, $(grep -aE '^(#|ℹ) fail ' "$f" | awk '{s+=$3} END {print s+0}') fail"
  fi
  [[ -z "$d" ]] && d="$(grep -aE '^BUILD (SUCCESSFUL|FAILED) in' "$f" | tail -1)"
  [[ -z "$d" ]] && d="$(grep -aE '^Ran [0-9]+ tests? in' "$f" | tail -1)"
  if grep -aqE '^[0-9]+ tests completed' "$f"; then d="$d; $(grep -aE '^[0-9]+ tests completed' "$f" | tail -1)"; fi
  printf '%s' "${d//|//}"
}

# step <component> <name> <mem> <cwd-relative-to-worktree> <shell command>
step() {
  local comp=$1 name=$2 mem=$3 rel=$4 cmd=$5
  local cwd="$WT/$rel" logf="$LOG_DIR/$comp--$name.log"
  if [[ -e "$LOG_DIR/.failed-$comp" ]]; then record "$comp" "$name" SKIP 0 "earlier step failed"; return 1; fi
  if (( DRY_RUN )); then
    printf '  %-15s %-20s mem<=%-4s cwd=%s\n      %s\n' "$comp" "$name" "$mem" "${rel:-.}" "$cmd"
    record "$comp" "$name" DRY 0 ""
    return 0
  fi
  log "$comp/$name ..."
  { printf '# %s/%s @ %s\n# cwd: %s\n# cmd: %s\n# mem: %s\n\n' "$comp" "$name" "$SHA" "$cwd" "$cmd" "$mem"; } >"$logf"
  local t0=$SECONDS rc
  local tmo=$STEP_TIMEOUT
  case "$comp" in android-*|journeys|benchmarks|desktop-native) tmo=$STEP_TIMEOUT_LONG ;; esac
  LOCAL_CI_STEP_LOG="$logf" limited "$mem" timeout -k 30 "$tmo" bash -c "cd \"$cwd\" && $cmd" >>"$logf" 2>&1
  rc=$?
  local dt=$((SECONDS - t0)) detail
  detail="$(detail_from_log "$logf")"
  if (( rc == 0 )); then
    record "$comp" "$name" PASS "$dt" "$detail"; log "$comp/$name PASS (${dt}s) $detail"
  else
    (( rc == 124 )) && detail="timed out after ${tmo}s (hung?) $detail"
    (( rc == 137 )) && detail="killed (exit 137: memory limit $mem or timeout kill) $detail"
    record "$comp" "$name" FAIL "$dt" "exit $rc; $detail"; log "$comp/$name FAIL (${dt}s) -> $logf"
    : >"$LOG_DIR/.failed-$comp"
  fi
  return "$rc"
}

NPM_CI='npm ci --prefer-offline --no-audit --no-fund'
GRADLEW="./gradlew ${GRADLE_FLAGS[*]@Q} -PbentoBuildPython=\"\$BENTO_BUILD_PYTHON\""

# ---------------------------------------------------------------- components
c_backend() {
  step backend uv-sync "$MEM_BACKEND" "" 'uv sync --project apps/api --frozen --extra dev --extra desktop'
  step backend pytest "$MEM_BACKEND" apps/api 'uv run --frozen pytest -p no:cacheprovider'
}
c_backend-smoke() {
  step backend-smoke uv-sync "$MEM_BACKEND" "" 'uv sync --project apps/api --frozen --extra dev'
  step backend-smoke pytest "$MEM_BACKEND" apps/api 'uv run --frozen pytest -p no:cacheprovider tests/smoke tests/api/android'
}
c_release() {
  step release unittest "$MEM_BACKEND" scripts/release/tests 'python3 -m unittest discover -s . -p "test_*.py"'
  step release version-check "$MEM_BACKEND" "" 'scripts/release/bento-release version check && scripts/release/bento-release changelog check'
}
c_web() {
  step web npm-ci "$MEM_TS" apps/web "$NPM_CI"
  step web vitest "$MEM_TS" apps/web 'npm test'
  step web build "$MEM_TS" apps/web 'npm run build'
}
c_desktop() {
  # The web lane runs first in the same lane and installs apps/web; otherwise install it here.
  [[ -n "${WANT[web]:-}" ]] || step desktop web-npm-ci "$MEM_TS" apps/web "$NPM_CI"
  step desktop npm-ci "$MEM_TS" apps/desktop "$NPM_CI"
  step desktop vitest "$MEM_TS" apps/desktop 'npm test'
  step desktop tsc-main "$MEM_TS" apps/desktop 'npm run build:main'
}
c_desktop-native() {
  [[ -n "${WANT[backend]:-}" ]] ||
    step desktop-native uv-sync "$MEM_BACKEND" "" 'uv sync --project apps/api --frozen --extra dev --extra desktop'
  [[ -n "${WANT[web]:-}" || -n "${WANT[desktop]:-}" ]] || step desktop-native web-npm-ci "$MEM_TS" apps/web "$NPM_CI"
  [[ -n "${WANT[desktop]:-}" ]] || step desktop-native npm-ci "$MEM_TS" apps/desktop "$NPM_CI"
  step desktop-native build-config "$MEM_TS" "" 'node apps/desktop/scripts/write-build-config.mjs'
  step desktop-native make "$MEM_DESKTOP_NATIVE" "" 'npm --prefix apps/desktop run make'
  step desktop-native smoke-packaged "$MEM_DESKTOP_NATIVE" "" 'npm --prefix apps/desktop run smoke:packaged'
  step desktop-native verify-artifacts "$MEM_TS" "" 'npm --prefix apps/desktop run verify:artifacts'
}
c_site() {
  step site test "$MEM_TS" apps/site 'npm test'
}
c_relay() {
  step relay npm-ci "$MEM_TS" apps/relay "$NPM_CI"
  step relay typecheck "$MEM_TS" apps/relay 'npm run typecheck'
  step relay vitest "$MEM_TS" apps/relay 'npm test'
}
android_prepare() {
  (( DRY_RUN )) && { printf '  %-15s %-20s link python-wheels/dist -> %s; write local.properties\n' android prepare "$WHEELS"; return 0; }
  [[ -d "$WHEELS" ]] || { record "$1" prepare FAIL 0 "no wheels at $WHEELS (python-wheels/build_all.sh)"; : >"$LOG_DIR/.failed-$1"; return 1; }
  ln -sfn "$WHEELS" "$WT/apps/android/python-wheels/dist"
  printf 'sdk.dir=%s\n' "$SDK" >"$WT/apps/android/local.properties"
}
c_android-fast() {
  android_prepare android-fast || return 1
  step android-fast generators "$MEM_TS" apps/android "$NPM_CI --prefix scripts && npm test --prefix scripts"
  step android-fast gradle "$MEM_GRADLE" apps/android "$GRADLEW :core:designsystem:verifyBentoGenerated :core:api:checkOpenApiDrift ktlintCheck detekt testDebugUnitTest verifyRoborazziDebug :app:assembleDebug"
}
c_android-full() {
  android_prepare android-full || return 1
  step android-full generators "$MEM_TS" apps/android "$NPM_CI --prefix scripts && npm test --prefix scripts"
  step android-full build-logic "$MEM_GRADLE" apps/android "$GRADLEW -p build-logic :convention:test"
  step android-full check "$MEM_GRADLE" apps/android "$GRADLEW check :core:designsystem-lint:test"
  # SEC-10: release packaging needs a non-placeholder site host; CI uses a reserved .test host (never shipped).
  step android-full assemble "$MEM_GRADLE" apps/android "$GRADLEW :app:assembleDebug :app:assembleRelease :app:assembleDebugAndroidTest -PbentoAbis=arm64-v8a,x86_64 -PbentoSiteHost=ci.bento.test -PbentoSiteUrl=https://ci.bento.test"
}
c_journeys() {
  [[ -n "${WANT[android-fast]:-}${WANT[android-full]:-}" ]] || android_prepare journeys || return 1
  step journeys connected "$MEM_EMULATOR" apps/android "\"$SELF\" __emulator-run $GRADLEW :app:connectedDebugAndroidTest :smoke:connectedCheck -Pandroid.testInstrumentationRunnerArguments.notClass=dev.bento.smoke.StartupBenchmark"
}
c_benchmarks() {
  [[ -n "${WANT[android-fast]:-}${WANT[android-full]:-}${WANT[journeys]:-}" ]] || android_prepare benchmarks || return 1
  step benchmarks startup "$MEM_EMULATOR" apps/android "\"$SELF\" __emulator-run $GRADLEW :smoke:connectedCheck -Pandroid.testInstrumentationRunnerArguments.class=dev.bento.smoke.StartupBenchmark"
  step benchmarks photos "$MEM_EMULATOR" apps/android "\"$SELF\" __emulator-run $GRADLEW :feature:photos-benchmark:connectedCheck"
}

run_lane() {   # run_lane <name> <components...>
  local lane=$1 c; shift
  (( $# )) || return 0
  wait_for_memory "$lane"
  for c in "$@"; do "c_$c" || true; done
}

# ---------------------------------------------------------------- setup
MAIN_CHECKOUT="$(git -C "$REPO" worktree list --porcelain | awk '/^worktree / {print $2; exit}')"
WHEELS="${BENTO_ANDROID_WHEELS:-$MAIN_CHECKOUT/apps/android/python-wheels/dist}"
export JAVA_HOME="$JAVA17" BENTO_BUILD_PYTHON="$BUILD_PY" ANDROID_HOME="$SDK" ANDROID_SDK_ROOT="$SDK"
export GRADLE_OPTS="-Dorg.gradle.daemon=false" CI=true UV_NO_PROGRESS=1 NO_COLOR=1 FORCE_COLOR=0
[[ -n "$NODE_DIR" ]] && export PATH="$NODE_DIR:$PATH"

mkdir -p "$LOG_DIR"
: >"$RESULTS"; : >"$NOTES"

cleanup() {
  [[ -n "$DRY_TMP" ]] && rm -rf "$DRY_TMP"
  if (( ! DRY_RUN )) && [[ -d "$WT" ]]; then
    if (( KEEP )); then log "kept worktree $WT"
    else git -C "$REPO" worktree remove --force "$WT" >/dev/null 2>&1 || rm -rf "$WT"; git -C "$REPO" worktree prune; fi
  fi
}
trap cleanup EXIT
trap 'log "interrupted"; exit 130' INT TERM

log "ref $REF -> $SHA ($SUBJECT)"
log "components: ${SELECTED[*]}$( (( PARALLEL )) && echo ' [parallel]')$( (( DRY_RUN )) && echo ' [dry-run]')"
log "logs: $LOG_DIR"
if (( DRY_RUN )); then
  echo "Plan for $SHORT (worktree would be $WT):"
else
  mkdir -p "$CI_ROOT/wt"
  git -C "$REPO" worktree add --detach --quiet "$WT" "$SHA" || die "git worktree add failed"
fi
(( HAVE_SCOPE )) || note "WARN systemd user scopes unavailable: memory limits not enforced"
if [[ " ${SELECTED[*]} " =~ \ (journeys|benchmarks)\  ]] && (( ! DRY_RUN )); then
  [[ -x "$SDK/emulator/emulator" ]] || note "WARN emulator binary missing under $SDK"
fi
for t in "$JAVA17/bin/java" "$BUILD_PY"; do
  [[ " ${SELECTED[*]} " =~ android|journeys|benchmarks ]] && [[ ! -x "$t" ]] && note "WARN missing $t"
done

# ---------------------------------------------------------------- run
T_START=$SECONDS
LANE_PY=() LANE_TS=() LANE_ANDROID=()
for c in "${SELECTED[@]}"; do
  case "$c" in
    backend|backend-smoke|release) LANE_PY+=("$c") ;;
    web|desktop|desktop-native|site|relay) LANE_TS+=("$c") ;;
    *) LANE_ANDROID+=("$c") ;;
  esac
done
if (( PARALLEL && ! DRY_RUN )); then
  run_lane python "${LANE_PY[@]}" & p1=$!
  sleep 2; run_lane ts "${LANE_TS[@]}" & p2=$!
  sleep 2; run_lane android "${LANE_ANDROID[@]}" & p3=$!
  wait $p1 $p2 $p3
else
  run_lane python "${LANE_PY[@]}"
  run_lane ts "${LANE_TS[@]}"
  run_lane android "${LANE_ANDROID[@]}"
fi
T_TOTAL=$((SECONDS - T_START))

# ---------------------------------------------------------------- summary
fmt_dur() { local s=$1; (( s >= 60 )) && printf '%dm%02ds' $((s / 60)) $((s % 60)) || printf '%ds' "$s"; }
OVERALL=PASS
grep -q $'\tFAIL\t' "$RESULTS" && OVERALL=FAIL
(( DRY_RUN )) && OVERALL=DRY-RUN
SUMMARY="$LOG_DIR/summary.md"
{
  printf '### Local CI %s — `%s` (%s)\n\n' "$OVERALL" "$SHORT" "$REF"
  printf -- '- Commit `%s` · tree `%s` · %s\n' "$SHA" "$TREE" "$SUBJECT"
  printf -- '- Ran %s on %s (%s CPU, %s GB RAM) · total %s%s\n' "$(date -Iseconds)" "$(uname -sr)" "$(nproc)" \
    "$(awk '/MemTotal/ {printf "%.0f", $2/1048576}' /proc/meminfo)" "$(fmt_dur "$T_TOTAL")" "$( (( PARALLEL )) && echo ' · parallel lanes')"
  printf -- '- Toolchain: uv %s · node %s · java %s · script `%s`\n' \
    "$(uv --version 2>/dev/null | awk '{print $2}')" "$(node -v 2>/dev/null)" \
    "$("$JAVA17/bin/java" -version 2>&1 | awk -F'"' '/version/ {print $2; exit}')" \
    "$(git -C "$REPO" hash-object "$SELF" | cut -c1-10)"
  printf -- '- Logs: `%s`\n\n' "$LOG_DIR"
  printf '| Component | Step | Result | Time | Detail |\n|---|---|---|---|---|\n'
  for c in "${COMPONENT_ORDER[@]}"; do
    awk -F'\t' -v c="$c" '$1 == c' "$RESULTS" | while IFS=$'\t' read -r comp name status secs detail; do
      printf '| %s | %s | %s | %s | %s |\n' "$comp" "$name" "$status" "$(fmt_dur "$secs")" "$detail"
    done
  done
  if [[ -s "$NOTES" ]]; then printf '\n'; sed 's/^/> /' "$NOTES"; fi
  if [[ "$OVERALL" == FAIL ]]; then
    printf '\n<details><summary>Failure tails</summary>\n\n'
    awk -F'\t' '$3 == "FAIL" {print $1 "--" $2}' "$RESULTS" | while read -r f; do
      printf '`%s.log`\n```\n' "$f"; tail -n 25 "$LOG_DIR/$f.log" | sed -E 's/\x1b\[[0-9;]*m//g'; printf '```\n'
    done
    printf '</details>\n'
  fi
} >"$SUMMARY"
cat "$SUMMARY"
if [[ -n "$RECORD" ]] && (( ! DRY_RUN )); then
  mkdir -p "$(dirname "$RECORD")"
  { printf '\n'; cat "$SUMMARY"; } >>"$RECORD"
  log "appended summary to $RECORD"
fi
[[ "$OVERALL" == FAIL ]] && exit 1
exit 0
