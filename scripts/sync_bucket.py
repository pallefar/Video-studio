"""Sync the artefact bucket to/from a local directory — the object half of
backup/restore (scripts/backup.sh, scripts/restore.sh).

Goes through ObjectStore (env-configured, like every service address) so the
same script works against MinIO locally and S3/R2 remotely — no bare boto3,
no aws-cli dependency.

    python scripts/sync_bucket.py pull <dir>   # bucket -> dir
    python scripts/sync_bucket.py push <dir>   # dir -> bucket (skips
                                               # same-size existing keys)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import structlog

from pipeline_core.storage import ObjectStore

log = structlog.get_logger()


def pull(store: ObjectStore, root: Path) -> int:
    count = 0
    for key in store.list_keys():
        target = root / key
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        store.get_file(key, target)
        count += 1
    return count


def push(store: ObjectStore, root: Path) -> int:
    existing = set(store.list_keys())
    count = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        key = path.relative_to(root).as_posix()
        if key in existing:
            continue
        store.put_file(key, path)
        count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("direction", choices=["pull", "push"])
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()

    store = ObjectStore()
    if args.direction == "pull":
        args.directory.mkdir(parents=True, exist_ok=True)
        count = pull(store, args.directory)
    else:
        if not args.directory.is_dir():
            parser.error(f"{args.directory} is not a directory")
        store.ensure_bucket()
        count = push(store, args.directory)
    log.info("sync_done", direction=args.direction, transferred=count,
             bucket=store.bucket, directory=str(args.directory))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
