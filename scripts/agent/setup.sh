#!/usr/bin/env bash
# Install everything the CI "Test / Lint / Build" job needs, so a cloud agent
# (Claude Code on the web / Codex Cloud) can verify changes without AWS.
# Idempotent. Needs network (PyPI + npm registry); run it before network is cut.
#
#   bash scripts/agent/setup.sh
#
# Python deps go into .venv (created only if missing). Use .venv/bin/python
# afterwards, or rely on PATH when the caller exports it.

set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT"

log() { printf '[agent-setup] %s\n' "$*"; }

PYTHON=${PYTHON:-python3}
if command -v python3.11 >/dev/null 2>&1; then PYTHON=python3.11; fi
log "python: $($PYTHON --version 2>&1), node: $(node --version 2>&1)"

if [ ! -x .venv/bin/python ]; then
  log "creating .venv"
  "$PYTHON" -m venv .venv
fi
log "installing requirements-dev.txt"
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements-dev.txt

# Codex Cloud: the default npm cache under $HOME is not writable. Fall back to
# a cache inside the repo (git-ignored) instead of failing npm ci.
npm_cache=$(npm config get cache 2>/dev/null || echo "$HOME/.npm")
if ! mkdir -p "$npm_cache" 2>/dev/null || [ ! -w "$npm_cache" ]; then
  export npm_config_cache="$ROOT/.npm-cache"
  log "npm cache $npm_cache is not writable; using $npm_config_cache"
fi

for dir in infra frontend; do
  log "npm ci in $dir"
  (cd "$dir" && npm ci --no-audit --no-fund --loglevel=error)
done

log "done"
