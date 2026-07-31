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

## Security posture

Single-user tool, deliberately without auth — the security boundary is the
machine, and everything is built to stay inside it:

- **Loopback only, everywhere.** The API binds 127.0.0.1 in every launcher
  and service unit, and docker-compose publishes Postgres/Redis/MinIO on
  `127.0.0.1:` only (they carry default dev credentials and no TLS — on
  0.0.0.0 they'd be handed to the whole LAN). A rented-GPU worker reaches
  the services over Tailscale/WireGuard, never via opened ports. Enforced
  by `tests/test_security.py`.
- **Uploads**: object keys are `uuid.{suffix}` with the suffix run through
  a strict allowlist — the client filename never reaches the object store;
  uploads are size-capped (413 beyond `MAX_UPLOAD_MB`).
- **Stock ingest treats its body as untrusted** (it's a relayed search
  result): downloads must be https, and provider/external-id are character-
  sanitised so a hostile body cannot write outside `assets/stock/` or
  overwrite other artefact namespaces.
- **No shell composition.** Every ffmpeg/subprocess call passes an argument
  list; there is no `shell=True`, no `eval`, no raw SQL (SQLModel bound
  parameters throughout), and the React panel never uses
  `dangerouslySetInnerHTML`.
- **Secrets** live in `.env` (gitignored) and flow through `Settings`; they
  are never logged. Presigned URLs expire after an hour.
- **Same-origin only**: no CORS middleware exists — the dev server proxies,
  and production serves the built panel from the API process itself.
- The structural gates (C1–C6: watermark, disclosure, private uploads,
  consent) are enforced in validators + tests, not UI — see
  `tests/test_compliance.py`.

Threat model note: MCP (`python -m studio_mcp`) gives any connected LLM the
same powers as the panel *except* publish/consent/approve, which have no
tools (asserted in `tests/test_mcp.py`). Don't connect MCP clients you
wouldn't hand the panel to.

## Env

`.env.example` is the canonical variable list — every `Settings` field
appears in it, enforced by the drift guard in `tests/test_ops.py`. New
setting ⇒ add it to both files or CI fails.

## Releases

One release per big milestone, version `v0.<milestone>.0`. Three ways to
cut one (all equivalent):

```bash
# 1. tag push
git tag v0.29.0 && git push origin v0.29.0

# 2. GitHub UI: Actions -> Release -> Run workflow (version input)

# 3. release commit — for environments that can push branches but not tags:
echo v0.29.0 > VERSION
git commit -am "release: v0.29.0" && git push
```

`.github/workflows/release.yml` then builds the panel, runs
`scripts/make_release.sh`, and publishes a GitHub Release with
`video-studio-<tag>-macos.zip`, `video-studio-<tag>-windows.zip`,
`SHA256SUMS.txt`, and notes taken from the latest section of
docs/milestones.md (`scripts/release_notes.py`).

Bundle guarantees (guarded by `tests/test_release.py`):

- Contents come from `git archive` — tracked files only, so `.env`, local
  databases and node_modules can never leak into a release.
- The control panel ships prebuilt (`web/dist`), and the API serves it
  itself — release users need Docker Desktop + Python 3.11, **not Node**.
- Each zip carries a platform GETTING-STARTED.txt: `./scripts/setup.sh
  --start` on macOS, `scripts\setup.ps1 -Start` on Windows.
- Upgrades: unzip the new version, copy `.env` across; alembic migrates
  the database on API start.
