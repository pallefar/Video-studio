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

- [x] Ingest base footage, enforce constant frame rate at ingest (reject VFR) *(cpu-lane `loop_preprocess_stage` auto-enqueued on loop creation; ffmpeg `vfrdet` — no ffprobe needed; ratio > 0.05 marks the loop rejected with an error, never discovered at assembly)*
- [x] Seam detection via perceptual hash, ping-pong fallback *(dHash + colour distance in `pipeline_core/seam.py`; a popping boundary re-renders as forward+reverse — seamless by construction — and swaps `source_uri`, doubling `frame_count`)*
- [ ] Latent cache built and persisted per loop *(the MuseTalk latent build in `worker_gpu/preprocess/loop_cache.py` is the GPU-host task)*
- [ ] Second render against a cached loop is measurably faster than the first *(needs the real latent cache)*

**Accept:** `python scripts/bench.py --loop <id>` shows cached run ≥ 40% faster *(CPU half proven in `tests/test_loop_preprocess.py` ✅ 2026-07-29; the cache benchmark is the workstation acceptance)*

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

- [x] Loudness normalise to −14 LUFS *(two-pass loudnorm: measure JSON → linear apply; output verified at −14 ±1.5 in the encode test)*
- [x] Watermark burn-in, full duration, bottom-right *(Pillow PNG overlay applied LAST in the graph, no enable= window — C1 has no off-switch: avatar output is always synthetic)*
- [x] Caption burn-in from faster-whisper word timings *(word timings via faster-whisper when installed; deterministic even-split over real TTS durations until then; burned as fontconfig-free PNG overlays)*
- [x] B-roll insertion at timestamps *(resolver-driven cutaways at segment beats, ≤4 s, voice bus continues; flagged/unapproved assets never selected)*
- [x] H.264 CRF 18, yuv420p, `+faststart` *(AAC 192k; C3 encode-chain probe: near-ultrasonic content survives loudnorm+AAC round-trip)*

**Accept:** an 8-minute job completes end to end; output plays in VLC and Chrome with correct A/V sync *(chain proven end-to-end on synthetic chunks in `tests/test_assemble.py` ✅ 2026-07-29; the 8-minute real-model run is the workstation acceptance)*

## M5 — Compliance gate

- [x] Validator rejects any job with `watermark.persistent != true` *(schema-level validator + gate + tests landed with M1)*
- [x] Validator rejects any job with `publish.altered_content != true` *(schema-level validator + gate + tests landed with M1)*
- [x] Provenance record written before publish is permitted *(publish route enforces this since M1; the M6 worker re-checks C4 before any upload)*
- [x] Frame sampling asserts watermark pixels present at 10%, 50%, 90% of duration *(on real assembled output — `tests/test_assemble.py::test_c1_watermark_frame_sampling`; M16 studio renders had it already)*

**Accept:** `pytest tests/test_compliance.py` passes, including the negative cases ✅ (2026-07-29)

## M6 — Publish

- [x] YouTube Data API v3, OAuth, refresh token persisted *(refresh-token flow in `worker_cpu/publish.py`; creds from env via Settings; unconfigured → the stage waits, `pip install -e ".[publish]"` on the box that uploads)*
- [x] Uploads land `private`, always — no path publishes directly *(privacyStatus is bound to a constant, never a parameter; asserted structurally in `tests/test_publish_worker.py`)*
- [x] `altered_content` set programmatically on upload *(`containsSyntheticMedia: true` on every insert)*
- [x] Exponential backoff; quota exhaustion is distinguished from real failure *(quota → job parks in `publishing` for the next window, no hammering; transient errors retry ×4 then fail retryably; C4 re-checked in the worker)*

**Accept:** a real upload lands private with the disclosure flag visible in Studio *(worker proven against a fake client ✅ 2026-07-29; the real-credential upload is the workstation acceptance)*

## M7 — Control panel

- [x] Submit script, pick loop + voice profile *(Avatar tab: script form with voice/loop pickers + inline creation)*
- [x] Job list with live status *(2 s polling; plain fetch — TanStack Query optional later)*
- [x] Preview before publish, per-segment re-render button *(video player over the presigned M4 output via `GET /jobs/{id}/preview`; re-render button with emotion picker)*
- [x] Manual publish confirmation — never automatic *(review-gated Publish button asks who reviewed; C5 message states the upload lands private)*

**Accept:** a full video produced without touching the terminal

## M8 — Stock ingest + asset library

- [x] Pexels + Pixabay clients behind one `StockProvider` interface *(pipeline_core/stock.py; keys via env, keyless providers unregistered)*
- [x] Ingest downloads to MinIO, persists `license`, `source_url`, `origin='stock'` *(cpu-lane `stock_ingest_stage`; Asset row exists only after bytes land)*
- [x] `has_identifiable_people` defaults `true` on stock ingest; resolver excludes flagged assets
- [x] Caption embedding + cosine search over the library *(deterministic hashing embedder default; `pip install -e ".[embed]"` swaps in MiniLM on CPU)*
- [x] Library browser in the control panel with an approve/flag toggle *(minimal — full panel at M7)*

**Accept:** `pytest tests/test_asset_resolver.py` passes, including the case that a flagged asset is never returned ✅ (2026-07-29)

## M9 — Generative B-roll lane

- [ ] Wan 2.2 quantised (GGUF/INT8) loads and generates a 5 s clip *(the executor is the M10 workstation task)*
- [x] Runs as a separate queue with an exclusive GPU lock — never concurrent with the render lane *(the lock landed early in `pipeline_core/locks.py`, proven by `tests/test_gpu_exclusivity.py` against real Redis; wan-lane jobs consume it via `generation_stage_local`)*
- [x] Generation requests enqueue and never block a render job *(separate `wan` queue — enqueueing never touches the render queue; lock contention re-raises as transient)*
- [x] Output lands in the library as `origin='generated'`, `approved=false` *(`run_generation`, proven in `tests/test_providers.py`)*
- [x] Approval gate in the control panel before an asset becomes selectable *(library approve/flag toggle; the resolver never returns an unapproved asset — `tests/test_asset_resolver.py`)*

**Accept:** `pytest tests/test_gpu_exclusivity.py` proves render and generation lanes cannot hold the GPU simultaneously; an unapproved generated asset is never selected by the resolver ✅ (2026-07-29; the real Wan 2.2 load is the workstation task)

---

# v2 — Higgsfield-class studio (planned)

Full plan and research: `docs/roadmap-v2.md`. Prerequisite: v1 M2–M7 shipped.
Owner decisions 2026-07-29: clone Higgsfield's capabilities self-hosted, add a real
multi-track video studio, and make the system a model aggregator — open models
locally/on rented GPUs AND proprietary models via API, behind one interface.

## M10 — Generation provider layer + wan-lane executor

- [x] `GenerationProvider` interface: capability discovery, submit, poll, fetch-to-MinIO; every output lands as an `Asset` (`origin='generated'`) with provider/model/params/cost provenance
- [x] Local provider: wan-lane executor — **ComfyUI headless decided and landed**: `pipeline_core/comfy.py` submit→poll→fetch client + per-model workflow templates as package data, CPU-proven against a fake ComfyUI (`tests/test_comfy.py`); `DEV_ENGINES=1` placeholder executor covers non-CUDA e2e; real-weights rendering = `COMFY_URL` config on the workstation (docs/workstation.md)
- [x] API provider class: aggregator gateway first (fal.ai) — keys from env only, unconfigured providers don't appear in the registry *(direct Sora/Veo integrations still open)*
- [x] API jobs run as network jobs on the CPU lane — never touch the GPU lock
- [x] Fallback chains: a request may declare provider preference order *(cross-lane re-dispatch on failure)*
- [ ] Benchmark on the 3090: Fun-Camera A14B GGUF + 4-step LoRA latency and VRAM (decides 14B vs 5B default)

**Accept:** `pytest tests/test_providers.py` — a fake provider round-trips a generation into the asset library with full provenance; unknown models are refused; an API-provider job never acquires the GPU lock ✅ (2026-07-29)

## M11 — Camera presets (the signature)

- [x] Preset registry as data (JSON): camera moves (crash zoom, dolly, dolly-zoom, orbit, FPV, bullet time…) with prompt templates + LoRA refs, stackable up to 3 *(16 presets in `pipeline_core/presets.py`; unaudited-LoRA validation structural)*
- [ ] Wan2.2-Fun-Control-Camera integration in the local provider; Civitai LoRAs individually licence-audited before inclusion *(motion codes + params wired through; runs once COMFY_URL points at the workstation ComfyUI — docs/workstation.md)*
- [x] Preset picker UI: preset → subject → generate (preset-first, prompt optional) — Higgsfield-style dark gallery, stack up to 3, engine picker from the provider catalog, live generation feed
- [ ] Advanced mode: Uni3C custom trajectories; ReCamMaster re-shoot of existing footage

**Accept:** golden-path test: preset request → generation record → asset with `origin='generated'`; a preset referencing an unaudited LoRA fails validation ✅ (2026-07-29, `tests/test_presets.py`)

## M12 — Image studio ("Soul" equivalent)

- [x] Z-Image Turbo (daily driver), Qwen-Image (thumbnails/text), SDXL (style LoRAs) in the provider registry *(registry entries with kind `image`; rendering waits on the M10 wan-lane executor or an API provider, like every local model)*
- [x] Style preset registry (curated looks, seasonal drops are content not code) *(shared with M19's style templates — one curated-look registry serves stills and video)*
- [x] Storyboard mode: multi-frame with shared seed/style ("Popcorn" equivalent) *(`frames > 1` on `POST /images/generate`: one seed for the request, shared params recorded on every frame)*
- [x] Thumbnail pipeline for the YouTube flow *(`POST /images/thumbnail`: 1280x720 on qwen-image, title text in the prompt template)*

**Accept:** style preset → image lands in library; storyboard produces N frames with recorded shared params ✅ (2026-07-29, `tests/test_image_studio.py`; Images tab in the panel with engine/style/identity pickers)

## M13 — VFX & finishing lane

- [x] Effect preset registry over Wan2.2-VACE-Fun (v2v restyle, levitation/disintegrate/fire-class effects); VACE 1.3B fast-preview path *(10 effects in `pipeline_core/effects.py`; `POST /effects/apply` with `preview` routing to the 1.3B model; renders once COMFY_URL is configured — docs/workstation.md)*
- [x] Upscale/interpolate finishing: SeedVR2-3B hero shots, Real-ESRGAN + FILM cheap lane *(RIFE stays out per the licence register's training-data caveat; `POST /effects/upscale`)*
- [x] Effects stack with camera presets (Higgsfield "Mix" mechanic) *(`compose_mix` reuses the M11 camera stack rules; motion codes ride along in params)*

**Accept:** effect preset applied to an existing library asset produces a new derived asset with provenance chain ✅ (2026-07-29, `tests/test_effects.py`; chain walkable via `GET /assets/{id}/provenance`, Effects/Upscale actions in the library panel)

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
- [x] ACE-Step music-bed generation into the library (shared lane) *(`POST /music/generate`; ModelSpec lane routing — shared residents ride the render queue under the render holder, never the wan lock; asset lands with its Apache-2.0 licence recorded; the real ACE-Step load is the workstation task like every local model)*
- [x] Emotion controls on Chatterbox TTS segments (Speak-style) *(data-driven preset registry in `pipeline_core/emotions.py` mapping to exaggeration/cfg_weight; `Segment.emotion` pinned next to the seed; per-segment re-render endpoint carries emotion/reseed; tts stage passes delivery params to the engine — audible once M3's real Chatterbox lands)*
- [x] Qwen3.5-4B (CPU) prompt enhancement for Wan prompts; Florence-2 auto-captioning of assets (feeds the M8 resolver) *(enhancement: `enhance=true` records raw+enhanced via `pipeline_core/enhance.py`, heuristic now applies the M27 structure frame, Qwen GGUF via `[enhance]` + `QWEN_MODEL_PATH`; captioning landed as M24's Florence-2 lane — the real weight loads are the workstation install)*

**Accept:** music generation lands as licensed-clean library asset; a prompt-enhanced generation records both raw and enhanced prompts ✅ (2026-07-29, `tests/test_music_and_enhance.py`)

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

## M21 — MCP control surface (any-LLM access; movie/game/other productions)

- [x] `studio_mcp` package: MCP server over stdio (`python -m studio_mcp`), a thin client of the HTTP API — every call passes the same routes and compliance gates as the panel; `STUDIO_API_URL` from env
- [x] ~25 tools: stats, projects, library (search/provenance/downloads), preset video, styled/shared-seed images, thumbnails, music, VFX + Mix, upscale, full storyboard flow with export progress, avatar jobs to the review gate
- [x] Human-judgement boundary is structural: publish (C5), consent (C6), and approve/flag have NO tools — asserted by `tests/test_mcp.py` against the server's tool registry
- [x] Production workflow prompts shipped with the server: `movie_scene_workflow`, `game_asset_batch`, `youtube_video_workflow`
- [x] `Project.kind` (video/movie/game/other, alembic 0012) organises productions; kind picker in the Projects tab

**Accept:** `pytest tests/test_mcp.py` — tools drive the real app end-to-end via ASGI transport; forbidden tools cannot exist; project kinds round-trip; a game asset batch shares one seed ✅ (2026-07-30; setup guide in docs/mcp.md)

## M22 — Cost tracking + observability

- [x] `ModelSpec.est_cost` as data: local models 0.0 (free, distinct from unpriced), fal roster carries per-generation estimates; `billed_cost` from the provider response wins over the estimate
- [x] `/stats` cost rollups via SQL aggregates: total, last-30d window, by-provider, by-project — coalesced to zeros on an empty DB
- [x] Engine pickers show price (`CatalogEntry.est_cost`); Dashboard "Spend 30d" tile; per-project cost chip in the Projects switcher — the single-user replacement for Higgsfield's credit system (roadmap §3)
- [x] Dependency-free SVG charts (`web/src/components/charts.tsx`, currentColor so both themes work): Dashboard "Stage durations" trend cards per stage — last run vs median with a `slow` chip when last > 1.5× median — **the thermal-throttle view the metrics table exists for** (pipeline-spec §5)

**Accept:** `pytest tests/test_dashboard.py tests/test_providers.py` — cost rollups incl. the empty-DB and out-of-window cases; billed-over-estimate precedence ✅ (2026-07-31)

## M23 — Editor v2: transport, audio lane, hover-scrub

- [x] Transport: play/pause (button + spacebar), rAF playhead advance on real-time delta; playing clips free-run the decoder and only correct >250 ms drift — no per-frame seeking; canvas sized by `doc.format` (16:9 / 9:16)
- [x] Audio lane: `doc.audio_tracks[0]` rendered and editable (add-from-library picker, move/trim via the shared drag machinery, gain 0–4 + duck toggle feeding the M16 sidechain graph); waveform strip from M14 `peaks.json` via the shared `Bars` chart; beds play under the transport (preview volume clamped at 1× — gain >1 applies at export)
- [x] Hover-scrub: `sprite.vtt` `#xywh` cues + `sprite.jpg` background-position floating thumb above the pointer — first consumer of the M14 sprite derivatives
- [x] Server: `GET /timelines/{id}/media` presigns audio-track assets alongside video clips
- [x] **Best-of-both merge on overlapping features** (OpenCut's mechanic adopted wherever theirs was stronger): visual **snap indicator line** during drags; **ctrl/cmd+wheel zoom anchored at the cursor** (trackpad pinch included — slider stays for coarse control); **true frame stepping** (←/→ = one 25 fps export frame, shift = 1 s); **drag-time overlap prevention** (their placement span-test — a drag clamps against neighbours instead of saving a 422); **paste at the playhead** when the run fits, lane-end fallback; **ruler drag-to-scrub**
- [x] **Studio layout, chosen in-app**: OpenCut's panel system — Assets (searchable library with thumbs, click-to-append; audio routes to the bed lane) | centered preview + full transport (⏮ ◀ ▶ ⏭, mono time readout) | context-sensitive Properties inspector (clip start/in/out seconds, audio gain/duck, text content + vertical position + timing) — over the full-width timeline; a persisted Studio/Simple toggle in the editor header keeps the original compact layout one click away; copy/paste (ctrl+C/V, appends at lane end to respect the no-overlap rule) and select-all (ctrl+A) complete the OpenCut action set
- [x] **OpenCut-grade editing UX** (patterns studied from OpenCut MIT, `pre-rewrite` tag — the licence register's approved reference): snapshot **undo/redo** (ctrl+Z / ctrl+shift+Z / ctrl+Y, one history entry per drag gesture), **S/Q/W** split / trim-left / trim-right at playhead (selection else clip-under-playhead), **ripple delete** (shift+del — later clips on every lane shift left so beds/titles stay in sync with the cut), **ctrl+D duplicate**, J/K/L + arrow-key transport (step/jump/home/end), **N** snap toggle (toolbar button too), shift-click **multi-select**, esc deselect, shortcut hint strip
- [x] **mediabunny (MPL-2.0) landed as the editor decode engine** — the licence-clean answer to "add Remotion" (Remotion/react-video-editor stay rejected, roadmap §6): `web/src/lib/frameSource.ts` wraps `Input`/`UrlSource`/`CanvasSink` for frame-exact WebCodecs decode of paused/scrub frames over the ingest proxies, dynamically imported so the demuxers live in a lazy chunk; `<video>` free-run stays for real-time playback and is the automatic fallback when the codec/browser can't decode

**Accept:** `pytest tests/test_timeline_editor.py` incl. audio-media presigning ✅ (2026-07-31; playback/waveform/scrub verified in-browser against the live stack — note: Playwright's OSS Chromium lacks H.264, real Chrome plays the ingest proxies natively)

## M24 — Library intelligence: Florence-2 auto-captioning

- [x] `pipeline_core/captioner.py`: Florence-2-base (MIT, licence register §6) `<MORE_DETAILED_CAPTION>` on CPU behind the `[caption]` extra; `NoopCaptioner` fallback keeps the lane alive without weights; `is_placeholder_caption()` heuristic (filenames, uuids, upload defaults)
- [x] Cpu-lane `caption_stage`: poster-frame source (image assets caption directly), idempotent — real captions are never overwritten unless `force`; caption is re-embedded so the M8 resolver finds assets by visual content; enqueued best-effort at the ingest tail
- [x] `POST /assets/{id}/caption` (202, `?force=true` to overwrite) — same route the panel and MCP can use
- [x] `scripts/backfill_embeddings.py`: fills missing resolver vectors inline; `--recaption` queues Florence-2 jobs for placeholder captions

**Accept:** `pytest tests/test_captioning.py` — placeholder heuristic, stage idempotency + re-embedding with an injected fake captioner, ingest-tail wiring, backfill script ✅ (2026-07-31; the real Florence-2 load is a workstation install like every local model)

## M25 — Ops: backup, restore, services

- [x] `scripts/backup.sh`: `pg_dump -Fc` (sqlite copy in dev) + incremental bucket mirror via `scripts/sync_bucket.py` — ObjectStore only, works against MinIO and S3/R2 alike; redis deliberately excluded (stages idempotent, docs/ops.md)
- [x] `scripts/restore.sh`: `pg_restore --clean --if-exists` + gap-filling bucket push (never clobbers newer artefacts); **drill executed against the live container stack** — snapshot → scratch DB + scratch bucket → verified contents
- [x] `.env.example` audit: every Settings field documented (stock/fal keys, YouTube OAuth, QWEN_MODEL_PATH, DEV_ENGINES, COMFY_*) with a two-way drift guard in `tests/test_ops.py`
- [x] `deploy/systemd/` (api, worker-cpu, worker-gpu, worker-wan, comfyui) + `deploy/launchd/` Mac dev-mode units — the wan queue finally has a dedicated runner (`worker_gpu/run_wan.py`, landed with Phase A); GPU units are single-instance by construction, never templated

**Accept:** `pytest tests/test_ops.py` — env drift both directions, sync round-trip incl. incremental/no-clobber semantics, unit coverage per lane ✅ (2026-07-31; backup+restore drill run against the live stack)

## M26 — Timeline completion, reliability, publish-everything, web tests

- [x] **Timeline feature completion**: per-clip audio fades (`fade_in_ms`/`fade_out_ms`, afade in the compiler's music chain, sliders + waveform ramps in the editor); `transition_ms` exposed as a Document properties section with boundary markers; **overlay video track rendered** — `video_tracks[1]` compiles as top-right PiP (1/3 width, under texts, always under C1; a generated overlay forces the watermark like a generated shot) with a dedicated editor lane, PiP add button and live preview compositing; filmstrip clip thumbnails from the M14 sprites; marquee rubber-band selection across all four lanes
- [x] **Reliability & control**: generation retry (failed→queued) / cancel (queued→cancelled, honoured by the worker), `/stats` health block (RQ worker liveness + queue depths, degrades with redis down), booleans-only `GET /config`, Settings tab (config checklist, worker chips with stale detection, DEV_ENGINES banner), dependency-free toasts, Library Caption button
- [x] **Publish everything**: migration 0013 lets `PublishRecord` reference an asset (exactly-one-subject check constraint); `POST /assets/{id}/publish` + `publish_asset_stage` reuse the M6 uploader — C4 record first, C5 review required, private always, quota parks; Library Publish action; MCP still publish-tool-free
- [x] **Frontend test harness**: pure timeline logic extracted to `web/src/lib/timelineOps.ts`; vitest with 21 unit cases; CI web job runs `npm test` + full build

**Accept:** `pytest tests/test_render_compiler.py tests/test_reliability.py tests/test_publish_worker.py tests/test_timeline_editor.py` + `npm test` ✅ (2026-07-31; PiP visibility proven on a real render, browser pass over fades/marquee/Settings)

## M27 — Prompt intelligence: catalog + reverse prompt engineering

- [x] `pipeline_core/prompts.py`: 30-entry curated prompt catalog as data — Wan structure frames with `{subject}` slots, camera language, motion qualifiers, lighting, style/film-stock, composition, standard video/image negatives, ACE-Step music tags; every technique entry carries its source attribution (wan27/VEED/InstaSD/MimicPC guides, roblaughter style-reference, SD modifier collections), audited by tests
- [x] `SavedPrompt` entity (alembic 0014) + `/prompts` CRUD — the user's prompt library (manual | catalog | reverse)
- [x] Reverse prompt engineering: `POST /prompts/reverse/{asset_id}` — Florence-2 caption (M24) → structure-framed prompt + kind-appropriate standard negative; `?save=true` files it; Library "→ Prompt" action
- [x] Enhancer upgrade: the heuristic applies the structure frame when a prompt lacks camera language — `enhance=true` produces Wan-shaped prompts even without Qwen weights
- [x] Prompts tab (searchable catalog, category chips, copy/save, source links, My prompts) + MCP tools (`prompt_catalog`, `reverse_prompt`, `save_prompt`, `list_saved_prompts`)

**Accept:** `pytest tests/test_prompts.py` — registry audit incl. attribution, CRUD round-trip, reverse-prompt paths incl. the placeholder-caption refusal, enhancer frame cases, MCP exposure ✅ (2026-07-31)

## M28 — Leonardo-class image studio, image→motion, audio suite UI

- [x] **Image studio v2** (Leonardo-style): settings rail (engine picker with price/notes, style gallery, aspect presets, frames/seed/identity) + prompt bar + a real generation gallery with image previews and per-image actions — Animate, Talk, Upscale, → Prompt, Download
- [x] **Image animation — the cheap-b-roll path**: `POST /images/animate` turns any library still into an i2v generation (wan2.2-i2v default, provenance via `source_asset_id`); the dev executor animates the actual still (slow push-in) so the flow is honest end-to-end without a GPU
- [x] **Talking & singing photos**: new `talking_image` kind on `musetalk-image` (MIT, render lane) — `POST /images/talk` takes a script (talking, optional voice profile) XOR an audio asset (singing); **C6 is not optional here**: a consented identity is required, asserted by tests; dev executor muxes still + speech-shaped audio into a real A/V clip
- [x] **Audio tab + voiceovers**: new `voice` kind on `chatterbox` (MIT, render lane), `POST /music/voice`; Audio section with ACE-Step music generation (catalog tag chips), voiceover form, and a play-in-place feed; ComfyUI template skeletons for both new kinds (`musetalk-image.json`, `chatterbox.json`) pass the structural audit
- [x] **ComfyUI installed and connected**: `scripts/install_comfyui.sh` (clone + venv + torch + requirements); `/config` gains `comfy_online` (live `/system_stats` ping, never just "configured"); Settings shows online / configured·offline / not set; the studio's client proven against a real ComfyUI — submit → poll → collect round-trip returning genuine bytes

**Accept:** `pytest tests/test_media_kinds.py` — animate/talk/voice routing incl. the C6-required and XOR negatives, dev A/V muxing probed with ffmpeg, comfy_online both ways ✅ (2026-07-31; full chain verified live in-browser: generate image → Animate → i2v asset, music + voiceover succeeded, Settings showing ComfyUI online)

## M29 — ComfyUI plugin installer + ElevenLabs provider

- [x] Node-pack manifest as data (`pipeline_core/comfy_nodes.py`): repo, licence, provided node types, dependent templates — GPL packs recorded under the sidecar exception (roadmap §6); `install_comfyui.sh` clones the exact manifest list (drift-guarded by `tests/test_comfy.py`) and exports the studio's workflow templates into ComfyUI's own UI (`user/default/workflows/studio-*.json`)
- [x] Live node-pack check: `ComfyUIClient.object_info()` + `GET /config/comfy` diff the templates against the running ComfyUI; Settings shows per-pack installed/missing chips with the repo to install — verified against a real ComfyUI (5/6 packs importable on the CPU container; MuseTalk's mmlab stack is the documented GPU-host install, docs/workstation.md §1)
- [x] Chatterbox template aligned with the real installed pack (`FL_ChatterboxTTS`, schema verified via `/object_info`)
- [x] ElevenLabs API provider (`eleven-tts`/`eleven-sfx`/`eleven-music`): key from env only, unconfigured → not registered; CLASS_API → network jobs on the cpu lane, never the GPU lock; per-plan commercial licence recorded on every generated asset; SFX duration clamped to the API cap
- [x] Audio tab engine pickers (local vs ElevenLabs with price), ElevenLabs voice-id field; Settings ElevenLabs row; `.env.example` + Settings drift guard holds

**Accept:** `pytest tests/test_comfy.py tests/test_providers.py` — manifest audit, install-script drift guard, `/config/comfy` missing-pack detection, ElevenLabs adapter (headers/clamps/costs) and cpu-lane routing ✅ (2026-07-31; node packs installed into the live ComfyUI, Settings verified in-browser)
