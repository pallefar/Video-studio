# Synthesis Summary — /gsd-ingest-docs (2026-08-02, mode: new)

Single entry point for downstream consumers (gsd-roadmapper). All claims trace to
`source:` lines in the per-type intel files.

## Doc counts by type

- PRD: 1 — docs/psd.md (medium confidence; hybrid, ADR-like decision sections extracted)
- SPEC: 2 — docs/pipeline-spec.md (high), docs/roadmap-v2.md (medium; hybrid, SPEC-dominant)
- DOC: 2 — docs/milestones.md (high), docs/workstation.md (high)
- ADR: 0 · UNKNOWN: 0 · locked sources: 0

## Extracted intel

- Decisions: 16 entries, 0 locked / 16 proposed (no source carries `locked: true`) →
  intel/decisions.md. Includes the owner-dated v2 decisions (2026-07-29, 2026-07-31)
  and the resolved ComfyUI-executor question.
- Requirements: 18 entries → intel/requirements.md
  (REQ-end-to-end-render, REQ-gpu-environment, REQ-schema-single-source,
  REQ-loop-preprocessing, REQ-gpu-worker, REQ-assembly, REQ-compliance-gate,
  REQ-publish, REQ-control-panel, REQ-stock-ingest-library, REQ-generative-broll-lane,
  REQ-broll-resolution, REQ-c1-visible-watermark, REQ-c2-altered-content,
  REQ-c3-audio-watermark, REQ-c4-provenance, REQ-c5-private-uploads,
  REQ-c6-identity-consent)
- Constraints: 12 entries → intel/constraints.md — nfr: 6 (hardware envelope, model
  roster, failure modes, performance placeholders, licence register, v2 compliance
  guardrails); schema: 2 (RenderJob + state machine, timeline/storyboard); protocol: 3
  (ffmpeg assembly chain, GPU lane scheduling, service topology); api-contract: 1
  (GenerationProvider layer)
- Context topics: 6 → intel/context.md — including the AUTHORITATIVE milestone state:
  M0–M30, 125/138 boxes checked; the 13 unchecked boxes (M0×4, M2.3, M2.4, M3.1,
  M3.4, M9.1, M10.6, M11.2, M17.2, M17.3) are all RTX-3090-workstation tasks whose
  ordered plan of record is docs/workstation.md §5 (runbook steps 1–15). This is the
  project's entire remaining gap.

## Conflicts

- Blockers: 0 (no locked sources → LOCKED-vs-LOCKED impossible; no UNKNOWNs)
- Competing variants / warnings: 2 — cross-ref cycle acknowledgment (companion-doc
  mutual references; flat extraction performed) and the TanStack-Query-vs-plain-fetch
  variant on REQ-control-panel
- Auto-resolved / info: 6 — milestone-state authority (by psd §8's own delegation),
  C6 provenance, VFR mechanism, RIFE→FILM, v1-before-v2 sequencing (historical),
  performance placeholders

Detail: /Users/karstenhaldan/Video-studio/.planning/INGEST-CONFLICTS.md

## Planning guidance for the roadmapper

- Treat milestone completion state as fact. Do not re-plan M1–M30 shipped work; the
  roadmap's open scope is the 13 workstation boxes, sequenced by workstation.md §5.
- The licence register (constraints: "Licence register (binding)") and compliance
  rules C1–C6 (requirements) are structural gates — carry them into REQUIREMENTS.md
  verbatim, not summarized away.
- Resolve the two WARNINGs with the user before routing.

## Files

- /Users/karstenhaldan/Video-studio/.planning/intel/decisions.md
- /Users/karstenhaldan/Video-studio/.planning/intel/requirements.md
- /Users/karstenhaldan/Video-studio/.planning/intel/constraints.md
- /Users/karstenhaldan/Video-studio/.planning/intel/context.md
- /Users/karstenhaldan/Video-studio/.planning/INGEST-CONFLICTS.md
