# Decisions

Extracted from decision-bearing sections of the ingested docs. No source doc is an ADR and
none carries `locked: true`, so every entry is `status: proposed` (classification-accurate);
the decision text records owner dates and finality language verbatim where the source has it.

## DEC-v1-stack: v1 stack selection
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§2)
- status: proposed
- decision: FastAPI + Pydantic v2 (API), Redis + RQ (queue), SQLModel + Alembic (ORM), Python native-venv GPU worker, Python + ffmpeg CPU worker, Vite + React + TS control panel, TanStack Query (client state), Tailwind + shadcn/ui, Docker Compose for Postgres/Redis/MinIO only. GPU layer forces Python (MuseTalk/Chatterbox have no JS bindings).
- scope: whole v1 stack

## DEC-no-nextjs: No Next.js — Vite SPA served by FastAPI
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§2.1)
- status: proposed
- decision: Single-user localhost tool: no SEO/SSR/server components/auth. Vite SPA hitting a JSON API; FastAPI serves the built bundle as static files — one origin, no CORS, no second deploy target.
- scope: frontend architecture

## DEC-gpu-worker-native: GPU worker not containerised locally; container is a CI build artefact
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§2.1)
- status: proposed
- decision: Run the GPU worker natively in a venv for local development (CUDA-in-Docker driver/toolkit mismatch risk). From M3 the container is written and built in CI on every push, but not run locally.
- scope: GPU worker deployment

## DEC-rented-gpu-portability: Design for rented GPUs from M1
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§2.2)
- status: proposed
- decision: All I/O through the S3 API (no local filesystem paths in the worker); no `localhost` in worker config (addresses from env); GPU worker stateless (queue + object store only); model weights pinned + scripted download; every stage idempotent on `(job_id, stage)`. Workers drain a queue, never one box per video. Rented boxes reached over Tailscale/WireGuard, never publicly exposed Redis/Postgres.
- scope: portability, worker architecture

## DEC-broll-asset-library: B-roll is an asset library, not a render stage
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§4.1)
- status: proposed
- decision: Wan 2.2 quantised consumes essentially the whole 3090 and cannot be resident alongside Chatterbox + MuseTalk, so B-roll generation is pre-produced into a searchable library; render jobs select from it via a three-tier resolver (library → stock API → generative, tier 3 never blocks a render).
- scope: B-roll subsystem, VRAM architecture

## DEC-wan22: Wan 2.2 for generative video; rejections recorded
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§4.1)
- status: proposed
- decision: Wan 2.2 (Apache 2.0), quantised GGUF/INT8 — never FP8 (sm_86). Rejected so it isn't relitigated: HunyuanVideo (Tencent community licence), LTX-2.3 (FP8 + 32 GB hardware mismatch), Mochi 1 (viable fallback, weaker feature set).
- scope: generative video model

## DEC-stock-providers: Pexels primary, Pixabay secondary; Unsplash rejected
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§4.1)
- status: proposed
- decision: Deciding factor is caching rights: Pixabay explicitly permits download/cache/serve from own infrastructure; Unsplash's hotlink/attribution rules fight the MinIO architecture and it has no video.
- scope: stock media providers

## DEC-stock-people-policy: Stock people-risk policy
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§4.1)
- status: proposed
- decision: `Asset.has_identifiable_people` required, defaulted `true` on stock ingest until a human clears it; flagged assets cannot be selected by the resolver; buy indemnified stock (Adobe/Getty/Storyblocks) if people-on-camera is genuinely needed; persist `license` + `source_url` on every asset at ingest.
- scope: asset library, legal exposure

## DEC-immutable-profiles: VoiceProfile/BaseLoop immutable once referenced
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§4)
- status: proposed
- decision: Re-cloning creates a new version (e.g. `karsten_v3`), never mutates an existing one — otherwise the back catalogue drifts and old renders cannot be reproduced.
- scope: data model versioning

## DEC-structural-compliance: Compliance enforced structurally, not procedurally
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§6)
- status: proposed
- decision: Anything that must hold unconditionally goes in a validator, a test, or a hook — never only in CLAUDE.md (context, not enforcement). C1–C5 live in `tests/test_compliance.py`, wired into CI.
- scope: compliance enforcement method

## DEC-v2-scope: v2 = Higgsfield-class aggregator + real multi-track studio
- source: /Users/karstenhaldan/Video-studio/docs/roadmap-v2.md (header, §0–§2)
- status: proposed
- decision: Owner decision 2026-07-29: clone Higgsfield's capabilities and product mechanics self-hosted single-user, add a real multi-track video editing studio, and make the system a model aggregator (open models locally, same models on rented GPUs, proprietary frontier models via API) behind one interface. SaaS mechanics (credits, tiers, referrals, feed, app store) not cloned.
- scope: v2 product scope

## DEC-provider-layer: Provider layer — local / remote-gpu / api classes
- source: /Users/karstenhaldan/Video-studio/docs/roadmap-v2.md (§3)
- status: proposed
- decision: Owner requirement 2026-07-29: one `GenerationProvider` interface; aggregator gateways first (fal.ai, Replicate), direct APIs where it matters (Sora, Veo, Runway, ElevenLabs). API keys from env only; unconfigured providers don't appear. API jobs are network jobs on the CPU lane, never touching the GPU lock. Cost tracked per generation; fallback chains by provider preference order.
- scope: model aggregation architecture

## DEC-licence-policy: Licence policy — MIT/Apache rule, register, sidecar exception
- source: /Users/karstenhaldan/Video-studio/docs/roadmap-v2.md (§6)
- status: proposed
- decision: The MIT/Apache rule governs model weights and studio dependencies; the §6 register is the binding adopt/conditional/rejected list. Sidecar exception (recorded 2026-07-31): ComfyUI (GPL-3.0) and its node packs run as a separate HTTP service, never linked into the studio process (same subprocess-isolation reasoning as audiowaveform). ElevenLabs generated audio commercially usable under paid-plan ToS, recorded per asset. Rejected list includes FLUX.1 [dev]/Klein 9B, MusicGen, HunyuanVideo 1.x (licence void in EU), LTX-Video 2, Llama, Remotion, react-video-editor, Twick, Etro, editly/FFCreator-as-dependency.
- scope: licensing, dependency selection

## DEC-storyboard-first: Storyboard-first creation
- source: /Users/karstenhaldan/Video-studio/docs/roadmap-v2.md (§4)
- status: proposed
- decision: Owner requirement 2026-07-29: every video starts as a `Storyboard` of `Shot`s (subject + preset stack + duration target) with a format (`long` 16:9 / `short` 9:16 ≤60 s) and optional style template; export compiles to the timeline document (refusing unfinished boards and over-cap shorts); storyboard → timeline → render is one continuum.
- scope: creation workflow

## DEC-identity-consent: Identity consent policy (structural, C6)
- source: /Users/karstenhaldan/Video-studio/docs/roadmap-v2.md (§8)
- status: proposed
- decision: Identity LoRA training and face-bearing generation restricted to identities with recorded consent (`consent_recorded_by`/`consent_at` on the `Identity` entity, append-once); endpoints refuse identities without it. Arbitrary third-party face-swap is not cloned. System remains an EU AI Act deployer; offering to others (provider role) is recorded as out of scope so it cannot happen by drift.
- scope: identity features, compliance

## DEC-comfyui-executor: ComfyUI headless as the wan-lane executor — decided and landed
- source: /Users/karstenhaldan/Video-studio/docs/milestones.md (M10); resolves the open question in /Users/karstenhaldan/Video-studio/docs/roadmap-v2.md (§9.1)
- status: proposed
- decision: ComfyUI headless decided over direct diffusers and landed: `pipeline_core/comfy.py` submit→poll→fetch client + per-model workflow templates; ComfyUI is a service dependency exactly like MinIO (own venv, `COMFY_URL`), per docs/workstation.md §1.
- scope: wan-lane execution
