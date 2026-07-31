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

export DEV_ENGINES="${DEV_ENGINES:-1}"

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
$PY worker_gpu/run_wan.py &
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
