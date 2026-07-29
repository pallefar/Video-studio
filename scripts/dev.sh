#!/usr/bin/env bash
# One-command dev stack: API + cpu worker + web panel.
# Prereqs: docker compose up -d (postgres/redis/minio), pip install -e ".[dev]",
# alembic upgrade head, npm install in web/. GPU worker runs separately on
# the 3090 host: python worker_gpu/run.py
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "[dev] starting api on :8000"
python -m uvicorn api.main:app --port 8000 --reload &

echo "[dev] starting cpu worker"
python worker_cpu/run.py &

echo "[dev] starting web on :5173"
(cd web && npm run dev -- --port 5173) &

wait
