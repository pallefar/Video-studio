#!/usr/bin/env bash
# One-command bootstrap for macOS (Apple Silicon or Intel) and Linux:
# checks every dependency, installs what's missing, prepares the stack.
# Idempotent — safe to re-run any time; it only installs what isn't there.
#
#   ./scripts/setup.sh           # check + install + prepare
#   ./scripts/setup.sh --start   # ...then launch the studio (dev_up.sh)
#
# Windows: use scripts\setup.ps1 instead.
set -euo pipefail
cd "$(dirname "$0")/.."

BOLD=$(tput bold 2>/dev/null || true); RESET=$(tput sgr0 2>/dev/null || true)
ok()   { echo "  ✓ $*"; }
todo() { echo "  → $*"; }
fail() { echo "  ✗ $*" >&2; exit 1; }

OS="$(uname -s)"
echo "${BOLD}== Video Studio setup ($OS) ==${RESET}"

# --- Homebrew (macOS package manager) ---------------------------------------
if [ "$OS" = "Darwin" ] && ! command -v brew >/dev/null; then
  todo "Homebrew not found — installing (you may be asked for your password)"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
fi

# --- git ---------------------------------------------------------------------
command -v git >/dev/null && ok "git $(git --version | cut -d' ' -f3)" || {
  if [ "$OS" = "Darwin" ]; then todo "installing git"; brew install git;
  else fail "git missing — install it with your package manager (apt install git)"; fi
}

# --- Python 3.11+ ------------------------------------------------------------
PYBIN=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null; then
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
      PYBIN="$candidate"; break
    fi
  fi
done
if [ -n "$PYBIN" ]; then
  ok "python $($PYBIN -c 'import sys; print(".".join(map(str, sys.version_info[:3])))') ($PYBIN)"
else
  if [ "$OS" = "Darwin" ]; then
    todo "Python 3.11+ not found — installing python@3.12"
    brew install python@3.12
    PYBIN=python3.12
  else
    fail "Python 3.11+ missing — install it (apt install python3.12 python3.12-venv)"
  fi
fi

# --- Node 20+ ----------------------------------------------------------------
if command -v node >/dev/null && [ "$(node -e 'console.log(process.versions.node.split(".")[0])')" -ge 20 ]; then
  ok "node $(node --version)"
else
  if [ "$OS" = "Darwin" ]; then todo "installing node"; brew install node;
  else fail "Node 20+ missing — install it (e.g. via https://nodejs.org or nvm)"; fi
fi

# --- Docker (postgres / redis / minio run in containers) ---------------------
if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
  ok "docker running"
else
  if command -v docker >/dev/null; then
    if [ "$OS" = "Darwin" ]; then
      todo "starting Docker Desktop / OrbStack"
      open -a OrbStack 2>/dev/null || open -a Docker 2>/dev/null || true
      for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 2; done
      docker info >/dev/null 2>&1 && ok "docker running" || fail "Docker installed but not running — start it and re-run"
    else
      fail "docker installed but the daemon isn't running (systemctl start docker)"
    fi
  else
    if [ "$OS" = "Darwin" ]; then
      todo "installing Docker Desktop (brew cask)"
      brew install --cask docker
      open -a Docker
      echo "    Docker Desktop needs a first-run confirmation — approve it, then re-run this script."
      exit 1
    else
      fail "docker missing — https://docs.docker.com/engine/install/"
    fi
  fi
fi

# --- .env --------------------------------------------------------------------
if [ -f .env ]; then ok ".env present"; else todo "creating .env from .env.example"; cp .env.example .env; fi

# --- Python venv + package ---------------------------------------------------
if [ ! -d .venv ]; then
  todo "creating virtualenv (.venv)"
  "$PYBIN" -m venv .venv
fi
todo "installing python package (editable, [dev] extras)"
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -e ".[dev]"
ok "python deps"

# --- Web deps ----------------------------------------------------------------
if [ ! -d web/node_modules ]; then
  todo "npm ci (web/)"
  (cd web && npm ci --silent)
fi
ok "web deps"

# --- Infrastructure + schema -------------------------------------------------
todo "starting postgres / redis / minio"
docker compose up -d --wait
todo "migrations + bucket"
./.venv/bin/python -m alembic upgrade head
./.venv/bin/python -c "from pipeline_core.storage import ObjectStore; ObjectStore().ensure_bucket()"
ok "database + object store ready"

# --- Sanity ------------------------------------------------------------------
./.venv/bin/python -m pytest tests/test_schema_roundtrip.py -q >/dev/null 2>&1 \
  && ok "smoke test passed" \
  || echo "  ! smoke test failed — run ./.venv/bin/python -m pytest tests -q to inspect"

echo
echo "${BOLD}Setup complete.${RESET} Start the studio with:  ./scripts/dev_up.sh"
echo "  (DEV_ENGINES=1 placeholder engines by default; real engines need the GPU host — docs/workstation.md)"

if [ "${1:-}" = "--start" ]; then
  exec ./scripts/dev_up.sh
fi
