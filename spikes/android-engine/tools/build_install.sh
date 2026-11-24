#!/usr/bin/env bash
# usage: build_install.sh [extra gradle args]   (BENTO_BUILD_PYTHON = a CPython 3.13 interpreter)
set -euo pipefail
cd "$(dirname "$0")/.."
export JAVA_HOME=${JAVA_HOME_17:-$HOME/.local/share/mise/installs/java/temurin-17}
./gradlew -q :app:assembleDebug -PbentoBuildPython="${BENTO_BUILD_PYTHON:-python3.13}" "$@"
adb install -r app/build/outputs/apk/debug/app-debug.apk | tail -1 && test "${PIPESTATUS[0]}" = 0
