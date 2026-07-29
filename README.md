# Video Studio

Self-hosted AI video studio: preset-driven generation (camera moves, styles),
per-project asset pools, storyboards, a timeline editor, and watermarked
ffmpeg exports — with an aggregator layer that runs open models on your own
GPU **or** proprietary models (Kling, Seedance, …) via API, behind one
interface. Single user, single RTX 3090, EU-AI-Act-compliant by construction.

Full product docs: [`docs/psd.md`](docs/psd.md) (v1 avatar pipeline) and
[`docs/roadmap-v2.md`](docs/roadmap-v2.md) (Higgsfield-class studio).
Progress: [`docs/milestones.md`](docs/milestones.md).

## Quickstart (workstation)

```bash
cp .env.example .env                  # adjust if needed
docker compose up -d                  # postgres, redis, minio
pip install -e ".[dev]"               # + ".[gpu]" on the 3090 host
alembic upgrade head
./scripts/dev.sh                      # api + cpu worker + web panel
```

Open http://localhost:5173 — create a project, generate or upload assets in
the **Asset center**, assemble them in the **Video center**, refine in the
**Editor**, export.

- Hosted models: set `FAL_API_KEY` in `.env` and pick a fal engine in the UI.
- GPU work (Wan camera presets, avatar pipeline): run
  `python scripts/verify_gpu.py` first — see `docs/milestones.md` M0.

## Verify

```bash
pytest                                # full suite, service-free
pytest tests/test_compliance.py       # C1-C5 gates
python packages/schema/export_ts.py   # after ANY schema change
```

## Architecture (one paragraph)

FastAPI + Postgres + Redis/RQ + MinIO. `packages/schema/models.py` is the
single source of truth (TypeScript types are generated — never hand-edit).
Two GPU lanes with an exclusive lock: render (Chatterbox + MuseTalk) and wan
(Wan 2.2 generation); API-model jobs run on the cpu/network lane. All
artefact I/O goes through one S3 interface; workers are stateless and
portable to rented GPUs. Compliance (visible AI watermark, disclosure flags,
provenance, private-only uploads) is enforced in validators and the render
compiler — not in habits. See `CLAUDE.md` for the hard constraints.
