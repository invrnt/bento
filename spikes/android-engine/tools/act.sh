#!/usr/bin/env bash
# usage: act.sh <action> [args-json] [timeout-s] — runs one spike action, prints "<action> <result-json>".
A=$1; ARGS=${2:-{\}}; T=${3:-300}
adb shell am start -n dev.bento.spike/.MainActivity --es action "$A" --es args "'$ARGS'" >/dev/null 2>&1
timeout "$T" bash -c "until adb logcat -d -s BentoSpike:I | grep -q 'RESULT $A '; do sleep 1; done"
# logcat truncates long lines; the full result is the last matching line of files/results.jsonl.
adb shell run-as dev.bento.spike cat files/results.jsonl | grep "\"action\":\"$A\"" | tail -1 |
  python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d['action'], json.dumps(d['result']))"
