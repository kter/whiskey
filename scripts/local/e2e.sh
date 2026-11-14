#!/usr/bin/env bash
# Browser smoke tests against the local stack. Called by `make e2e`, which exports
# the local AWS endpoint settings (see Makefile).
#
#   moto (:5000) -> local-init -> FastAPI adapter (:8000) -> nuxt dev (:3000, mock auth)
#   -> playwright test -> stop everything this script started, even on failure.
#
# Logs and failure artefacts go to .cache/e2e/ (git-ignored). Extra arguments are
# passed to `playwright test` (e.g. `make e2e E2E_ARGS="--grep 検索"`).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

VENV_PYTHON="$ROOT/.venv/bin/python"
OUT="$ROOT/.cache/e2e"
API_PORT=8000
WEB_PORT=3000
WEB_URL="http://localhost:${WEB_PORT}"
READY_TIMEOUT="${E2E_READY_TIMEOUT:-180}"

for path in "$VENV_PYTHON" frontend/node_modules/@playwright/test; do
  if [[ ! -e "$path" ]]; then
    echo "missing $path: run 'bash scripts/agent/setup.sh' first" >&2
    exit 1
  fi
done

rm -rf "$OUT"
mkdir -p "$OUT"

# Loopback checks must not go through the agent/corporate proxy.
lcurl() { curl --noproxy '*' -fs -o /dev/null --max-time 5 "$@"; }

port_in_use() {
  "$VENV_PYTHON" - "$1" <<'PY'
import socket, sys
port = int(sys.argv[1])
for host in ("127.0.0.1", "::1"):
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex((host, port)) == 0:
                sys.exit(0)
    except OSError:  # e.g. IPv6 disabled in the container
        continue
sys.exit(1)
PY
}

# Refuse to test against servers this script did not start (stale code, other data).
for port in "$API_PORT" "$WEB_PORT"; do
  if port_in_use "$port"; then
    echo "port $port is already in use; stop that server before 'make e2e'" >&2
    exit 1
  fi
done

started_moto=0
api_pid=""
web_pid=""

stop_group() {
  local pid="$1" name="$2"
  [[ -n "$pid" ]] || return 0
  if kill -0 "$pid" 2>/dev/null; then
    kill -TERM -- "-$pid" 2>/dev/null || true
    for _ in $(seq 1 50); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.2
    done
    if kill -0 "$pid" 2>/dev/null; then
      echo "[e2e] $name did not stop on SIGTERM; sending SIGKILL" >&2
      kill -KILL -- "-$pid" 2>/dev/null || true
    fi
  fi
}

cleanup() {
  local rc=$?
  trap - EXIT INT TERM
  echo "[e2e] stopping local stack"
  stop_group "$web_pid" "nuxt dev"
  stop_group "$api_pid" "api"
  if [[ "$started_moto" -eq 1 ]]; then
    "$VENV_PYTHON" scripts/local/moto_server.py stop || true
  fi
  if [[ "$rc" -ne 0 ]]; then
    echo "[e2e] FAILED (exit $rc). Logs and artefacts: $OUT" >&2
  fi
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

wait_for() {
  local name="$1" url="$2" pid="$3" log="$4"
  echo "[e2e] waiting for $name at $url"
  for _ in $(seq 1 "$READY_TIMEOUT"); do
    if lcurl "$url"; then return 0; fi
    if [[ -n "$pid" ]] && ! kill -0 "$pid" 2>/dev/null; then
      echo "[e2e] $name exited before becoming ready; last log lines:" >&2
      tail -n 40 "$log" >&2 || true
      return 1
    fi
    sleep 1
  done
  echo "[e2e] $name was not ready within ${READY_TIMEOUT}s; last log lines:" >&2
  tail -n 40 "$log" >&2 || true
  return 1
}

# --- moto ------------------------------------------------------------------
if lcurl http://127.0.0.1:5000/moto-api/; then
  echo "[e2e] reusing the running moto (it is left running afterwards)"
else
  "$VENV_PYTHON" scripts/local/moto_server.py start
  started_moto=1
fi
make --no-print-directory local-init > "$OUT/local-init.log" 2>&1 || {
  echo "[e2e] local-init failed:" >&2; tail -n 40 "$OUT/local-init.log" >&2; exit 1;
}

# --- API (no --reload: one process group, deterministic shutdown) -----------
setsid "$VENV_PYTHON" -m uvicorn local_api.main:app --host 127.0.0.1 --port "$API_PORT" \
  > "$OUT/api.log" 2>&1 < /dev/null &
api_pid=$!
wait_for "api" "http://127.0.0.1:${API_PORT}/api/whiskeys/search?q=bowmore" "$api_pid" "$OUT/api.log"

# --- Nuxt dev server with mock auth -----------------------------------------
(
  cd frontend
  export NUXT_PUBLIC_MOCK_AUTH=1
  export NUXT_PUBLIC_API_BASE_URL="http://localhost:${API_PORT}"
  export NUXT_TELEMETRY_DISABLED=1
  exec setsid npx nuxt dev --port "$WEB_PORT" --host localhost
) > "$OUT/nuxt.log" 2>&1 < /dev/null &
web_pid=$!
wait_for "nuxt dev" "$WEB_URL/" "$web_pid" "$OUT/nuxt.log"

# --- Playwright ----------------------------------------------------------------
echo "[e2e] chromium: ${PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH:-<playwright-managed>}"
set +e
(cd frontend && E2E_BASE_URL="$WEB_URL" npx playwright test "$@")
rc=$?
set -e
exit "$rc"
