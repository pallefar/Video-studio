# PSD — Avatar Render Pipeline

**Product:** Self-hosted AI avatar video pipeline for YouTube
**Owner:** Karsten
**Target:** Single workstation, RTX 3090 (24 GB, Ampere `sm_86`)
**Build method:** Claude Code, milestone by milestone
**Companion doc:** `docs/pipeline-spec.md` (hardware, models, ffmpeg chains, failure modes)

---

## 1. Problem statement

Producing talking-head YouTube video consumes the time that should go to client work. Commercial SaaS (HeyGen, Synthesia) solves it but caps throughput, holds the face and voice model, and cannot be extended into a product.

This system renders presenter video locally from a script, with AI disclosure enforced structurally rather than by habit.

**Success:** a script goes in, a compliant, publishable 1080p video comes out, unattended, in under 20 minutes of wall clock.

**Non-goals (v1):** real-time conversation, multi-user, multi-tenant, cloud deployment, Teams integration, script generation. The system renders scripts. It does not write them.

---

## 2. Stack decision

The GPU layer forces Python — MuseTalk and Chatterbox have no JS bindings, and there is no path around this. Everything else is chosen to avoid adding a third runtime.

| Layer | Choice | Rationale |
|---|---|---|
| API | FastAPI + Pydantic v2 | Job schema, validation, and OpenAPI from one set of models |
| Queue | Redis + RQ | Celery's config surface is a tax you don't need at this scale |
| ORM | SQLModel + Alembic | Pydantic-native; one model definition, not two |
| GPU worker | Python, native venv | **Not containerised** — see §2.1 |
| CPU worker | Python + ffmpeg | Parallelisable, no GPU contention |
| Control panel | Vite + React + TS | Your home turf; the UI need is genuinely simple |
| Client state | TanStack Query | Job-status polling *is* the client state problem |
| Styling | Tailwind + shadcn/ui | Fast, familiar |
| Infra | Docker Compose | Postgres, Redis, MinIO only |

### 2.1 Two decisions worth defending

**No Next.js.** This is a single-user tool on localhost. No SEO, no SSR, no server components, no auth. A Vite SPA hitting a JSON API is the whole requirement. FastAPI serves the built bundle as static files — one origin, no CORS, no second deploy target.

**The GPU worker is not in Docker *for local development*.** CUDA-in-Docker on a workstation is a reliable way to lose two days to driver and toolkit version mismatches before rendering a single frame. Run it natively in a venv, pointed at the same Redis.

But rented GPUs are the stated destination, so the container is a build artefact from M3 onward — written, built in CI, not run locally. An unused Dockerfile rots; one that CI builds on every push does not, and it catches dependency drift while the fix is still cheap. See §2.2.

### 2.2 Designing for rented GPUs without paying for it now

The move from workstation to rented box should be a config change, not a rewrite. That costs almost nothing if these hold from M1, and is expensive to retrofit later.

| Constraint | Why |
|---|---|
| **All I/O through the S3 API.** No local filesystem paths anywhere in the worker. | MinIO locally, S3/R2/B2 remotely — same code, different endpoint |
| **No `localhost` in worker config.** Redis and Postgres addresses come from env, always. | The worker must not assume it shares a machine with anything |
| **The GPU worker is stateless.** Everything in and out via queue + object store. | A rented box can vanish mid-job; state on its disk is state you lose |
| **Model weights: pinned versions, scripted download.** | Baking them into an image later becomes mechanical rather than archaeological |
| **Every stage idempotent, keyed by `job_id` + `stage`.** | Interruptible/spot instances are the cheap ones; retry has to be safe |

**Cold start becomes your dominant cost.** On hourly rental, a box that takes four minutes to boot and pull multi-gigabyte weights before a twelve-minute render is burning a third of what you pay. Design the worker to **drain a queue, not serve a job**: spin up, process everything pending, shut down. Never one box per video.

**Networking:** do not expose Redis or Postgres publicly to let rented workers reach them. Put the workstation and the rented box on a Tailscale or WireGuard mesh and bind to the private interface. This is fifteen minutes of setup and removes an entire category of risk.

---

## 3. Repository structure

```
avatar-pipeline/
├── CLAUDE.md                    # lean, see §7
├── docker-compose.yml           # postgres, redis, minio ONLY
├── docs/
│   ├── psd.md                   # this file
│   ├── pipeline-spec.md         # hardware + model reference
│   └── milestones.md            # checkbox task list, Claude Code ticks these
├── packages/
│   └── schema/
│       ├── models.py            # Pydantic — SINGLE SOURCE OF TRUTH
│       └── export_ts.py         # generates web/src/types/schema.ts
├── api/
│   ├── main.py
│   ├── routes/{jobs,assets,loops,publish}.py
│   ├── db.py
│   └── validators/compliance.py # §6 — hard gate
├── worker_gpu/
│   ├── run.py                   # single process, concurrency=1
│   ├── engines/{tts,lipsync}.py # models load ONCE at boot
│   └── preprocess/loop_cache.py # latent cache builder
├── worker_cpu/
│   ├── run.py
│   └── ffmpeg/{assemble,captions,watermark}.py
├── web/
│   └── src/{routes,components,types}/
├── tests/
│   ├── test_compliance.py       # §6 gate — must pass before publish ships
│   ├── test_schema_roundtrip.py
│   └── test_queue_topology.py   # asserts GPU concurrency == 1
└── scripts/
    ├── verify_gpu.py            # capability check, run first
    └── bench.py                 # measure, don't trust estimates
```

---

## 4. Data model

`packages/schema/models.py` is the single source of truth. TypeScript types are **generated**, never hand-written — schema drift between API and UI is the most tedious bug class in this kind of project and it's fully avoidable.

Core entities:

| Entity | Purpose | Key fields |
|---|---|---|
| `VoiceProfile` | Versioned voice clone | `id`, `reference_audio_uri`, `embedding_uri`, `engine`, `version` |
| `BaseLoop` | Preprocessed footage + latent cache | `id`, `source_uri`, `latents_uri`, `bbox_uri`, `fps`, `frame_count`, `seam_index` |
| `RenderJob` | One video, full lifecycle | see `docs/pipeline-spec.md` §3 for the complete JSON |
| `Segment` | One TTS unit, individually re-renderable | `idx`, `text`, `pause_after_ms`, `audio_uri`, `duration_ms`, `seed` |
| `PublishRecord` | Provenance + disclosure audit trail | `job_id`, `youtube_id`, `altered_content`, `reviewed_by`, `published_at` |
| `Asset` | One reusable B-roll clip or image | `id`, `origin`, `uri`, `caption`, `embedding`, `duration_ms`, `has_identifiable_people`, `license`, `source_url`, `approved` |

**Versioning rule:** `VoiceProfile` and `BaseLoop` are immutable once a job references them. Re-cloning creates `karsten_v3`, it does not mutate `karsten_v2`. Otherwise your back catalogue drifts and you cannot reproduce an old render.

---

## 4.1 B-roll and stock media subsystem

### The VRAM constraint that shapes everything

Wan 2.2 quantised consumes essentially the entire 3090. It **cannot** be resident alongside Chatterbox and MuseTalk. This is not a tuning problem, it's an architectural one, and the naive design — "generate B-roll as a stage inside the render job" — fails on it.

**So B-roll is an asset library, not a render stage.** Clips are produced ahead of time into a searchable library; a render job *selects* from that library. This is better for four independent reasons beyond the VRAM one:

- Video generation is slow — minutes per five-second clip on a 3090. Inline generation makes render times unpredictable.
- Generated video quality is variable. You want a human approval gate before a clip reaches a published video.
- Assets are reusable. The same office-desk shot serves twenty videos.
- The B-roll lane batches naturally — run it overnight while the render lane is idle.

### Three-tier resolution

When a script beat needs visual cover, resolve in this order:

| Tier | Source | Latency | Cost | Use when |
|---|---|---|---|---|
| 1 | Local asset library | instant | none | Almost always — check here first |
| 2 | Stock API (Pexels, Pixabay) | seconds | free | Real-world footage: offices, cities, hands on keyboards |
| 3 | Generative (Wan 2.2) | minutes, queued | GPU time | Nothing real exists — abstract concepts, specific product visuals |

Tier 3 never blocks a render. It enqueues a request, the render proceeds with tier 1 or 2, and the generated clip lands in the library for next time.

**Matching beats to assets:** embed asset captions and script-beat descriptions with a small text embedding model, cosine-match, threshold. Sub-threshold means fall through to the next tier. This is a few hundred lines and it's what makes the library actually usable once it passes a hundred clips.

### Generative model choice

**Wan 2.2 (Alibaba).** Apache 2.0, no commercial restriction, and it covers text-to-video, image-to-video and editing in a single deployment. It runs on 24 GB with quantisation — use **GGUF or INT8, never FP8**, for the same `sm_86` reason as everything else.

Rejected, with reasons worth recording so they don't get revisited:

- **HunyuanVideo** — Tencent community licence, requires review for some commercial applications. Better face rendering, not worth the legal ambiguity for a monetised channel.
- **LTX-2.3** — the standard model wants 80 GB; the distilled variant needs 32 GB *and* FP8, which the 3090 does not have. Out on hardware regardless of licence. Reports on its commercial terms also conflict between Apache-2.0-under-a-revenue-threshold and a separate Lightricks agreement — verify directly if hardware ever changes.
- **Mochi 1** — Apache 2.0 and viable at 24 GB with linear quadrant attention, but Wan 2.2's feature set is stronger. Keep as fallback.

### Stock provider choice

**Pexels primary, Pixabay secondary.** Both photos and video, both free, neither requires attribution.

The deciding factor is not quality, it's caching rights. This pipeline downloads assets into MinIO and serves them from there. **Pixabay explicitly permits downloading, caching and serving from your own infrastructure.** Unsplash's API rules are built around hotlinking and attribution, which fights the architecture — and it has no video. Use Pexels for video-first search, Pixabay where you need permissive caching, skip Unsplash.

### The stock licensing trap

All three free platforms grant broad commercial rights and **none of them provide model releases or indemnification.** You assume the legal risk. Anyone can upload anything.

For a monetised channel this is a real exposure, and it has a cheap structural fix:

- `Asset.has_identifiable_people` is a required field, defaulted to `true` for anything ingested from a stock API until a human clears it.
- Assets flagged `true` cannot be selected by the resolver. Prefer hands, objects, environments, backs of heads, out-of-focus crowds.
- If you genuinely need people on camera, buy from a provider that indemnifies (Adobe Stock, Getty, Storyblocks). One licensed clip costs less than one dispute.
- Persist `license` and `source_url` on every asset at ingest. Reconstructing provenance a year later from memory is not possible.

### Compliance interaction

- AI-generated B-roll is already covered by your existing watermark and `altered_content` flag. No new disclosure obligation — but the flag becomes *non-negotiable* rather than merely required, since realistic synthetic footage of places and events is squarely what Article 50(4) targets.
- `Asset.origin` (`generated` | `stock` | `own`) feeds the provenance record. C4 should record which assets appeared in each published video.
- **Real stock footage strengthens your inauthentic-content position.** A video mixing your own screen recordings, licensed stock, and some generated cover reads as produced. One that's entirely synthetic on a repeated template does not. This is a monetisation argument, not just an aesthetic one.

---

## 5. Milestones

Each milestone has a **verifiable** acceptance criterion — a command that exits zero, not a subjective judgement. This matters more than usual when an agent is doing the work: "done when it works" is not checkable, "done when `pytest tests/test_compliance.py` passes" is.

### M0 — Environment
- [ ] `scripts/verify_gpu.py` asserts `torch.cuda.get_device_capability() == (8, 6)` and fails loudly otherwise
- [ ] Chatterbox loads and produces a 10 s clip from a reference sample
- [ ] MuseTalk loads and lip-syncs 5 s against a test clip
- [ ] Both resident simultaneously, peak VRAM logged and under 20 GB

**Accept:** `python scripts/verify_gpu.py && python scripts/bench.py --smoke` exits 0

### M1 — Schema + API skeleton
- [ ] Pydantic models for all §4 entities
- [ ] `export_ts.py` generates TS types; a schema change that isn't re-exported fails CI
- [ ] Postgres via Alembic, MinIO buckets provisioned
- [ ] CRUD for jobs, loops, voice profiles
- [ ] **All storage access through an S3 client behind one interface** — no `open()` on a job artefact anywhere outside it
- [ ] All service addresses from env vars; no `localhost` literal in worker code

**Accept:** `pytest tests/test_schema_roundtrip.py tests/test_portability.py` passes, where the portability test greps the worker packages for local-path and localhost literals and fails on a hit

### M2 — Loop preprocessing
- [ ] Ingest base footage, enforce constant frame rate at ingest (reject VFR)
- [ ] Seam detection via perceptual hash, ping-pong fallback
- [ ] Latent cache built and persisted per loop
- [ ] Second render against a cached loop is measurably faster than the first

**Accept:** `python scripts/bench.py --loop <id>` shows cached run ≥ 40% faster

### M3 — GPU worker
- [ ] Single long-lived process, models warm at boot, never unloaded
- [ ] Consumes `tts` and `lipsync` stages from Redis
- [ ] Segment-level retry — one bad sentence re-renders alone
- [ ] Chunked lip-sync at 60–90 s windows
- [ ] Seeds pinned and persisted per segment

**Accept:** `pytest tests/test_queue_topology.py` asserts GPU concurrency is 1; a job goes `queued → lipsync` unattended

### M4 — Assembly
- [ ] Loudness normalise to −14 LUFS
- [ ] Watermark burn-in, full duration, bottom-right
- [ ] Caption burn-in from faster-whisper word timings
- [ ] B-roll insertion at timestamps
- [ ] H.264 CRF 18, yuv420p, `+faststart`

**Accept:** an 8-minute job completes end to end; output plays in VLC and Chrome with correct A/V sync

### M5 — Compliance gate
- [ ] Validator rejects any job with `watermark.persistent != true`
- [ ] Validator rejects any job with `publish.altered_content != true`
- [ ] Provenance record written before publish is permitted
- [ ] Frame sampling asserts watermark pixels present at 10%, 50%, 90% of duration

**Accept:** `pytest tests/test_compliance.py` passes, including the negative cases

### M6 — Publish
- [ ] YouTube Data API v3, OAuth, refresh token persisted
- [ ] Uploads land `private`, always — no path publishes directly
- [ ] `altered_content` set programmatically on upload
- [ ] Exponential backoff; quota exhaustion is distinguished from real failure

**Accept:** a real upload lands private with the disclosure flag visible in Studio

### M7 — Control panel
- [ ] Submit script, pick loop + voice profile
- [ ] Job list with live status (TanStack Query polling, 2 s interval)
- [ ] Preview before publish, per-segment re-render button
- [ ] Manual publish confirmation — never automatic

**Accept:** a full video produced without touching the terminal

### M8 — Stock ingest + asset library

Ship this before M9. It's cheap, it's CPU-only, and it makes B-roll useful without touching the GPU.

- [ ] Pexels + Pixabay clients behind one `StockProvider` interface
- [ ] Ingest downloads to MinIO, persists `license`, `source_url`, `origin='stock'`
- [ ] `has_identifiable_people` defaults `true` on stock ingest; resolver excludes flagged assets
- [ ] Caption embedding + cosine search over the library
- [ ] Library browser in the control panel with an approve/flag toggle

**Accept:** `pytest tests/test_asset_resolver.py` passes, including the case that a flagged asset is never returned

### M9 — Generative B-roll lane
- [ ] Wan 2.2 quantised (GGUF/INT8) loads and generates a 5 s clip
- [ ] Runs as a **separate queue with an exclusive GPU lock** — never concurrent with the render lane
- [ ] Generation requests enqueue and never block a render job
- [ ] Output lands in the library as `origin='generated'`, `approved=false`
- [ ] Approval gate in the control panel before an asset becomes selectable

**Accept:** `pytest tests/test_gpu_exclusivity.py` proves render and generation lanes cannot hold the GPU simultaneously; an unapproved generated asset is never selected by the resolver

---

## 6. Compliance requirements — structural, not procedural

These are the requirements most likely to be quietly dropped during implementation, because they are invisible until something goes wrong. They belong in validators and tests, where they cannot be forgotten.

| ID | Requirement | Enforced by |
|---|---|---|
| C1 | Visible "Made with AI" watermark, full duration | Pydantic validator + frame-sampling test |
| C2 | YouTube `altered_content` set on every upload | Publish-worker precondition |
| C3 | Chatterbox audio watermark preserved through encode | Encode chain test |
| C4 | Provenance record per published video | FK constraint — publish requires a `PublishRecord` |
| C5 | Uploads land private, human review before public | No API path sets `public` |

**C1 satisfies EU AI Act Article 50(4)** (applicable from 2 August 2026): disclosure must be clear and perceivable to a person at first exposure. A visible burn-in meets that; machine-readable marking alone does not.

**C2 is a separate obligation** and does not substitute for C1, nor C1 for C2. Both, every time.

**Important for Claude Code specifically:** CLAUDE.md is context, not enforcement — Claude treats it as guidance and can reason its way around it. Anything that must hold unconditionally goes in a validator, a test, or a hook. Put C1–C5 in `tests/test_compliance.py` and wire it into CI, not into a bullet in your instructions file.

---

## 7. CLAUDE.md

Keep it under 200 lines — it loads at the start of every session and larger files consume context you'd rather spend on code. Point at `docs/` with `@` references for anything not needed every session. The live version is the repo-root `CLAUDE.md`.

---

## 8. Working method with Claude Code

- **One milestone per session.** `/clear` between them. M0–M7 are sized deliberately for this.
- **Milestones live in `docs/milestones.md` as checkboxes.** Claude Code ticks them off as it goes, and the file survives context resets — it's the durable progress record, not the conversation.
- **Acceptance criteria are commands.** Ask for the test before the implementation on M5 in particular; compliance logic written after the fact tends to be shaped to pass rather than to be correct.
- **`CLAUDE.local.md`** (gitignored) for machine-specific paths — CUDA location, model weight directories, MinIO credentials.
- **Benchmark at M0 and replace the estimates** in `docs/pipeline-spec.md` §6 with your real numbers. Everything downstream should reason from measurements taken on your card, not from figures quoted for a V100.

---

## 9. Out of scope for v1, deliberately

Recorded so they don't creep in mid-build:

- Script generation — you write the scripts, that's the part with your expertise in it
- Multi-language / dubbing
- Real-time or conversational rendering
- Teams meeting integration
- Multi-user, auth, or anything resembling SaaS

**Rented GPU execution is out of scope for v1 but not out of mind** — the §2.2 constraints are built in from M1 so the move is a config change. Don't implement remote execution until the local pipeline has shipped real videos.

**The fork worth naming now.** "Hosting it" splits into two very different products:

*Remote execution for yourself* — the §2.2 constraints are the whole job. Swap MinIO for S3, point the worker at a rented box over Tailscale, done. No new obligations.

*Offering it to other people* — this is a different product with a materially heavier legal position. Under the EU AI Act you shift from **deployer** to **provider** of a generative AI system, and provider obligations include machine-readable marking of synthetic output, plus responsibility for what your users generate with someone else's face. Voice-clone consent verification stops being your own problem and becomes a feature you have to build. Budget for that properly if you go there; don't drift into it.

Either way: the GPU worker and schema survive the transition largely intact. The control panel does not. Build it cheaply and don't get attached to it.
