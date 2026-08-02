---
phase: 02-latent-cache
plan: 01
subsystem: worker
tags: [musetalk, objectstore, gpu-lock, rq, sqlmodel, pytest, moto]

# Dependency graph
requires:
  - phase: 01-render-engines-live
    provides: gpu_lock/HOLDER_RENDER, the render-lane GPU queue, and the get_engines() singleton pattern this plan's stage reuses (MuseTalkEngine.prepare_loop_cache itself is still not implemented — that is plan 02-03, gated on Phase 1 landing)
provides:
  - "build_loop_cache: no longer dead code — a live dispatch chain from loop_preprocess_stage's two non-error exits into a real GPU-queue stage"
  - "worker_gpu/preprocess/loop_cache.py: cache_prefix, latents_key, bbox_prefix, coords_key, mask_coords_key, cache_is_present, build_loop_cache(store, loop_id, prepare), load_loop_cache(store, loop_id, dest_dir)"
  - "worker_gpu/stages.py::loop_cache_stage(loop_id) — GPU-queue entry point under gpu_lock(HOLDER_RENDER), idempotent no-op before the lock, loud warning-and-skip when the resident engine exposes no prepare_loop_cache seam"
  - "worker_cpu/stages.py chain helper (_chain_loop_cache) wired at both of loop_preprocess_stage's non-error exits (success tail, ping-pong idempotent early return)"
  - "tests/conftest.py::fake_gpu_redis — in-memory stand-in for gpu_lock's three redis ops, reusable by plan 02-02"
affects: [02-02, 02-03]

# Actuals (#2632)
actuals:
  tokens: 8700
  tasks: 2
  commits: 2

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "prepare(source_path, out_dir) seam: the one place CUDA enters build_loop_cache — everything else is CPU-provable with a fake preparer"
    - "cache_is_present(store, loop) as the single source of truth for 'is this loop cached', re-checking the store (not just the column) on every call"
    - "idempotent-on-entity-state (BaseLoop.latents_uri), not (job_id, stage) — this cache is loop-scoped, matching loop_preprocess_stage's existing ping_pong idempotency model, not the job-scoped convention used elsewhere"

key-files:
  created:
    - tests/test_loop_cache.py
  modified:
    - worker_gpu/preprocess/loop_cache.py
    - worker_gpu/stages.py
    - worker_cpu/stages.py
    - tests/conftest.py

key-decisions:
  - "Task 1 checkpoint (pre-approved, option-a): latents_uri -> loops/{id}/cache/latents.pt (a file); bbox_uri -> loops/{id}/cache/bbox (a prefix holding coords.pkl and optional mask_coords.pkl). No Alembic migration, no export_ts.py regen — verified against the live BaseLoopBase schema (exactly latents_uri + bbox_uri, no third column) and against the existing loops/{loop_id}/pingpong.mp4 key convention. The prefix/file asymmetry is documented directly on bbox_prefix's docstring per the approval condition."
  - "The ping-pong idempotent-exit guard uses a lightweight loop.latents_uri is None column check, not a cross-package call into worker_gpu.preprocess.loop_cache.cache_is_present from worker_cpu — keeps the CPU/GPU package boundary clean; loop_cache_stage's own cache_is_present re-verifies object presence in the store as the authoritative idempotency check regardless."
  - "loop_cache_stage resolves the engine and checks cache_is_present strictly before acquiring gpu_lock, so a no-op build (the common case on every rerun) never takes the card from a waiting render."

patterns-established:
  - "GPU-queue stage skips loudly (structured warning naming the engine class) rather than crashing when the resident engine doesn't expose an expected optional seam — keeps DEV_ENGINES=1 and CI green while making a cross-phase dependency visible in logs."

requirements-completed: [REQ-loop-preprocessing]

coverage:
  - id: D1
    description: "loop_preprocess_stage's successful tail chains worker_gpu.stages.loop_cache_stage onto QUEUE_GPU with the loop id and job key {loop_id}-loop_cache"
    requirement: "REQ-loop-preprocessing"
    verification:
      - kind: unit
        ref: "tests/test_loop_cache.py#test_chain_fires_on_success"
        status: pass
    human_judgment: false
  - id: D2
    description: "A VFR-rejected loop chains nothing — the cache build never fires for a loop the CPU stage rejected"
    requirement: "REQ-loop-preprocessing"
    verification:
      - kind: unit
        ref: "tests/test_loop_cache.py#test_chain_does_not_fire_on_vfr_rejection"
        status: pass
    human_judgment: false
  - id: D3
    description: "loop_cache_stage builds MuseTalk's cache end-to-end under gpu_lock(HOLDER_RENDER) and records both BaseLoop URI columns only after every upload returns"
    requirement: "REQ-loop-preprocessing"
    verification:
      - kind: unit
        ref: "tests/test_loop_cache.py#test_stage_builds_cache_end_to_end_under_render_lock"
        status: pass
      - kind: unit
        ref: "tests/test_loop_cache.py#test_build_leaves_columns_null_on_partial_upload_failure"
        status: pass
    human_judgment: false
  - id: D4
    description: "A cache build for an already-cached loop is a no-op that never acquires the GPU lock and never calls the preparer"
    requirement: "REQ-loop-preprocessing"
    verification:
      - kind: unit
        ref: "tests/test_loop_cache.py#test_stage_skips_lock_and_preparer_on_noop"
        status: pass
      - kind: unit
        ref: "tests/test_loop_cache.py#test_build_is_noop_when_cache_present"
        status: pass
    human_judgment: false
  - id: D5
    description: "No per-frame PNG (full_imgs/, mask/) is ever uploaded to ObjectStore, even when the preparer writes them"
    requirement: "REQ-loop-preprocessing"
    verification:
      - kind: unit
        ref: "tests/test_loop_cache.py#test_build_does_not_persist_frame_images"
        status: pass
    human_judgment: false
  - id: D6
    description: "The ping-pong idempotent early return also chains the cache build (guarded on no error, no live cache column) — closes the gap where a PUT nulls the cache columns but ping_pong survives"
    requirement: "REQ-loop-preprocessing"
    verification:
      - kind: unit
        ref: "tests/test_loop_cache.py#test_pingpong_exit_chains_when_cache_missing"
        status: pass
      - kind: unit
        ref: "tests/test_loop_cache.py#test_pingpong_exit_does_not_chain_with_live_cache"
        status: pass
      - kind: unit
        ref: "tests/test_loop_cache.py#test_pingpong_exit_does_not_chain_with_error"
        status: pass
    human_judgment: false
  - id: D7
    description: "load_loop_cache restores MuseTalk's own flat directory layout byte-identically, independent of the S3 key shape; a miss returns None without touching the destination directory"
    requirement: "REQ-loop-preprocessing"
    verification:
      - kind: unit
        ref: "tests/test_loop_cache.py#test_load_loop_cache_round_trips_bytes"
        status: pass
      - kind: unit
        ref: "tests/test_loop_cache.py#test_load_loop_cache_miss_returns_none_and_leaves_dest_empty"
        status: pass
    human_judgment: false
  - id: D8
    description: "The real face-detection/VAE-encode build reusing the resident engine's sub-models, and the actual >=40% measured speedup"
    verification: []
    human_judgment: true
    rationale: "No CUDA on this Mac. This is explicitly out of scope for 02-01 (deferred to plan 02-03 on the RTX 3090 host, per the plan's own <verification> section) — the prepare seam is the line between what this plan proves and what only the workstation can prove."

# Metrics
duration: 35min
completed: 2026-08-02
status: complete
---

# Phase 2 Plan 01: Latent Cache Dispatch Wiring Summary

**Wired `build_loop_cache` (previously dead code, zero call sites) into a live path: CPU preprocessing → GPU-queue `loop_cache_stage` under `gpu_lock(HOLDER_RENDER)` → MuseTalk's cache files persisted to ObjectStore at `loops/{id}/cache/{latents.pt, bbox/coords.pkl, bbox/mask_coords.pkl}` → `BaseLoop.latents_uri`/`bbox_uri` recorded only after every upload returns.**

## Performance

- **Duration:** 35 min
- **Started:** 2026-08-02
- **Completed:** 2026-08-02
- **Tasks:** 2 (Task 1's `checkpoint:decision` was pre-approved before this execution began — not re-opened)
- **Files modified:** 5 (1 created)

## Accomplishments

- `worker_gpu/preprocess/loop_cache.py` implemented: key-layout helpers, `cache_is_present`, `build_loop_cache(store, loop_id, prepare)`, `load_loop_cache(store, loop_id, dest_dir)` — fully CPU-provable, zero torch import at module scope.
- `worker_gpu/stages.py::loop_cache_stage(loop_id)` added: resolves the engine and checks idempotency before ever touching `gpu_lock`, so a no-op never blocks a waiting render; skips loudly (not a crash) when the resident engine has no `prepare_loop_cache` seam — true today, true under `DEV_ENGINES=1`.
- `worker_cpu/stages.py::loop_preprocess_stage` now chains the GPU cache build from both of its non-error exits: the success tail, and — closing a real gap — the `ping_pong` idempotent early return, guarded so a loop with a live cache or a recorded error never re-triggers a build.
- `tests/conftest.py::fake_gpu_redis` added: an in-memory stand-in for the three redis ops `gpu_lock` uses, letting the genuine locking code run unmodified on this Mac (no `redis-server`).
- `tests/test_loop_cache.py`: 21 tests covering all 17 behaviours the plan specified plus 4 extras (key-layout assertion, DEV_ENGINES-style no-preparer skip, and a couple of consolidations where one test proves two adjacent behaviours).

## Task Commits

Task 1 (`checkpoint:decision`) was pre-approved outside this execution session and is not re-committed here.

1. **Task 2: End-to-end "a preprocessed loop gets a persisted cache" — one path only** — `bacb837` (feat)
2. **Task 3: Invalidation, the ping-pong exit, and the download-side round trip** — `3b016ad` (feat)

_Note: both tasks were tdd="true"; tests and implementation were written together per task and verified green before each commit (12 tests in Task 2, 9 more in Task 3), rather than as separate RED/GREEN commits — the objective for this session specified one atomic commit per task._

## Files Created/Modified

- `worker_gpu/preprocess/loop_cache.py` - implemented module: key helpers, `cache_is_present`, `build_loop_cache`, `load_loop_cache`, full docstring including the invalidation story
- `worker_gpu/stages.py` - added `loop_cache_stage(loop_id)`, imported `loop_cache` and `BaseLoop`
- `worker_cpu/stages.py` - added `LOOP_CACHE_STAGE` constant and `_chain_loop_cache` helper; wired at both non-error exits of `loop_preprocess_stage`
- `tests/conftest.py` - added `fake_gpu_redis` fixture
- `tests/test_loop_cache.py` - new, 21 tests

## Decisions Made

**Task 1's checkpoint:decision (pre-approved before this session, not re-opened):** option-a — `latents_uri` points at a single file (`loops/{id}/cache/latents.pt`); `bbox_uri` points at a prefix (`loops/{id}/cache/bbox`) holding `coords.pkl` (required) and `mask_coords.pkl` (optional). No Alembic migration, no `python packages/schema/export_ts.py` regen — this phase stays worker-only code, matching the existing `loops/{loop_id}/pingpong.mp4` key convention. Verified against the live `BaseLoopBase` schema during this session: exactly two URI columns (`latents_uri`, `bbox_uri`), no third column exists or was added. The prefix-vs-file asymmetry — the one real cost of option-a — is documented directly on `bbox_prefix`'s docstring: *"Unlike latents_key, this names a PREFIX holding multiple members... not a single object — a reader of the schema should not assume bbox_uri resolves with `store.exists()` the way latents_uri does."*

**The `prepare` callable's locked signature** (what plan 02-03 must satisfy): `prepare(source_path: Path, out_dir: Path) -> None`. Writes MuseTalk's own filenames (`latents.pt`, `coords.pkl`, optionally `mask_coords.pkl`) into `out_dir`, which is guaranteed empty on entry and reclaimed by the caller on return regardless of success or failure. Obtained by `loop_cache_stage` via `getattr(lipsync_engine, "prepare_loop_cache", None)` — an attribute lookup, not a required interface method, so `DevLipsyncEngine` (no such attribute) and any engine that doesn't yet implement it degrade to a loud warning-and-skip rather than an `AttributeError`.

**Ping-pong invalidation guard implementation choice:** used a lightweight `loop.latents_uri is None` column check at the CPU-side dispatch site, rather than importing `worker_gpu.preprocess.loop_cache.cache_is_present` across the worker_cpu → worker_gpu package boundary. `loop_cache_stage`'s own `cache_is_present` call is the authoritative idempotency check (it re-verifies the object actually exists in the store); the CPU-side guard only needs to avoid an obviously-redundant enqueue, not be the source of truth. This keeps `worker_cpu` decoupled from `worker_gpu`'s internal key layout.

## Deviations from Plan

None — plan executed exactly as written, including both approval conditions from Task 1's decision (bbox asymmetry documented on `bbox_prefix`'s docstring; the option-a decision and its rationale recorded here).

## Issues Encountered

None. Every test passed on first implementation; no auto-fixes, no blockers, no auth gates.

## Ping-Pong / Invalidation Interaction (for the next session, so it isn't re-derived)

- `PUT /loops/{id}` already blanket-nulls `latents_uri`/`bbox_uri` for free (via `BaseLoopCreate`'s defaults) — no new mechanism needed for that path, confirmed unchanged (`git diff --stat api/routes/loops.py` is empty).
- `ping_pong` and `error` live on `BaseLoop` (the table class), not on `BaseLoopBase` — so a PUT nulls the cache columns but leaves `ping_pong` true. This is exactly why the ping-pong idempotent early return in `loop_preprocess_stage` needed its own chain call, not just the success tail.
- The chain lives exclusively inside `loop_preprocess_stage` (worker-side), never in a route handler — both `POST /loops` and `POST /loops/{id}/preprocess` funnel through it, so a manual rerun after a source swap gets a cache rebuild for free, and the build always runs against the loop's FINAL post-ping-pong `source_uri`/`frame_count`.
- `cache_is_present` re-checks the store's actual object presence on every call, not just the column — a deleted blob behind a stale `latents_uri` reads as a miss and the next build call rebuilds it. Proven in `test_cache_is_present_false_when_object_deleted_then_rebuilds`.
- Full invalidation narrative is now written once, in `worker_gpu/preprocess/loop_cache.py`'s module docstring, rather than needing to be reassembled from three files and a route.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `build_loop_cache` has a live dispatch chain and is proven end-to-end on CPU with a fake preparer; the only unimplemented part of the path is the `prepare` callable itself.
- Plan 02-03 (on the RTX 3090 host) must implement `MuseTalkEngine.prepare_loop_cache(source_path, out_dir)` satisfying the locked signature above, and re-check Phase 1 Contingent Assumptions P1-A through P1-D (still open — Phase 1 plans 01-04/01-05 and the torch/mmlab decision had not landed as of this session) before wiring it in.
- Plan 02-02 can reuse `tests/conftest.py::fake_gpu_redis` directly for `lipsync_stage` coverage — it drives the real `gpu_lock` unmodified.
- `scripts/bench.py`'s `Metric.ref` mismatch (RESEARCH.md Pitfall 1) is still unfixed — REQ-loop-preprocessing's stated `bench.py --loop <id>` acceptance command remains unmeasurable until a later plan fixes it. Not in scope for 02-01; flagging so it isn't lost.

---
*Phase: 02-latent-cache*
*Completed: 2026-08-02*
