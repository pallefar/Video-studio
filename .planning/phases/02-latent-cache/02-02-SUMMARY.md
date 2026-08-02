---
phase: 02-latent-cache
plan: 02
subsystem: infra
tags: [metrics, sqlmodel, bench, observability, pytest]

# Dependency graph
requires:
  - phase: 02-latent-cache
    provides: "plan 02-01's fake_gpu_redis fixture (tests/conftest.py), reused unmodified for driving lipsync_stage's real gpu_lock code path on this CUDA-less, redis-server-less Mac"
provides:
  - "pipeline_core.metrics::LIPSYNC_STAGE, lipsync_metric_ref(job_id, loop_id), lipsync_ref_suffix(loop_id) — the one shared definition of the lipsync metric ref format, consumed by both the writer (worker_gpu.stages.lipsync_stage) and the reader (scripts/bench.py::bench_loop)"
  - "worker_gpu.stages.lipsync_stage recording its own scoped timed() span (idempotent skip outside the span, failure path still inside it) instead of the blanket @timed_stage decorator"
  - "scripts/bench.py::bench_loop matching by ref suffix instead of substring, so it can actually find rows for a loop, and refuses pre-fix or other-loop rows"
  - "tests/test_bench_loop.py — 14-behaviour regression harness covering both halves of the ref contract in one file"
affects: [02-03]

# Actuals (#2632)
actuals:
  tokens: 5360
  tasks: 2
  commits: 2

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "writer/reader ref contract expressed as two paired helper functions (lipsync_metric_ref / lipsync_ref_suffix) sharing one separator constant, tested for agreement by construction rather than by two hardcoded format strings — the same category of load-bearing shape as lipsync_chunk_key's relationship to the assembler's glob"
    - "scoped timed() span placed to exclude an idempotent early return while still covering the failure path, nested inside the stage's own open_session() block so the span's own metric-write session never overlaps an open outer transaction (the outer session's writes are already committed via advance_job/fail_job by the time the span's finally fires)"

key-files:
  created:
    - tests/test_bench_loop.py
  modified:
    - packages/pipeline_core/metrics.py
    - worker_gpu/stages.py
    - scripts/bench.py

key-decisions:
  - "Ref format: job_id + ':' + loop_id (colon separator, module constant). A UUID's canonical form never contains a colon, so a suffix match on ':' + loop_id can never collide with a job id or a different loop's ref — chosen over Pitfall 1's option 2 (querying RenderJob.base_loop_id first) because it works whether the operator re-renders one job twice or renders two different jobs against the same loop, per the plan's and RESEARCH.md's explicit recommendation."
  - "The timed() span is nested INSIDE lipsync_stage's existing open_session() block, positioned after the idempotency check and job.base_loop_id lookup. This keeps the diff to one function (no double session-open, no re-fetching the job) while still satisfying both load-bearing properties the plan named: the idempotent return sits before the span ever opens (so a skip never triggers the span's own metric-write session), and by the time the span's finally fires, the outer session's writes (advance_job's or fail_job's commit) have already landed — so the span's own separate open_session() call for the metric row never contends with an open outer transaction on the shared SQLite connection."
  - "bench_loop's suffix match uses SQLAlchemy's Column.endswith() (LIKE '%<suffix>') rather than re-deriving the separator in scripts/bench.py — the helper is the single source of truth for the format, per the plan's explicit instruction not to re-derive it in the reader."

patterns-established:
  - "A writer/reader metric-ref contract lives in one module (pipeline_core.metrics) as a matched pair of functions with a shared separator constant, and is regression-tested in one file covering both halves — so a future change to either side alone breaks a test in the same file instead of silently reintroducing an unmeasurable acceptance command."

requirements-completed: [REQ-loop-preprocessing]

coverage:
  - id: D1
    description: "lipsync_stage and bench_loop share one definition of the lipsync metric ref format (LIPSYNC_STAGE, lipsync_metric_ref, lipsync_ref_suffix), agreement asserted by construction rather than by two hardcoded format strings"
    requirement: "REQ-loop-preprocessing"
    verification:
      - kind: unit
        ref: "tests/test_bench_loop.py#test_ref_and_suffix_agree_by_construction"
        status: pass
      - kind: unit
        ref: "tests/test_bench_loop.py#test_ref_suffix_no_cross_loop_collision"
        status: pass
      - kind: unit
        ref: "tests/test_bench_loop.py#test_legacy_job_only_ref_carries_no_loop_suffix"
        status: pass
    human_judgment: false
  - id: D2
    description: "A completed lipsync run records exactly one metric row whose ref names both the job and the loop; a skipped (idempotent) run records none; a failed run still records one"
    requirement: "REQ-loop-preprocessing"
    verification:
      - kind: unit
        ref: "tests/test_bench_loop.py#test_lipsync_completion_writes_one_row_with_shared_ref"
        status: pass
      - kind: unit
        ref: "tests/test_bench_loop.py#test_idempotent_skip_records_no_row"
        status: pass
      - kind: unit
        ref: "tests/test_bench_loop.py#test_failed_lipsync_still_records_row"
        status: pass
      - kind: unit
        ref: "tests/test_bench_loop.py#test_tts_stage_ref_still_bare_job_id"
        status: pass
    human_judgment: false
  - id: D3
    description: "bench_loop's --loop query actually finds rows for a loop (suffix match), computes cold/cached/speedup correctly ordered by recency (not insertion), reports pass/fail against the 40% target, and refuses to match pre-fix job-only refs, other loops' rows, or rows from unrelated stages"
    requirement: "REQ-loop-preprocessing"
    verification:
      - kind: unit
        ref: "tests/test_bench_loop.py#test_bench_loop_reports_speedup_when_cache_meets_target"
        status: pass
      - kind: unit
        ref: "tests/test_bench_loop.py#test_bench_loop_fails_loudly_when_cache_underperforms"
        status: pass
      - kind: unit
        ref: "tests/test_bench_loop.py#test_bench_loop_orders_by_recency_not_insertion"
        status: pass
      - kind: unit
        ref: "tests/test_bench_loop.py#test_bench_loop_needs_two_rows_names_count_found"
        status: pass
      - kind: unit
        ref: "tests/test_bench_loop.py#test_bench_loop_ignores_other_loops"
        status: pass
      - kind: unit
        ref: "tests/test_bench_loop.py#test_bench_loop_ignores_legacy_job_only_refs"
        status: pass
      - kind: unit
        ref: "tests/test_bench_loop.py#test_bench_loop_ignores_other_stages_with_same_ref"
        status: pass
    human_judgment: false
  - id: D4
    description: "The measured cached run is actually >= 40% faster than the cold run on real hardware"
    verification: []
    human_judgment: true
    rationale: "WORKSTATION EVIDENCE REQUIRED per this plan's own must_haves — no CUDA on this Mac. Deferred to plan 02-03 on the RTX 3090 host; this plan proves only that the command can now return a true answer, not what that answer will be."

# Metrics
duration: 25min
completed: 2026-08-02
status: complete
---

# Phase 2 Plan 02: Latent-Cache Measurement Fix Summary

**Fixed the writer/reader ref mismatch that made `python scripts/bench.py --loop <id>` — Phase 2's own stated acceptance command — permanently unable to find any row, and closed the more dangerous companion bug where an idempotent lipsync skip could be misread as a near-100%-speedup cached run.**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-08-02
- **Tasks:** 2 (both `auto`, `tdd="true"`)
- **Files modified:** 4 (1 created: `tests/test_bench_loop.py`)

## Accomplishments

- `pipeline_core.metrics` gained `LIPSYNC_STAGE`, `lipsync_metric_ref(job_id, loop_id)`, and `lipsync_ref_suffix(loop_id)` — one shared, colon-separated ref format definition consumed by both the writer and the reader, replacing three independent literals.
- `worker_gpu/stages.py::lipsync_stage` no longer uses the blanket `@timed_stage("lipsync")` decorator. It now opens an explicit `timed()` span scoped to start *after* the idempotent early return (so a duplicate delivery records nothing) and to still cover the engine-failure path (so a failed render remains visible in the metrics table). `git diff` confirms the change is confined to `lipsync_stage` and the import block — `tts_stage`, both generation stages, and `identity_training_stage` are byte-identical.
- `scripts/bench.py::bench_loop` now filters on `LIPSYNC_STAGE` and matches `Metric.ref` by suffix (`lipsync_ref_suffix(loop_id)`) instead of substring-containing the raw loop id — the exact bug that made every `--loop` run report "found 0" regardless of whether the cache worked. The 40% threshold, ordering, limit, `smoke()`, `_require_gpu()`, `VRAM_BUDGET_GB`, and the argument parser are all byte-identical (confirmed via `git diff`).
- `tests/test_bench_loop.py`: 14 behaviours in one file — 7 on the writer half (ref/suffix agreement by construction, no cross-loop collision, legacy refs never carry a loop suffix, a completed run writes exactly one correctly-refed row, a skip writes none, a failure still writes one, `tts_stage`'s ref is untouched), 7 on the reader half (pass/fail against the 40% target, recency ordering independent of insertion order, exact found-count messaging, no cross-loop leakage, no match on legacy job-only refs, other stages sharing the same ref format are ignored).

## Task Commits

1. **Task 1: Give the lipsync metric a ref that names both the job and the loop** - `9e8e9ba` (feat)
2. **Task 2: Make bench_loop query what lipsync_stage actually writes** - `3de257c` (feat)

_Note: both tasks were `tdd="true"`; tests and implementation were written together per task and verified green before each commit, following the same one-atomic-commit-per-task approach 02-01 established for this phase, rather than separate RED/GREEN commits._

## Files Created/Modified

- `packages/pipeline_core/metrics.py` — added `LIPSYNC_STAGE`, `lipsync_metric_ref`, `lipsync_ref_suffix`, and the module-level separator constant; `timed_stage`/`timed` themselves untouched
- `worker_gpu/stages.py` — `lipsync_stage` rewritten to use a scoped `timed()` span instead of the blanket decorator; every other stage function byte-identical
- `scripts/bench.py` — `bench_loop`'s query rewritten to filter by stage constant and match by ref suffix; docstrings updated; `smoke()`/`_require_gpu()`/parser untouched
- `tests/test_bench_loop.py` — new, 14 tests covering both halves of the writer/reader contract

## Decisions Made

See `key-decisions` in frontmatter: the colon-separated ref format (option 1 from RESEARCH.md Pitfall 1, chosen over the two-query alternative), the span's placement inside the existing `open_session()` block (avoids double-fetching the job while still satisfying both load-bearing structural properties), and using `Column.endswith()` rather than re-deriving the separator in `scripts/bench.py`.

## Deviations from Plan

None — plan executed exactly as written, including both structural properties Task 1 called load-bearing (idempotent return outside the span; failure path still inside it) and both interface-stability constraints Task 2 called load-bearing (`smoke()`/`_require_gpu()`/parser untouched; 40% threshold unchanged).

## Issues Encountered

None. All 14 new tests passed on first implementation; no auto-fixes, no blockers, no auth gates. Full `pytest` suite (all pre-existing tests) stayed green throughout, confirmed before each of the two commits, along with `cd web && npm test && npm run build`.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `python scripts/bench.py --loop <id>` can now return a true pass/fail answer once two lipsync runs against a loop are recorded — the mechanism plan 02-03's workstation session will actually use to measure the real speedup.
- What this plan does NOT establish: that the number printed on the RTX 3090 host will clear 40%. That is real hardware behavior, explicitly out of scope here, and is plan 02-03's job (`WORKSTATION EVIDENCE REQUIRED`, tracked as D4 above with `human_judgment: true`).
- `tests/conftest.py::fake_gpu_redis` (from 02-01) was reused directly for `lipsync_stage` coverage here, confirming it's a stable, reusable seam for driving real `gpu_lock`-guarded stages on this CUDA-less, redis-server-less Mac.

---
*Phase: 02-latent-cache*
*Completed: 2026-08-02*
