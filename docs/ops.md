# Ops — backup, restore, services

Single-user studio, but the asset library and provenance records are the
product; losing them costs real render-hours and real API dollars. This is
the minimal ops story: one backup script, one restore script, service units
for boot-time bring-up.

## What holds state

| Store | Contents | Backed up? |
|---|---|---|
| Postgres | jobs, assets, generations, storyboards, timelines, provenance, consent, metrics | **Yes** — `pg_dump -Fc` |
| MinIO/S3 bucket | every artefact: sources, TTS wavs, renders, derivatives, LoRAs | **Yes** — mirrored via `scripts/sync_bucket.py` (ObjectStore, env-configured) |
| Redis | RQ queues, GPU locks | **No — deliberately.** Every stage is idempotent on `(job_id, stage)`; after a restore, re-enqueue anything mid-flight and it re-runs safely. Locks are ephemeral by design. |
| Weights | model zoo (~150–300 GB) | No — pinned versions + scripted download (docs/workstation.md) re-materialise them |

## Backup

```bash
./scripts/backup.sh                # -> backups/2026-07-31_0500/
./scripts/backup.sh /mnt/nas/studio
```

Produces `db.dump` (`pg_dump --format=custom`; a straight file copy for a
sqlite dev DB) and `bucket/` (full object mirror; incremental — existing
files are skipped, so a NAS target only pulls new artefacts each run).

Schedule it: `crontab -e` → `0 5 * * * cd /opt/video-studio && ./scripts/backup.sh /mnt/nas/studio >> /var/log/studio-backup.log 2>&1`

## Restore

```bash
systemctl stop studio-api studio-worker-cpu studio-worker-gpu studio-worker-wan
./scripts/restore.sh backups/2026-07-31_0500
systemctl start studio-api studio-worker-cpu studio-worker-gpu studio-worker-wan
```

`pg_restore --clean --if-exists` replaces objects in place; the bucket push
skips keys that already exist (restore fills gaps, it never clobbers newer
artefacts). Jobs that were active during the snapshot sit in an active
status with an empty queue — retry them from the panel (failed → queued) or
re-enqueue; idempotent stages make this always safe.

**Drill it**: once after setup, restore a fresh snapshot into a scratch
Postgres DB + bucket (point `DATABASE_URL`/`S3_BUCKET` at scratch names) and
open the panel against it. A backup that has never been restored is a hope,
not a backup.

## Services

`deploy/systemd/` (Linux workstation) and `deploy/launchd/` (Mac dev mode)
carry one unit per process — the same processes `scripts/dev_up.sh` starts
by hand:

| Unit | Process | Notes |
|---|---|---|
| `studio-api` | uvicorn `api.main:app` | localhost only — single-user tool |
| `studio-worker-cpu` | `worker_cpu/run.py` | ffmpeg, ingest, captioning, network jobs |
| `studio-worker-gpu` | `worker_gpu/run.py` | render lane, concurrency 1, **never two instances** |
| `studio-worker-wan` | `worker_gpu/run_wan.py` | wan lane; exclusive GPU lock vs render lane |
| `studio-comfyui` | ComfyUI headless :8188 | the M10 executor (docs/workstation.md) |

Install (Linux): copy to `/etc/systemd/system/`, adjust `User=`/paths,
`systemctl daemon-reload && systemctl enable --now <unit>`. Postgres, Redis
and MinIO come from `docker compose up -d` (or distro services) and are not
duplicated here. The GPU workers stay native processes — containerising them
is a hard "do not" (CLAUDE.md).

Mac (dev mode): `cp deploy/launchd/*.plist ~/Library/LaunchAgents/ &&
launchctl load ~/Library/LaunchAgents/com.studio.*.plist` — DEV_ENGINES=1 is
baked into the plists; there is no GPU render unit on the Mac.

## Env

`.env.example` is the canonical variable list — every `Settings` field
appears in it, enforced by the drift guard in `tests/test_ops.py`. New
setting ⇒ add it to both files or CI fails.
