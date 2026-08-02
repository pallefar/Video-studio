---
phase: 01-render-engines-live
plan: 04
subsystem: gpu-render-lane
tags: [bench, vram-measurement, chatterbox, musetalk, cuda, nvidia-smi, cli]

# Dependency graph
requires:
  - phase: 01-render-engines-live (plan 01-03)
    provides: ChatterboxEngine.synthesize_segment / MuseTalkEngine.sync_chunk public method signatures (still NotImplementedError bodies, blocked on plan 01-01 Task 4's torch/mmlab decision)
provides:
  - "bench.py --smoke rewritten to drive the real engine public methods and measure honest device-level VRAM, verified end-to-end on CPU (CUDA-refusal path only — this plan does not, and cannot, prove the render path itself)"
affects: [workstation smoke run (Task 2), milestone recording (Task 3), Phase 3 Wan VRAM sizing]

# Actuals (#2632)
actuals:
  tokens: 4257
  tasks: 1
  commits: 1

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "bench.py resolves render-input DB entities (VoiceProfile/BaseLoop) before any model load, so a misconfigured host fails in ~2s instead of after a multi-GB load"
    - "ephemeral bench RenderJob/Segment rows are cleaned up in a finally block, on both success and failure"
    - "VRAM measurement reports three figures (torch allocated peak, torch reserved peak, nvidia-smi device-level used) and labels which one the budget was judged against, falling back to torch reserved peak when nvidia-smi is unavailable"

key-files:
  created: []
  modified:
    - scripts/bench.py
    - tests/test_render_engines.py

key-decisions:
  - "Task 1 only was executed in this session (CPU-verifiable half); Tasks 2 and 3 are deliberately deferred — they need the RTX 3090 workstation and consume Task 2's measurements, which do not exist yet"
  - "Fixed _require_gpu()'s ImportError branch message to say \"CUDA device\" (was \"requires the GPU host\", no CUDA substring) so the no-torch-installed path on this Mac matches the plan's stated acceptance text and the CUDA-not-available branch's wording — Rule 1 auto-fix, not a plan deviation in behavior"
  - "No milestone boxes were ticked. docs/milestones.md, docs/workstation.md, docs/pipeline-spec.md, .planning/ROADMAP.md were NOT touched — those are Task 3's job and depend on Task 2's measured numbers"

patterns-established:
  - "Smoke-test scripts that must run on a CUDA-less dev machine call the cheap CUDA guard first, before any DB or storage I/O, so the guard's exit code and message are reachable without live services"

requirements-completed: []  # REQ-gpu-environment / REQ-gpu-worker are only satisfied by Task 2's workstation run; Task 1 alone does not complete them

coverage:
  - id: D1
    description: "bench.py --smoke rewritten to render through ChatterboxEngine.synthesize_segment and MuseTalkEngine.sync_chunk (the real public methods), with the dead 'blocked on engine implementation' catch removed"
    verification:
      - kind: unit
        ref: "grep -c 'blocked on engine implementation' scripts/bench.py == 0; grep -c 'synthesize_segment' scripts/bench.py >= 1; grep -c 'sync_chunk' scripts/bench.py >= 1"
        status: pass
    human_judgment: false
  - id: D2
    description: "VRAM measurement reports torch allocated peak, torch reserved peak, and nvidia-smi device-level figure, judging the 20 GB budget against the device-level figure with a labelled fallback to torch reserved peak"
    verification:
      - kind: unit
        ref: "grep -c 'nvidia-smi' scripts/bench.py >= 1; grep -c 'max_memory_reserved' scripts/bench.py >= 1"
        status: pass
    human_judgment: false
  - id: D3
    description: "bench.py --smoke on the Mac (no CUDA) exits 1 with a CUDA-device message and no traceback; bench.py with no flag exits non-zero"
    verification:
      - kind: unit
        ref: "tests/test_render_engines.py::test_smoke_exits_1_with_cuda_message_and_no_traceback_when_gpu_absent"
        status: pass
      - kind: integration
        ref: "python scripts/bench.py --smoke (subprocess, exit 1, 'CUDA' in stderr, no 'Traceback'); python scripts/bench.py (subprocess, exit != 0)"
        status: pass
    human_judgment: false
  - id: D4
    description: "New --voice/--base-loop CLI flags parse alongside --smoke without colliding with --loop's existing parser entry; --smoke and --loop remain mutually exclusive and one is required"
    verification:
      - kind: unit
        ref: "tests/test_render_engines.py::test_bench_cli_requires_exactly_one_of_smoke_or_loop, ::test_bench_cli_rejects_both_smoke_and_loop, ::test_bench_cli_voice_and_base_loop_parse_alongside_smoke, ::test_bench_cli_base_loop_flag_does_not_collide_with_loop_flag"
        status: pass
    human_judgment: false
  - id: D5
    description: "The render path itself (real 10s Chatterbox clip, real 5s MuseTalk lip-sync, honest peak VRAM under 20 GB, worker boot with warmed models) is executed and confirmed genuine (voice-cloned, lip-synced) on the RTX 3090"
    verification: []
    human_judgment: true
    rationale: "Requires CUDA hardware absent from this Mac; this is exactly Task 2 (checkpoint:human-verify), explicitly out of scope for this session and not attempted here"

# Metrics
duration: 35min
completed: 2026-08-02
status: partial
---

# Phase 1 Plan 4: Make bench.py --smoke actually render, and measure VRAM honestly (Task 1 of 3 — PARTIAL)

**bench.py --smoke rewritten to drive ChatterboxEngine.synthesize_segment / MuseTalkEngine.sync_chunk against an ephemeral RenderJob and report three VRAM figures (torch allocated, torch reserved, nvidia-smi device-level), judging the 20 GB budget against the device figure — CPU-verified only; the render path itself is unexercised until the RTX 3090 workstation session.**

## Scope of this summary

This plan has three tasks. **Only Task 1 was executed in this session**, by explicit
orchestrator instruction. Task 2 (`checkpoint:human-verify`, running the smoke on the
RTX 3090) and Task 3 (recording measured numbers and ticking milestone boxes) are
untouched and remain blocked on workstation hardware this session does not have.

**No milestone box was ticked.** `docs/milestones.md`, `docs/workstation.md`,
`docs/pipeline-spec.md`, and `.planning/ROADMAP.md` were not modified — Task 3 owns
those edits and needs Task 2's measured numbers, which do not exist yet.

## Performance

- **Duration:** ~35 min
- **Started:** 2026-08-02 (session start)
- **Completed:** 2026-08-02
- **Tasks:** 1 of 3 (Task 1 only, per scope boundary)
- **Files modified:** 2 (`scripts/bench.py`, `tests/test_render_engines.py`)

## Accomplishments

- `smoke()` in `scripts/bench.py` now resolves `--voice` / `--base-loop` render inputs
  (defaulting to the most recently created `VoiceProfile` / `BaseLoop`) before loading
  any model, creates an ephemeral `RenderJob` + `Segment` via
  `pipeline_core.segmenting.make_segments`, and calls the real
  `ChatterboxEngine.synthesize_segment` and `MuseTalkEngine.sync_chunk` public methods —
  never a private shortcut.
- Both artefacts are downloaded and probed (`worker_cpu/ffmpeg/ingest.py::probe`) for
  measured duration; the TTS clip is asserted `>= 10,000 ms` and the lip-sync chunk
  `5,000 ms ± 250 ms`. The chunk's resolution, fps, and audio-stream presence are also
  printed, so the video-only requirement is visible in the transcript.
- VRAM measurement now prints three figures — torch allocated peak, torch reserved
  peak, and the device-level figure sampled via `nvidia-smi --query-gpu=memory.used` —
  and judges `VRAM_BUDGET_GB` (20 GB) against the device-level figure, falling back to
  torch reserved peak (with a printed label) when `nvidia-smi` is unavailable.
- The dead `NotImplementedError` catch and its `"blocked on engine implementation"`
  message are removed.
- The ephemeral bench job/segment rows are deleted in a `finally` block regardless of
  outcome — a bench row can never be mistaken for a stuck render in the panel.
- Added CPU-only tests to `tests/test_render_engines.py`: CLI mutual-exclusivity and
  required-one for `--smoke`/`--loop`, `--voice`/`--base-loop` parsing alongside
  `--smoke` without colliding with `--loop`'s parser entry, and `smoke()` exiting 1
  with a CUDA-device message and no traceback when no GPU is present. No test fakes
  CUDA availability to reach the render path.

## Task Commits

1. **Task 1: Make bench.py --smoke actually render, and measure VRAM honestly** -
   `3e4dc01` (feat)

_Tasks 2 and 3 not attempted this session — see Scope of this summary above. No plan
metadata commit was made either, since the plan as a whole is not complete._

## Acceptance Criteria Results (Task 1, observed on this Mac)

All eight of Task 1's acceptance criteria were run and observed directly, not assumed:

| Criterion | Result |
|---|---|
| `python scripts/bench.py --smoke` exits 1 with a CUDA-device message, no traceback | PASS — stderr: `bench.py requires a CUDA device: install the GPU extra first — pip install -e ".[gpu]"` |
| `python scripts/bench.py` (no flag) exits non-zero, reports one of `--smoke`/`--loop` required | PASS — argparse: `error: one of the arguments --smoke --loop is required` |
| `grep -c 'blocked on engine implementation' scripts/bench.py` == 0 | PASS (0) |
| `grep -c 'synthesize_segment' scripts/bench.py` >= 1 | PASS (2) |
| `grep -c 'sync_chunk' scripts/bench.py` >= 1 | PASS (1) |
| `grep -c 'nvidia-smi' scripts/bench.py` >= 1 | PASS (7) |
| `grep -c 'max_memory_reserved' scripts/bench.py` >= 1 | PASS (1) |
| `pytest tests/test_render_engines.py -x` passes, including new CLI tests | PASS (23 passed) |
| No test fakes CUDA availability to exercise the render path | PASS by inspection — `test_smoke_exits_1_with_cuda_message_and_no_traceback_when_gpu_absent` runs the real (unmocked) `_require_gpu()` guard on this Mac's no-torch environment |
| `pytest -x` (full suite) passes on the Mac | PASS |

Additional gate run per this session's `<constraints>` (not part of Task 1's own
acceptance criteria, but required before committing): `cd web && npm test && npm run
build` — both green (21/21 tests, `tsc --noEmit && vite build` clean).

## Files Created/Modified

- `scripts/bench.py` — `smoke()` rewritten to render through the real engine methods
  and measure honest device-level VRAM; `_require_gpu()` message fix; new
  `--voice`/`--base-loop` CLI flags; dead `NotImplementedError` catch removed
- `tests/test_render_engines.py` — 5 new CPU-only CLI/guard tests for `scripts/bench.py`

## Decisions Made

- **Fixed `_require_gpu()`'s ImportError message (Rule 1 — bug):** the existing message
  (`"bench.py requires the GPU host: pip install -e ".[gpu]""`) does not contain the
  substring `"CUDA"`, but this Mac has no `torch` installed at all, so `--smoke` hits
  exactly that branch — and the plan's own acceptance criteria (and Task 2's runbook
  text) require the "requires a CUDA device" message to appear on stderr regardless of
  which branch is hit. Changed the message to `"bench.py requires a CUDA device: install
  the GPU extra first — pip install -e ".[gpu]""` so both the no-torch and the
  torch-but-no-CUDA branches say the same thing. This is a one-line message fix with no
  behavior change to control flow or exit codes.
- **Order of the CUDA guard vs. render-input resolution:** `_require_gpu()` still runs
  first, before any DB session is opened. The plan's "resolve render inputs first, before
  loading any model" instruction is about avoiding a multi-GB model load on a workstation
  with CUDA but no seeded `VoiceProfile`/`BaseLoop` — not about skipping the (near-free)
  CUDA availability check. Keeping the CUDA guard first is also what makes this Mac's
  acceptance criteria reachable without a live Postgres/Redis/MinIO stack.
- **No milestone or doc edits.** Per the scope boundary, `docs/milestones.md`,
  `docs/workstation.md`, `docs/pipeline-spec.md`, and `.planning/ROADMAP.md` were left
  untouched. Ticking any box here would misrepresent evidence that does not exist yet.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `_require_gpu()` ImportError message missing "CUDA" substring**
- **Found during:** Task 1, while verifying the plan's own acceptance criterion (`'CUDA' in r.stderr`)
- **Issue:** On a machine with no `torch` installed at all (this Mac), `_require_gpu()`'s `except ImportError` branch printed `"bench.py requires the GPU host: pip install -e \".[gpu]\""` — no "CUDA" substring — while the sibling `if not torch.cuda.is_available()` branch already said "requires a CUDA device". The plan's stated acceptance ("exits 1 with the 'requires a CUDA device' message") and Task 2's runbook wording assume one consistent message; the pre-existing code only satisfied that on a host with CPU-only torch installed, not a host with no torch at all.
- **Fix:** Reworded the ImportError branch to `"bench.py requires a CUDA device: install the GPU extra first — pip install -e \".[gpu]\""`.
- **Files modified:** `scripts/bench.py`
- **Verification:** `python scripts/bench.py --smoke` on this Mac (no torch) now exits 1 with `"CUDA"` present in stderr and no traceback; new test `test_smoke_exits_1_with_cuda_message_and_no_traceback_when_gpu_absent` covers it.
- **Committed in:** `3e4dc01` (part of Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug fix, message text only, no control-flow change)
**Impact on plan:** Necessary for Task 1's own acceptance criteria to hold on this authoring machine. No scope creep — no other engine, doc, or milestone file touched.

## Issues Encountered

None beyond the message-text bug above. The full `pytest -x` suite and `cd web && npm
test && npm run build` were both green with no further fixes needed.

## User Setup Required

None — no external service configuration required for Task 1. Task 2 will require a
live RTX 3090 workstation with Postgres, Redis, and MinIO reachable per
`docs/workstation.md`, and at least one `VoiceProfile` (with reference audio) and one
`BaseLoop` created in the panel before `--smoke` can resolve render inputs.

## Next Phase Readiness

**Blocked — not ready to proceed to Task 3.** Task 2 (`checkpoint:human-verify`, running
`python scripts/bench.py --smoke` and `python worker_gpu/run.py` on the RTX 3090) must
run first and produce:
- The full `--smoke` output (measured TTS clip duration, measured chunk duration, all
  three VRAM figures, exit code)
- A human's by-ear/by-eye confirmation that the TTS clip is genuinely voice-cloned and
  the lip-sync chunk shows genuine synchronized motion (not merely correctly sized)
- `ffmpeg -i <chunk>` confirmation of a video-only stream
- The worker boot log showing both real engine classes warmed before job consumption

Only once that report exists can Task 3 write real, dated, sourced numbers into
`docs/milestones.md`, `docs/workstation.md`, and `docs/pipeline-spec.md` §6, and tick
M0.2, M0.3, M0.4, and M3.1. **This session invented no numbers and ticked no boxes.**

Task 1's CPU-verifiable half is done and gives Task 2 a bench harness that will fail
helpfully (not with a traceback) if the workstation is misconfigured, and that measures
the card's actual occupancy rather than torch's understated bookkeeping — directly
serving Phase 3's later need to fit the 16–22 GB Wan lane into what's left on the card.

---
*Phase: 01-render-engines-live*
*Plan: 04 (Task 1 of 3 — PARTIAL)*
*Completed: 2026-08-02*
