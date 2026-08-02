# Constraints

Extracted from the two SPECs: docs/pipeline-spec.md and docs/roadmap-v2.md.

## Hardware envelope — RTX 3090, sm_86, no FP8
- source: /Users/karstenhaldan/Video-studio/docs/pipeline-spec.md (§1)
- type: nfr
- content: RTX 3090, 24 GB GDDR6X — one model lane at a time; render and B-roll generation mutually exclusive. Compute capability `sm_86` (Ampere): no FP8 (needs Ada `sm_89` / Hopper `sm_90`); BF16 for inference, GGUF/INT8 for quantised checkpoints. Render-lane VRAM budget: Chatterbox + MuseTalk resident together, peak < 20 GB (asserted by `bench.py --smoke`). B-roll lane: Wan 2.2 quantised ≈ full card, separate queue with exclusive GPU lock (`tests/test_gpu_exclusivity.py`). Thermals: long renders throttle; every stage logs duration to the metrics table; throughput regression is the first throttling symptom. `scripts/verify_gpu.py` asserts capability `(8, 6)` and exits non-zero otherwise.

## Model roster — licences and precision
- source: /Users/karstenhaldan/Video-studio/docs/pipeline-spec.md (§2)
- type: nfr
- content: Chatterbox (MIT, BF16, emits inaudible audio watermark that must survive the encode chain — C3); MuseTalk (MIT, BF16, benefits from the per-loop latent cache); Wan 2.2 (Apache 2.0, GGUF/INT8, never FP8, separate lane only); faster-whisper (MIT, int8 on CPU, word-level timings feed caption burn-in). Rejected (recorded so not relitigated): XTTS v2 (CPML non-commercial), F5-TTS (CC-BY-NC), Wav2Lip (research-only), HunyuanVideo, LTX-2.3, Mochi 1 (fallback). Weights: pinned versions, scripted download, never committed to git; local path via CLAUDE.local.md/env.

## RenderJob canonical JSON + job state machine
- source: /Users/karstenhaldan/Video-studio/docs/pipeline-spec.md (§3)
- type: schema
- content: RenderJob carries id, title, script, status, voice_profile_id, base_loop_id, watermark {text, position, persistent}, publish {altered_content, visibility}, segments [{idx, text, pause_after_ms, audio_uri, duration_ms, seed}], error, timestamps. Single source of truth is `packages/schema/models.py` (the example is illustrative, the schema normative). State machine: `queued → tts → lipsync → assemble → review → publishing → published`; `failed` reachable from any active stage (`failed → queued` retries); `review → queued` for per-segment re-renders; `cancelled` terminal. Every stage idempotent on `(job_id, stage)`; segment-level TTS uses `tts:{idx}`.

## ffmpeg assembly chain
- source: /Users/karstenhaldan/Video-studio/docs/pipeline-spec.md (§4)
- type: protocol
- content: Ingest rule: constant frame rate only — reject VFR at loop ingest, never discover drift at assembly. Assembly order: (1) two-pass `loudnorm` to −14 LUFS (`I=-14:TP=-1.5:LRA=11`); (2) "Made with AI" watermark burn-in, bottom-right, full duration, never a timed overlay (C1, frame-sampled 10/50/90%); (3) caption burn-in from faster-whisper word timings; (4) B-roll overlay/concat at beat timestamps with avatar audio continuing underneath; (5) `libx264 -crf 18 -pix_fmt yuv420p -movflags +faststart`, AAC 192k. C3 constraint: Chatterbox audio watermark must survive loudnorm + AAC (round-trip test). Lip-sync chunked at 60–90 s windows, stitched at assembly.

## Failure-mode handling
- source: /Users/karstenhaldan/Video-studio/docs/pipeline-spec.md (§5)
- type: nfr
- content: VFR source → reject at ingest (never mid-pipeline). CUDA OOM → chunked windows + segment retry, never widen the window on retry. Bad TTS sentence → segment is the retry unit, re-render `tts:{idx}` alone with its pinned seed. Thermal throttling → per-stage metrics, alert on regression not absolutes. Vanishing spot/rented box → stages idempotent on `(job_id, stage)`, re-enqueue always safe. YouTube quota exhaustion → distinguish from real failure, back off to next quota window. Seam pop → perceptual-hash seam detection at ingest, ping-pong fallback.

## Performance budget — PLACEHOLDERS pending workstation measurement
- source: /Users/karstenhaldan/Video-studio/docs/pipeline-spec.md (§6)
- type: nfr
- content: All figures are estimates, not measurements — M0's `bench.py --smoke` replaces them (workstation runbook step 15 in docs/workstation.md §5). Placeholders for an 8-min video: TTS ~2–3 min; lip-sync cached ~6–8 min / first-run ~10–14 min; assembly + encode ~2–3 min; total wall-clock target < 20 min (PSD success criterion); Wan 2.2 5 s clip ~3–6 min. Do not reason from these numbers downstream.

## Service topology
- source: /Users/karstenhaldan/Video-studio/docs/pipeline-spec.md (§7)
- type: protocol
- content: Local: docker-compose provides Postgres 16 (:5432), Redis 7 (:6379), MinIO (:9000, console :9001); API and workers run natively. All addresses flow from env (`.env.example`) through `pipeline_core.settings.Settings`; worker packages contain no service literals (`tests/test_portability.py`). Remote: same worker code, env pointed at a rented box over Tailscale/WireGuard; MinIO swapped for S3/R2 via `S3_ENDPOINT`; workers drain the queue and shut down.

## GenerationProvider layer contract
- source: /Users/karstenhaldan/Video-studio/docs/roadmap-v2.md (§3)
- type: api-contract
- content: One `GenerationProvider` interface; every request names a `(provider, model)` pair. Output always lands in MinIO as an `Asset` (`origin='generated'`) with full provenance (provider, model, params, seed where available, cost) and always passes the same compliance gates — the provider layer cannot bypass them. Provider classes: `local` (wan-lane executor, needs the GPU lock), `remote-gpu` (same executor on a rented box — a provider entry, no new architecture), `api` (network jobs on the CPU lane: submit → poll → download with backoff, never touch the GPU lock). Keys/endpoints from env/Settings only; unconfigured providers absent from the registry. Capability discovery maps model → capabilities (t2v, i2v, camera-control, lipsync, image, upscale, max duration/resolution). Every API generation records billed cost (or estimate). Fallback chains: a preset declares provider preference order. Per-provider ToS grants recorded in the registry at integration time, not assumed; configuring a key is the per-provider data-egress decision.

## Timeline and storyboard schema
- source: /Users/karstenhaldan/Video-studio/docs/roadmap-v2.md (§4)
- type: schema
- content: Timeline JSON schema modelled on OpenTimelineIO semantics (Apache 2.0; `opentimelineio` Python package server-side for validation/interchange); OpenCut (MIT) is the approved open reference. Client preview: canvas compositor over server-generated 720p short-GOP H.264 proxies via mediabunny (MPL-2.0) + WebCodecs; no in-browser export. Server-side final render: timeline-JSON → ffmpeg `filter_complex` compiler in the CPU worker (trim/setpts, per-track overlay + xfade, PNG text overlays, amix + sidechaincompress ducking keyed by the voice bus, segment-then-concat; MLT/melt as escape hatch). Asset ingest fan-out: ffprobe/probe metadata, 720p proxy, sprite-sheet + WebVTT, waveform peaks. Storyboard: ordered `Shot`s (subject + preset stack + duration target), format `long` 16:9 or `short` 9:16 ≤60 s, optional style template; export refuses unfinished boards and over-cap shorts. Compliance hook: any timeline referencing an `origin='generated'` asset (or avatar segment) gets the C1 watermark injected into the filtergraph — structurally, no off-switch.

## GPU lane scheduling
- source: /Users/karstenhaldan/Video-studio/docs/roadmap-v2.md (§5)
- type: protocol
- content: v1 two-lane design extends unchanged (`pipeline_core/locks.py`, `tests/test_gpu_exclusivity.py`). Render lane (shared residents, <20 GB): Chatterbox + MuseTalk, optionally Z-Image Turbo, SDXL, VACE 1.3B previews, Real-ESRGAN, RIFE-class interpolation, ACE-Step base, SeedVR2-3B. Wan lane (exclusive lock): all Wan 2.2 14B variants (T2V/I2V, Fun-Camera, VACE-Fun), Uni3C, ReCamMaster, Qwen-Image 20B, SeedVR2-7B, LoRA training. CPU: ffmpeg render compiler, proxies/sprites/waveforms, Qwen3.5-4B prompt LLM, Florence-2. Wan-lane jobs batch/overnight-friendly, never block a render.

## Licence register (binding)
- source: /Users/karstenhaldan/Video-studio/docs/roadmap-v2.md (§6)
- type: nfr
- content: Adopt (clean for commercial use): Wan 2.2 family incl. Fun-Camera/VACE-Fun (Apache 2.0), Uni3C (Apache 2.0), ReCamMaster (MIT), Z-Image (Apache 2.0), Qwen-Image (Apache 2.0), FLUX.2 Klein 4B only (Apache 2.0), SDXL (OpenRAIL++-M), SeedVR2 (Apache 2.0), Real-ESRGAN (BSD-3), FILM (Apache 2.0), ACE-Step (Apache 2.0), Qwen3.5 (Apache 2.0), Florence-2 (MIT), OpenTimelineIO (Apache 2.0), mediabunny (MPL-2.0), OpenCut code (MIT), Chatterbox (MIT), MuseTalk (MIT). Conditional (revisit before relying on): RIFE (training-data caveat — FILM is the clean fallback), Stable Audio Open (<$1M revenue cap), Civitai camera LoRAs (audit each individually). Sidecar exception (2026-07-31): ComfyUI GPL-3.0 + node packs as an HTTP sidecar only (per-pack licences in `pipeline_core/comfy_nodes.py`); ElevenLabs per paid-plan ToS recorded per asset. Rejected — do not introduce: FLUX.1 [dev] and [dev]-licensed variants, FLUX.2 Klein 9B, MusicGen/AudioCraft, HunyuanVideo 1.x (licence void in EU), LTX-Video 2, MMAudio weights, Llama family, Remotion, openvideodev/react-video-editor, Twick, Etro, editly/FFCreator as dependencies. Model weights on the workstation must stay inside this register (docs/workstation.md §2: "nothing outside it").

## v2 compliance guardrails
- source: /Users/karstenhaldan/Video-studio/docs/roadmap-v2.md (§8)
- type: nfr
- content: C1–C5 carry over unchanged and extend to v2 outputs: any rendered timeline containing generated assets or avatar footage gets the watermark burn-in and `altered_content` on upload; frame-sampling tests extend to studio renders (M16). Identity policy structural like C1–C5 (see REQ-c6-identity-consent). Single-user self-hosted keeps EU AI Act deployer status; offering to others flips to provider (machine-readable marking, consent verification as a feature, liability for users' generations) — not planned, recorded so it cannot happen by drift.
