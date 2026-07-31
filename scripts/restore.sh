#!/usr/bin/env bash
# Restore a scripts/backup.sh snapshot: database first, then the artefact
# bucket. Stop the API and workers before running; re-enqueue anything that
# was mid-flight afterwards (stages are idempotent — docs/ops.md).
#
#   ./scripts/restore.sh backups/2026-07-31_0500
set -euo pipefail
cd "$(dirname "$0")/.."

SNAPSHOT="${1:?usage: ./scripts/restore.sh <snapshot-dir>}"
[ -d "$SNAPSHOT" ] || { echo "no such snapshot: $SNAPSHOT" >&2; exit 1; }

if [ -f .env ]; then set -a; . ./.env; set +a; fi

DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://avatar:avatar@localhost:5432/avatar}"
PG_URL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"

if [ -f "$SNAPSHOT/studio.sqlite3" ]; then
  DB_FILE="${DATABASE_URL#sqlite:///}"; DB_FILE="${DB_FILE%%\?*}"
  cp "$SNAPSHOT/studio.sqlite3" "$DB_FILE"
  echo "sqlite restored -> $DB_FILE"
elif [ -f "$SNAPSHOT/db.dump" ]; then
  # --clean --if-exists: replace objects in place; the DB itself must exist
  pg_restore --clean --if-exists --no-owner --dbname="$PG_URL" "$SNAPSHOT/db.dump"
  echo "pg_restore <- $SNAPSHOT/db.dump"
else
  echo "snapshot has no database dump" >&2; exit 1
fi

if [ -d "$SNAPSHOT/bucket" ]; then
  python scripts/sync_bucket.py push "$SNAPSHOT/bucket"
fi

echo "restore complete from $SNAPSHOT"
