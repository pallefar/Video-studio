# Ingest Conflicts — /gsd-ingest-docs (2026-08-02)

Docs synthesized: 5 (1 PRD, 2 SPEC, 2 DOC). No ADRs, no locked sources, no UNKNOWN
classifications — LOCKED-vs-LOCKED contradiction is not possible in this set.
Precedence applied: ADR > SPEC > PRD > DOC (no per-doc overrides present).

## Conflict Detection Report

### BLOCKERS (0)

(none)

### WARNINGS (2)

[WARNING] Cross-reference cycle spans all five ingested docs
  Found: the mention-level cross_ref graph is a single strongly connected component —
    psd.md ↔ pipeline-spec.md, psd.md ↔ milestones.md, milestones.md ↔ roadmap-v2.md,
    milestones.md ↔ workstation.md (companion-doc mutual references)
  Impact: a strict cycle policy would exclude the entire set from synthesis. Source
    inspection shows the content-level delegation is acyclic (psd delegates schema
    detail to pipeline-spec §3; pipeline-spec delegates rationale back to psd §4.1 —
    disjoint content, no circular definition), so synthesis proceeded as flat per-doc
    extraction with no recursive reference-following. Risk if the reading is wrong:
    double-counted or circularly-derived intel
  → Confirm the companion-link reading (expected: approve). If any content was
    double-counted, re-run ingest with --manifest trimming cross_refs per doc

[WARNING] Competing acceptance variants for REQ-control-panel (client-state library)
  Found: docs/psd.md §2 (stack table) and §5 M7 require "TanStack Query polling, 2 s
    interval"; docs/milestones.md M7 (ticked, shipped) records "2 s polling; plain
    fetch — TanStack Query optional later"
  Impact: precedence says PRD > DOC, but the DOC records what actually shipped and its
    completion state is fact. Synthesis cannot pick without either overriding shipped
    reality or silently amending the PRD's stack decision. Both variants are preserved
    (REQ-control-panel notes the divergence; DEC-v1-stack records TanStack Query)
  → Either amend psd.md §2/§5 to accept plain fetch, or add a "migrate to TanStack
    Query" task downstream. Choose before routing

### INFO (6)

[INFO] Auto-resolved: milestone completion state — milestones.md wins over psd.md §5
  Note: docs/psd.md §5 shows M0–M9 boxes unchecked (authoring-time template); docs/
    milestones.md shows 125/138 checked. Resolved in favour of milestones.md NOT by
    precedence inversion but by explicit delegation: psd.md §8 states "Milestones live
    in docs/milestones.md as checkboxes … it's the durable progress record." The
    higher-precedence PRD itself designates the DOC as authoritative for progress.
    Completion state is treated as fact throughout the intel (intel/context.md)

[INFO] Auto-resolved: C6 numbering and provenance
  Note: docs/psd.md §6 defines C1–C5 only. The identity-consent rule is defined in
    docs/roadmap-v2.md §8 ("structural, like C1–C5") and is numbered C6 in docs/
    milestones.md (M17, M21, M28) and in api/validators/compliance.py. Extracted as
    REQ-c6-identity-consent with roadmap-v2 §8 as source — do not cite psd.md for C6

[INFO] Auto-resolved: VFR-detection mechanism — constraint upheld, tool differs
  Note: docs/pipeline-spec.md §4 says "probe with ffprobe; reject VFR at loop ingest";
    docs/milestones.md M2/M14 record the shipped mechanism as ffmpeg `vfrdet` /
    `ffmpeg -i` parse ("no ffprobe needed with the static build"). The SPEC's binding
    intent — reject VFR at ingest, never discover drift at assembly — is satisfied;
    the tool named in the SPEC is illustrative. SPEC constraint recorded as-is in
    intel/constraints.md; shipped mechanism recorded in intel/context.md

[INFO] Auto-resolved: RIFE excluded, FILM adopted for the cheap interpolation lane
  Note: docs/roadmap-v2.md §2 feature map lists "Real-ESRGAN + RIFE cheap lane", but
    the same doc's §6 register marks RIFE conditional (training-data caveat, "FILM is
    the clean fallback") and docs/milestones.md M13 records "RIFE stays out per the
    licence register's training-data caveat; Real-ESRGAN + FILM cheap lane". Intra-doc
    resolution: the binding §6 register wins over the §2 table; the shipped state
    agrees. FILM is the adopted interpolator

[INFO] Sequencing prerequisite in roadmap-v2 header overtaken by events
  Note: docs/roadmap-v2.md header states "v1's M2–M7 render pipeline must ship before
    v2 work starts", yet docs/milestones.md shows v2 (M10–M30) essentially complete
    while M0/M2.3–4/M3.1,4/M9.1 remain open. Not a live conflict: the open boxes are
    exclusively RTX-3090 hardware tasks (CPU-verifiable halves shipped and tested),
    and the ordered runbook in docs/workstation.md §5 is the plan of record for them.
    Treat the header sentence as historical planning guidance

[INFO] pipeline-spec §6 performance figures are placeholders by design
  Note: docs/pipeline-spec.md §6 carries an explicit banner: every number is an
    estimate until `bench.py --smoke` runs on the 3090; docs/workstation.md §5 step 15
    replaces the table and deletes the banner. Downstream planning must not schedule
    against these figures
