---
phase: 01-render-engines-live
plan: 05
subsystem: gpu-render-lane
tags: [lipsync, frame-continuity, chunking, muse-talk, base-loop, cpu-verifiable]

# Dependency graph
requires:
  - phase: 01-render-engines-live (plan 01-03)
    provides: MuseTalkEngine.sync_chunk / DevLipsyncEngine.sync_chunk shared call contract (real engine body still NotImplementedError, blocked on plan 01-01 Task 4's torch/mmlab decision)
  - phase: 01-render-engines-live (plan 01-04)
    provides: bench.py --smoke render path and honest VRAM measurement (workstation-blocked, unrelated to this task's arithmetic)
provides:
  - "loop_frame_offset(start_ms, fps, frame_count) in worker_gpu/engines/audio.py — the single pure function that decides which base-loop frame a chunk starts rendering from, pinned by CPU tests"
affects: [MuseTalkEngine.sync_chunk wiring (deferred to workstation session), Task 2's seam-check verification, Task 3's milestone record]

# Actuals (#2632)
actuals:
  tokens: 2453
  tasks: 1
  commits: 1

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "loop_frame_offset recomputes the frame position fresh from the absolute start_ms every call (round(start_ms * fps / 1000) % frame_count) rather than accumulating per-chunk deltas, so there is no linear drift to bound — verified directly rather than assumed"

key-files:
  created: []
  modified:
    - worker_gpu/engines/audio.py
    - tests/test_render_engines.py

key-decisions:
  - "Task 1 only was executed in this session, per explicit orchestrator scope boundary; Tasks 2 (workstation checkpoint) and 3 (milestone/doc closure) were not attempted"
  - "MuseTalkEngine.sync_chunk wiring deferred: 01-03 left sync_chunk as a bare `raise NotImplementedError(\"M3\")` with no existing-chunk-key early return and no prepared-loop memo — the surrounding orchestration the plan's <action> assumed already existed. Wiring loop_frame_offset into it now would mean writing that orchestration for the first time (engine implementation), not wiring an offset into existing code. Per the scope boundary's explicit fallback, only the pure function and its tests were implemented; the wiring is recorded here as deferred work for the workstation session, alongside plan Tests 5-6 (existing-chunk skip, prepared-loop memo reuse), which describe sync_chunk behavior and could not be written without first building that orchestration"
  - "chunking.py and dev.py left completely untouched, as both the plan's <action> and the acceptance criteria require"

patterns-established:
  - "A frame-offset function pinned by an executed (not merely asserted) mutation experiment: Test 2's chaining assertion was manually broken with a constant-0 substitute, run, observed to fail, then the substitute was discarded and the original restored before committing"

requirements-completed: []  # REQ-gpu-worker's real render-lane behavior is only satisfied once sync_chunk wiring (deferred) and Task 2's workstation render exist

coverage:
  - id: D1
    description: "loop_frame_offset(0, fps, frame_count) == 0, and a start beyond one full loop wraps modulo frame_count"
    verification:
      - kind: unit
        ref: "tests/test_render_engines.py::test_loop_frame_offset_starts_at_zero_and_wraps_modulo_frame_count"
        status: pass
      - kind: integration
        ref: "python -c \"from worker_gpu.engines.audio import loop_frame_offset; assert loop_frame_offset(0,25.0,250)==0; assert loop_frame_offset(10000,25.0,250)==0; assert loop_frame_offset(4000,25.0,250)==100\" — exit 0"
        status: pass
    human_judgment: false
  - id: D2
    description: "Offsets chain across contiguous chunk_windows() boundaries: offset(window N+1) == (offset(window N) + frames rendered in window N) % frame_count — the seam-free property"
    verification:
      - kind: unit
        ref: "tests/test_render_engines.py::test_loop_frame_offset_chains_across_contiguous_windows"
        status: pass
      - kind: manual-experiment
        ref: "loop_frame_offset temporarily replaced with a constant-0 function; test_loop_frame_offset_chains_across_contiguous_windows run and observed to fail (assert 0 == 100 at start=74000); original implementation then restored from backup and re-verified green"
        status: pass
    human_judgment: false
  - id: D3
    description: "Non-integer frame-count windows (100ms at 24fps = 2.4 frames) do not drift: offset stays within one frame of the exact unrounded modular value across 10 consecutive windows"
    verification:
      - kind: unit
        ref: "tests/test_render_engines.py::test_loop_frame_offset_bounds_drift_for_non_integer_frame_windows"
        status: pass
    human_judgment: false
  - id: D4
    description: "chunk_windows() output durations sum exactly to the total span, and loop_frame_offset produces a well-formed in-range offset for every resulting window"
    verification:
      - kind: unit
        ref: "tests/test_render_engines.py::test_chunk_window_durations_sum_exactly_to_total_span"
        status: pass
    human_judgment: false
  - id: D5
    description: "packages/pipeline_core/chunking.py and worker_gpu/engines/dev.py are untouched by this task"
    verification:
      - kind: unit
        ref: "git diff --stat packages/pipeline_core/chunking.py worker_gpu/engines/dev.py — empty"
        status: pass
    human_judgment: false
  - id: D6
    description: "MuseTalkEngine.sync_chunk requests loop frames from loop_frame_offset and reuses a prepared-loop memo across windows; a chunk whose key already exists is skipped on re-render (plan Tests 5-6)"
    verification: []
    human_judgment: true
    rationale: "sync_chunk is still the bare NotImplementedError stub 01-03 left it as, with no existing-chunk-key check or prepared-loop memo to wire the offset into yet. Writing that orchestration now would be engine implementation, which is out of scope per the scope boundary and blocked on plan 01-01 Task 4's torch/mmlab decision. Deferred to the workstation session alongside Task 2."

# Metrics
duration: 25min
completed: 2026-08-02
status: partial
---

# Phase 1 Plan 5: Make consecutive chunks frame-continuous across the base loop (Task 1 of 3 — PARTIAL)

**`loop_frame_offset(start_ms, fps, frame_count)` added to `worker_gpu/engines/audio.py` — a pure, modular function pinning the base-loop frame a lip-sync chunk starts rendering from, so chunk N+1 can resume where chunk N ended instead of restarting the loop at frame 0. Pinned by four CPU tests (exact values, chaining across `chunk_windows()`, bounded non-integer drift, duration-sum coverage) plus an executed constant-0 mutation experiment. Wiring into `MuseTalkEngine.sync_chunk` is deferred — the stub has no existing orchestration to wire into yet.**

## Scope of this summary

This plan has three tasks. **Only Task 1 was executed in this session**, by explicit
orchestrator instruction. Task 2 (`checkpoint:human-verify`, the first unattended
end-to-end render on the RTX 3090) and Task 3 (ticking M3.4 and closing the phase
record) are untouched and remain blocked on workstation hardware this session does not
have.

**No milestone box was ticked.** `docs/milestones.md`, `docs/workstation.md`,
`.planning/ROADMAP.md`, and `.planning/STATE.md` were not modified.

## Performance

- **Duration:** ~25 min
- **Started:** 2026-08-02 (session start)
- **Completed:** 2026-08-02
- **Tasks:** 1 of 3 (Task 1 only, per scope boundary)
- **Files modified:** 2 (`worker_gpu/engines/audio.py`, `tests/test_render_engines.py`)

## Accomplishments

- Added `loop_frame_offset(start_ms, fps, frame_count)` to `worker_gpu/engines/audio.py`:
  `round(start_ms * fps / 1000) % frame_count`. Pure function of its three arguments,
  rounds rather than truncates, and is recomputed fresh from the absolute `start_ms` on
  every call rather than accumulated step by step — the reason there is no linear drift
  to bound.
- Added four tests to `tests/test_render_engines.py` covering the plan's Tests 1-4:
  - `test_loop_frame_offset_starts_at_zero_and_wraps_modulo_frame_count` — the exact
    values from the plan's own acceptance criterion, plus a beyond-one-loop wrap case.
  - `test_loop_frame_offset_chains_across_contiguous_windows` — the chaining property
    over `chunk_windows([37_000] * 7)` with `fps=25.0, frame_count=250` chosen so
    frames-per-window (925 or 1850) is never a multiple of `frame_count`, making the
    assertion actually distinguish real modular arithmetic from a constant-0 stub.
  - `test_loop_frame_offset_bounds_drift_for_non_integer_frame_windows` — 10 consecutive
    100ms windows at 24fps (2.4 frames/window, non-integer) stay within 1 frame of the
    exact unrounded modular value at every step.
  - `test_chunk_window_durations_sum_exactly_to_total_span` — builds on (does not
    duplicate) `test_chunking.py`'s own duration-sum coverage, and additionally checks
    `loop_frame_offset` produces a well-formed in-range offset for every resulting
    window.
- Added a fifth test, `test_loop_frame_offset_chaining_fails_under_constant_zero_mutation`,
  that runs the chaining check against an explicit constant-0 substitute inline and
  asserts it fails — a permanent regression guard for the property the plan's
  acceptance criteria required a one-time manual demonstration of.
- **Ran the plan-required mutation experiment for real**, not merely asserted it would
  happen: temporarily replaced `loop_frame_offset`'s body with `return 0` in
  `worker_gpu/engines/audio.py`, ran
  `pytest tests/test_render_engines.py::test_loop_frame_offset_chains_across_contiguous_windows`,
  observed the failure (`assert 0 == 100` at `loop_frame_offset(74000, 25.0, 250)`), then
  restored the original file from a pre-mutation backup and re-ran the full test module
  green before committing.

## Task Commits

1. **Task 1: Make consecutive chunks frame-continuous across the base loop** -
   `2a22ec5` (feat)

_Tasks 2 and 3 not attempted this session — see Scope of this summary above. No plan
metadata commit was made either, since the plan as a whole is not complete._

## Acceptance Criteria Results (Task 1, observed on this Mac)

| Criterion | Result |
|---|---|
| `pytest tests/test_render_engines.py -x` passes with all six behaviours; Tests 1-4 assert exact arithmetic | **Modified**: Tests 1-4 pass exactly as specified. Tests 5-6 (sync_chunk existing-chunk skip, prepared-loop memo reuse) are deferred — see "Deviations from Plan" below — 28/28 tests in the module pass, including the 5 new ones added |
| `python -c "from worker_gpu.engines.audio import loop_frame_offset; assert loop_frame_offset(0,25.0,250)==0; assert loop_frame_offset(10000,25.0,250)==0; assert loop_frame_offset(4000,25.0,250)==100"` exits 0 | PASS |
| Test 2's chaining assertion fails if `loop_frame_offset` is replaced by a constant 0 — verified by trying it, then restored | PASS — executed, observed `assert 0 == 100` failure, restored, re-verified green |
| `git diff --stat packages/pipeline_core/chunking.py` shows no changes | PASS (empty) |
| `git diff --stat worker_gpu/engines/dev.py` shows no changes | PASS (empty) |
| `pytest tests/test_chunking.py tests/test_dev_engines.py tests/test_pipeline_flow.py tests/test_portability.py -x` stays green | PASS (20 passed, 4 skipped) |
| `pytest -x` (full suite) passes on the Mac | PASS (547 passed, 14 skipped) |

Additional gate run per this session's `<constraints>` (not part of Task 1's own
acceptance criteria, but required before committing): `cd web && npm test && npm run
build` — both green (21/21 tests, `tsc --noEmit && vite build` clean).

## Files Created/Modified

- `worker_gpu/engines/audio.py` — added `loop_frame_offset(start_ms, fps, frame_count)`
- `tests/test_render_engines.py` — 5 new CPU-only tests for the frame-offset arithmetic,
  plus the `chunk_windows` import needed to build them on real window boundaries

## Decisions Made

- **Task 1 only, per scope boundary.** Tasks 2 and 3 were not attempted this session.
- **Deferred `MuseTalkEngine.sync_chunk` wiring (Rule 4-adjacent — architectural gap, not
  auto-fixed).** The plan's `<action>` says "Everything else in the method stays as plan
  01-03 left it — the early return on an existing chunk key, the window audio
  reconstruction, the in-memory prepared-loop memo, the video-only output, and the exact
  chunk key," implying that orchestration already exists in `sync_chunk`. It does not:
  `worker_gpu/engines/lipsync.py::MuseTalkEngine.sync_chunk` is still the bare
  `raise NotImplementedError("M3")` 01-03 left it as (01-03-SUMMARY.md confirms
  `ChatterboxEngine`/`MuseTalkEngine` key resolution was explicitly out of scope for that
  plan, blocked on 01-01 Task 4's one-way torch/mmlab decision). Writing the
  existing-chunk-key check, the prepared-loop memo, and the offset call into `sync_chunk`
  now would mean authoring that surrounding orchestration for the first time — engine
  implementation, not offset wiring — which this session's scope boundary explicitly
  rules out ("Do not implement the engine to satisfy a wiring step"). Per that boundary's
  own fallback instruction, only the pure function and its tests (Tests 1-4) were
  implemented; plan Tests 5-6, which describe `sync_chunk` behavior, could not be written
  meaningfully against an unconditional-raise stub and are deferred alongside the wiring
  itself.
- **`worker_gpu/engines/lipsync.py` left completely untouched.** Not listed in the
  `git diff --stat` gates the way `chunking.py`/`dev.py` are, but touching it to add
  wiring against a stub that cannot exercise it would be exactly the "implement the
  engine to satisfy a wiring step" the scope boundary forbids.
- **Chose `frame_count=250`, `fps=25.0`, `spans=[37_000]*7` for the chaining test** so
  that frames-per-window (925 or 1850) is never an exact multiple of `frame_count` —
  otherwise a constant-0 stub would coincidentally satisfy the chaining assertion and the
  mutation-detection requirement would be untestable. Verified this with the actual
  mutation experiment, not just by inspection.

## Deviations from Plan

### Auto-fixed Issues

None — Rules 1-3 did not apply; the only tension found (Task 2 checkpoint's
`<precondition>` on the workstation and 01-03's actual `sync_chunk` stub state vs. the
plan's `<action>` assumption) was handled per explicit scope-boundary instructions rather
than autonomous deviation rules.

### Scope Boundary Application

**1. Deferred MuseTalkEngine.sync_chunk wiring and plan Tests 5-6**
- **Found during:** Task 1 read_first, cross-checking `worker_gpu/engines/lipsync.py`
  against the plan's `<action>` assumption that 01-03 already implemented the
  existing-chunk-key check, window audio reconstruction, and prepared-loop memo.
- **Issue:** `sync_chunk` is `raise NotImplementedError("M3")` and nothing else. There is
  no orchestration to wire `loop_frame_offset` into without writing it from scratch.
- **Resolution:** Per this session's explicit scope-boundary instruction ("If it cannot
  [be done against the existing stub], implement the pure function and its tests, and
  record the deferred wiring explicitly in the summary as work for the workstation
  session"), implemented only `loop_frame_offset` and Tests 1-4. Tests 5-6 and the
  `sync_chunk` wiring are recorded here as deferred to the workstation session, when
  plan 01-01 Task 4's torch/mmlab decision unblocks real engine implementation.
- **Files affected:** None beyond what was already committed — `lipsync.py` remains
  byte-identical to its pre-plan state.

---

**Total deviations:** 0 auto-fixed. 1 scope-boundary application (deferred wiring,
explicitly authorized rather than an unplanned discovery).
**Impact on plan:** Task 1's CPU-verifiable arithmetic half is complete and correct. The
seam-avoidance behavior itself (loop frames actually driving MuseTalk output) cannot
exist until the engine is implemented on the workstation — this was already true before
this session started, given 01-03's scope.

## Known Stubs

- **`worker_gpu/engines/lipsync.py::MuseTalkEngine.sync_chunk`** — still
  `raise NotImplementedError("M3")`. Not created or modified by this task; pre-existing
  from plan 01-03. Will be resolved when plan 01-01 Task 4's torch/mmlab decision is made
  and the workstation session implements the real engine, wiring `loop_frame_offset` in
  at that point.

## Issues Encountered

None beyond the plan-vs-codebase discrepancy documented above (handled per explicit
scope-boundary instruction, not as an ad hoc deviation).

## User Setup Required

None for Task 1. Task 2 requires the RTX 3090 workstation with the full stack running
(API, CPU worker, GPU worker, Postgres, Redis, MinIO) per `docs/workstation.md`, exactly
as its `<precondition>` states.

## Next Phase Readiness

**Blocked — not ready to proceed to Task 2 or Task 3 in this session.** Task 2
(`checkpoint:human-verify`) needs the RTX 3090 workstation this session does not have,
and additionally now needs `MuseTalkEngine.sync_chunk` actually implemented — including
the `loop_frame_offset` wiring deferred here — before a real multi-chunk render can be
attempted. That implementation work depends on plan 01-01 Task 4's torch/mmlab decision,
which is outside this plan's scope entirely.

What this session hands forward:
- `loop_frame_offset(start_ms, fps, frame_count)`, ready to be called directly from
  `sync_chunk` once that method has real inference logic to call it around.
- Four tests pinning its exact behavior (values, chaining, drift bound, duration-sum
  well-formedness), so a future implementer gets an immediate CPU-only regression signal
  if the wiring gets the arithmetic wrong.
- A documented, precise account of exactly what's missing in `sync_chunk` (no
  existing-chunk-key check, no prepared-loop memo) so the workstation session does not
  have to rediscover this from scratch.

---
*Phase: 01-render-engines-live*
*Plan: 05 (Task 1 of 3 — PARTIAL)*
*Completed: 2026-08-02*
