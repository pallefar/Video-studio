---
phase: 01-render-engines-live
plan: 02
subsystem: render-worker
tags: [pytest, structlog, tdd, worker_gpu, contract-test]

# Dependency graph
requires:
  - phase: 01-render-engines-live (plan 01, wave 1, parallel)
    provides: workstation dependency bring-up (Chatterbox/MuseTalk install, not consumed by this plan)
provides:
  - "worker_gpu/run.py:main() warms both engines (get_engines()) before worker.work() — M3.1 code half"
  - "tests/test_render_engines.py — CPU-only regression harness for the render engines, extended by plans 01-03/01-04"
  - "Locked contract: ChatterboxEngine/MuseTalkEngine signatures match DevTTSEngine/DevLipsyncEngine positionally"
  - "Locked contract: real engines' load() refuses without CUDA; EMOTIONS presets stay inside Chatterbox's documented ranges"
affects: [01-render-engines-live/01-03, 01-render-engines-live/01-04]

actuals:
  tokens: 2807
  tasks: 2
  commits: 3

tech-stack:
  added: []
  patterns:
    - "structlog.testing.capture_logs() to assert on boot-log event names/fields and their relative order without configuring a logging backend"
    - "inspect.signature() structural comparison (arity/order, not names) to lock an interface contract between two implementations that intentionally differ in parameter naming"

key-files:
  created:
    - tests/test_render_engines.py
  modified:
    - worker_gpu/run.py

key-decisions:
  - "Task 2 required no source changes — the real-vs-dev engine contract and the emotion-preset shape already matched; the task's job was to lock it with tests, not fix it"
  - "Faked Redis/RQ at the module attribute level (redis.Redis, rq.Queue, rq.Worker) rather than mocking worker_gpu.run's local names, matching main()'s lazy-import style (from redis import Redis resolves the patched attribute at call time)"

patterns-established:
  - "Boot-time singleton warming: entrypoint calls the shared get_engines() singleton and logs before/after events naming the resolved classes, rather than letting the singleton populate lazily on first use"

requirements-completed: [REQ-gpu-worker]

coverage:
  - id: D1
    description: "worker_gpu/run.py:main() warms both engines before worker.work() (call order asserted)"
    requirement: "REQ-gpu-worker"
    verification:
      - kind: unit
        ref: "tests/test_render_engines.py::test_main_warms_engines_before_worker_consumes_jobs"
        status: pass
      - kind: unit
        ref: "tests/test_render_engines.py::test_main_boot_log_names_the_warmed_engine_classes"
        status: pass
    human_judgment: false
  - id: D2
    description: "A boot-time model-load failure stops the worker rather than starting it in a job-failing state"
    requirement: "REQ-gpu-worker"
    verification:
      - kind: unit
        ref: "tests/test_render_engines.py::test_main_propagates_engine_load_failure_and_never_starts_worker"
        status: pass
    human_judgment: false
  - id: D3
    description: "get_engines() is called exactly once during boot (no duplicate model load)"
    requirement: "REQ-gpu-worker"
    verification:
      - kind: unit
        ref: "tests/test_render_engines.py::test_main_calls_get_engines_exactly_once_during_boot"
        status: pass
    human_judgment: false
  - id: D4
    description: "ChatterboxEngine/MuseTalkEngine method signatures match DevTTSEngine/DevLipsyncEngine positionally (structural, not name-based)"
    requirement: "REQ-gpu-worker"
    verification:
      - kind: unit
        ref: "tests/test_render_engines.py::test_chatterbox_and_dev_tts_synthesize_segment_share_a_call_contract"
        status: pass
      - kind: unit
        ref: "tests/test_render_engines.py::test_musetalk_and_dev_lipsync_sync_chunk_share_a_call_contract"
        status: pass
    human_judgment: false
  - id: D5
    description: "Real engines' load() raises rather than returns without CUDA (dev mode stays strictly opt-in)"
    requirement: "REQ-gpu-worker"
    verification:
      - kind: unit
        ref: "tests/test_render_engines.py::test_real_engine_load_refuses_without_cuda"
        status: pass
    human_judgment: false
  - id: D6
    description: "Every EMOTIONS preset carries exactly Chatterbox's two keys, within its documented ranges — no translation layer needed"
    requirement: "REQ-gpu-worker"
    verification:
      - kind: unit
        ref: "tests/test_render_engines.py::test_emotion_presets_carry_exactly_chatterbox_two_keys_in_range"
        status: pass
    human_judgment: false
  - id: D7
    description: "Both real engines construct from an ObjectStore alone and expose load(), matching get_engines()'s uniform construction"
    requirement: "REQ-gpu-worker"
    verification:
      - kind: unit
        ref: "tests/test_render_engines.py::test_real_engine_constructs_from_store_alone_and_exposes_load"
        status: pass
    human_judgment: false

duration: 16min
completed: 2026-08-02
status: complete
---

# Phase 1 Plan 2: Boot-Time Engine Warming and Interface Contract Summary

**`worker_gpu/run.py` now warms both render engines before consuming jobs, and `tests/test_render_engines.py` locks the real-vs-dev engine interface contract with 11 CUDA-free tests.**

## Performance

- **Duration:** 16 min
- **Started:** 2026-08-02T07:07Z (approx, first read)
- **Completed:** 2026-08-02T07:23:14Z
- **Tasks:** 2/2 completed
- **Files modified:** 2 (`worker_gpu/run.py`, `tests/test_render_engines.py`)

## Accomplishments

- `worker_gpu/run.py:main()` now imports and calls `get_engines()` (from `worker_gpu.stages`) before `worker.work()`, closing the M3.1 boot-warming gap RESEARCH.md's Pitfall 2 identified — the first real job no longer pays model-load latency inline, and a load failure now stops the worker instead of silently starting a job-failing process.
- Two structured boot-log events (`gpu_worker_warming_start` / `gpu_worker_warming_done`) bracket the warming call and name the resolved engine classes, so a boot transcript proves both models are resident.
- New `tests/test_render_engines.py` (11 tests) is the phase's CPU-only regression harness: 4 tests lock the boot-warming behavior (call order, log content, failure propagation, exactly-once call), 7 tests lock the real-vs-dev engine interface contract (signature arity/order via `inspect.signature`, CUDA-guard refusal, emotion-preset shape/range, uniform `ObjectStore`-only construction).
- Confirmed live (per the plan's acceptance criteria) that reverting the `get_engines()` call in `run.py` makes the new test suite fail, then restored it — the regression guard actually guards.

## Task Commits

Each task was committed atomically (TDD RED → GREEN for Task 1; test-only for Task 2):

1. **Task 1: Warm both models at boot in worker_gpu/run.py**
   - `1c866d3` test(01-02): add failing tests for boot-time engine warming (RED)
   - `2f16cab` feat(01-02): warm both engines at boot in worker_gpu/run.py (GREEN)
2. **Task 2: Lock the engine interface contract with a CUDA-free test**
   - `c93e52a` test(01-02): lock the real-vs-dev engine interface contract

_Note: Task 2 required no source changes — the contract it locks already held in the existing code, so it has a single commit rather than a RED/GREEN pair (see Decisions)._

## Files Created/Modified

- `tests/test_render_engines.py` - New CPU-only regression harness: boot-warming tests (Task 1) + engine interface/emotion contract tests (Task 2). 11 tests total.
- `worker_gpu/run.py` - `main()` now calls `get_engines()` before `worker.work()`, with structured before/after boot-log events naming the loaded engine classes.

## Decisions Made

- **Task 2 is test-only, no RED phase needed for its own commit**: unlike Task 1 (new behavior in `run.py`), Task 2's five contract behaviors (signature parity, CUDA guard, emotion-preset shape, uniform construction) were already true of the existing `ChatterboxEngine`/`MuseTalkEngine`/`DevTTSEngine`/`DevLipsyncEngine`/`EMOTIONS` code. Writing these tests against unmodified code is the correct outcome per the plan ("A signature drift... fails a CPU test, not a 3090 render" — the guard, not a fix, is the deliverable). All 7 Task 2 tests passed on first run; no fail-fast RED violation applies because no new behavior was being introduced.
- **Faked `redis.Redis`/`rq.Queue`/`rq.Worker` at module-attribute level**: `main()` does `from redis import Redis` / `from rq import Queue, Worker` as lazy imports inside the function body (matching the file's existing style). Patching `redis.Redis` / `rq.Worker` / `rq.Queue` directly (rather than `worker_gpu.run.Redis` etc., which don't exist as module-level names) is what the lazy `from X import Y` resolves against at call time.
- **`capture_logs()` over `caplog`**: this codebase never calls `structlog.configure()`, so structlog's default `PrintLogger` backend does not route through stdlib `logging` and would not be visible to pytest's `caplog` fixture. `structlog.testing.capture_logs()` captures regardless of configuration and was used to assert both event names and their relative order (`warm_start < warm_done < work_reached`).

## Deviations from Plan

None - plan executed exactly as written. Both tasks' acceptance criteria were verified explicitly:
- Task 1: call-order test, boot-log content test, failure-propagation test, exactly-once test all pass; `get_engines()` textually precedes `worker.work()` in `run.py`; removing the call was confirmed to break the new tests (then restored); `tests/test_dev_engines.py`, `tests/test_queue_topology.py`, `tests/test_pipeline_flow.py`, `tests/test_portability.py` all stay green.
- Task 2: all 5 contract behaviors covered; `grep -c 'inspect.signature'` reports 3 (≥1 required); `grep -c 'is_available'` reports 0 (required, after rewording a docstring reference that would otherwise have tripped the check); a scratch REPL check confirmed a synthetic third EMOTIONS key trips the assertion; `tests/test_dev_engines.py`, `tests/test_emotions.py` stay green; full `pytest` and `cd web && npm test && npm run build` are green.

## Issues Encountered

- Task 2's `test_real_engine_load_refuses_without_cuda` docstring initially referenced `torch.cuda.is_available` by name to explain what NOT to monkeypatch — this accidentally tripped the plan's own `grep -c 'is_available' tests/test_render_engines.py` acceptance check (which must report 0). Reworded the docstring to describe the same constraint without the literal string; re-verified the grep count is 0 and all tests still pass.

## User Setup Required

None - no external service configuration required. This plan is entirely CPU-provable; no CUDA, weights, or workstation access needed.

## Next Phase Readiness

- `worker_gpu/run.py`'s boot path and `tests/test_render_engines.py`'s CPU-only harness are ready for plan 01-03's tracer (real Chatterbox/MuseTalk implementation) to build against an already-guarded contract and an already-correct boot sequence.
- The GPU-host confirmation that boot warming actually loads real weights (not just the dev-engine stand-ins used here) remains gated in plan 01-03 Task 4, as designed — this plan's acceptance is strictly the CPU-provable half.
- `tests/test_render_engines.py` test names are recorded above (coverage IDs D1-D7 map to the 7 contract tests; D1-D3 map to the 4 boot-warming tests) so plans 01-03 and 01-04, which extend this module, do not duplicate or contradict them.

---
*Phase: 01-render-engines-live*
*Completed: 2026-08-02*
