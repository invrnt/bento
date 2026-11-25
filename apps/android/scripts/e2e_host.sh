# Sourced by feature/*/e2e/run_journeys.sh: host ports and a host process that is always stopped.
#
# The phone keeps fixed loopback ports (its relay URL, dev options and the androidTest HostDevice use them); the host
# side binds free ports (or the BENTO_E2E_*_PORT ones given) and `adb reverse` maps phone port -> host port, so a
# port taken on the development machine never collides with the harness.

# A free 127.0.0.1 TCP port, or $1 when it is set (an explicit BENTO_E2E_*_PORT).
e2e_port() {
  if [[ -n "${1:-}" ]]; then echo "$1"; return; fi
  python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
}

# e2e_reverse <phone port> <host port>
e2e_reverse() { "$adb" reverse "tcp:$1" "tcp:$2" >/dev/null; }

# e2e_start_host <pgids file> <command…>: runs the command in its own process group (e2e_host_pid).
e2e_start_host() {
  e2e_host_pgids="$1"
  shift
  setsid "$@" &
  e2e_host_pid=$!
}

# Stops the host's process group, then every sidecar group it recorded (they run in their own sessions), so a host
# that crashed or was killed never leaks `bento-sidecar` processes.
e2e_stop_host() {
  local pid="${e2e_host_pid:-}" group i
  e2e_host_pid=""
  if [[ -n "$pid" ]]; then
    kill -TERM -- "-$pid" 2>/dev/null || true
    for i in $(seq 1 30); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
    kill -KILL -- "-$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  fi
  if [[ -n "${e2e_host_pgids:-}" && -f "$e2e_host_pgids" ]]; then
    while read -r group; do [[ -n "$group" ]] && kill -TERM -- "-$group" 2>/dev/null || true; done <"$e2e_host_pgids"
    sleep 1
    while read -r group; do [[ -n "$group" ]] && kill -KILL -- "-$group" 2>/dev/null || true; done <"$e2e_host_pgids"
  fi
  return 0
}
