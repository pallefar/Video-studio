# Milestones

Durable progress record. Claude Code ticks boxes as work lands; this file
survives context resets. Acceptance criteria are commands that exit zero —
see docs/psd.md §5 for full rationale.

## M0 — Environment

- [ ] `scripts/verify_gpu.py` asserts `torch.cuda.get_device_capability() == (8, 6)` and fails loudly otherwise *(script written; must be run on the 3090 host)*
- [ ] Chatterbox loads and produces a 10 s clip from a reference sample
- [ ] MuseTalk loads and lip-syncs 5 s against a test clip
- [ ] Both resident simultaneously, peak VRAM logged and under 20 GB

**Accept:** `python scripts/verify_gpu.py && python scripts/bench.py --smoke` exits 0

## M1 — Schema + API skeleton

- [x] Pydantic models for all §4 entities
- [x] `export_ts.py` generates TS types; a schema change that isn't re-exported fails CI
- [x] Postgres via Alembic *(initial migration authored and CI-tested against a Postgres service; MinIO bucket provisioning via `ObjectStore.ensure_bucket()` — run against live services on the workstation)*
- [x] CRUD for jobs, loops, voice profiles
- [x] All storage access through an S3 client behind one interface — no `open()` on a job artefact anywhere outside it
- [x] All service addresses from env vars; no `localhost` literal in worker code

**Accept:** `pytest tests/test_schema_roundtrip.py tests/test_portability.py` passes ✅ (2026-07-29)

## M2 — Loop preprocessing

- [ ] Ingest base footage, enforce constant frame rate at ingest (reject VFR)
- [ ] Seam detection via perceptual hash, ping-pong fallback
- [ ] Latent cache built and persisted per loop
- [ ] Second render against a cached loop is measurably faster than the first

**Accept:** `python scripts/bench.py --loop <id>` shows cached run ≥ 40% faster

## M3 — GPU worker

*Orchestration skeleton landed ahead of time (CPU-verifiable, tested against real
Redis + RQ with fake engines in `tests/test_pipeline_flow.py`). What remains for
M3 proper is the model integration on the 3090: real Chatterbox/MuseTalk loads in
`worker_gpu/engines/`, warmed at boot from `run.py`.*

- [ ] Single long-lived process, models warm at boot, never unloaded *(engine cache + boot hook stubbed; real loads pending)*
- [x] Consumes `tts` and `lipsync` stages from Redis *(stage chain `tts → lipsync → assemble` runs unattended; e2e-tested)*
- [x] Segment-level retry — one bad sentence re-renders alone *(tts skips segments with audio; failed → queued re-enters; e2e-tested)*
- [ ] Chunked lip-sync at 60–90 s windows *(window derivation + orchestration done in `pipeline_core/chunking.py`; real MuseTalk chunk rendering pending)*
- [x] Seeds pinned and persisted per segment *(generated at ingest, passed to the engine, immutable through retries)*

**Accept:** `pytest tests/test_queue_topology.py` asserts GPU concurrency is 1; a job goes `queued → lipsync` unattended

## M4 — Assembly

- [ ] Loudness normalise to −14 LUFS
- [ ] Watermark burn-in, full duration, bottom-right
- [ ] Caption burn-in from faster-whisper word timings
- [ ] B-roll insertion at timestamps
- [ ] H.264 CRF 18, yuv420p, `+faststart`

**Accept:** an 8-minute job completes end to end; output plays in VLC and Chrome with correct A/V sync

## M5 — Compliance gate

- [ ] Validator rejects any job with `watermark.persistent != true` *(schema-level validator + gate + tests landed with M1; frame-sampling pending)*
- [ ] Validator rejects any job with `publish.altered_content != true` *(schema-level validator + gate + tests landed with M1)*
- [ ] Provenance record written before publish is permitted *(publish route enforces this since M1)*
- [ ] Frame sampling asserts watermark pixels present at 10%, 50%, 90% of duration

**Accept:** `pytest tests/test_compliance.py` passes, including the negative cases

## M6 — Publish

- [ ] YouTube Data API v3, OAuth, refresh token persisted
- [ ] Uploads land `private`, always — no path publishes directly
- [ ] `altered_content` set programmatically on upload
- [ ] Exponential backoff; quota exhaustion is distinguished from real failure

**Accept:** a real upload lands private with the disclosure flag visible in Studio

## M7 — Control panel

- [ ] Submit script, pick loop + voice profile
- [ ] Job list with live status (TanStack Query polling, 2 s interval)
- [ ] Preview before publish, per-segment re-render button
- [ ] Manual publish confirmation — never automatic

**Accept:** a full video produced without touching the terminal

## M8 — Stock ingest + asset library

- [ ] Pexels + Pixabay clients behind one `StockProvider` interface
- [ ] Ingest downloads to MinIO, persists `license`, `source_url`, `origin='stock'`
- [ ] `has_identifiable_people` defaults `true` on stock ingest; resolver excludes flagged assets
- [ ] Caption embedding + cosine search over the library
- [ ] Library browser in the control panel with an approve/flag toggle

**Accept:** `pytest tests/test_asset_resolver.py` passes, including the case that a flagged asset is never returned

## M9 — Generative B-roll lane

- [ ] Wan 2.2 quantised (GGUF/INT8) loads and generates a 5 s clip
- [ ] Runs as a separate queue with an exclusive GPU lock — never concurrent with the render lane *(the lock itself landed early in `pipeline_core/locks.py`, proven by `tests/test_gpu_exclusivity.py` against real Redis)*
- [ ] Generation requests enqueue and never block a render job
- [ ] Output lands in the library as `origin='generated'`, `approved=false`
- [ ] Approval gate in the control panel before an asset becomes selectable

**Accept:** `pytest tests/test_gpu_exclusivity.py` proves render and generation lanes cannot hold the GPU simultaneously; an unapproved generated asset is never selected by the resolver

---

# v2 — Higgsfield-class studio (planned)

Full plan and research: `docs/roadmap-v2.md`. Prerequisite: v1 M2–M7 shipped.
Owner decisions 2026-07-29: clone Higgsfield's capabilities self-hosted, add a real
multi-track video studio, and make the system a model aggregator — open models
locally/on rented GPUs AND proprietary models via API, behind one interface.

## M10 — Generation provider layer + wan-lane executor

- [ ] `GenerationProvider` interface: capability discovery, submit, poll, fetch-to-MinIO; every output lands as an `Asset` (`origin='generated'`) with provider/model/params/cost provenance
- [ ] Local provider: wan-lane executor (decide ComfyUI headless vs diffusers here) running Wan 2.2 T2V/I2V under the existing GPU lock
- [ ] API provider class: aggregator gateway first (fal.ai or Replicate), then one direct integration (Sora or Veo); keys from env only — unconfigured providers don't appear in the registry
- [ ] API jobs run as network jobs on the CPU lane with backoff — never touch the GPU lock
- [ ] Fallback chains: a request may declare provider preference order
- [ ] Benchmark on the 3090: Fun-Camera A14B GGUF + 4-step LoRA latency and VRAM (decides 14B vs 5B default)

**Accept:** `pytest tests/test_providers.py` — a fake provider round-trips a generation into the asset library with full provenance; unknown models are refused; an API-provider job never acquires the GPU lock

## M11 — Camera presets (the signature)

- [ ] Preset registry as data (JSON): camera moves (crash zoom, dolly, dolly-zoom, orbit, FPV, bullet time…) with prompt templates + LoRA refs, stackable up to 3
- [ ] Wan2.2-Fun-Control-Camera integration in the local provider; Civitai LoRAs individually licence-audited before inclusion
- [ ] Preset picker UI: image in → preset → clip in library (preset-first, prompt optional)
- [ ] Advanced mode: Uni3C custom trajectories; ReCamMaster re-shoot of existing footage

**Accept:** golden-path test: preset request → generation record → asset with `origin='generated'`; a preset referencing an unaudited LoRA fails validation

## M12 — Image studio ("Soul" equivalent)

- [ ] Z-Image Turbo (daily driver), Qwen-Image (thumbnails/text), SDXL (style LoRAs) in the provider registry
- [ ] Style preset registry (curated looks, seasonal drops are content not code)
- [ ] Storyboard mode: multi-frame with shared seed/style ("Popcorn" equivalent)
- [ ] Thumbnail pipeline for the YouTube flow

**Accept:** style preset → image lands in library; storyboard produces N frames with recorded shared params

## M13 — VFX & finishing lane

- [ ] Effect preset registry over Wan2.2-VACE-Fun (v2v restyle, levitation/disintegrate/fire-class effects); VACE 1.3B fast-preview path
- [ ] Upscale/interpolate finishing: SeedVR2-3B hero shots, Real-ESRGAN + RIFE (or FILM) cheap lane
- [ ] Effects stack with camera presets (Higgsfield "Mix" mechanic)

**Accept:** effect preset applied to an existing library asset produces a new derived asset with provenance chain

## M14 — Studio ingest pipeline

- [ ] RQ fan-out per uploaded/generated asset: ffprobe metadata, 720p short-GOP proxy, sprite-sheet + WebVTT scrub thumbnails, waveform peaks (audiowaveform subprocess)
- [ ] All artefacts in MinIO next to the source; assets browsable in the panel

**Accept:** ingest of a test clip produces proxy + sprites + VTT + peaks, all addressable by URI

## M15 — Timeline editor MVP

- [ ] Timeline JSON schema modelled on OpenTimelineIO semantics (validated server-side)
- [ ] Multi-track React timeline: trim, split, move, snap; text overlays; audio tracks
- [ ] Client-side canvas preview over proxies (mediabunny + WebCodecs); "close-enough" WYSIWYG
- [ ] Timeline persists as a document entity, versioned

**Accept:** editor round-trip test: build timeline → save → reload → identical JSON; preview renders without server round-trips

## M16 — Server render compiler

- [ ] Timeline JSON → ffmpeg `filter_complex` compiler in the CPU worker: trim/setpts, per-track overlay, xfade transitions, PNG text overlays, amix + sidechaincompress ducking, segment-then-concat for long timelines
- [ ] Progress reporting via `-progress` parse into the metrics table
- [ ] **Compliance hook: timeline containing any `origin='generated'` asset or avatar footage gets the C1 watermark injected into the filtergraph; frame-sampling test extends to studio renders**

**Accept:** `pytest tests/test_render_compiler.py` — golden filtergraphs for trim/transition/ducking cases; the compliance case proves a generated-asset timeline cannot render without the watermark

## M17 — Identity & consent ("Soul ID" equivalent)

- [ ] `Identity` entity with `consent_recorded_by`/`consent_at`; training and face-bearing generation endpoints refuse identities without consent — structural, like C1–C5
- [ ] LoRA training job (SDXL/Z-Image) on the wan lane, overnight batch
- [ ] Trained identity usable across image studio, storyboards, avatars

**Accept:** `pytest tests/test_identity_consent.py` — training/generation without recorded consent is refused at the API layer

## M18 — Audio suite & prompt intelligence

- [ ] ACE-Step music-bed generation into the library (shared lane)
- [ ] Emotion controls on Chatterbox TTS segments (Speak-style)
- [ ] Qwen3.5-4B (CPU) prompt enhancement for Wan prompts; Florence-2 auto-captioning of assets (feeds the M8 resolver)

**Accept:** music generation lands as licensed-clean library asset; a prompt-enhanced generation records both raw and enhanced prompts
