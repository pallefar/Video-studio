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
  - "Task 2 package-legitimacy approval: MuseTalk main HEAD SHA 0a89dec45a0192b824e3cf4daf96c239440c5ed8 (observed 2025-09-26), all five sources confirmed MIT/Apache-2.0-equivalent — the SHA Task 3 must pass as MUSETALK_COMMIT and Task 5 must pin"
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
  - "Task 2 approved by the human at the orchestrator level: all five package sources confirmed MIT/Apache-2.0-equivalent and correctly owned; MuseTalk main HEAD SHA 0a89dec45a0192b824e3cf4daf96c239440c5ed8 (2025-09-26) recorded for Task 3 to pass as MUSETALK_COMMIT and Task 5 to pin permanently. install_engines.sh's MUSETALK_COMMIT default was deliberately NOT changed from 'main' at this step — Task 3 passes the SHA explicitly via env per the plan, and Task 5 hard-codes it as the default only after Task 3's real install confirms it resolves cleanly on the host."

requirements-completed: []  # REQ-gpu-environment is NOT complete — Tasks 3-5 (the actual GPU-host bring-up) are checkpoint-blocked

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
    description: "Every package this installer touches was verified against its official registry/repo page before first install on the workstation (Task 2) — chatterbox-tts (resemble-ai, MIT, 0.1.7), TMElyralab/MuseTalk (MIT, main HEAD 0a89dec45a0192b824e3cf4daf96c239440c5ed8), openmim + mmengine/mmcv/mmdet/mmpose (all github.com/open-mmlab/*)"
    verification:
      - kind: manual_procedural
        ref: "Human verified all five sources live against PyPI/GitHub (resume-signal: 'approved — MuseTalk main HEAD SHA observed and pinned: 0a89dec45a0192b824e3cf4daf96c239440c5ed8'); MuseTalk LICENSE shows GitHub NOASSERTION but file content confirmed 'MIT License, Copyright (c) 2024 Tencent Music Entertainment Group' — flagged as a GitHub SPDX-detection quirk, not a licensing concern"
        status: pass
    human_judgment: true
    rationale: "Blocking-human legitimacy gate per RESEARCH.md's Package Legitimacy Audit fallback rule — required visiting live PyPI/GitHub pages, which this authoring machine cannot do itself; the human's verification is recorded here but the gate is inherently human-judgment and is not re-classified as automatable."
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

**Task 1 (installer + Settings wiring) is complete and committed; Task 2's package-legitimacy gate is approved with the MuseTalk SHA pinned; Tasks 3-5 remain checkpoint-blocked on physical RTX 3090 access — this plan cannot proceed further from a CUDA-less Mac.**

## Performance

- **Duration:** 22 min (Task 1); Task 2 approval relayed by the orchestrator, no additional authoring time on this machine
- **Started:** 2026-08-02T07:26:00Z (approx, first read)
- **Completed:** 2026-08-02T07:48:00Z (Task 1 commit); Task 2 approved same session
- **Tasks:** 1/5 executed on this machine, 1/5 (Task 2) approved via human verification relayed by the orchestrator; Tasks 3-5 not started — checkpoint-blocked
- **Files modified:** 5

## Accomplishments

- `scripts/install_engines.sh`: one-command GPU-host installer covering `pip install -e ".[gpu]"` → `chatterbox-tts==${CHATTERBOX_VERSION}` → commit-pinned MuseTalk clone → unpinned `mim install mmengine mmcv mmdet mmpose` → MuseTalk weight download → a "RESOLVED VERSIONS" report → `scripts/verify_gpu.py`, in the exact order RESEARCH.md's Pitfall 1 says determines which torch survives.
- `--dry-run` flag: every side-effecting command routes through a `run()` wrapper that echoes instead of executing, so the script is provably exercisable (and CI-testable) from this non-CUDA Mac — verified live: `bash scripts/install_engines.sh --dry-run` exits 0 with no network calls.
- `Settings.musetalk_root` (empty default) + `MUSETALK_ROOT` in `.env.example`, following the existing "empty means use the default" convention; `third_party/` added to `.gitignore` (MuseTalk is pinned by SHA in the installer, never committed).
- `tests/test_engine_install.py`: 11 CPU-only assertions locking the installer's shape (executable bit, pipefail, unpinned mmlab install, MuseTalk repo reference, both env overrides, verify_gpu call, resolved-versions report, dry-run guard, Settings default, .env.example key).

## Task Commits

1. **Task 1: Author scripts/install_engines.sh — the one-command GPU-host engine install** - `19c6ff0` (feat)
2. **Task 2: Package legitimacy gate** - approved (no code change; this SUMMARY is the record) — MuseTalk main HEAD SHA `0a89dec45a0192b824e3cf4daf96c239440c5ed8` (2025-09-26) pinned for Task 3/5

Tasks 3-5 are not yet attempted — see "Checkpoint Blocked" below.

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

## Task 2: Package Legitimacy Gate — APPROVED

Cleared by a human at the orchestrator level (evidence recorded in the orchestrator conversation, relayed here for the durable record):

| Source | Verdict |
|---|---|
| `chatterbox-tts` (PyPI) | resemble-ai org (`engineering@resemble.ai`), MIT, version `0.1.7` exists, homepage `github.com/resemble-ai/chatterbox` |
| `resemble-ai/chatterbox` (GitHub) | LICENSE: MIT (SPDX-verified) |
| `TMElyralab/MuseTalk` (GitHub) | Owner: TMElyralab; LICENSE file: "MIT License, Copyright (c) 2024 Tencent Music Entertainment Group" (GitHub's UI shows NOASSERTION — a detection quirk, not a licensing concern); **main HEAD SHA: `0a89dec45a0192b824e3cf4daf96c239440c5ed8`** (2025-09-26) |
| `openmim` (PyPI) | MIM Authors, `github.com/open-mmlab/mim` |
| `mmengine`/`mmcv`/`mmdet`/`mmpose` | All resolve to `github.com/open-mmlab/*` |

All five sources confirmed MIT or Apache-2.0-equivalent per CLAUDE.md's licence rule. No package failed the check. The MuseTalk SHA above is what Task 3 must pass as `MUSETALK_COMMIT=0a89dec45a0192b824e3cf4daf96c239440c5ed8` when invoking `scripts/install_engines.sh` on the workstation, and what Task 5 hard-codes as the script's default once Task 3 confirms it resolves cleanly.

## Checkpoint Blocked

Execution now stops at **Task 3**, which requires physical or remote access to the RTX 3090 workstation — unreachable from this CUDA-less Mac:

- **Task 3** (`checkpoint:human-verify`, precondition: physical/remote RTX 3090 access): Run `MUSETALK_COMMIT=0a89dec45a0192b824e3cf4daf96c239440c5ed8 bash scripts/install_engines.sh` on the actual workstation, let it run to completion (it ends by running `verify_gpu.py`), then prove `torch`+`chatterbox`+`musetalk` import together in one interpreter, and report the "RESOLVED VERSIONS" block, the wheel-vs-source-build timing for mmcv, `pip show resemble-perth`, and any warnings — even if the script exits 0.
- **Task 4** (`checkpoint:decision`, `gate="blocking"`, one-way reversibility): Standardize the resolved torch/mmlab stack based on Task 3's measurement. Cannot be decided without that measurement.
- **Task 5** (`auto`): Pin the resolved versions into `pyproject.toml`/`scripts/install_engines.sh` (including hard-coding `MUSETALK_COMMIT`'s default to the SHA above once Task 3 confirms it), document them in `docs/workstation.md`, and tick M0.1 in `docs/milestones.md`. Blocked on Tasks 3-4's real numbers — writing this now would mean inventing version numbers, which the plan explicitly forbids ("do not invent any").

No GPU-host action was attempted on this machine, per the standing constraint that this is a Mac with no CUDA.

## Issues Encountered

None on Task 1 or Task 2. The plan's own architecture anticipated this stopping point exactly — 2 of 5 tasks are Mac-authorable, 3 are workstation-human gates, and this plan is "deliberately gate-heavy" by design (see PLAN.md `<objective>`).

## User Setup Required

**Before this plan can proceed, a human must:**

1. Complete Task 3 on (or shelled into) the RTX 3090 workstation: run `MUSETALK_COMMIT=0a89dec45a0192b824e3cf4daf96c239440c5ed8 bash scripts/install_engines.sh`, and report the "RESOLVED VERSIONS" block plus `verify_gpu.py` output.
2. Resume plan 01-01 with a fresh execution once Task 3's report exists, so Task 4's decision and Task 5's pinning can proceed against real, measured values.

## Next Phase Readiness

- Plan 01-02 (already complete, see `01-02-SUMMARY.md`) does not depend on this plan's Tasks 3-5 — it built the boot-time engine warming and the CPU-only interface contract independently.
- Plan 01-03 (real Chatterbox/MuseTalk implementation) is explicitly written against whatever this plan resolves and **cannot start** until Tasks 3-5 land with real version numbers and a standardized torch/mmlab stack.
- REQ-gpu-environment remains open — this plan's Task 1 authoring and Task 2 approval are necessary but not sufficient for it; M0.1-M0.4 in `docs/milestones.md` are still unchecked.

---
*Phase: 01-render-engines-live*
*Completed: 2026-08-02 (Tasks 1-2 done — plan status: partial, checkpoint-blocked at Task 3)*
