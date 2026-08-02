---
phase: 01-render-engines-live
plan: 01
subsystem: gpu-environment
tags: [chatterbox-tts, musetalk, openmim, torch, gpu-host, install-script]

# Dependency graph
requires: []
provides:
  - "scripts/install_engines.sh — one-command GPU-host installer (dry-run exercisable from a Mac); NOT yet run for real on the 3090"
  - "Settings.musetalk_root (empty default) + MUSETALK_ROOT env key"
  - "tests/test_engine_install.py — CPU-only shape lock for the installer"
affects: [01-render-engines-live/01-03]

actuals:
  tokens: 2417
  tasks: 1
  commits: 1

tech-stack:
  added: []
  patterns:
    - "run() dry-run wrapper: every side-effecting shell command is routed through a helper that either executes or echoes it, so a GPU-host installer stays exercisable and CI-testable from a non-CUDA machine"

key-files:
  created:
    - scripts/install_engines.sh
    - tests/test_engine_install.py
  modified:
    - packages/pipeline_core/settings.py
    - .env.example
    - .gitignore

key-decisions:
  - "Task 1 authored exactly as specified — no deviations. The installer's real dependency-resolution numbers (torch/mmcv/chatterbox-tts pins) cannot be produced on this Mac and are deliberately left as placeholders (CHATTERBOX_VERSION=0.1.7 default, MUSETALK_COMMIT=main default) for Task 5 to tighten once Task 3 measures them on the 3090."

requirements-completed: []  # REQ-gpu-environment is NOT complete — Tasks 2-5 (the actual GPU-host bring-up) are checkpoint-blocked

coverage:
  - id: D1
    description: "scripts/install_engines.sh installs the [gpu] extra, chatterbox-tts, a commit-pinned MuseTalk clone, and the unpinned mmlab stack via openmim, in the torch-preserving order RESEARCH.md Pitfall 1 requires"
    verification:
      - kind: unit
        ref: "tests/test_engine_install.py::test_mim_line_installs_all_four_mmlab_packages_unpinned"
        status: pass
      - kind: unit
        ref: "tests/test_engine_install.py::test_install_script_references_the_official_musetalk_repo"
        status: pass
    human_judgment: false
  - id: D2
    description: "Installer is dry-run exercisable and CI-testable from a non-CUDA Mac (guards nvidia-smi absence, --dry-run echoes all side-effecting commands)"
    verification:
      - kind: unit
        ref: "tests/test_engine_install.py::test_install_script_dry_run_is_exercisable_without_gpu_host"
        status: pass
      - kind: other
        ref: "bash scripts/install_engines.sh --dry-run (manual run, exit 0, no network touched)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Settings.musetalk_root field (empty default) and matching MUSETALK_ROOT env key, portable to a rented GPU host"
    verification:
      - kind: unit
        ref: "tests/test_engine_install.py::test_settings_musetalk_root_defaults_to_empty_string"
        status: pass
      - kind: unit
        ref: "tests/test_engine_install.py::test_musetalk_root_documented_in_env_example"
        status: pass
    human_judgment: false
  - id: D4
    description: "Every package this installer touches was verified against its official registry/repo page before first install on the workstation (Task 2)"
    verification: []
    human_judgment: true
    rationale: "Blocking-human legitimacy gate per RESEARCH.md's Package Legitimacy Audit fallback rule — requires visiting live PyPI/GitHub pages, which cannot be done from this authoring machine or auto-approved regardless of auto_advance."
  - id: D5
    description: "The installer actually runs on the RTX 3090 and produces a real, measured dependency resolution (torch/mmcv/chatterbox-tts/MuseTalk versions, VRAM-relevant install behavior)"
    verification: []
    human_judgment: true
    rationale: "Requires physical/remote access to the RTX 3090 workstation (nvidia-smi, CUDA toolchain) — not producible or verifiable from this CUDA-less Mac."
  - id: D6
    description: "The project standardizes on a named dependency-resolution option (Task 4) based on Task 3's measured output"
    verification: []
    human_judgment: true
    rationale: "One-way architectural decision (reversibility: one-way) that depends on Task 3's real measurement, which does not yet exist."
  - id: D7
    description: "The resolved versions are pinned into pyproject.toml/install_engines.sh and documented in docs/workstation.md; M0.1 ticked with a real device string (Task 5)"
    verification: []
    human_judgment: true
    rationale: "Depends on Task 3's measured values and Task 4's decision — neither exists yet; cannot be authored without inventing numbers, which the plan explicitly forbids."

duration: 22min
completed: 2026-08-02
status: partial
---

# Phase 1 Plan 1: GPU Host Environment + Dependency Resolution Summary

**Task 1 (author the installer + Settings wiring) is complete and committed; Tasks 2-5 are checkpoint-blocked on the RTX 3090 workstation and a human package-legitimacy review — this plan cannot proceed further from a CUDA-less Mac.**

## Performance

- **Duration:** 22 min (Task 1 only)
- **Started:** 2026-08-02T07:26:00Z (approx, first read)
- **Completed:** 2026-08-02T07:48:00Z (Task 1 commit)
- **Tasks:** 1/5 completed (Task 1 auto; Tasks 2-5 not started — checkpoint-blocked)
- **Files modified:** 5

## Accomplishments

- `scripts/install_engines.sh`: one-command GPU-host installer covering `pip install -e ".[gpu]"` → `chatterbox-tts==${CHATTERBOX_VERSION}` → commit-pinned MuseTalk clone → unpinned `mim install mmengine mmcv mmdet mmpose` → MuseTalk weight download → a "RESOLVED VERSIONS" report → `scripts/verify_gpu.py`, in the exact order RESEARCH.md's Pitfall 1 says determines which torch survives.
- `--dry-run` flag: every side-effecting command routes through a `run()` wrapper that echoes instead of executing, so the script is provably exercisable (and CI-testable) from this non-CUDA Mac — verified live: `bash scripts/install_engines.sh --dry-run` exits 0 with no network calls.
- `Settings.musetalk_root` (empty default) + `MUSETALK_ROOT` in `.env.example`, following the existing "empty means use the default" convention; `third_party/` added to `.gitignore` (MuseTalk is pinned by SHA in the installer, never committed).
- `tests/test_engine_install.py`: 11 CPU-only assertions locking the installer's shape (executable bit, pipefail, unpinned mmlab install, MuseTalk repo reference, both env overrides, verify_gpu call, resolved-versions report, dry-run guard, Settings default, .env.example key).

## Task Commits

1. **Task 1: Author scripts/install_engines.sh — the one-command GPU-host engine install** - `19c6ff0` (feat)

Tasks 2-5 are not yet attempted — see "Checkpoint Blocked" below.

## Files Created/Modified

- `scripts/install_engines.sh` - New executable installer (dry-run supported)
- `tests/test_engine_install.py` - New CPU-only shape-lock test module (11 tests)
- `packages/pipeline_core/settings.py` - Added `musetalk_root: str = ""` field
- `.env.example` - Added `MUSETALK_ROOT=` key with explanatory comment
- `.gitignore` - Added `third_party/` (vendored, SHA-pinned research repos)

## Decisions Made

- No deviations — Task 1 executed exactly as specified. Placeholder defaults (`CHATTERBOX_VERSION=0.1.7`, `MUSETALK_COMMIT=main`) are intentional per the plan's own design: Task 5 tightens them to exact pins only after Task 3 measures real values on the 3090, so this task does not invent numbers it cannot verify.

## Deviations from Plan

None - Task 1 executed exactly as written. All of Task 1's acceptance criteria were verified explicitly on this machine:
- `bash -n scripts/install_engines.sh` exits 0; `bash scripts/install_engines.sh --dry-run` exits 0, no network touched
- `pytest tests/test_engine_install.py -x` passes (11 assertions, exceeds the required 8)
- `pytest tests/test_portability.py -x` stays green (21 tests total across both files)
- `git check-ignore third_party/MuseTalk` exits 0
- `python -c "from pipeline_core.settings import Settings; assert Settings().musetalk_root == ''"` exits 0
- `grep -c MUSETALK_ROOT .env.example` reports 1
- Full `pytest` suite green (no failures); `cd web && npm test -- --run` (21/21 passed) and `npm run build` (tsc + vite build) both green, per CLAUDE.md's full-suite-green-before-commit gate

## Checkpoint Blocked

Execution stopped honestly at **Task 2**, the first of three workstation-human gates this plan is deliberately built around (RESEARCH.md's central risk cannot be resolved off the GPU host). None of Tasks 2-5 have been attempted:

- **Task 2** (`checkpoint:human-verify`, `gate="blocking-human"`): Package legitimacy gate — a human must visit the live PyPI/GitHub pages for `chatterbox-tts`, `TMElyralab/MuseTalk`, `openmim`, and the `mmengine`/`mmcv`/`mmdet`/`mmpose` family, confirm MIT/Apache-2.0 licensing, and record the MuseTalk `main` HEAD SHA. This gate is never auto-approvable regardless of `auto_advance` (RESEARCH.md's Package Legitimacy Audit fallback rule), and requires live web access this execution environment does not have.
- **Task 3** (`checkpoint:human-verify`, precondition: physical/remote RTX 3090 access): Run `scripts/install_engines.sh` on the actual workstation and report the resolved dependency stack, VRAM-relevant install timing, and `verify_gpu.py` output. Blocked on Task 2's clearance and on GPU-host access this machine (a CUDA-less Mac) does not have.
- **Task 4** (`checkpoint:decision`, `gate="blocking"`, one-way reversibility): Standardize the resolved torch/mmlab stack based on Task 3's measurement. Cannot be decided without that measurement.
- **Task 5** (`auto`): Pin the resolved versions into `pyproject.toml`/`scripts/install_engines.sh`, document them in `docs/workstation.md`, and tick M0.1 in `docs/milestones.md`. Blocked on Tasks 3-4's real numbers — writing this now would mean inventing version numbers, which the plan explicitly forbids ("do not invent any").

No GPU-host action was attempted on this machine, per the standing constraint that this is a Mac with no CUDA.

## Issues Encountered

None on Task 1. The plan's own architecture anticipated the stopping point exactly — 2 of 5 tasks are Mac-authorable, 3 are workstation-human gates, and this plan is "deliberately gate-heavy" by design (see PLAN.md `<objective>`).

## User Setup Required

**Before this plan can proceed, a human must:**

1. Complete Task 2 on any machine with a browser: visit the five package pages listed in `01-01-PLAN.md` Task 2, confirm MIT/Apache-2.0 licensing and correct ownership, and record the MuseTalk `main` HEAD SHA.
2. Complete Task 3 on (or shelled into) the RTX 3090 workstation: run `MUSETALK_COMMIT=<the SHA from step 1> bash scripts/install_engines.sh`, and report the "RESOLVED VERSIONS" block plus `verify_gpu.py` output.
3. Resume plan 01-01 with a fresh execution once Task 2's approval and Task 3's report exist, so Task 4's decision and Task 5's pinning can proceed against real, measured values.

## Next Phase Readiness

- Plan 01-02 (already complete, see `01-02-SUMMARY.md`) does not depend on this plan's Tasks 2-5 — it built the boot-time engine warming and the CPU-only interface contract independently.
- Plan 01-03 (real Chatterbox/MuseTalk implementation) is explicitly written against whatever this plan resolves and **cannot start** until Tasks 2-5 land with real version numbers and a standardized torch/mmlab stack.
- REQ-gpu-environment remains open — this plan's Task 1 is necessary but not sufficient for it; M0.1-M0.4 in `docs/milestones.md` are still unchecked.

---
*Phase: 01-render-engines-live*
*Completed: 2026-08-02 (Task 1 only — plan status: partial, checkpoint-blocked)*
