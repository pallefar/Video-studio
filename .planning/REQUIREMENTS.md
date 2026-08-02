# Requirements: AI Video Studio

**Defined:** 2026-08-02 (ingested from docs/psd.md, docs/roadmap-v2.md via /gsd-ingest-docs)
**Core Value:** A script becomes a compliant, publishable 1080p video, unattended, in under 20 minutes of wall clock — with compliance enforced structurally.

Completion state below reflects the authoritative milestone record (`docs/milestones.md`,
125/138 boxes checked — treated as fact). Checked requirements are shipped and test-green;
unchecked requirements are the RTX-3090-workstation acceptance gap, sequenced by
`docs/workstation.md` §5.

## v1 Requirements

### Pipeline

- [ ] **REQ-end-to-end-render**: A script goes in, a compliant, publishable 1080p video comes out, unattended, in under 20 minutes of wall clock.
  Acceptance: end-to-end job completes within the wall-clock target (bench-measured; pipeline-spec §6 placeholders replaced with measured figures).
- [ ] **REQ-gpu-environment**: `verify_gpu.py` asserts capability `(8, 6)`; Chatterbox and MuseTalk load, run, and are resident simultaneously with peak VRAM logged under 20 GB.
  Acceptance: `python scripts/verify_gpu.py && python scripts/bench.py --smoke` exits 0 on the 3090 host.
- [x] **REQ-schema-single-source**: `packages/schema/models.py` is the single source of truth; TS types generated; Postgres via Alembic; MinIO provisioned; all storage via one S3-client interface; no `localhost` literal in worker code.
  Acceptance: `pytest tests/test_schema_roundtrip.py tests/test_portability.py` passes. — Shipped (M1)
- [ ] **REQ-loop-preprocessing**: CFR-enforced ingest (reject VFR); perceptual-hash seam detection with ping-pong fallback; latent cache built and persisted per loop; second render against a cached loop measurably faster.
  Acceptance: `python scripts/bench.py --loop <id>` shows cached run ≥ 40% faster. — Ingest/seam shipped (M2.1, M2.2); real latent cache + cache benchmark open (M2.3, M2.4)
- [ ] **REQ-gpu-worker**: Single long-lived process, models warm at boot and never unloaded; consumes `tts` and `lipsync` from Redis; segment-level retry; chunked lip-sync at 60–90 s windows; seeds pinned per segment.
  Acceptance: `pytest tests/test_queue_topology.py` (green); a job goes `queued → lipsync` unattended with real engines. — Topology/orchestration shipped; real engine loads + real chunked lip-sync open (M3.1, M3.4)
- [x] **REQ-assembly**: Loudness −14 LUFS; watermark burn-in full duration; caption burn-in from faster-whisper word timings; B-roll insertion; H.264 CRF 18, yuv420p, `+faststart`.
  Acceptance: an 8-minute job completes end to end; output plays in VLC and Chrome with correct A/V sync. — Shipped (M4)
- [ ] **REQ-publish**: YouTube Data API v3 with OAuth + persisted refresh token; uploads land `private` always; `altered_content` set programmatically; backoff distinguishes quota exhaustion from real failure.
  Acceptance: a real upload lands private with the disclosure flag visible in Studio. — Code + tests shipped (M6); real-credential workstation acceptance open (runbook step 14)
- [x] **REQ-control-panel**: Submit script, pick loop + voice profile; job list with live status (2 s polling); preview before publish with per-segment re-render; manual publish confirmation, never automatic.
  Acceptance: a full video produced without touching the terminal. — Shipped (M7)
  Resolution (user-decided 2026-08-02): plain fetch polling is the accepted stack — shipped reality accepted over psd's TanStack Query spec. TanStack Query is an optional future improvement, NOT a requirement.

### Assets & B-roll

- [x] **REQ-stock-ingest-library**: Pexels + Pixabay behind one `StockProvider` interface; ingest persists `license`, `source_url`, `origin='stock'`; `has_identifiable_people` defaults true and resolver excludes flagged assets; caption embedding + cosine search; library browser with approve/flag.
  Acceptance: `pytest tests/test_asset_resolver.py` passes, including that a flagged asset is never returned. — Shipped (M8)
- [ ] **REQ-generative-broll-lane**: Wan 2.2 quantised (GGUF/INT8) loads and generates a 5 s clip; separate queue with exclusive GPU lock, never concurrent with the render lane; output lands `origin='generated'`, `approved=false`; approval gate before selectability.
  Acceptance: `pytest tests/test_gpu_exclusivity.py` (green); an unapproved generated asset is never selected; a real 5 s clip generates on the 3090. — Lanes/locks/gates shipped (M9); first real Wan clip open (M9.1)
- [x] **REQ-broll-resolution**: Three-tier resolution — local library (instant) → stock API (seconds) → generative queue (minutes, never blocking); beat-to-asset matching by embedding cosine similarity with threshold fall-through.
  Acceptance: `pytest tests/test_asset_resolver.py`. — Shipped (M8/M9)

### Compliance (C1–C6 — structural gates, carried verbatim)

- [x] **REQ-compliance-gate**: Validator rejects `watermark.persistent != true` and `publish.altered_content != true`; provenance record written before publish is permitted; frame sampling asserts watermark pixels at 10%, 50%, 90% of duration. The enforcement umbrella over C1–C5.
  Acceptance: `pytest tests/test_compliance.py` passes, including negative cases. — Shipped (M5)
- [x] **REQ-c1-visible-watermark** (C1): Visible "Made with AI" watermark, full duration. Satisfies EU AI Act Article 50(4) (applicable from 2 August 2026): disclosure clear and perceivable at first exposure; machine-readable marking alone does not suffice.
  Acceptance: Pydantic validator + frame-sampling test (10%, 50%, 90% of duration). — Shipped (M5; extended structurally to studio renders in M16)
- [x] **REQ-c2-altered-content** (C2): YouTube `altered_content` set on every upload. Separate obligation from C1 — neither substitutes for the other; both, every time.
  Acceptance: publish-worker precondition. — Shipped (M5/M6)
- [x] **REQ-c3-audio-watermark** (C3): Chatterbox audio watermark preserved through the encode chain (loudnorm + AAC round-trip).
  Acceptance: encode chain test. — Shipped (M4/M5)
- [x] **REQ-c4-provenance** (C4): Provenance record per published video; records which assets appeared (`Asset.origin` feeds it).
  Acceptance: FK constraint — publish requires a `PublishRecord`. — Shipped (M5)
- [x] **REQ-c5-private-uploads** (C5): Uploads land private; human review before public.
  Acceptance: no API path sets `public`. — Shipped (M6)
- [x] **REQ-c6-identity-consent** (C6): Identity LoRA training and face-bearing generation refuse identities without recorded consent (`consent_recorded_by`/`consent_at`, append-once); enforced at the API layer and re-checked in the wan-lane worker so a raw enqueue can't bypass the route.
  Acceptance: `pytest tests/test_identity_consent.py` — refusal without consent. — Shipped (M17); refusal path re-verified against the real trainer in Phase 5

## v2 Requirements

None deferred — the v2 studio scope (roadmap-v2 M10–M30) is shipped per the milestone
record. Future improvements tracked as out-of-scope options below, not requirements.

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| TanStack Query polling migration | Optional future improvement only — plain fetch accepted as the shipped stack (user decision 2026-08-02) |
| Script generation, multi-language/dubbing, real-time conversational rendering, Teams integration | v1 non-goals (psd §1) |
| Multi-user / auth / SaaS mechanics (credits, tiers, referrals, feed, app store) | Single-user self-hosted by design (roadmap-v2 §0) |
| Marketing/UGC factory | Not cloned from Higgsfield (roadmap-v2 §2) |
| Offering the system to others | EU AI Act deployer → provider flip; recorded so it cannot happen by drift (psd §9, roadmap-v2 §8) |
| Arbitrary third-party face-swap | Identity features are consent-gated (C6); not cloned |
| Rejected models/deps (FLUX.1 [dev], FLUX.2 Klein 9B, MusicGen, HunyuanVideo 1.x, LTX-Video 2, MMAudio, Llama, Remotion, react-video-editor, Twick, Etro, editly/FFCreator) | Licence register rejected list (roadmap-v2 §6) — do not introduce |

## Traceability

Which phases cover which requirements. Shipped requirements trace to completed
milestones (completion state is fact per docs/milestones.md); open requirements trace
to roadmap phases.

| Requirement | Phase | Status |
|-------------|-------|--------|
| REQ-gpu-environment | Phase 1 | Pending |
| REQ-gpu-worker | Phase 1 | Pending |
| REQ-loop-preprocessing | Phase 2 | Pending |
| REQ-generative-broll-lane | Phase 3 | Pending |
| REQ-publish | Phase 6 | Pending |
| REQ-end-to-end-render | Phase 6 | Pending |
| REQ-schema-single-source | Shipped (M1) | Complete |
| REQ-assembly | Shipped (M4) | Complete |
| REQ-compliance-gate | Shipped (M5) | Complete |
| REQ-control-panel | Shipped (M7) | Complete |
| REQ-stock-ingest-library | Shipped (M8) | Complete |
| REQ-broll-resolution | Shipped (M8/M9) | Complete |
| REQ-c1-visible-watermark | Shipped (M5/M16) | Complete |
| REQ-c2-altered-content | Shipped (M5/M6) | Complete |
| REQ-c3-audio-watermark | Shipped (M4/M5) | Complete |
| REQ-c4-provenance | Shipped (M5) | Complete |
| REQ-c5-private-uploads | Shipped (M6) | Complete |
| REQ-c6-identity-consent | Shipped (M17) | Complete (re-verified in Phase 5) |

**Coverage:**
- v1 requirements: 18 total
- Mapped to phases or shipped milestones: 18 (6 → open phases, 12 → completed milestones)
- Unmapped: 0

---
*Requirements defined: 2026-08-02 (ingest)*
*Last updated: 2026-08-02 after roadmap creation*
