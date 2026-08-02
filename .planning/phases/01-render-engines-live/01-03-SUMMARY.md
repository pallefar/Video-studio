---
phase: 01-render-engines-live
plan: 03
subsystem: gpu-worker
tags: [ffmpeg, moto, s3-contract, audio-pipeline, dev-engines]

# Dependency graph
requires:
  - phase: 01-01
    provides: pinned torch/chatterbox/MuseTalk versions and the install script; Task 4's torch/mmlab GPU decision is still open (blocked on hardware)
  - phase: 01-02
    provides: boot-time engine warming in worker_gpu/run.py and the dev/real engine call-contract tests in tests/test_render_engines.py
provides:
  - worker_gpu/engines/audio.py — the CUDA-free contract layer (PROJECT_SAMPLE_RATE/PROJECT_CHANNELS, find_ffmpeg, run_ffmpeg, tts_segment_key, lipsync_chunk_key, write_project_wav, build_window_audio)
  - dev.py repointed at the shared contract helpers instead of duplicating them
  - CPU-verified proof that the artefact-key shapes and 48kHz-stereo convention are correct, independent of any model
affects: [01-04, 01-05]

# Actuals (#2632)
actuals:
  tokens: 5238
  tasks: 2
  commits: 2

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Shared CUDA-free contract module (audio.py) that both dev and real engines import from, so artefact keys and audio format have exactly one definition"
    - "Window-audio reconstruction: build the full segment+pause timeline with ffmpeg concat, apad to the declared total (never trim short), then output-side atrim to the requested window"

key-files:
  created:
    - worker_gpu/engines/audio.py
  modified:
    - worker_gpu/engines/dev.py
    - tests/test_render_engines.py

key-decisions:
  - "Executed only the CUDA-free half of plan 01-03: the contract layer (Task 1's <action> minus the two model bodies) plus Task 2 in full. ChatterboxEngine and MuseTalkEngine stay NotImplementedError stubs — this is a deliberate, orchestrator-approved partial execution, not a discovered blocker."
  - "build_window_audio pads the concatenated timeline to its declared total duration with ffmpeg's apad filter before trimming the window, so a source WAV that encodes a few ms short of its declared duration_ms never produces a short chunk."
  - "Verified segment placement on the timeline using a zero-crossing frequency estimate on extracted PCM windows (three widely-separated tone frequencies) rather than adding an FFT dependency just for the test."

patterns-established:
  - "New engine helpers land in worker_gpu/engines/audio.py; dev.py and any future real engine import from there rather than redefining keys/format constants."

requirements-completed: []  # REQ-gpu-environment and REQ-gpu-worker are NOT complete — see "Next Phase Readiness"

coverage:
  - id: D1
    description: "worker_gpu/engines/audio.py: shared key/format contract (tts_segment_key, lipsync_chunk_key, write_project_wav) proven CUDA-free"
    verification:
      - kind: unit
        ref: "tests/test_render_engines.py#test_tts_and_lipsync_key_shapes_round_trip_through_assemble_sort"
        status: pass
      - kind: unit
        ref: "tests/test_render_engines.py#test_lipsync_chunk_key_survives_out_of_order_writes"
        status: pass
      - kind: unit
        ref: "tests/test_render_engines.py#test_write_project_wav_converts_to_project_convention"
        status: pass
    human_judgment: false
  - id: D2
    description: "build_window_audio reconstructs one lip-sync window's audio from segment WAVs + trailing pauses, output exactly end_ms-start_ms long, at 48kHz stereo"
    verification:
      - kind: unit
        ref: "tests/test_render_engines.py#test_build_window_audio_matches_window_length"
        status: pass
      - kind: unit
        ref: "tests/test_render_engines.py#test_build_window_audio_places_segments_at_timeline_offsets"
        status: pass
      - kind: unit
        ref: "tests/test_render_engines.py#test_build_window_audio_is_project_convention"
        status: pass
    human_judgment: false
  - id: D3
    description: "dev.py repointed at audio.py's helpers; dev/real engine artefact keys stay in sync by construction; test_dev_engines.py unchanged and green"
    verification:
      - kind: unit
        ref: "tests/test_dev_engines.py#test_dev_pipeline_end_to_end"
        status: pass
      - kind: unit
        ref: "tests/test_render_engines.py#test_dev_engines_produce_the_keys_audio_py_defines"
        status: pass
    human_judgment: false
  - id: D4
    description: "ChatterboxEngine.synthesize_segment and MuseTalkEngine.sync_chunk — real model implementations"
    verification: []
    human_judgment: true
    rationale: "Explicitly out of scope for this execution. Blocked on plan 01-01 Task 4's torch/mmlab decision, which requires a GPU measurement not available on this Mac. Cannot be verified without CUDA; implementing without the decision risks rework."

# Metrics
duration: 35min
completed: 2026-08-02
status: partial
---

# Phase 1 Plan 03: CUDA-Free Audio Contract Layer + Dev Engine Repoint (Partial) Summary

**Extracted the shared artefact-key/48kHz-stereo contract into `worker_gpu/engines/audio.py` and repointed dev.py at it — the two real engine bodies (Chatterbox, MuseTalk) remain unimplemented, blocked on the GPU decision from plan 01-01 Task 4.**

## Status: PARTIAL EXECUTION (deliberate, orchestrator-approved)

This plan (01-03) has two tasks. Task 1's full scope covers both the CUDA-free
contract layer AND filling in `ChatterboxEngine`/`MuseTalkEngine` with real
model code. **Only the CUDA-free contract layer was built.** Task 2 (repoint
dev.py) was executed in full, since it depends only on the contract layer,
not on the model implementations.

**Reason:** 01-03 Task 1 carries an explicit precondition on plan 01-01 Task
4's one-way torch/mmlab decision, which itself requires a GPU measurement.
Neither has happened — there is no GPU available in this session (this Mac
has no CUDA device). Writing the real engine bodies now would be
unverifiable here and would risk rework once the torch/mmlab decision lands.

## Performance

- **Duration:** ~35 min
- **Tasks:** 2 of 2 in scope for this execution (Task 1 partial, Task 2 full); plan 01-03 itself remains incomplete
- **Files modified:** 3 (1 created, 2 modified)

## What was built

- **`worker_gpu/engines/audio.py`** (new): `PROJECT_SAMPLE_RATE`/`PROJECT_CHANNELS`
  (48000/2), `find_ffmpeg()` and `run_ffmpeg()` lifted verbatim from dev.py,
  `tts_segment_key()`/`lipsync_chunk_key()` (byte-identical to dev.py's prior
  inline f-strings), `write_project_wav()` (any WAV -> 48kHz stereo pcm_s16le),
  and `build_window_audio()` (reconstructs one lip-sync window's audio from
  segment WAVs + trailing pauses, on the same duration_ms+pause_after_ms
  timeline `chunk_windows()` derives its windows from).
- **`worker_gpu/engines/dev.py`**: `_find_ffmpeg`/`_run`/the two inline key
  f-strings/the literal `48000`/`2` ffmpeg flags all replaced with imports
  from `worker_gpu.engines.audio`. Output is byte-identical — proven by
  `test_dev_engines.py` staying green unchanged and a new cross-engine key
  test that runs the real `DevTTSEngine`/`DevLipsyncEngine` and asserts their
  produced S3 keys equal `audio.py`'s helpers.
- **`tests/test_render_engines.py`**: 9 new tests — 6 covering the audio.py
  contract helpers on real ffmpeg (key shapes and ordering, format
  conversion, window-audio length/placement/convention), 1 cross-engine key
  test for Task 2 (see above), and 2 more support fixtures.

## Tests added (9, all pass on this Mac with real ffmpeg, no CUDA)

1. `test_tts_and_lipsync_key_shapes_round_trip_through_assemble_sort` — key
   shapes match dev/assembler convention, round-tripped through the
   assembler's own sort function.
2. `test_lipsync_chunk_key_survives_out_of_order_writes` — `chunk_keys_for_job`
   returns ascending window order regardless of write order.
3. `test_write_project_wav_converts_to_project_convention` — 24kHz mono ->
   48kHz stereo pcm_s16le, duration preserved within 20ms.
4. `test_build_window_audio_matches_window_length` — output is exactly
   `end_ms - start_ms` long (within 40ms) for a window starting and ending
   mid-segment.
5. `test_build_window_audio_places_segments_at_timeline_offsets` — segment
   audio lands at the `duration_ms + pause_after_ms` offset, not naive
   concatenation, proven via zero-crossing frequency estimation on three
   distinct-tone segments.
6. `test_build_window_audio_is_project_convention` — output is 48kHz stereo.
7. `test_dev_engines_produce_the_keys_audio_py_defines` — the actual
   `DevTTSEngine`/`DevLipsyncEngine` output keys equal `audio.py`'s helpers
   (Task 2's required cross-engine test).

**Explicitly NOT written** (out of scope): the plan's behavior Tests 7-9,
which exercise `MuseTalkEngine.sync_chunk`'s idempotency short-circuit and
`ChatterboxEngine.synthesize_segment`'s voice-profile memoisation — both
require the real engine bodies that are out of scope here.

## Task Commits

1. **Task 1 (partial — contract layer only): `worker_gpu/engines/audio.py`** — `d95b1cd` (feat)
2. **Task 2 (full): repoint dev.py at the shared contract** — `c133846` (feat)

No plan-metadata commit was made for STATE.md/ROADMAP.md — see Constraints below.

## Files Created/Modified

- `worker_gpu/engines/audio.py` — new CUDA-free contract module
- `worker_gpu/engines/dev.py` — imports the shared helpers instead of duplicating them
- `tests/test_render_engines.py` — 9 new CPU-only tests

## Decisions Made

- Scoped this execution to exactly the contract layer + dev repoint, per
  explicit orchestrator instruction — not a decision made mid-execution.
- `build_window_audio` pads the concatenated timeline to its declared total
  before trimming the window (ffmpeg `apad=whole_dur=`), so minor
  source-encode rounding never produces a short chunk.
- Used a zero-crossing frequency estimator (not FFT) to verify segment
  placement in tests — sufficient to distinguish three widely-separated
  tones without a new test dependency.
- The cross-engine key test (`test_dev_engines_produce_the_keys_audio_py_defines`)
  was written and committed alongside `audio.py` in the Task 1 commit rather
  than in the Task 2 commit, since both tests were authored in the same file
  edit pass before either commit. It only exercises the dev engines (the
  real engines' key resolution is unreachable without their model bodies) —
  documented as a minor commit-boundary deviation, not a scope change.

## Deviations from Plan

### Auto-fixed Issues

None — no bugs or missing critical functionality encountered in the scoped work.

### Scope-boundary deviations (expected, not auto-fixed)

**1. [Deliberate partial execution] ChatterboxEngine and MuseTalkEngine left as `NotImplementedError` stubs**
- **Found during:** Task 1 read-first (precondition check)
- **Issue:** Task 1's `<precondition>` requires plan 01-01 Task 4's torch/mmlab decision (option-a/b/c vs option-d), which itself requires a GPU measurement. No GPU is available in this session.
- **Action:** Per explicit orchestrator scope, built only the CUDA-free contract layer from Task 1's `<action>` block and skipped the `ChatterboxEngine.synthesize_segment`/`MuseTalkEngine.sync_chunk` implementations entirely. Task 1's behavior Tests 7-9 (which test those bodies) were not written.
- **Files affected:** worker_gpu/engines/tts.py, worker_gpu/engines/lipsync.py — untouched, confirmed via `git diff --stat` (no changes) and `grep -c NotImplementedError` (2 hits each, unchanged).

---

**Total deviations:** 0 auto-fixed; 1 deliberate scope boundary (pre-approved, not a rule 1-4 case)
**Impact on plan:** Plan 01-03 is NOT complete. Its `<success_criteria>` "Real Chatterbox and real MuseTalk implementations replace both NotImplementedError stubs" is unmet. Everything else in the plan's success criteria (shared key/format definitions, chunk key ordering, window-audio timeline correctness, stages/chunking/locks untouched) is met and CPU-verified.

## Issues Encountered

None.

## Constraints honored

- Did not modify `STATE.md` or `ROADMAP.md` (explicit instruction) — this
  SUMMARY documents the work but the phase-level tracking files are
  untouched. Whoever resumes plan 01-03 should update those once the
  remaining work lands.
- Absolute gate (`pytest` full suite + `cd web && npm test && npm run build`)
  run green before every commit.
- Normal commits with hooks; no `--no-verify` used.

## Next Phase Readiness — What remains blocked

Plan 01-03 is **incomplete**. A future session must still, once plan 01-01
Task 4's torch/mmlab decision is made on GPU hardware:

1. **`worker_gpu/engines/tts.py` — `ChatterboxEngine.load()` and
   `.synthesize_segment()`:** import ChatterboxTTS per RESEARCH.md Pattern 1,
   load onto CUDA in BF16; `synthesize_segment` must resolve the job's
   VoiceProfile from the DB, memoise reference-audio download per voice
   profile id in an instance-scoped temp dir, pin the torch seed, call
   `generate()` with the emotion dict's two keys passed straight through, and
   use `write_project_wav`/`tts_segment_key` from `audio.py` (now available)
   for the format/key contract.
2. **`worker_gpu/engines/lipsync.py` — `MuseTalkEngine.load()` and
   `.sync_chunk()`:** resolve the MuseTalk clone root from
   `Settings().musetalk_root` (fallback repo-relative), APPEND (never
   prepend) it to `sys.path`, load MuseTalk's model set per its own
   inference entrypoint (read on the GPU host — not knowable from this
   repo); `sync_chunk` must short-circuit on existing chunk keys, build
   window audio via `audio.build_window_audio`, prepare per-loop bboxes/VAE
   latents in-memory only (never persisted to `BaseLoop.latents_uri`/
   `bbox_uri`), and use `lipsync_chunk_key` for the output key.
3. **The plan's behavior Tests 7-9** (idempotency short-circuit, voice-profile
   memoisation, no-per-call `load()`) must be added to
   `tests/test_render_engines.py` once those bodies exist.
4. **`bench.py --smoke`** on the 3090 (plan 01-04) is still the actual proof
   the model calls work — this session proves nothing about the model calls
   themselves, only the surrounding contract.
5. Update `STATE.md`/`ROADMAP.md` once the above lands and plan 01-03 is
   genuinely complete.

What IS ready now: any future engine implementation can import
`find_ffmpeg`, `run_ffmpeg`, `tts_segment_key`, `lipsync_chunk_key`,
`write_project_wav`, and `build_window_audio` from `worker_gpu.engines.audio`
with a CPU-proven contract already in place.

---
*Phase: 01-render-engines-live*
*Completed: 2026-08-02 (partial)*

## Self-Check: PASSED

- FOUND: worker_gpu/engines/audio.py
- FOUND: .planning/phases/01-render-engines-live/01-03-SUMMARY.md
- FOUND commit: d95b1cd
- FOUND commit: c133846
