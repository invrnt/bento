#!/usr/bin/env bash
# PSS (dumpsys meminfo, KB): baseline app without Python, engine idle, engine busy (200 MB upload). Prints JSON lines.
set -euo pipefail
cd "$(dirname "$0")/.."
PKG=dev.bento.spike
pss() { adb shell dumpsys meminfo $PKG | tr -d '\r' | awk '/TOTAL PSS:/{print $3}'; }
# App Summary rows ("Native Heap:  52808  53772"): PSS is the first number after the colon.
section() { adb shell dumpsys meminfo $PKG | tr -d '\r' | awk -F: -v k="$1" '$1 ~ "^ *"k"$" {split($2, a, " "); print a[1]; exit}'; }
adb shell run-as $PKG touch files/no-python
adb shell am force-stop $PKG; sleep 2; adb shell am start -n $PKG/.MainActivity >/dev/null; sleep 15
echo "{\"phase\":\"baseline_no_python\",\"pss_kb\":$(pss),\"native_heap_kb\":$(section 'Native Heap')}"
adb shell run-as $PKG rm files/no-python
adb shell am force-stop $PKG; sleep 2; adb logcat -c
tools/act.sh ready '{}' 120 >/dev/null; sleep 30
for i in 1 2 3; do echo "{\"phase\":\"engine_idle\",\"pss_kb\":$(pss),\"native_heap_kb\":$(section 'Native Heap'),\"code_kb\":$(section 'Code')}"; sleep 5; done
adb shell am start -n $PKG/.MainActivity --es action upload_big --es args "'{\"size_mb\":200}'" >/dev/null 2>&1
max=0; for i in $(seq 1 60); do v=$(pss); [ "$v" -gt "$max" ] && max=$v; adb logcat -d -s BentoSpike:I | grep -q "RESULT upload_big" && break; sleep 0.5; done
echo "{\"phase\":\"engine_busy_upload_200mb_max\",\"pss_kb\":$max}"
sleep 20; echo "{\"phase\":\"engine_idle_after_upload\",\"pss_kb\":$(pss)}"
