# Roadmap v2 — Higgsfield-class creative studio + video editor

**Status:** planned (owner decision, 2026-07-29). Builds on v1 (docs/psd.md), which
remains the foundation: v1's M2–M7 render pipeline must ship before v2 work starts.
Research basis: Higgsfield feature teardown, open-model landscape for a single RTX
3090 (sm_86, no FP8), and browser-editor architecture — all summarised here with
licences verified as of July 2026.

**Scope statement:** clone the *capabilities and product mechanics* of Higgsfield AI
as a self-hosted, single-user tool, and add what Higgsfield itself lacks — a real
multi-track video editing studio. Like Higgsfield, the system is a **model
aggregator**: one generation interface routes to (a) open models running locally on
the 3090, (b) the same open models on rented GPUs (v1 §2.2 portability — a config
change), and (c) **proprietary frontier models via their APIs** (Sora, Veo, Kling,
Seedance, Minimax, and whatever ships next) — see §3. Not cloned: their SaaS
mechanics (credits, tiers, referrals, community feed, app store) — meaningless for
one user. Every *self-hosted* capability below maps to an open, commercially-licensed
model that runs on the 3090; API providers extend the roster beyond it.

---

## 1. What Higgsfield is, condensed

Higgsfield's product identity (verified by research, mid-2026):

1. **Preset-first UX** — the founding wedge. Pick a preset (camera move, VFX,
   style), drop in an image, generate. Prompting is optional refinement. 50–70+
   one-click camera presets (crash zoom, dolly zoom, 360 orbit, FPV drone, bullet
   time…), stackable up to 3; ~23+ VFX presets (levitation, disintegration, set on
   fire…) with curated combos.
2. **Model aggregation** — one UI over Sora/Veo/Kling/Seedance/Wan/Minimax plus
   in-house models (DoP I2V, Soul image, Popcorn storyboards).
3. **Identity as an asset** — Soul ID: train a character once (~20 photos), reuse
   it across images, avatars, and ads.
4. **Speak** — photo + script → talking-head video with emotion-aware TTS, auto
   expressions, camera moves; dubbing into 70+ languages.
5. **Marketing/UGC factory** — product URL → UGC-style ads with consistent avatars
   and locked product shots.
6. **Dual-queue economics** — priority (credits) vs unlimited (shared queue, one
   concurrent job). Their queue mechanics map cleanly onto our existing
   gpu/wan lane split.
7. **No real NLE** — editing is clip-level templates ("Mixed Media") plus announced
   Photoshop/DaVinci plugins. **Our video studio goes beyond the clone here.**

## 2. Feature map: Higgsfield → v2 self-hosted equivalent

| Higgsfield feature | v2 equivalent | Engine (licence) | Lane |
|---|---|---|---|
| Camera presets (crash zoom, orbit, dolly…) | Preset registry + one-click camera-move generation from a still | **Wan2.2-Fun-Control-Camera A14B** GGUF (Apache 2.0) + audited Civitai motion LoRAs | wan (exclusive) |
| Motion stacking / custom trajectories | Advanced trajectory mode | **Uni3C** (Apache 2.0) via WanVideoWrapper; **ReCamMaster** (MIT) for re-shooting existing footage | wan |
| Text/image-to-video | Already planned (v1 B-roll lane, Wan 2.2) | Wan 2.2 T2V/I2V (Apache 2.0) | wan |
| VFX presets (Effects/Effects Mix) | Effect preset registry over video-to-video restyling | **Wan2.2-VACE-Fun-A14B** GGUF (Apache 2.0); Wan 2.1 VACE 1.3B for fast previews | wan / shared (1.3B) |
| Soul image model + style presets | Image studio with curated style presets | **Z-Image Turbo** (Apache 2.0) daily driver; **Qwen-Image** GGUF (Apache 2.0) for text-heavy thumbnails; **SDXL** (OpenRAIL++-M) for style LoRAs | shared-ish / wan (Qwen 20B) |
| Soul ID (character consistency) | Per-identity LoRA training + locked "identity" entity | SDXL / Z-Image LoRA training on the 3090 (overnight batch, wan lane) | wan |
| Popcorn (storyboards) | Multi-frame storyboard generation with consistent seed/identity | Z-Image/SDXL + identity LoRA + shared seeds | shared |
| Speak (talking avatars) | Already core v1 (Chatterbox + MuseTalk); v2 adds emotion controls + preset avatars | Chatterbox (MIT), MuseTalk (MIT) | gpu (render) |
| Higgsfield Audio (TTS, voice clone) | Already core v1 (VoiceProfile) | Chatterbox (MIT) | gpu |
| Music generation (Higgsfield lacks it) | Music bed generation for the editor | **ACE-Step 1.5 base** (Apache 2.0) | shared |
| SFX | CC0 libraries first; Stable Audio Open Small only under its <$1M revenue condition (recorded as conditional) | Stability Community License | shared |
| Upscale / enhance | Finishing pass in the editor | **SeedVR2-3B** (Apache 2.0) hero shots; **Real-ESRGAN** (BSD-3) + **RIFE** (MIT, data caveat noted) cheap lane | wan / shared |
| Prompt enhancement | LLM prompt rewriter (Wan prompts benefit hugely) | **Qwen3.5-4B** GGUF on CPU (Apache 2.0); **Florence-2** (MIT) for captioning | CPU |
| Model aggregation (Sora/Veo/Kling/Seedance/Minimax under one UI) | **Provider layer (§3)** — same interface over local, rented-GPU, and API models | Per-provider APIs + aggregator gateways | provider (network) |
| Marketing/UGC factory | Out of scope for v2.0 — single-channel tool, revisit if ever needed | — | — |
| Community feed, credits, apps, API resellers | Not applicable single-user | — | — |
| Mixed Media / AI Video Editor | **Superseded by the full video studio (§4)** | — | — |

## 3. Model provider layer — local, rented, and API (owner requirement, 2026-07-29)

The aggregator core. One `GenerationProvider` interface; every generation request
names a `(provider, model)` pair and everything downstream is identical: the output
always lands in MinIO as an `Asset` (`origin='generated'`), always carries full
provenance (provider, model, params, seed where available, cost), and always passes
the same compliance gates.

**Provider classes:**

1. **`local`** — the wan-lane executor on this workstation (ComfyUI headless or
   diffusers, decided at M10). Runs the open-model roster in §2. Needs the GPU lock.
2. **`remote-gpu`** — the *same* executor on a rented box. Already designed for in
   v1 §2.2 (S3-only I/O, env addresses, stateless, drain-the-queue); becomes just a
   provider entry whose queue points at the rented worker. No new architecture.
3. **`api`** — proprietary hosted models. Two integration styles:
   - **Aggregator gateways first** (fal.ai, Replicate): one integration surface,
     dozens of models (Kling, Seedance, Hailuo/Minimax, Wan-hosted, LTX-hosted,
     upscalers…), unified async job API. This is the cheapest way to match
     Higgsfield's roster breadth on day one.
   - **Direct APIs where it matters**: OpenAI (Sora), Google Gemini API (Veo),
     Runway, ElevenLabs (voice, if ever wanted beyond Chatterbox). Direct
     integrations get first-party features and pricing but cost one adapter each.

**Mechanics:**

- API keys and endpoints from env/Settings only — same rule as every other service
  address. A provider with no key configured simply doesn't appear in the registry.
- API jobs are **network jobs**: they run on the CPU/worker lane with submit → poll
  → download, never touch the GPU lock, and are retried with backoff. Local jobs
  keep the existing wan-lane lock semantics. Same queue architecture, different lane.
- **Capability discovery**: the registry maps model → capabilities (t2v, i2v,
  camera-control, lipsync, image, upscale, max duration/resolution) so the UI can
  offer "which model for this job" the way Higgsfield merchandises engines
  (Sora=realism, Veo=lighting, Kling=humans, Wan=camera).
- **Cost tracking**: every API generation records its billed cost (or token/credit
  estimate) on the generation record — the single-user replacement for Higgsfield's
  credit system, and the input for the "is a rented GPU cheaper than the API for
  this workload" decision later.
- **Fallback chains**: a preset can declare provider preference order (e.g. camera
  preset → local Fun-Camera; if the lane is busy and the user wants it now → Kling
  via API). Mirrors Higgsfield's priority-vs-relaxed dual queue with real semantics.

**Compliance interactions (structural, as always):** API-generated output is still
synthetic media — C1 watermark and C2 `altered_content` apply identically; the
provider layer cannot bypass the gates because outputs only enter the pipeline as
`origin='generated'` assets. Sending prompts/images to third-party APIs is a data
egress decision the owner makes per-provider by configuring a key. Each provider's
ToS grants on generated content differ (most grant commercial use; some restrict
training or watermark their output) — recorded per provider in the registry at
integration time, not assumed.

## 4. Video studio (the part Higgsfield doesn't have)

Architecture (licences verified; full research in the PR history):

1. **Own timeline UI + data model** in the existing Vite/React SPA. Timeline JSON
   schema modelled on **OpenTimelineIO** semantics (Apache 2.0; use the `opentimelineio`
   Python package server-side for validation and NLE interchange). Study/lift from
   **OpenCut** (MIT, 79k stars) — the strongest open reference; treat
   openvideodev/react-video-editor and Twick as UX references only (non-OSS licences).
2. **Client-side preview**: canvas compositor decoding **server-generated 720p
   short-GOP H.264 proxies** via **mediabunny** (MPL-2.0) + WebCodecs (safe on 2026
   desktop browsers). No in-browser export — preview is "close-enough" WYSIWYG.
3. **Server-side final render**: a hand-written ~500-line **timeline-JSON → ffmpeg
   `filter_complex` compiler** in the CPU worker (trim/setpts normalisation,
   per-track `overlay` + `xfade`, pre-rendered PNG text overlays, `amix` +
   `sidechaincompress` ducking with the voice track as sidechain, segment-then-concat
   for long timelines). References: json-to-ffmpeg (MIT), editly's spec (MIT,
   unmaintained — reference only). Escape hatch if semantics outgrow filtergraphs: MLT/melt.
4. **Asset ingest fan-out** (RQ jobs → MinIO): ffprobe metadata, 720p proxy,
   sprite-sheet + WebVTT scrub thumbnails (`fps`+`tile` filters), waveform peaks via
   **audiowaveform** (GPL-3.0, subprocess-only — no contamination) drawn with
   Peaks.js (LGPL-3.0) or custom canvas.
5. **Compliance hook**: the render compiler checks whether the timeline references
   any asset with `origin='generated'` (or an avatar segment). If yes, the C1
   watermark burn-in is injected into the filtergraph — structurally, same as v1.

## 5. GPU scheduling on the 3090

The v1 two-lane design (render lane vs wan lane, exclusive lock —
`pipeline_core/locks.py`, proven in `tests/test_gpu_exclusivity.py`) extends
naturally; nothing new architecturally, only more wan-lane workloads:

- **Render lane (shared residents, <20 GB):** Chatterbox + MuseTalk (+ optionally
  Z-Image Turbo, SDXL, VACE 1.3B previews, Real-ESRGAN, RIFE, ACE-Step base,
  SeedVR2-3B marginal).
- **Wan lane (exclusive lock):** all Wan 2.2 14B variants (T2V/I2V, Fun-Camera,
  VACE-Fun), Uni3C, ReCamMaster, Qwen-Image 20B, SeedVR2-7B, LoRA training.
- **CPU:** ffmpeg render compiler, proxies/sprites/waveforms, Qwen3.5-4B prompt LLM
  (llama.cpp), Florence-2.

Wan-lane jobs remain batch/overnight-friendly and never block a render — v1's rule.
Generation execution: evaluate **headless ComfyUI as the wan-lane executor** (the
camera/VACE workflows are ComfyUI-mature; wrapping beats reimplementing) vs direct
diffusers. Decide at M10; the queue/lock architecture is identical either way.

## 6. Licence register

**Adopt (clean for commercial use):** Wan 2.2 family incl. Fun-Camera/VACE-Fun
(Apache 2.0), Uni3C (Apache 2.0), ReCamMaster (MIT), Z-Image (Apache 2.0),
Qwen-Image (Apache 2.0), FLUX.2 Klein **4B only** (Apache 2.0), SDXL (OpenRAIL++-M),
SeedVR2 (Apache 2.0), Real-ESRGAN (BSD-3), FILM (Apache 2.0), ACE-Step (Apache 2.0),
Qwen3.5 (Apache 2.0), Florence-2 (MIT), OpenTimelineIO (Apache 2.0), mediabunny
(MPL-2.0), OpenCut code (MIT), Chatterbox (MIT), MuseTalk (MIT).

**Conditional (recorded, revisit before relying on):** RIFE (MIT code, training-data
caveat — FILM is the clean fallback); Stable Audio Open (<$1M revenue cap); Civitai
camera LoRAs (audit each LoRA's licence individually before commercial use).

**Rejected — do not introduce (adds to v1's list):** FLUX.1 [dev] and all
[dev]-licensed FLUX variants, FLUX.2 Klein 9B (non-commercial); MusicGen/AudioCraft
(CC-BY-NC); HunyuanVideo 1.x (licence void in EU — fatal for an EU operator);
LTX-Video 2 (custom licence + FP8-first); MMAudio weights (commercial suitability
disclaimed); Llama family (usable but restricted — redundant next to Qwen);
**Remotion** and **openvideodev/react-video-editor** as dependencies (source-available,
team-gated, terms can change); Twick (Sustainable Use License); Etro (GPL + thin
maintenance); editly/FFCreator as dependencies (unmaintained — spec references only).

## 7. Milestones

M10–M18, appended to docs/milestones.md with acceptance criteria. Sequence: the
provider layer + wan-lane executor first (M10 — everything else routes through it),
then the signature clone features (M11–M13), then the studio (M14–M16), then
identity + audio polish (M17–M18). v1 M2–M7 ship first.

## 8. Compliance and ethics guardrails

- C1–C5 carry over unchanged and extend to v2 outputs: any rendered timeline
  containing generated assets or avatar footage gets the watermark burn-in (§4.5)
  and the `altered_content` flag on upload. Frame-sampling tests extend to studio
  renders at M16.
- **Identity policy (structural, like C1–C5):** identity LoRA training ("Soul ID"
  equivalent) and face-bearing avatar generation are restricted to identities with
  recorded consent — practically: the owner. A new `Identity` entity carries
  `consent_recorded_by` / `consent_at`, and training/generation endpoints refuse
  identities without it. Arbitrary face-swap of third parties is **not** cloned.
- Single-user, self-hosted: we remain an EU AI Act *deployer*. The v1 §9 warning
  stands and gets sharper with v2's capabilities — offering any of this to other
  people flips us to *provider* (machine-readable marking, consent verification as
  a feature, liability for users' generations). Not planned; recorded so it cannot
  happen by drift.

## 9. Open questions / risks

1. **ComfyUI vs diffusers** as the wan-lane executor (decide at M10). ComfyUI wins
   on workflow maturity for camera/VACE; adds a service dependency and its own
   Python env.
2. **14B-on-24GB latency**: Fun-Camera A14B GGUF with 4-step accelerator LoRAs is
   reported workable but tight (~16–22 GB). If quality/speed disappoints, the 5B
   variants are the fallback at lower fidelity. Benchmark early in M10, workstation
   session — same "measure, don't trust estimates" rule as v1 M0.
3. **Preset quality parity**: Higgsfield's presets are curated/tuned; ours will need
   iteration on prompt templates + LoRA weights per move. The preset registry is
   data (JSON), so tuning is content work, not code work.
4. **Editor scope creep**: the studio is the largest single work item (M14–M16).
   The MVP cut is: multi-track, trim/split/move, xfade, text overlays, audio ducking,
   proxy preview, server render. Everything else (keyframed effects, masks, speed
   ramps) is post-MVP.
5. **Disk**: model zoo grows to ~150–300 GB of weights. Pinned versions + scripted
   download (v1 rule) becomes mandatory hygiene, and the weights directory needs its
   own drive budget.
