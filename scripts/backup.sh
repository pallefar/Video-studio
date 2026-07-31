#!/usr/bin/env bash
# Studio backup: Postgres dump + artefact bucket mirror into one dated
# directory. Redis queues are deliberately NOT backed up — every stage is
# idempotent on (job_id, stage), so re-enqueueing after a restore is always
# safe (docs/ops.md).
#
#   ./scripts/backup.sh [target-dir]      # default: ./backups
set -euo pipefail
cd "$(dirname "$0")/.."

TARGET="${1:-backups}/$(date +%Y-%m-%d_%H%M)"
mkdir -p "$TARGET"

# .env is where DATABASE_URL etc live locally; already-exported env wins.
if [ -f .env ]; then set -a; . ./.env; set +a; fi

DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://avatar:avatar@localhost:5432/avatar}"
# pg_dump wants a plain postgresql:// URL, not SQLAlchemy's +psycopg dialect
PG_URL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"

case "$DATABASE_URL" in
  sqlite*)
    DB_FILE="${DATABASE_URL#sqlite:///}"; DB_FILE="${DB_FILE%%\?*}"
    cp "$DB_FILE" "$TARGET/studio.sqlite3"
    echo "sqlite copied -> $TARGET/studio.sqlite3"
    ;;
  *)
    pg_dump --format=custom --file="$TARGET/db.dump" "$PG_URL"
    echo "pg_dump -> $TARGET/db.dump"
    ;;
esac

python scripts/sync_bucket.py pull "$TARGET/bucket"

echo "backup complete: $TARGET"
