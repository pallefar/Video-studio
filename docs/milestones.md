# Milestones

Durable progress record. Claude Code ticks boxes as work lands; this file
survives context resets. Acceptance criteria are commands that exit zero —
see docs/psd.md §5 for full rationale.

## M0 — Environment

- [ ] `scripts/verify_gpu.py` asserts `torch.cuda.get_device_capability() == (8, 6)` and fails loudly otherwise *(script written; must be run on the 3090 host)*
- [ ] Chatterbox loads and produces a 10 s clip from a reference sample
- [ ] MuseTalk loads and lip-syncs 5 s against a test clip
- [ ] Both resident simultaneously, peak VRAM logged and under 20 GB

**Accept:** `python scripts/verify_gpu.py && python scripts/bench.py --smoke` exits 0

## M1 — Schema + API skeleton

- [ ] Pydantic models for all §4 entities
- [ ] `export_ts.py` generates TS types; a schema change that isn't re-exported fails CI
- [ ] Postgres via Alembic
- [ ] CRUD for jobs, loops, voice profiles
- [ ] All storage access through an S3 client behind one interface — no `open()` on a job artefact anywhere outside it
- [ ] All service addresses from env vars; no `localhost` literal in worker code

**Accept:** `pytest tests/test_schema_roundtrip.py tests/test_portability.py` passes

## M2 — Loop preprocessing

- [ ] Ingest base footage, enforce constant frame rate at ingest (reject VFR)
- [ ] Seam detection via perceptual hash, ping-pong fallback
- [ ] Latent cache built and persisted per loop
- [ ] Second render against a cached loop is measurably faster than the first

**Accept:** `python scripts/bench.py --loop <id>` shows cached run ≥ 40% faster

## M3 — GPU worker

- [ ] Single long-lived process, models warm at boot, never unloaded
- [ ] Consumes `tts` and `lipsync` stages from Redis
- [ ] Segment-level retry — one bad sentence re-renders alone
- [ ] Chunked lip-sync at 60–90 s windows
- [ ] Seeds pinned and persisted per segment

**Accept:** `pytest tests/test_queue_topology.py` asserts GPU concurrency is 1; a job goes `queued → lipsync` unattended

## M4 — Assembly

- [ ] Loudness normalise to −14 LUFS
- [ ] Watermark burn-in, full duration, bottom-right
- [ ] Caption burn-in from faster-whisper word timings
- [ ] B-roll insertion at timestamps
- [ ] H.264 CRF 18, yuv420p, `+faststart`

**Accept:** an 8-minute job completes end to end; output plays in VLC and Chrome with correct A/V sync

## M5 — Compliance gate

- [ ] Validator rejects any job with `watermark.persistent != true`
- [ ] Validator rejects any job with `publish.altered_content != true`
- [ ] Provenance record written before publish is permitted
- [ ] Frame sampling asserts watermark pixels present at 10%, 50%, 90% of duration

**Accept:** `pytest tests/test_compliance.py` passes, including the negative cases

## M6 — Publish

- [ ] YouTube Data API v3, OAuth, refresh token persisted
- [ ] Uploads land `private`, always — no path publishes directly
- [ ] `altered_content` set programmatically on upload
- [ ] Exponential backoff; quota exhaustion is distinguished from real failure

**Accept:** a real upload lands private with the disclosure flag visible in Studio

## M7 — Control panel

- [ ] Submit script, pick loop + voice profile
- [ ] Job list with live status (TanStack Query polling, 2 s interval)
- [ ] Preview before publish, per-segment re-render button
- [ ] Manual publish confirmation — never automatic

**Accept:** a full video produced without touching the terminal

## M8 — Stock ingest + asset library

- [ ] Pexels + Pixabay clients behind one `StockProvider` interface
- [ ] Ingest downloads to MinIO, persists `license`, `source_url`, `origin='stock'`
- [ ] `has_identifiable_people` defaults `true` on stock ingest; resolver excludes flagged assets
- [ ] Caption embedding + cosine search over the library
- [ ] Library browser in the control panel with an approve/flag toggle

**Accept:** `pytest tests/test_asset_resolver.py` passes, including the case that a flagged asset is never returned

## M9 — Generative B-roll lane

- [ ] Wan 2.2 quantised (GGUF/INT8) loads and generates a 5 s clip
- [ ] Runs as a separate queue with an exclusive GPU lock — never concurrent with the render lane
- [ ] Generation requests enqueue and never block a render job
- [ ] Output lands in the library as `origin='generated'`, `approved=false`
- [ ] Approval gate in the control panel before an asset becomes selectable

**Accept:** `pytest tests/test_gpu_exclusivity.py` proves render and generation lanes cannot hold the GPU simultaneously; an unapproved generated asset is never selected by the resolver
