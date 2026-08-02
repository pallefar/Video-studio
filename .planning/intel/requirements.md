# Requirements

Extracted from the PRD (docs/psd.md), with C6 sourced from roadmap-v2 §8 as numbered in
milestones.md/code. Completion state per requirement is NOT recorded here — the
authoritative progress record is docs/milestones.md (see intel/context.md).

## REQ-end-to-end-render
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§1)
- description: A script goes in, a compliant, publishable 1080p video comes out, unattended, in under 20 minutes of wall clock. Non-goals v1: real-time conversation, multi-user/multi-tenant, cloud deployment, Teams integration, script generation.
- acceptance: end-to-end job completes within the wall-clock target (bench-measured, pipeline-spec §6)
- scope: whole-pipeline success criterion

## REQ-gpu-environment
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§5 M0)
- description: `verify_gpu.py` asserts capability `(8, 6)`; Chatterbox and MuseTalk load, run, and are resident simultaneously with peak VRAM logged under 20 GB.
- acceptance: `python scripts/verify_gpu.py && python scripts/bench.py --smoke` exits 0
- scope: M0 environment

## REQ-schema-single-source
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§4, §5 M1)
- description: `packages/schema/models.py` is the single source of truth; TS types are generated, never hand-written; Postgres via Alembic; MinIO buckets provisioned; CRUD for jobs, loops, voice profiles; all storage via one S3-client interface; all service addresses from env, no `localhost` literal in worker code.
- acceptance: `pytest tests/test_schema_roundtrip.py tests/test_portability.py` passes (portability test greps worker packages for local-path/localhost literals)
- scope: M1 schema + API skeleton

## REQ-loop-preprocessing
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§5 M2)
- description: Ingest base footage enforcing constant frame rate (reject VFR); seam detection via perceptual hash with ping-pong fallback; latent cache built and persisted per loop; second render against a cached loop measurably faster.
- acceptance: `python scripts/bench.py --loop <id>` shows cached run ≥ 40% faster
- scope: M2 loop preprocessing

## REQ-gpu-worker
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§5 M3)
- description: Single long-lived process, models warm at boot and never unloaded; consumes `tts` and `lipsync` stages from Redis; segment-level retry; chunked lip-sync at 60–90 s windows; seeds pinned and persisted per segment.
- acceptance: `pytest tests/test_queue_topology.py` asserts GPU concurrency is 1; a job goes `queued → lipsync` unattended
- scope: M3 GPU worker

## REQ-assembly
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§5 M4)
- description: Loudness normalise to −14 LUFS; watermark burn-in full duration bottom-right; caption burn-in from faster-whisper word timings; B-roll insertion at timestamps; H.264 CRF 18, yuv420p, `+faststart`.
- acceptance: an 8-minute job completes end to end; output plays in VLC and Chrome with correct A/V sync
- scope: M4 assembly

## REQ-compliance-gate
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§5 M5)
- description: Validator rejects `watermark.persistent != true` and `publish.altered_content != true`; provenance record written before publish is permitted; frame sampling asserts watermark pixels at 10%, 50%, 90% of duration.
- acceptance: `pytest tests/test_compliance.py` passes, including negative cases
- scope: M5 compliance gate

## REQ-publish
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§5 M6)
- description: YouTube Data API v3 with OAuth + persisted refresh token; uploads land `private` always (no path publishes directly); `altered_content` set programmatically; exponential backoff with quota exhaustion distinguished from real failure.
- acceptance: a real upload lands private with the disclosure flag visible in Studio
- scope: M6 publish

## REQ-control-panel
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§5 M7)
- description: Submit script, pick loop + voice profile; job list with live status (2 s polling); preview before publish with per-segment re-render; manual publish confirmation, never automatic. Note: psd specifies TanStack Query polling — see INGEST-CONFLICTS.md WARNING (shipped implementation uses plain fetch).
- acceptance: a full video produced without touching the terminal
- scope: M7 control panel

## REQ-stock-ingest-library
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§5 M8)
- description: Pexels + Pixabay behind one `StockProvider` interface; ingest downloads to MinIO persisting `license`, `source_url`, `origin='stock'`; `has_identifiable_people` defaults true on stock ingest and resolver excludes flagged assets; caption embedding + cosine search; library browser with approve/flag toggle.
- acceptance: `pytest tests/test_asset_resolver.py` passes, including that a flagged asset is never returned
- scope: M8 stock ingest + asset library

## REQ-generative-broll-lane
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§5 M9)
- description: Wan 2.2 quantised (GGUF/INT8) loads and generates a 5 s clip; runs as a separate queue with an exclusive GPU lock, never concurrent with the render lane; generation requests never block a render; output lands `origin='generated'`, `approved=false`; approval gate before selectability.
- acceptance: `pytest tests/test_gpu_exclusivity.py` proves lanes cannot hold the GPU simultaneously; an unapproved generated asset is never selected
- scope: M9 generative B-roll lane

## REQ-broll-resolution
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§4.1)
- description: Three-tier resolution for script-beat cover: local library (instant) → stock API (seconds) → generative queue (minutes, never blocking). Beat-to-asset matching by caption/beat embedding cosine similarity with a threshold; sub-threshold falls through to the next tier.
- acceptance: resolver behaviour covered by `tests/test_asset_resolver.py`
- scope: B-roll resolver

## REQ-c1-visible-watermark
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§6 C1)
- description: Visible "Made with AI" watermark, full duration. Satisfies EU AI Act Article 50(4) (applicable from 2 August 2026): disclosure clear and perceivable at first exposure; machine-readable marking alone does not suffice.
- acceptance: Pydantic validator + frame-sampling test
- scope: compliance C1

## REQ-c2-altered-content
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§6 C2)
- description: YouTube `altered_content` set on every upload. Separate obligation from C1 — neither substitutes for the other; both, every time.
- acceptance: publish-worker precondition
- scope: compliance C2

## REQ-c3-audio-watermark
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§6 C3)
- description: Chatterbox audio watermark preserved through the encode chain (loudnorm + AAC round-trip).
- acceptance: encode chain test
- scope: compliance C3

## REQ-c4-provenance
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§6 C4)
- description: Provenance record per published video; should record which assets appeared in each published video (`Asset.origin` feeds it).
- acceptance: FK constraint — publish requires a `PublishRecord`
- scope: compliance C4

## REQ-c5-private-uploads
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§6 C5)
- description: Uploads land private; human review before public.
- acceptance: no API path sets `public`
- scope: compliance C5

## REQ-c6-identity-consent
- source: /Users/karstenhaldan/Video-studio/docs/roadmap-v2.md (§8); numbered C6 in /Users/karstenhaldan/Video-studio/docs/milestones.md (M17, M21, M28)
- description: Identity LoRA training and face-bearing generation refuse identities without recorded consent (`consent_recorded_by`/`consent_at`, append-once); enforced at the API layer and re-checked in the wan-lane worker so a raw enqueue can't bypass the route.
- acceptance: `pytest tests/test_identity_consent.py` — training/generation without recorded consent is refused
- scope: compliance C6 (identity consent)
