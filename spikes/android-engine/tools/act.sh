#!/usr/bin/env bash
# usage: act.sh <action> [args-json] [timeout-s]
A=$1; ARGS=${2:-{\}}; T=${3:-300}
adb shell am start -n dev.bento.spike/.MainActivity --es action "$A" --es args "'$ARGS'" >/dev/null
timeout $T bash -c "until adb logcat -d -s BentoSpike:I | grep -q 'RESULT $A '; do sleep 1; done"
adb logcat -d -s BentoSpike:I | grep "RESULT $A " | tail -1 | sed 's/.*RESULT //'
