---
gsd_state_version: '1.0'
status: planning
progress:
  total_phases: 6
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-08-02)

**Core value:** A script becomes a compliant, publishable 1080p video, unattended, in under 20 minutes of wall clock — with compliance (C1–C6) enforced structurally.
**Current focus:** Phase 1 — Render Engines Live (RTX 3090 workstation)

## Current Position

Phase: 1 of 6 (Render Engines Live)
Plan: Not planned yet
Status: Ready to plan
Last activity: 2026-08-02 — Project initialized from ingest (/gsd-ingest-docs → roadmap); PROJECT.md, REQUIREMENTS.md, ROADMAP.md written

Progress: [░░░░░░░░░░] 0% (roadmap phases; the underlying milestone record is 125/138 boxes — the 6 phases close the remaining 13)

## Performance Metrics

**Velocity:**
- Total plans completed: 0
- Average duration: -
- Total execution time: -

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**
- Last 5 plans: -
- Trend: -

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions (16 proposed from ingest, 0 locked).
Recent decisions affecting current work:

- Ingest gate (2026-08-02, user-decided): REQ-control-panel accepts shipped reality — plain fetch polling is the accepted stack; TanStack Query is an optional future improvement, NOT a requirement
- docs/milestones.md is the authoritative completion record (125/138 checked — fact); remaining work sequenced strictly by docs/workstation.md §5
- DEC-comfyui-executor: ComfyUI headless is the wan-lane executor (landed M10) — Phase 3 brings it up on hardware

### Pending Todos

- Automate identity-LoRA sync from `s3://…/identities/{id}/lora.safetensors` into ComfyUI `models/loras/` (open item, workstation.md §2 — surfaces in Phase 5)
- ComfyUI workflow-template tuning on the workstation (content work, not code work — workstation.md §3)

### Blockers/Concerns

- All 6 phases require physical access to the RTX 3090 workstation — nothing in this roadmap can be completed in macOS dev mode (DEV_ENGINES placeholders verify wiring only)
- ComfyUI-MuseTalk node pack needs the mmlab stack — GPU-host install only, will not import on a CPU box (workstation.md §1)
- Phase 5 overnight LoRA run holds the exclusive wan-lane GPU lock — schedule around render needs; `COMFY_TIMEOUT_S` bounds lock duration
- pipeline-spec §6 figures are placeholders until Phase 6 — do not reason from them

## Deferred Items

None yet.

## Session Continuity

Last session: 2026-08-02 — Phase 1 Wave 1 executed to the hardware boundary. Plan 01-02 COMPLETE (boot-time engine warming in `worker_gpu/run.py` + 11-test CPU contract harness, TDD). Plan 01-01 PARTIAL: Task 1 done (`scripts/install_engines.sh` + tests + `MUSETALK_ROOT` setting), Task 2 package-legitimacy gate APPROVED by the owner — MuseTalk pinned at `0a89dec45a0192b824e3cf4daf96c239440c5ed8` (2025-09-26), Chatterbox `chatterbox-tts` 0.1.7 (MIT, resemble-ai), mm* all open-mmlab.

Also done since: plan 01-03 **partial** — `worker_gpu/engines/audio.py` (the CUDA-free contract layer: 48 kHz/stereo constants, ffmpeg helpers, `tts_segment_key`/`lipsync_chunk_key`, `write_project_wav`, `build_window_audio`) plus 01-03 Task 2 in full (dev engines repointed at it, output byte-identical). 9 new CPU tests with real ffmpeg. The two engine bodies remain `NotImplementedError` by design — see 01-03-SUMMARY.md.

**Mac-side work for Phase 1 is now exhausted.** Everything remaining needs the card.

**Phase 2 (Latent Cache) pre-planned and its Mac-side half executed (2026-08-02).** Planned ahead of its Phase 1 dependency by owner decision; the plan-checker passed it and independently confirmed four real defects found by reading source:
- `build_loop_cache` was dead code (one repo-wide occurrence — its own definition); nothing dispatched it.
- `bench.py --loop <id>` could never match a row: `@timed_stage("lipsync")` writes `ref=job_id`, bench filtered `ref.contains(loop_id)` — independent UUIDs. Phase 2's own acceptance criterion was unmeasurable.
- The blanket decorator wrapped the idempotent early return, so a duplicate delivery wrote a near-zero row that `bench_loop` would read as the cached run — **a false pass reporting ~100% speedup with nothing cached**.
- On a ping-ponged loop, `BaseLoopCreate` nulls the cache URIs on PUT while `ping_pong` survives (table-only), and `loop_preprocess_stage` returns early before its tail — a replaced source would silently never rebuild.

Done on the Mac (plans 02-01 + 02-02, 5 of 8 tasks, 33 new tests): dispatch chain `loop_preprocess_stage` → `loop_cache_stage` (under `gpu_lock(HOLDER_RENDER)`) → `build_loop_cache` → ObjectStore → columns; ping-pong invalidation chain site; `lipsync_metric_ref`/`lipsync_ref_suffix` shared helper with a scoped `timed()` span that excludes the early return; `bench_loop` suffix-matched query.

**Cache layout — ONE-WAY DECISION, locked (owner chose option-a):** `latents_uri` → `loops/{loop_id}/cache/latents.pt` (file); `bbox_uri` → `loops/{loop_id}/cache/bbox` (PREFIX holding `coords.pkl` + optional `mask_coords.pkl`). No migration, worker-only, matching `loops/{id}/pingpong.mp4`. Reversal cost if ever needed: schema-only migration; the S3 objects don't move.

Remaining for Phase 2 = plan **02-03 only**, GPU-blocked: re-check assumptions P1-A…P1-E against Phase 1's landed engine (cheap reads), implement `MuseTalkEngine.prepare_loop_cache` + the `sync_chunk` cache-hit path, then the workstation ≥40% acceptance run.

Next step: **Task 3 of plan 01-01 — needs the RTX 3090 host.** On the workstation, repo root, studio venv active:

```
MUSETALK_COMMIT=0a89dec45a0192b824e3cf4daf96c239440c5ed8 bash scripts/install_engines.sh
python -c "import torch, chatterbox, sys; sys.path.append('third_party/MuseTalk'); import musetalk; print(torch.__version__)"
```

Report back the installer's RESOLVED VERSIONS block, whether mmcv came from a wheel or a source build (and how long), `pip show resemble-perth`, and any warnings even on exit 0. That measurement feeds Task 4's one-way `checkpoint:decision` (the torch/mmlab stack standardization) — the open risk is MuseTalk's documented `torch==2.0.1` vs Chatterbox's `torch>=2.6`. No CUDA box? `scripts/rent_gpu.sh` (multi-provider) then `scripts/vast_comfyui.sh`.
