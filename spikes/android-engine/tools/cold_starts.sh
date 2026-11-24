#!/usr/bin/env bash
# usage: cold_starts.sh <n> [out.jsonl]  — force-stop, launch with action=ready, record the RESULT line.
set -euo pipefail
N=${1:-20}; OUT=${2:-/dev/stdout}
for i in $(seq 1 "$N"); do
  adb shell am force-stop dev.bento.spike
  sleep 2
  adb logcat -c
  adb shell am start -W -n dev.bento.spike/.MainActivity --es action ready | grep -E "TotalTime" | tr -d '\r' > /tmp/claude-am.txt || true
  timeout 120 bash -c "until adb logcat -d -s BentoSpike:I | grep -q 'RESULT ready '; do sleep 0.5; done"
  line=$(adb logcat -d -s BentoSpike:I | grep 'RESULT ready ' | tail -1 | sed 's/.*RESULT ready //')
  echo "{\"run\":$i,\"am_total_time_ms\":$(awk '{print $2}' /tmp/claude-am.txt),\"result\":$line}" >> "$OUT"
done
