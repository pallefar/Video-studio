# Onboarding Summary — AI Video Studio

Onboarded: 2026-08-02 (brownfield: existing codebase + existing milestone system)

## What was learned

- **Codebase map** (`.planning/codebase/`, 7 documents, 2,427 lines): STACK, INTEGRATIONS, ARCHITECTURE, STRUCTURE, CONVENTIONS, TESTING, CONCERNS — evidence-backed, mapped at commit `98b76b1`.
- **Docs ingested** (5, via /gsd-ingest-docs, MODE=new): `docs/milestones.md` [DOC], `docs/workstation.md` [DOC], `docs/pipeline-spec.md` [SPEC], `docs/roadmap-v2.md` [SPEC], `docs/psd.md` [PRD]. Synthesis intel in `.planning/intel/` (entry: SYNTHESIS.md). Conflicts: 0 blockers, 2 warnings (both resolved — cross-ref cycle acknowledged; REQ-control-panel accepts shipped plain-fetch reality, TanStack Query out of scope), 6 auto-resolved. Report: `.planning/INGEST-CONFLICTS.md`.

## Planning structure

- `PROJECT.md` — hard constraints (licence register roadmap-v2 §6, compliance C1–C6), 16 proposed decisions, 0 locked.
- `REQUIREMENTS.md` — 18 requirements (12 shipped, 6 open), all mapped.
- `ROADMAP.md` — M0–M30 incorporated as completed record (fact, not re-derived); **6 open phases covering the 13 remaining workstation boxes** in `docs/workstation.md` §5 runbook order:
  1. Render Engines Live · 2. Latent Cache · 3. Wan Lane Bring-Up · 4. Camera Presets on Hardware · 5. Identity Training · 6. Acceptance Close-Out
- `STATE.md` — cross-phase blocker: every open phase requires the RTX 3090 host (or a rented CUDA box — `scripts/rent_gpu.sh` / `scripts/vast_comfyui.sh`).

## Source of truth note

`docs/milestones.md` remains the durable progress record the repo's own conventions tick; `.planning/ROADMAP.md` incorporates it. When a workstation box is ticked, update both.

## Next command

`/gsd-plan-phase 1` — plan "Render Engines Live" (runbook steps 1–3), to be executed on the GPU host.
