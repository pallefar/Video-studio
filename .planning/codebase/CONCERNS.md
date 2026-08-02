<!-- refreshed: 2026-08-02 -->
# Codebase Concerns

**Analysis Date:** 2026-08-02

## Critical Constraints (Structural, Never Violate)

These are not bugs — they are invariants built into the schema, validators, and tests. Violating them silently breaks core systems.

### C1–C5 Compliance Gates (Enforcement: `tests/test_compliance.py`)

**C1: Visible "Made with AI" watermark, full duration**
- Files: `worker_cpu/ffmpeg/assemble.py`, `packages/schema/models.py` (validator), `tests/test_assemble.py::test_c1_watermark_frame_sampling`
- Enforcement: Pydantic validator rejects `watermark.persistent != true`; frame-sampling test asserts pixels at 10%, 50%, 90% of video duration
- Failure mode: Avatar output published without watermark = silent compliance violation
- Test coverage: Structural — cannot be disabled; M5 and M16 (studio) include frame-sampling probes

**C2: YouTube `altered_content` flag on every upload**
- Files: `worker_cpu/publish.py`, `packages/schema/models.py` (validator)
- Enforcement: Pydantic validator rejects `publish.altered_content != true`; publish worker precondition
- Failure mode: Uploads land with synthetic-media flag missing = disclosure violation
- Implements: EU AI Act Article 50(4) requirement

**C3: Chatterbox audio watermark preserved through encode**
- Files: `worker_cpu/ffmpeg/assemble.py`, `tests/test_assemble.py::test_c3_encode_chain_probe`
- Enforcement: AAC encode-chain test verifies ultrasonic watermark survives loudnorm + codec round-trip
- Failure mode: Encoding destroys watermark = watermark present in source but not in published output

**C4: Provenance record per published video**
- Files: `packages/schema/models.py` (FK constraint), `worker_cpu/publish.py`
- Enforcement: FK on PublishRecord; publish route enforces creation before allowing the upload
- Failure mode: Orphaned published videos (no provenance = untraced origin)

**C5: Uploads land private, human review before public**
- Files: `api/routes/jobs.py`, `tests/test_publish_worker.py::test_uploads_land_private`
- Enforcement: `privacyStatus` bound to constant (never a parameter); no API path sets `public`
- Failure mode: Unreviewed AI content published publicly

**Related: C6 Identity Consent Gate (v2 structural)**
- Files: `packages/schema/models.py` (Identity entity with `consent_recorded_by`/`consent_at`), validator in progress
- Status: Structure landed; enforcement at training/generation endpoints pending M17 acceptance
- Failure mode: Third-party face/voice used for LoRA training or avatar generation without consent

## Tech Debt

### GPU Exclusivity Lock — 24 GB Single Lane, No Oversubscription

**What's locked in:**
- Files: `packages/pipeline_core/locks.py`, `tests/test_gpu_exclusivity.py`
- Constraint: One GPU holder at a time — render lane and wan lane compete for the RTX 3090's 24 GB
- Current occupants: Chatterbox + MuseTalk resident (render), Wan 2.2 exclusive (wan lane)
- Latency risk: Fun-Camera A14B GGUF at 16–22 GB is "tight but reported workable" (roadmap-v2 §9); no safety margin

**Decisions deferred to workstation (M0):**
- Benchmark Fun-Camera A14B + 4-step LoRA on the 3090 — if disappointing, fallback to 5B variants at lower fidelity
- Latent cache measurement (M2) — MuseTalk chunk rendering speed improvement is real-hardware only

**Impact if wrong:**
- OOM during rendering = job fails + GPU lock not released → stale-lock safety (TTL 12 h) must kick in
- Solution is in place: TTL prevents brick; but a 12 h GPU stall is a production outage

**Files to monitor:**
- `worker_gpu/engines/dev.py` — placeholder during development; real Chatterbox/MuseTalk loads pending M3 workstation
- `worker_gpu/engines/` (all) — engine boot hooks must never hold the lock longer than necessary

### Workstation-Only Milestone Boxes (13 Unchecked)

These are intentionally CPU-proven via mocking but require real hardware validation. They are **not** blocked on architectural concerns — they are measurement + integration tasks.

**M0 Environment — GPU verification (3 boxes):**
- `scripts/verify_gpu.py` asserts `torch.cuda.get_device_capability() == (8, 6)` — must run on the 3090
- Chatterbox + MuseTalk simultaneous load, peak VRAM < 20 GB — real measurement
- Files: `scripts/verify_gpu.py`, `scripts/bench.py`, `tests/test_dev_engines.py`

**M2 Loop Preprocessing — Latent cache (2 boxes):**
- Latent cache built and persisted per loop in `worker_gpu/preprocess/loop_cache.py`
- Speed benchmark: cached render ≥ 40% faster than first run
- Files: `worker_gpu/preprocess/loop_cache.py` (stubbed), `scripts/bench.py` (workstation task)
- Current: CPU half proven; real MuseTalk latent build = workstation acceptance

**M3 GPU Worker — Model loads (2 boxes):**
- Single long-lived process, models warm at boot, never unloaded
- Chunked lip-sync at 60–90 s windows with real MuseTalk rendering
- Files: `worker_gpu/run.py` (orchestration landed), `worker_gpu/engines/` (real loads pending), `pipeline_core/chunking.py` (window math done)
- Current: Orchestration e2e-tested with fake engines; real integration pending

**M9-M11 Generative B-roll + Camera Presets (4 boxes):**
- Wan 2.2 quantised (GGUF/INT8) loads and generates 5 s clip
- Benchmark Fun-Camera A14B: VRAM + latency (decides 14B vs 5B default)
- Wan2.2-Fun-Control-Camera integration + Civitai LoRA audit
- LoRA training job (M17) on the wan lane, overnight batch
- Files: `packages/pipeline_core/workflows/wan2*.json` (templates awaiting schema verification on real ComfyUI), `packages/pipeline_core/presets.py` (16 presets wired), `worker_gpu/engines/identity.py` (LoRA trainer stubbed)
- Current: Templates validated structurally in `tests/test_comfy.py` against mock ComfyUI; real workstation ComfyUI deployment will verify node schemas match

**Impact of leaving unchecked indefinitely:**
- M0–M3 unchecked = avatar pipeline never tested on real hardware
- M9–M11 unchecked = all Higgsfield-class features remain proof-of-concept
- Current status: CPU/CI proofs exist; workstation measurement is the gate

### ComfyUI Dependency — GPL-3.0 Sidecar with Mixed Node Packs

**Architecture decision (M10, recorded 2026-07-31):**
- Files: `packages/pipeline_core/comfy.py`, `packages/pipeline_core/comfy_nodes.py`, `packages/pipeline_core/workflows/`
- ComfyUI itself is GPL-3.0; runs as a separate subprocess/HTTP service over network boundary
- Studio code is MIT/Apache 2.0; never linked into ComfyUI process
- Custom node packs: mixed licences (Apache-2.0, MIT, GPL-3.0) — recorded per-pack in `comfy_nodes.py`

**Why this works legally:**
- GPL-3.0 comfyui + HTTP boundary = "sidecar exception" (roadmap-v2 §6)
- Model weights (Wan, FLUX.2 Klein 4B, Z-Image, etc.) are Apache-2.0 or compatible
- Governance: Studio stays MIT/Apache; ComfyUI remains in a separate bounded process

**Fragility:**
- ComfyUI version pins are not stored in `pyproject.toml` (it's not a Python dependency)
- Workflow templates (JSON) must be re-exported from ComfyUI on version upgrade
- Tests validate template structure (`test_every_model_has_a_structurally_valid_template`) but don't execute on real ComfyUI until M10 workstation

**Monitor:**
- Custom node pack additions must be audited for licences before inclusion in `comfy_nodes.py`
- Workflow validation is CPU-only; real ComfyUI schema verification happens on workstation

### Licence Register — Hard Boundaries (Roadmap-v2 §6)

**Adopt (clean for commercial use):**
- Wan 2.2 family (Apache 2.0), Uni3C (Apache 2.0), Z-Image (Apache 2.0), Qwen-Image (Apache 2.0), FLUX.2 Klein 4B (Apache 2.0), Qwen3.5 (Apache 2.0), Chatterbox (MIT), MuseTalk (MIT), Florence-2 (MIT)
- Enforce in tests: rejection of unlicensed models at generation time

**Conditional (recorded, revisit before relying on):**
- RIFE (MIT code but training-data caveat — FILM is clean fallback)
- Stable Audio Open (<$1M revenue cap) — tracked on generated assets
- Civitai camera LoRAs (audit each individually before commercial use)

**Hard rejected (DO NOT introduce):**
- FLUX.1 [dev] and [dev]-licensed variants (non-commercial)
- MusicGen/AudioCraft (CC-BY-NC)
- HunyuanVideo 1.x (licence void in EU)
- LTX-Video 2 (custom licence + FP8-first)
- Remotion, openvideodev/react-video-editor (source-available, team-gated, terms can change)
- Files: `docs/roadmap-v2.md` §6, `tests/test_comfy.py::test_every_model_has_a_structurally_valid_template`

**Risk:** Drift happens via new capability requests ("can we use X for Y?"). Licence decisions are recorded in roadmap-v2 — new models must be added there with justification before being integrated.

### Stable Audio Open — Revenue Cap Condition

**Files:** `docs/roadmap-v2.md` line 59, `packages/pipeline_core/providers.py` (music generation)
- Model: Stable Audio Open Small
- Condition: <$1M revenue cap for commercial use
- Current use: Music bed generation for the editor (M18)
- Enforcement: Recorded on every generated audio's `licence` field; configuring the model is opt-in via env
- Risk: If studio revenue ever exceeds $1M, this model becomes unlicensed and must be swapped for ACE-Step or similar

**Monitor:** Business model decisions. If licensing changes, the condition must be re-audited.

### ElevenLabs API Integration — Per-Provider Data Egress Decision

**Files:** `packages/pipeline_core/providers.py` (api provider), `docs/roadmap-v2.md` §6
- Status: Landed in M29 (voice cloning, audio watermark via API)
- ToS: Generated audio is commercially usable under paid plan
- Governance: Setting `ELEVENLABS_API_KEY` in env is the per-provider data-egress decision
- Enforcement: Recorded on every generated asset's `licence` field
- Risk: Prompts/voice samples sent to third-party API (no local fallback for voice cloning)

**Impact:** If ever moving to multi-user or offering as a service, voice-clone consent verification becomes a structural requirement (not just operator choice).

### Sora / Gemini Veo API Integrations — Landed but Cost-Tracking Incomplete

**Files:** `packages/pipeline_core/providers.py` (api provider for OpenAI Sora, Gemini Veo), tests incomplete
- Status: Landed M29 (direct APIs for t2v/i2v via fal/aggregators)
- Cost tracking: Generation records `cost` field but billing not yet wired to Settings
- Failure mode: Cost estimate is per-generation; actual billing accumulates and is not yet surfaced in dashboard
- Priority: M30+ (monitoring/cost dashboards); doesn't block generation

## Scaling Limits

### Model Zoo Disk Footprint — 150–300 GB

**Files:** `docs/roadmap-v2.md` §9 line 250, `docs/ops.md`
- Full roster: Wan (full + quants), FLUX.2 Klein, Z-Image, Qwen-Image, SDXL + style LoRAs, music/SFX models = ~150–300 GB
- Pinned versions + scripted download (existing v1 rule) = mandatory hygiene
- Failure mode: No budget = disk full mid-training (LoRA overnight batch writes checkpoint every N steps)

**Monitor:** Weights directory needs its own drive budget. Benchmark on M0 — measure actual sizes on the 3090 host.

### macOS Running — Memory Stalls at 18 GB Unified

**Files:** `docs/milestones.md` M30, `docs/mac-dev.md`
- Real M30 result: 832×480×33 frames blew past 18 GB unified memory on MacBook Pro M3 Max
- Swap collapse: step time went from 19 s → 2056 s (63x slowdown)
- Solution: Restricted to 640×384×25 on Mac (viable canvas on 18 GB)
- Workaround: Rented GPU escape hatch (`scripts/vast_comfyui.sh`)

**Constraint:** Mac development is dev-engines mode only for production features. Real generation on Mac requires either (a) external GPU rental or (b) Sora/Veo API providers configured.

### RQ Job Timeout Gotcha — 180 s Default Kills Real Renders

**Files:** `packages/pipeline_core/dispatch.py`, `tests/test_queue_topology.py` (fixed 2026-08-01)
- Issue: RQ's 180 s default job timeout killed real Wan renders (~13 min on M3 Max for 640×384×25)
- Fix applied: Dispatcher now enqueues with 12 h last-resort timeout
- Lesson: No timeout is appropriate for large model inference. The 12 h value is safety-net only; most jobs complete far faster.

**Files to monitor:** `packages/pipeline_core/dispatch.py` — if job enqueue changes, timeout must be preserved.

## Fragile Areas

### macOS Fork-Safety / RQ Workhorse Signal 6

**Files:** `docs/milestones.md` M30, `scripts/dev_up.sh`
- Issue: RQ forks work-horses on macOS. ObjC initialization post-fork dies with signal 6 on every forked process
- Fix: Export `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` before starting RQ worker
- Current: `dev_up.sh` sets this automatically on Darwin
- Risk: If this env var is ever removed or conditional logic added, macOS immediately breaks

**Files to check:** `scripts/dev_up.sh` — this workaround is undocumented in code comments and must be preserved.

### DEV_ENGINES Placeholder Mode — Must Not Silently Become Production

**Files:** `worker_gpu/engines/dev.py`, `tests/test_dev_engines.py`, `CLAUDE.md`, `docs/mac-dev.md`
- Mechanism: DEV_ENGINES=1 env var swaps Chatterbox/MuseTalk for `say` command and loop cycling
- Safety: Placeholder engines **announce themselves** at boot with a warning banner
- Opt-in: DEV_ENGINES is deliberate — no silent fallback
- Risk: If placeholder is ever removed or fallback added without announcement, users may unknowingly generate with wrong engines

**Guard:** Warning message in `worker_gpu/engines/dev.py` is the only safeguard. CI should test with DEV_ENGINES=0 to ensure real-engine load paths work.

### Asset Resolver — Fragile "Never Return Unapproved Assets" Gate

**Files:** `packages/pipeline_core/resolver.py`, `tests/test_asset_resolver.py`
- Constraint: Generated assets default `approved=false`; B-roll selection **must never** return an unapproved asset
- Current: Resolver filters by `approved=true` in the query
- Risk: If filtering logic is ever inverted or removed, unapproved AI-generated content could be selected for render
- Impact: Would violate Higgsfield parity (all generated assets go through approval before use)

**Monitor:** Resolver tests must include negative case: "an unapproved asset is never returned by the resolver" — currently passing.

### Template Injection — Unmapped Params Silently Ignored

**Files:** `packages/pipeline_core/comfy.py::inject()`
- Behavior: `inject()` merges template defaults + supplied values; unmapped values are ignored
- Example: t2v doesn't accept source_image (I2V does) — passing source_image to t2v is silently dropped
- Why fragile: No error if a required model parameter is misspelled in the template mapping
- Mitigation: `tests/test_comfy.py::test_every_model_has_a_structurally_valid_template()` validates all input paths structurally

**Guard:** Each model's template test exercises all required paths. New templates must add a corresponding test case.

### Compliance Validators — Pydantic Order Matters

**Files:** `packages/schema/models.py` (validators), `api/validators/compliance.py`
- Issue: SQLModel bypasses Pydantic validation on table instantiation; compliance validators only run at API edge (Create schemas) and publish gate
- Why it matters: Direct ORM inserts skip validation; only routes + workers see full validation
- Safety: Publish worker re-checks C4/C5 before upload; no path publishes without these

**Guard:** Compliance tests include negative cases (job with watermark=false is rejected at submission). Validators live in code, never deleted without updated tests.

## Performance Bottlenecks

### MuseTalk Chunk Rendering — 60–90 s Windows, Latency Unknown

**Files:** `packages/pipeline_core/chunking.py` (math landed), `worker_gpu/engines/` (real rendering pending M3)
- Issue: Long audio clips (>90 s) must be lip-synced in chunks to prevent OOM
- Window derivation: Done in chunking.py; real rendering = M3 workstation task
- Latency: Estimated but not measured — actual chunk latency on the 3090 unknown until M3
- Risk: If latency is worse than estimated, video assembly will be slower than expected

**Measurement needed:** `scripts/bench.py --lipsync` on the 3090 with real chunks.

### Two-Pass Loudnorm — Can Be Slow on Large Files

**Files:** `worker_cpu/ffmpeg/assemble.py`, `tests/test_assemble.py`
- Process: First pass measures loudness to JSON; second pass applies linear normalization
- Target: −14 LUFS with ±1.5 tolerance
- Risk: ffmpeg loudnorm can be slow on large/long audio. Measured on CI (synthetic); real numbers on production videos unknown

**Monitor:** If assembly times exceed expectations, loudnorm may be the culprit. Fallback: skip first pass and use defaults.

### Caption Embedding — Deterministic but CPU-Intensive

**Files:** `packages/pipeline_core/embeddings.py`, `packages/pipeline_core/captioner.py`
- Process: Every asset gets a caption; captions are embedded for library search
- Default: Deterministic hashing embedder (fast, no model)
- Upgrade path: `pip install -e ".[embed]"` swaps in MiniLM on CPU
- Risk: MiniLM embedding on every asset ingest can be slow at scale; no progress reporting

**Current:** Default is fast. Embedding upgrade is opt-in for now.

## Dependencies at Risk

### Civitai LoRA Licensing — Per-LoRA Audit Required

**Files:** `docs/roadmap-v2.md` §6, `packages/pipeline_core/presets.py` (camera move LoRAs referenced)
- Issue: Camera move LoRAs from Civitai are audited individually for licence
- Current: 16 presets in presets.py reference LoRA URIs; each was audited for Apache-2.0/MIT compatibility
- Risk: If new LoRAs are added without audit, they could introduce unlicensed content

**Guard:** Licence audit happens before adding any new LoRA URI to presets.py. Recorded in commit message or docs.

### Reminders about Rejected Dependencies

**Remotion, openvideodev/react-video-editor** (rejected for video editor base):
- Reason: Source-available, team-gated, terms can change
- Impact: Cannot use as a dependency; must build editor internals from scratch
- Status: Timeline editor built in React + canvas (M16 complete)

**RIFE for interpolation** (conditional, FILM is clean fallback):
- Training-data caveat on RIFE limits commercial use
- Current: Using FILM instead for clean interpolation path
- RIFE avoided: No new code should introduce it

## Missing Critical Features

### Identity Consent Gate — Structure Landed, Enforcement Pending M17

**Files:** `packages/schema/models.py` (Identity entity with `consent_recorded_by`/`consent_at`), validators pending
- Requirement: Identity LoRA training and face-bearing avatar generation restricted to identities with recorded consent
- Practical: The owner only (single-user self-hosted)
- Status: Entity structure exists; training/generation endpoints still accept any identity (enforcement = M17 task)
- Risk: If M17 is skipped, identity features remain open to third-party faces without structural safeguard

**Impact:** C6 compliance gate (roadmap-v2 §8) is not yet enforced.

### Operator Consent Interface — Not Built

**Files:** None yet — future M17 task
- What's needed: UI/endpoint to record operator consent for an identity (photos + acknowledgment)
- Current: Hardcoded assumption that operator = owner
- Risk: If multi-user ever becomes tempting, lack of consent UX is a blocker

### Rented GPU Workflow — Designed but Not Integrated

**Files:** `docs/psd.md` §2.2 (design), `docs/mac-dev.md` (escape hatch), `scripts/vast_comfyui.sh` (partial)
- Status: Architecture supports rented-GPU workers (stateless, S3 I/O, env-configurable); executor layer can target remote boxes
- Current: Not tested end-to-end; vastAI bootstrap script exists but is manual
- Risk: Rented GPU path remains theoretical until exercised on real hardware

### Multi-Provider Fallback Chains — Partially Implemented

**Files:** `packages/pipeline_core/providers.py::generate()`, `packages/pipeline_core/generation.py`
- Design: Generation can declare provider preference order; if one fails, try the next
- Status: Infrastructure exists; tested with mock providers
- Gap: Real cross-provider retries (e.g., local Wan fails → retry on API) not yet exercised

## Test Coverage Gaps

### Compliance Frame-Sampling — Proven for Avatar, Needs Studio Verification

**Files:** `tests/test_assemble.py::test_c1_watermark_frame_sampling` (avatar), needs extension to M16
- Current: C1 watermark verified on avatar output at 10%, 50%, 90% frame sampling
- Gap: Studio renders (M16) promised the same; not yet exercised
- Risk: Timeline editor output might escape frame-sampling audit if test isn't extended at M16

### Real-ComfyUI Template Validation — Only CPU-Proven

**Files:** `tests/test_comfy.py::test_every_model_has_a_structurally_valid_template()`, all mock
- Status: Every template is structurally validated (output node exists, input paths resolve)
- Gap: Real ComfyUI `/object_info` schema not verified against templates; node-pack assumptions not tested
- Risk: Template that passes CPU test might fail on real ComfyUI if node packs are missing or API changed

### GPU Exclusivity — Proven in CI, Real Hardware Unknown

**Files:** `tests/test_gpu_exclusivity.py` (against real Redis, fake GPU)
- Status: Lock semantics proven against Redis; TTL expiry and stale-holder safety tested
- Gap: Real dual-hold contention on the 3090 never measured; concurrent job cancellation + lock release edge cases unknown
- Risk: Edge case where render and wan jobs collide unexpectedly

### Publish Worker Retry Logic — Quota vs Real Failure Not Tested

**Files:** `worker_cpu/publish.py`, `tests/test_publish_worker.py` (against fake YouTube API)
- Status: Quota exhaustion handling (parks job, retries next window) proven with mock
- Gap: Real YouTube API quota behavior on this account unknown; what "next window" should be is estimated
- Risk: If YouTube quota reset timing differs, jobs might retry too aggressively or timeout

### Storyboard Generation — Shared Seed Validation Incomplete

**Files:** `packages/pipeline_core/generation.py`, `tests/test_schema_roundtrip.py` (mock only)
- Status: Storyboard spec (frames > 1, shared seed/params recorded) defined and parsed
- Gap: Real multi-frame generation end-to-end not proven; real-model latency for N frames unknown
- Risk: Shared seed semantics might not survive API provider implementation

## Scaling Risks

### Redis Single Instance — No Redundancy

**Files:** `docker-compose.yml`, `docs/ops.md`
- Current: Single Redis instance (development/testing)
- Risk: If Redis goes down, all queues are blocked; GPU lock is unreachable
- Mitigation: Idempotent stage keys mean jobs can be re-queued after restore
- Note: RQ has no persistence requirement (idempotency by design)

### Postgres Single Instance — No Replication

**Files:** `docker-compose.yml`, `docs/ops.md`
- Current: Single Postgres instance
- Risk: Data loss if database fails; no backup strategy documented
- Mitigation: Schema is regenerated from migrations; only user data is at risk
- Note: Ops guide says "No" to persistence for weights/Postgres — but this means operator must manage backups

### MinIO Single Bucket — No Lifecycle or Cleanup

**Files:** `packages/pipeline_core/storage.py`, `api/routes/assets.py`
- Risk: MinIO bucket grows unbounded; old generations, failed jobs, thumbnails never expire
- Current: No TTL or cleanup policy defined
- Impact: Disk usage grows indefinitely until operator manually prunes

**Monitor:** Implement cleanup (TTL on failed jobs, old generations after review period, etc.) before scaling to long-running production.

## Decisions Documented, Not Implemented

### ComfyUI vs Diffusers (M10 Decision)

**Files:** `docs/roadmap-v2.md` §9
- Decision: ComfyUI chosen for workflow maturity (camera/VACE preset integration); diffusers is the fallback if ComfyUI adds too much overhead
- Status: ComfyUI landed in M10 via separate service; all Wan/camera/VACE templates use ComfyUI
- Risk: If ComfyUI maintenance drops or licensing changes, diffusers branch point is lost; re-implementing in diffusers would be substantial

### 14B-on-24GB Latency (M10 Benchmark)

**Files:** `docs/roadmap-v2.md` §9 line 239
- Issue: Fun-Camera A14B + 4-step LoRA reported as "workable but tight" (16–22 GB)
- Deferral: Benchmark on M0/M10 workstation; if disappointing, use 5B variants at lower fidelity
- Status: Deferred to workstation; 5B fallback exists in model registry but untested

### Preset Quality Parity with Higgsfield

**Files:** `docs/roadmap-v2.md` §9 line 243
- Issue: Higgsfield's 50–70+ presets are curated/tuned; ours must iterate on prompt templates + LoRA weights
- Work type: Content, not code — but quality bar is external (Higgsfield benchmark)
- Status: 16 presets drafted in `presets.py`; fidelity vs Higgsfield unknown

## Known Gotchas for Future Work

### Studio Editor Scope (M14–M16) — MVP Cut Required

**Files:** `docs/roadmap-v2.md` §9 line 246
- Risk: Editor is the largest single work item (M14–M16); scope creep into keyframes/masks/speed ramps post-MVP
- Current MVP: multi-track, trim/split/move, xfade, text overlays, audio ducking, proxy preview, server render
- Extensions out of scope for v2.0: keyframed effects, masks, speed ramps, color grading

### Single-User Assumption — Provider Shift if Ever Multi-User

**Files:** `docs/psd.md` §9, `docs/roadmap-v2.md` §8
- Assumption: Single-user, self-hosted → EU AI Act deployer (not provider)
- Flip point: Offering this to other people → provider status (machine-readable marking + consent verification for all outputs)
- Risk: Scope creep toward "share my renders with friends" is a different product with materially heavier obligations

### DEV_ENGINES Not for Production — CI Must Verify Real-Engine Paths

**Files:** `CLAUDE.md`, `tests/test_dev_engines.py`
- Constraint: DEV_ENGINES=1 is dev-only; CI must test with DEV_ENGINES=0 to ensure real paths work
- Current: CI runs full stack against fake ComfyUI (dev mode); real Chatterbox/MuseTalk only on workstation
- Risk: If CI ever switches to dev-engines-only, real-engine breakage goes undetected

---

*Concerns audit: 2026-08-02*
