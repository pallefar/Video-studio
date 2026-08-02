# Roadmap: AI Video Studio

## Overview

Brownfield project with an authoritative milestone record: `docs/milestones.md`
(M0–M30, 138 boxes, 125 checked) is fact and is incorporated below, not re-derived.
The entire remaining gap is 13 unchecked boxes — all RTX-3090-workstation tasks —
phased here following the ordered runbook in `docs/workstation.md` §5 (steps 1–15):
GPU sanity → real engine loads → first render → latent cache → ComfyUI/Wan bring-up →
camera presets → identity training → real-credential publish → measured numbers into
pipeline-spec §6. When Phase 6 completes, `docs/milestones.md` has no unchecked boxes
and full pytest + vitest + build are green — the project's definition of done.

## Completed Milestones (M0–M30 — record: docs/milestones.md, treated as fact)

Compressed; do not re-plan. Milestones carrying open workstation boxes point at the
phase that closes them.

| Milestone | Delivered | Status |
|-----------|-----------|--------|
| M0 — Environment | verify_gpu script; engines resident < 20 GB | 0/4 boxes — all → Phase 1 |
| M1 — Schema + API skeleton | schema single source, TS generation, Alembic, MinIO, portability tests | Shipped |
| M2 — Loop preprocessing | CFR-enforced ingest, seam detection + ping-pong fallback | 2 open (M2.3, M2.4) → Phase 2 |
| M3 — GPU worker | long-lived worker, queue topology, chunk orchestration, seed pinning | 2 open (M3.1, M3.4) → Phase 1 |
| M4 — Assembly | loudnorm −14 LUFS, watermark, captions, B-roll insert, H.264 CRF 18 | Shipped |
| M5 — Compliance gate | validators, frame sampling, provenance precondition, negative tests | Shipped |
| M6 — Publish | YouTube OAuth, private-always uploads, altered_content, quota backoff | Shipped (real-credential acceptance → Phase 6) |
| M7 — Control panel | submit / live status / preview / manual publish (plain fetch polling — accepted) | Shipped |
| M8 — Stock ingest + asset library | Pexels/Pixabay, licence persisted, people-flag gate, embedding search | Shipped |
| M9 — Generative B-roll lane | wan queue, exclusive GPU lock, approval gate | 1 open (M9.1) → Phase 3 |
| M10 — Provider layer + wan-lane executor | GenerationProvider, ComfyUI submit→poll→fetch client, workflow templates | 1 open (M10.6) → Phase 3 |
| M11 — Camera presets (the signature) | 16 presets, preset registry, motion codes wired | 1 open (M11.2) → Phase 4 |
| M12 — Image studio ("Soul" equivalent) | image generation studio | Shipped |
| M13 — VFX & finishing lane | VFX presets, enhancement lane | Shipped |
| M14 — Studio ingest pipeline | probe metadata, proxies, sprites, waveforms | Shipped |
| M15 — Timeline editor MVP | multi-track timeline, canvas preview | Shipped |
| M16 — Server render compiler | timeline-JSON → ffmpeg filter_complex, structural C1 injection | Shipped |
| M17 — Identity & consent ("Soul ID") | Identity entity, C6 consent gates, training stage + queue routing | 2 open (M17.2, M17.3) → Phase 5 |
| M18 — Audio suite & prompt intelligence | ACE-Step, prompt LLM, caption/embedding stack | Shipped (hardware re-verify in Phase 6) |
| M19 — Storyboards, style templates & formats | Storyboard/Shot schema, long/short formats, export gates | Shipped |
| M20 — Projects: asset center → video center | project workspace | Shipped |
| M21 — MCP control surface | any-LLM access; no publish/consent/approve tools exposed | Shipped |
| M22 — Cost tracking + observability | per-generation cost, metrics | Shipped |
| M23 — Editor v2 | transport, audio lane, hover-scrub | Shipped |
| M24 — Library intelligence | Florence-2 auto-captioning | Shipped |
| M25 — Ops | backup, restore, services | Shipped |
| M26 — Timeline completion, reliability, publish-everything, web tests | | Shipped |
| M27 — Prompt intelligence | catalog + reverse prompt engineering | Shipped |
| M28 — Leonardo-class image studio, image→motion, audio suite UI | | Shipped |
| M29 — ComfyUI plugin installer + ElevenLabs provider | | Shipped |
| M30 — macOS live generation | Wan2.1-T2V-1.3B on MPS (asset 738a5389, 2026-08-01) | Shipped |

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

All six phases run on the RTX 3090 host, in runbook order (docs/workstation.md §5).

- [ ] **Phase 1: Render Engines Live** - GPU sanity, real Chatterbox + MuseTalk loads, first end-to-end avatar render (runbook 1–3; M0.1–M0.4, M3.1, M3.4)
- [ ] **Phase 2: Latent Cache** - Real per-loop MuseTalk latent cache; cached re-render measurably faster (runbook 4–5; M2.3, M2.4)
- [ ] **Phase 3: Wan Lane Bring-Up** - ComfyUI sidecar live, first Wan 2.2 clip, Fun-Camera benchmark decides 14B vs 5B (runbook 6–8; M9.1, M10.6)
- [ ] **Phase 4: Camera Presets on Hardware** - Presets render acceptably, Civitai LoRA licence audits, Uni3C/ReCamMaster trajectories (runbook 9–10; M11.2)
- [ ] **Phase 5: Identity Training** - Real LoRA trainer, overnight run, trained identity usable everywhere, C6 holds (runbook 11–12; M17.2, M17.3)
- [ ] **Phase 6: Acceptance Close-Out** - Enhancement re-verify, real-credential publish, measured numbers into pipeline-spec §6, all boxes ticked (runbook 13–15)

## Phase Details

### Phase 1: Render Engines Live
**Goal**: The avatar render lane runs with real models on the 3090 — GPU verified, Chatterbox + MuseTalk resident under budget, and a scripted avatar video renders end-to-end unattended
**Depends on**: Nothing (first phase — runbook steps 1–3)
**Requirements**: REQ-gpu-environment, REQ-gpu-worker
**Milestone boxes**: M0.1, M0.2, M0.3, M0.4, M3.1, M3.4
**Success Criteria** (what must be TRUE):
  1. `python scripts/verify_gpu.py` exits 0 on the 3090 host (capability `(8, 6)`)
  2. Real engine loads implemented in `worker_gpu/engines/{tts,lipsync}.py`; `python scripts/bench.py --smoke` exits 0 with Chatterbox producing a 10 s clip, MuseTalk lip-syncing 5 s, and both resident simultaneously with peak VRAM logged under 20 GB
  3. A short script submitted in the panel goes `queued → review` unattended — the first real end-to-end avatar render
  4. A >90 s script splits into 60–90 s chunked lip-sync windows with real MuseTalk and stitches without a visible seam
**Plans**: 5 plans (4 waves — plans 01 and 02 run in parallel; the rest are strictly sequential per runbook order)

Plans:
- [ ] 01-01-PLAN.md — GPU host environment: resolve the Chatterbox/MuseTalk torch conflict, pin it, `verify_gpu.py` green (M0.1)
- [ ] 01-02-PLAN.md — Warm both models at boot in `worker_gpu/run.py`; lock the engine interface contract with CUDA-free tests (M3.1 code half)
- [ ] 01-03-PLAN.md — Tracer: real Chatterbox + real MuseTalk render one sentence to one lip-synced chunk, sharing one contract layer
- [ ] 01-04-PLAN.md — `bench.py --smoke` renders for real on the 3090; honest peak-VRAM measurement under 20 GB (M0.2, M0.3, M0.4, M3.1)
- [ ] 01-05-PLAN.md — Frame-continuous multi-window chunking; first unattended `queued → review` render from the panel (M3.4)

### Phase 2: Latent Cache
**Goal**: Re-rendering against a preprocessed loop is measurably faster because the real MuseTalk latent cache is built and persisted per loop
**Depends on**: Phase 1 (real MuseTalk engine; runbook steps 4–5)
**Requirements**: REQ-loop-preprocessing
**Milestone boxes**: M2.3, M2.4
**Success Criteria** (what must be TRUE):
  1. The real latent cache build in `worker_gpu/preprocess/loop_cache.py` runs on the 3090 and the cache is persisted per loop
  2. `python scripts/bench.py --loop <id>` compares the two latest lipsync runs and shows the cached run ≥ 40% faster than the first
**Plans**: 3 plans (3 waves — strictly sequential; waves 1 and 2 are fully CPU-doable on a Mac, wave 3 needs the 3090)

Plans:
- [ ] 02-01-PLAN.md — Tracer: wire the dead `build_loop_cache` path end to end — dispatch chain, GPU stage, ObjectStore bridge, invalidation, with the model call behind one seam (CPU-doable now)
- [ ] 02-02-PLAN.md — Fix the two bugs that make this phase's own acceptance command unmeasurable: the lipsync metric ref and `bench_loop`'s query (CPU-doable now)
- [ ] 02-03-PLAN.md — Real MuseTalk preparation behind the seam, cache-hit path in `sync_chunk`, and the ≥ 40% workstation measurement (M2.3, M2.4 — GPU-blocked)

### Phase 3: Wan Lane Bring-Up
**Goal**: The generative lane is live on hardware — ComfyUI headless serving as the wan-lane executor, Wan 2.2 generating real clips, and the Fun-Camera benchmark deciding the 14B-vs-5B default
**Depends on**: Phase 2 (render lane fully proven first, per runbook order; runbook steps 6–8)
**Requirements**: REQ-generative-broll-lane
**Milestone boxes**: M9.1, M10.6
**Success Criteria** (what must be TRUE):
  1. ComfyUI headless runs on :8188 with every node pack from the `pipeline_core/comfy_nodes.py` manifest importable; the Settings tab shows **online** and the template diff against `/object_info` is clean
  2. Bring-up order holds smallest-first: a z-image-turbo still, then a Wan 2.2 quantised (GGUF) 5 s t2v clip generated via the panel, landing as `origin='generated'`, `approved=false`
  3. Lane exclusivity holds on hardware: a wan-lane generation never holds the GPU concurrently with a render, and a queued generation never blocks a render
  4. Fun-Camera A14B GGUF + 4-step LoRA benchmarked (latency + VRAM via nvidia-smi recorded); the 14B-vs-5B default is decided and written down
**Plans**: 8 plans (8 waves — strictly sequential; waves 1–5 are fully CPU-doable now on a Mac, waves 6–8 need a CUDA sm_86 card: the 3090 OR a rented box via `scripts/rent_gpu.sh` + an SSH tunnel)

**Planning finding (2026-08-02):** 10 of the 13 shipped workflow templates are structurally broken —
6 wire CLIP/VAE from output indices a one-output loader does not have, 8 omit `VHS_VideoCombine`
inputs the pack declares required, and 5 contain a node unreachable from the graph's output so the
studio parameter patched into it is silently discarded (Fun-Camera's `camera_motion`, i2v/VACE
source assets, SDXL's identity LoRA). The existing structural audit passes all 13. Every repair is
CPU-provable and is front-loaded ahead of any hardware session.

Plans:
- [ ] 03-01-PLAN.md — Tracer: signature-driven graph audit (output-index bounds, required inputs, reachability) proven end to end on a new `wan2.2-ti2v-5b` path; multi-path input mapping (CPU-doable now)
- [ ] 03-02-PLAN.md — Wan 2.2 A14B rebuilt as the two-expert MoE it actually is: two loaders, two chained samplers, connected source/camera inputs (CPU-doable now)
- [ ] 03-03-PLAN.md — The 4-step Lightning Fun-Camera arm + `scripts/bench.py --wan`: latency and peak VRAM sampled during the run, works over an SSH tunnel (CPU-doable now)
- [ ] 03-04-PLAN.md — The remaining repairs (VACE 1.3B, qwen-image, sdxl, musetalk, uni3c, recammaster) and the audit closed as a permanent standing gate (CPU-doable now)
- [ ] 03-05-PLAN.md — Bring-up tooling: node-pack commit pinning, one template-derived model fetcher with a filename drift guard, runbook steps 6–8 as commands (CPU-doable now)
- [ ] 03-06-PLAN.md — ComfyUI live on hardware: licence gate, pinned install, installed-vs-recorded signature check, clean `/object_info` diff (criterion 1 — GPU-blocked)
- [ ] 03-07-PLAN.md — Smallest-first first clips and lane exclusivity under real load (criteria 2 + 3, M9.1 — GPU-blocked)
- [ ] 03-08-PLAN.md — Fun-Camera benchmark, the 14B-vs-5B decision, and applying it everywhere the default is named (criterion 4, M10.6 — GPU-blocked)

### Phase 4: Camera Presets on Hardware
**Goal**: The signature camera-preset experience works on real hardware — presets render acceptably through Wan2.2-Fun-Control-Camera, with every Civitai LoRA individually licence-audited before inclusion
**Depends on**: Phase 3 (wan lane + 14B/5B decision; runbook steps 9–10)
**Requirements**: None open (delivers M11.2; licence-register constraint roadmap-v2 §6 applies — Civitai LoRAs are conditional entries)
**Milestone boxes**: M11.2
**Success Criteria** (what must be TRUE):
  1. At least one camera preset per category renders acceptably via the Wan2.2-Fun-Control-Camera integration in the local provider
  2. Every Civitai camera LoRA added to `models/loras/` has an individual licence audit recorded before inclusion — none enters unaudited
  3. Uni3C / ReCamMaster advanced-trajectory workflows are re-verified on hardware (templates added per workstation.md §3, structural audit `pytest tests/test_comfy.py` green)
**Plans**: TBD

### Phase 5: Identity Training
**Goal**: A real identity LoRA trains overnight on the wan lane and the trained identity is usable across image studio, storyboards, and avatars — with the C6 consent gate holding against the real trainer
**Depends on**: Phase 3 (wan lane live; ComfyUI `models/loras/` path working — Phase 4 precedes per runbook order; runbook steps 11–12)
**Requirements**: None open (delivers M17.2, M17.3; REQ-c6-identity-consent — shipped — is re-verified against the real trainer)
**Milestone boxes**: M17.2, M17.3
**Success Criteria** (what must be TRUE):
  1. `worker_gpu/engines/identity.py` implements the real LoRA trainer (SDXL/Z-Image); an overnight training run launched from the Identities tab completes on the wan lane under the exclusive GPU lock
  2. Trained weights land at `s3://…/identities/{id}/lora.safetensors` and reach ComfyUI's `models/loras/` (synced; automation of the sync noted as open item if not closed here)
  3. A trained identity generates via `identity_id` in the image studio, in a storyboard, and in an avatar flow
  4. Training or generation for an identity without recorded consent is still refused with the real trainer in the loop (`pytest tests/test_identity_consent.py` green — C6)
**Plans**: TBD

### Phase 6: Acceptance Close-Out
**Goal**: The acceptance-day runbook table is done — enhancement/captions re-verified on hardware, a real-credential publish lands private with disclosure, measured figures replace the pipeline-spec placeholders, and the milestone file has no unchecked boxes
**Depends on**: Phase 5 (all milestone boxes ticked before close-out; runbook steps 13–15)
**Requirements**: REQ-publish, REQ-end-to-end-render
**Milestone boxes**: none new (M6 workstation acceptance; M18.4 hardware re-verify; pipeline-spec §6 banner)
**Success Criteria** (what must be TRUE):
  1. Real enhancement + caption extras installed (`pip install -e ".[enhance,caption]"`, `QWEN_MODEL_PATH` set) and `scripts/backfill_embeddings.py --recaption` runs on the workstation (M18.4 re-verified)
  2. A reviewed render publishes to YouTube with real `YOUTUBE_*` credentials: the upload lands **private** with the `altered_content` disclosure visible in Studio — no path publishes public
  3. An 8-minute video completes end to end in under 20 minutes of measured wall clock; the placeholder table in `docs/pipeline-spec.md` §6 is replaced with measured figures and the placeholder banner deleted
  4. `docs/milestones.md` has no unchecked boxes and full pytest + vitest + build are green — the project's definition of done
**Plans**: TBD

## Progress

**Execution Order:** Strict runbook order — 1 → 2 → 3 → 4 → 5 → 6 (docs/workstation.md §5, top to bottom).

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Render Engines Live | 0/5 | Planned | - |
| 2. Latent Cache | 0/3 | Planned | - |
| 3. Wan Lane Bring-Up | 0/TBD | Not started | - |
| 4. Camera Presets on Hardware | 0/TBD | Not started | - |
| 5. Identity Training | 0/TBD | Not started | - |
| 6. Acceptance Close-Out | 0/TBD | Not started | - |

---
*Roadmap created: 2026-08-02 (mode: new-project-from-ingest; milestone record incorporated, not re-derived)*
