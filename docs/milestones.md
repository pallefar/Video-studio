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

- [x] Pexels + Pixabay clients behind one `StockProvider` interface *(pipeline_core/stock.py; keys via env, keyless providers unregistered)*
- [x] Ingest downloads to MinIO, persists `license`, `source_url`, `origin='stock'` *(cpu-lane `stock_ingest_stage`; Asset row exists only after bytes land)*
- [x] `has_identifiable_people` defaults `true` on stock ingest; resolver excludes flagged assets
- [x] Caption embedding + cosine search over the library *(deterministic hashing embedder default; `pip install -e ".[embed]"` swaps in MiniLM on CPU)*
- [x] Library browser in the control panel with an approve/flag toggle *(minimal — full panel at M7)*

**Accept:** `pytest tests/test_asset_resolver.py` passes, including the case that a flagged asset is never returned ✅ (2026-07-29)

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

- [x] `GenerationProvider` interface: capability discovery, submit, poll, fetch-to-MinIO; every output lands as an `Asset` (`origin='generated'`) with provider/model/params/cost provenance
- [ ] Local provider: wan-lane executor (decide ComfyUI headless vs diffusers here) running Wan 2.2 T2V/I2V under the existing GPU lock *(lane routing + lock wrapper landed; the executor itself is the workstation decision)*
- [x] API provider class: aggregator gateway first (fal.ai) — keys from env only, unconfigured providers don't appear in the registry *(direct Sora/Veo integrations still open)*
- [x] API jobs run as network jobs on the CPU lane — never touch the GPU lock
- [x] Fallback chains: a request may declare provider preference order *(cross-lane re-dispatch on failure)*
- [ ] Benchmark on the 3090: Fun-Camera A14B GGUF + 4-step LoRA latency and VRAM (decides 14B vs 5B default)

**Accept:** `pytest tests/test_providers.py` — a fake provider round-trips a generation into the asset library with full provenance; unknown models are refused; an API-provider job never acquires the GPU lock ✅ (2026-07-29)

## M11 — Camera presets (the signature)

- [x] Preset registry as data (JSON): camera moves (crash zoom, dolly, dolly-zoom, orbit, FPV, bullet time…) with prompt templates + LoRA refs, stackable up to 3 *(16 presets in `pipeline_core/presets.py`; unaudited-LoRA validation structural)*
- [ ] Wan2.2-Fun-Control-Camera integration in the local provider; Civitai LoRAs individually licence-audited before inclusion *(motion codes + params wired through; executor is the M10 workstation task)*
- [x] Preset picker UI: preset → subject → generate (preset-first, prompt optional) — Higgsfield-style dark gallery, stack up to 3, engine picker from the provider catalog, live generation feed
- [ ] Advanced mode: Uni3C custom trajectories; ReCamMaster re-shoot of existing footage

**Accept:** golden-path test: preset request → generation record → asset with `origin='generated'`; a preset referencing an unaudited LoRA fails validation ✅ (2026-07-29, `tests/test_presets.py`)

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

- [x] Cpu-lane ingest per asset: stream probe (parsed from `ffmpeg -i` — no ffprobe needed with the static build), 720p short-GOP proxy, sprite-sheet + WebVTT scrub thumbnails, waveform peaks (PCM extract + pure-python buckets — no audiowaveform binary needed)
- [x] Derivatives live at the conventional `assets/derived/{asset_id}/` prefix (no schema change); `GET /assets/{id}/derived` presigns whatever exists; the editor's media endpoint prefers the proxy automatically; Ingest button in the library

**Accept:** ingest of a test clip produces proxy + sprites + VTT + peaks, all addressable by URI ✅ (2026-07-29, `tests/test_ingest_pipeline.py` — real ffmpeg end-to-end incl. idempotent re-run)

## M15 — Timeline editor MVP

- [x] Timeline JSON schema modelled on OpenTimelineIO semantics (validated server-side: trim ranges, per-track overlap rejection)
- [x] Multi-track React timeline: trim, split, move, snap, zoom; text overlay track *(audio tracks land with M18's music beds; extra video overlay tracks render post-MVP)*
- [x] Client-side canvas preview over presigned sources — no server round-trips per frame *(mediabunny + WebCodecs over 720p proxies upgrades this with M14's ingest pipeline)*
- [x] Timeline persists as a document entity, versioned (optimistic concurrency: stale saves 409)
- [x] Storyboard → editor hand-off (`POST /storyboards/{id}/edit`) and editor export through the M16 compiler with trims + timed text overlays

**Accept:** editor round-trip test: build timeline → save → reload → identical JSON; preview renders without server round-trips ✅ (2026-07-29, `tests/test_timeline_editor.py`)

## M16 — Server render compiler

- [x] Timeline JSON → ffmpeg `filter_complex` compiler in the CPU worker: per-shot fps/scale/pad/setpts normalisation, concat or xfade transition chain, PNG watermark overlay (Pillow-rendered — no fontconfig dependency), **full audio graph: voice bus from shot audio (silent segments fill gaps, acrossfade under xfade), music bus with gain/delay, sidechaincompress ducking keyed by the voice bus**, silent bed fallback, H.264 CRF 18 yuv420p +faststart *(segment-then-concat optimisation when timelines get long)*
- [x] Progress reporting via `-progress` parse into the metrics table *(`worker_cpu/ffmpeg/progress.py` streams `-progress pipe:1` blocks; the export stage records throttled snapshots + expected total as metric rows; `GET /metrics/exports/{ref}` serves pct/done for polling and the storyboard panel shows a live render bar)*
- [x] **Compliance hook: the watermark decision lives INSIDE the compiler with no off-switch — any `origin='generated'` shot forces the C1 overlay (full duration, bottom-right) and compiling generated content without the overlay raises. Frame-sampling test proves watermark pixels at 10/50/90% of real rendered output**
- [x] `export_stage` renders for real: fetch shots from the store → compile → ffmpeg (system binary or imageio-ffmpeg static) → upload → the export lands as an asset in the library and the project pool

**Accept:** `pytest tests/test_render_compiler.py` — golden filtergraphs (single/concat/xfade/short-format), the compliance cases, real end-to-end renders, and C1 frame sampling ✅ (2026-07-29)

## M17 — Identity & consent ("Soul ID" equivalent)

- [x] `Identity` entity with `consent_recorded_by`/`consent_at`; training and face-bearing generation endpoints refuse identities without consent — structural, like C1–C5 *(C6 in api/validators/compliance.py, re-checked in the wan-lane worker so a raw enqueue can't bypass the route; consent is append-once)*
- [ ] LoRA training job (SDXL/Z-Image) on the wan lane, overnight batch *(stage + queue routing + exclusive-lock orchestration landed in `worker_gpu.stages.identity_training_stage`; the real trainer in `worker_gpu/engines/identity.py` is the workstation task, like M3's engines)*
- [ ] Trained identity usable across image studio, storyboards, avatars *(generations accept `identity_id` and carry the trained LoRA uri into provider params; storyboard/avatar wiring follows the M10 executor)*
- [x] Identities tab in the panel: create, record consent (append-once), train/retrain with status chips

**Accept:** `pytest tests/test_identity_consent.py` — training/generation without recorded consent is refused at the API layer ✅ (2026-07-29)

## M18 — Audio suite & prompt intelligence

- [x] Audio infrastructure (landed ahead of the models): timeline audio tracks (`AudioClip` with gain + per-clip duck flag), shot audio forms the voice bus in exports, music beds mix under it with sidechain ducking, `POST /assets/upload` brings your own music/footage in, and every worker stage records its duration to the metrics table (`GET /metrics`)
- [ ] ACE-Step music-bed generation into the library (shared lane)
- [ ] Emotion controls on Chatterbox TTS segments (Speak-style)
- [ ] Qwen3.5-4B (CPU) prompt enhancement for Wan prompts; Florence-2 auto-captioning of assets (feeds the M8 resolver)

**Accept:** music generation lands as licensed-clean library asset; a prompt-enhanced generation records both raw and enhanced prompts

## M19 — Storyboards, style templates & formats

Owner requirement (2026-07-29): per-video storyboard planning, style templates,
full-length + Shorts formats, export path. Full design: docs/roadmap-v2.md §4.

- [x] `Storyboard` + `Shot` entities (alembic 0003): ordered shots with subject, preset stack, duration target; format `long` (16:9) / `short` (9:16, ≤60 s)
- [x] Style template registry as data (`pipeline_core/styles.py`, 8 curated looks); style suffix applied to every shot generation, grade params reserved for M16
- [x] Per-shot generation through the provider layer — format resolution/aspect/duration cap flow into generation params; succeeded generations link their asset to the shot
- [x] Export compiles the storyboard into an ordered timeline document (409 on unfinished shots; shorts capped at 60 s total) and enqueues the cpu-lane export job
- [x] Full-length render of the exported timeline — landed with the M16 ffmpeg compiler: export now produces a real MP4 back into the library/project pool
- [x] Storyboards tab in the panel: board list + create (title/format/style), shot rows with status chips, per-shot generate/regenerate, export button gated on readiness

**Accept:** `pytest tests/test_storyboards.py` — style+format flow into generation params, shorts duration cap enforced at generation and export, export refuses unfinished boards, ordered timeline compiled ✅ (2026-07-29)

## M20 — Projects: asset center → video center

Owner requirement (2026-07-29): a project per video-effort — build the asset pool
first (asset creation center), assemble videos from it after (video creation
center). Assets are shared: one asset serves any number of projects and stands
alone for social posting.

- [x] `Project` entity + `ProjectAsset` many-to-many link (alembic 0004); storyboards and generations carry an optional `project_id`
- [x] Generations scoped to a project auto-link their output asset into the project pool on success
- [x] Attach/detach any library asset to any project — detaching never removes it from the library or other projects
- [x] Shots can use a pooled asset directly (`asset_id` on shot creation) — no generation needed; export works from pooled assets alone
- [x] `GET /assets/{id}/download` — presigned URL for social posting / external tools
- [x] Panel: Projects home tab — project switcher, then "1 · Asset center" (preset generation scoped to the project + pool/library attach-detach-download) and "2 · Video center" (the project's storyboards)

**Accept:** `pytest tests/test_projects.py` — cross-project asset sharing, auto-link on generation success, pooled-asset shots exporting, presigned downloads ✅ (2026-07-29)
