#!/usr/bin/env bash
# One-command dev studio — designed for Apple Silicon Macs (M-series), works
# on any machine without CUDA. Runs the FULL pipeline with dev engines
# (DEV_ENGINES=1): placeholder voice + static avatar, real everything else.
#
#   ./scripts/dev_up.sh          # start everything, Ctrl-C stops it all
#   DEV_ENGINES=0 ./scripts/dev_up.sh   # workstation mode (real engines)
#
# Prereqs (macOS): Docker Desktop or OrbStack, Python 3.11+, Node 20+.
#   brew install python@3.12 node && open -a Docker
# Full walkthrough: docs/mac-dev.md

set -euo pipefail
cd "$(dirname "$0")/.."

# A start is also an upgrade: fast-forward to the branch's latest commits and
# refresh deps when their manifests changed, so the stack always runs what is
# committed. Skipped when the tree has local edits (never clobber work in
# progress); NO_UPDATE=1 skips entirely; a failed pull (offline) starts the
# local version instead of blocking.
if [ "${NO_UPDATE:-0}" != 1 ]; then
  if git diff --quiet && git diff --cached --quiet; then
    echo "==> self-update (NO_UPDATE=1 to skip)"
    before=$(git rev-parse HEAD)
    git pull --ff-only 2>/dev/null || echo "    !! pull failed (offline?) — starting the local version"
    if [ "$(git rev-parse HEAD)" != "$before" ]; then
      git --no-pager log --oneline "$before..HEAD" | sed 's/^/    + /'
      if [ -d .venv ] && ! git diff --quiet "$before" HEAD -- pyproject.toml; then
        echo "==> pyproject.toml changed — refreshing venv"
        ./.venv/bin/pip install -q -e ".[dev]"
      fi
      if [ -d web/node_modules ] && ! git diff --quiet "$before" HEAD -- web/package-lock.json; then
        echo "==> web lockfile changed — npm ci"
        (cd web && npm ci --silent)
      fi
    fi
  else
    echo "==> local edits present — skipping self-update"
  fi
fi

export DEV_ENGINES="${DEV_ENGINES:-1}"

# macOS: RQ forks a work-horse per job; newer Darwin kills the fork when
# Objective-C classes initialize post-fork (instant signal-6 job failures).
# Standard mitigation for forking workers on macOS.
[ "$(uname -s)" = "Darwin" ] && export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

echo "==> infrastructure (postgres, redis, minio)"
docker compose up -d --wait

if [ ! -d .venv ]; then
  echo "==> creating venv + installing"
  python3 -m venv .venv
  ./.venv/bin/pip install -q -e ".[dev]"
fi
PY=./.venv/bin/python

echo "==> migrations + bucket"
$PY -m alembic upgrade head
$PY -c "from pipeline_core.storage import ObjectStore; ObjectStore().ensure_bucket()"

if [ ! -d web/node_modules ]; then
  echo "==> npm ci"
  (cd web && npm ci --silent)
fi

PIDS=()
cleanup() {
  echo; echo "==> stopping"
  for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "==> api :8000"
$PY -m uvicorn api.main:app --host 127.0.0.1 --port 8000 &
PIDS+=($!)

echo "==> cpu worker (ffmpeg: preprocess, assemble, export, publish)"
$PY worker_cpu/run.py &
PIDS+=($!)

echo "==> render-lane worker (dev engines: DEV_ENGINES=$DEV_ENGINES)"
$PY worker_gpu/run.py &
PIDS+=($!)

echo "==> wan-lane worker (generation queue)"
# M30: a configured ComfyUI (COMFY_URL in env or .env) means the wan lane
# does REAL generation — on a Mac that's the MPS-sized wan2.1-t2v-1.3b.
# Dev engines stay on for the render lane only (voice/lipsync placeholders).
WAN_DEV_ENGINES="$DEV_ENGINES"
COMFY_CONFIGURED="${COMFY_URL:-$(grep -E '^COMFY_URL=.+' .env 2>/dev/null | head -1 | cut -d= -f2-)}"
if [ -n "$COMFY_CONFIGURED" ]; then
  WAN_DEV_ENGINES=0
  echo "    COMFY_URL configured ($COMFY_CONFIGURED) — wan lane generates for real"
fi
DEV_ENGINES="$WAN_DEV_ENGINES" $PY worker_gpu/run_wan.py &
PIDS+=($!)

echo "==> panel :5173"
(cd web && npx vite --port 5173 --strictPort) &
PIDS+=($!)

sleep 2
echo
echo "  Studio:  http://localhost:5173"
echo "  API:     http://localhost:8000/docs"
echo "  MinIO:   http://localhost:9001  (minioadmin / minioadmin)"
echo
echo "  Dev engines are ON — avatar jobs render end to end with the macOS"
echo "  'say' voice and a static loop. Ctrl-C stops everything."
echo
wait
