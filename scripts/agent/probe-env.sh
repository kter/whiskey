#!/usr/bin/env bash
# Probe a cloud agent environment (Claude Code on the web / Codex Cloud) and print
# what this repo's verification steps can rely on. Read-only: installs nothing,
# prints no secret values (environment variable NAMES only).
#
# Usage: bash scripts/agent/probe-env.sh
# On Codex Cloud, run it twice: once from the setup script (network on) and once
# as an agent task (network may be off), then compare.

set -u

section() { printf '\n## %s\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }
show() { # show <label> <command...>
  local label=$1; shift
  local out
  if out=$("$@" 2>&1 | head -n 3); then
    printf '%-22s %s\n' "$label" "${out//$'\n'/ | }"
  else
    printf '%-22s FAIL (%s)\n' "$label" "${out//$'\n'/ | }"
  fi
}

section "System"
show "uname" uname -srm
show "os-release" sh -c '. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME"'
show "cpus" nproc
show "memory" sh -c "free -h | awk '/Mem:/ {print \$2\" total, \"\$7\" available\"}'"
show "disk (cwd)" sh -c "df -h . | awk 'NR==2 {print \$4\" free\"}'"
show "uid" id -u
if sudo -n true 2>/dev/null; then echo "sudo                   passwordless OK"; else echo "sudo                   not available"; fi

section "Toolchain (CI uses Python 3.11 / Node 22)"
for cmd in python3 python3.11 node npm npx java git gh docker uv pyenv; do
  if have "$cmd"; then
    case $cmd in
      java) show "$cmd" sh -c 'java -version 2>&1' ;;
      gh) show "$cmd" gh --version ;;
      *) show "$cmd" "$cmd" --version ;;
    esac
  else
    printf '%-22s not installed\n' "$cmd"
  fi
done
if [ -s "${NVM_DIR:-$HOME/.nvm}/nvm.sh" ]; then echo "nvm                    present"; else echo "nvm                    not found"; fi

section "Docker"
if have docker; then
  show "docker info" sh -c 'docker info --format "server {{.ServerVersion}}"'
  show "docker compose" docker compose version
else
  echo "docker                 not installed"
fi

section "Browsers"
for cmd in chromium chromium-browser google-chrome google-chrome-stable; do
  have "$cmd" && show "$cmd" "$cmd" --version
done
if [ -d "$HOME/.cache/ms-playwright" ]; then
  echo "playwright cache       $(ls "$HOME/.cache/ms-playwright" | tr '\n' ' ')"
else
  echo "playwright cache       none"
fi

section "Network (HTTP status or failure, 8s timeout)"
probe_url() {
  local code
  code=$(curl -sS -o /dev/null -m 8 -w '%{http_code}' "$1" 2>&1) || code="FAIL ${code}"
  printf '%-48s %s\n' "$1" "$code"
}
if have curl; then
  for url in \
    https://pypi.org/simple/pip/ \
    https://registry.npmjs.org/vitest \
    https://github.com/ \
    https://cdn.playwright.dev/ \
    https://playwright.azureedge.net/ \
    https://api.dev.whiskeybar.site/api/whiskeys/search/?q=test \
    https://sts.ap-northeast-1.amazonaws.com/ ; do
    probe_url "$url"
  done
else
  echo "curl                   not installed"
fi

section "Local servers (can a background process serve localhost?)"
if have python3; then
  port=18765
  python3 -m http.server "$port" --bind 127.0.0.1 >/dev/null 2>&1 &
  pid=$!
  ok=no
  for _ in $(seq 1 20); do
    if curl -s -o /dev/null "http://127.0.0.1:$port/"; then ok=yes; break; fi
    sleep 0.25
  done
  kill "$pid" 2>/dev/null
  echo "background localhost   $ok"
fi

section "Credentials present? (names only, values never printed)"
names=$(env | cut -d= -f1 | grep -E '^(AWS_|GH_|GITHUB_|ANTHROPIC_|OPENAI_)' | sort | tr '\n' ' ')
echo "env names              ${names:-none}"
[ -e "$HOME/.aws" ] && echo "~/.aws                 exists" || echo "~/.aws                 absent"
if have gh; then
  if gh auth status >/dev/null 2>&1; then echo "gh auth                logged in"; else echo "gh auth                not logged in"; fi
fi

echo
echo "probe finished"
