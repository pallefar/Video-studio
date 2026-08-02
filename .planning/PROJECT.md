# AI Video Studio

(repo: Video-studio — "Avatar Render Pipeline → AI Video Studio")

## What This Is

A self-hosted, single-user AI video studio: script goes in, a compliant, publishable
1080p avatar video comes out unattended — plus a Higgsfield-class generation studio
(camera presets, image studio, identities, storyboards, multi-track timeline editor,
model aggregation) built on the same pipeline. Runs in macOS dev mode (Apple Silicon,
`DEV_ENGINES` placeholders + MPS wan lane) and in production on an RTX 3090 GPU
workstation.

## Core Value

A script becomes a compliant, publishable 1080p video, unattended, in under 20 minutes
of wall clock — with compliance (C1–C6) enforced structurally, never procedurally.

## Definition of Done

`docs/milestones.md` has no unchecked boxes (13 remain, all RTX-3090-workstation tasks,
ordered by `docs/workstation.md` §5), with full pytest + vitest + build green.

## Requirements

### Validated

<!-- Shipped and confirmed by the authoritative milestone record (docs/milestones.md, treated as fact). -->

- ✓ REQ-schema-single-source — M1 (schema single source, TS generated, portability tests)
- ✓ REQ-assembly — M4 (loudnorm −14 LUFS, watermark, captions, B-roll insert, H.264 CRF 18)
- ✓ REQ-compliance-gate — M5 (validators, frame sampling, provenance precondition)
- ✓ REQ-control-panel — M7 (plain fetch polling accepted as the shipped stack — user decision 2026-08-02)
- ✓ REQ-stock-ingest-library — M8 (Pexels + Pixabay, licence persisted, people-flag gate)
- ✓ REQ-broll-resolution — M8/M9 (three-tier resolver, flagged assets never selected)
- ✓ REQ-c1-visible-watermark — M5/M16 (structural burn-in, frame-sampled 10/50/90%)
- ✓ REQ-c2-altered-content — M5/M6 (publish-worker precondition)
- ✓ REQ-c3-audio-watermark — M4/M5 (encode-chain round-trip test)
- ✓ REQ-c4-provenance — M5 (publish requires a PublishRecord)
- ✓ REQ-c5-private-uploads — M6 (no API path sets public)
- ✓ REQ-c6-identity-consent — M17 (consent enforced at API and wan-lane worker; re-verified against the real trainer in Phase 5)

### Active

<!-- The entire remaining gap: 13 workstation boxes, sequenced by docs/workstation.md §5. -->

- [ ] REQ-gpu-environment — verify_gpu on the 3090; Chatterbox + MuseTalk resident, peak VRAM < 20 GB (M0)
- [ ] REQ-gpu-worker — real engine loads warm at boot; chunked lip-sync with real MuseTalk (M3.1, M3.4)
- [ ] REQ-loop-preprocessing — real latent cache built and persisted; cached re-render ≥ 40% faster (M2.3, M2.4)
- [ ] REQ-generative-broll-lane — Wan 2.2 quantised loads and generates a 5 s clip on the exclusive wan lane (M9.1)
- [ ] REQ-publish — real-credential YouTube publish lands private with disclosure visible in Studio (M6 workstation acceptance)
- [ ] REQ-end-to-end-render — wall-clock target < 20 min bench-measured; pipeline-spec §6 placeholders replaced

### Out of Scope

- Script generation, multi-language/dubbing, real-time conversational rendering, Teams integration — v1 non-goals (psd §1)
- Multi-user / auth / SaaS mechanics (credits, tiers, referrals, feed, app store) — single-user self-hosted by design (roadmap-v2 §0)
- Marketing/UGC factory (Higgsfield's) — not cloned (roadmap-v2 §2)
- Offering the system to others — flips EU AI Act deployer → provider (materially heavier obligations); recorded so it cannot happen by drift (psd §9, roadmap-v2 §8)
- Arbitrary third-party face-swap — not cloned; identity features are consent-gated (C6)
- TanStack Query polling migration — optional future improvement, explicitly NOT a requirement (user decision 2026-08-02; plain fetch is the accepted stack)
- Rejected models/deps per the licence register — FLUX.1 [dev], FLUX.2 Klein 9B, MusicGen, HunyuanVideo 1.x, LTX-Video 2, MMAudio weights, Llama family, Remotion, react-video-editor, Twick, Etro, editly/FFCreator (roadmap-v2 §6: do not introduce)

## Context

- **Brownfield with an authoritative record**: `docs/milestones.md` (M0–M30, 138 boxes,
  125 checked) is the durable progress record; completion state is fact. The 13 unchecked
  boxes are all RTX-3090-workstation tasks; their ordered plan of record is
  `docs/workstation.md` §5 (runbook steps 1–15).
- **Codebase map**: `.planning/codebase/` (7 evidence-backed documents). Trust it over
  psd §3's original repo sketch — the codebase has since grown `pipeline_core`,
  `studio_mcp`, `deploy/`, etc.
- **Architecture**: FastAPI + Redis/RQ + SQLModel; three queue lanes — `gpu` (render:
  Chatterbox + MuseTalk shared residents), `wan` (exclusive GPU lock: Wan 2.x via the
  ComfyUI headless sidecar), `cpu` (ffmpeg, API providers, publish). Vite/React SPA
  served by FastAPI; MCP control surface; Docker Compose only for Postgres/Redis/MinIO.
- **Two runtimes**: macOS dev mode (`DEV_ENGINES=1` placeholders, MPS wan lane, M30
  live generation on Wan2.1-T2V-1.3B) and the RTX 3090 workstation for production
  engines (three native processes + ComfyUI sidecar, never containerised locally).
- **Working method**: acceptance criteria are commands that exit 0; compliance tests
  written before implementation; `CLAUDE.local.md` (gitignored) for machine paths;
  weights pinned + scripted download, never in git.

## Constraints

- **Hardware envelope (hard)**: RTX 3090, 24 GB, `sm_86` — **no FP8** (BF16 inference,
  GGUF/INT8 quantised). One model lane at a time; render lane (Chatterbox + MuseTalk)
  peak < 20 GB; Wan lane exclusive GPU lock (`tests/test_gpu_exclusivity.py`).
  `scripts/verify_gpu.py` first, always. — pipeline-spec §1
- **Licence register (binding, hard)**: roadmap-v2 §6 is the adopt/conditional/rejected
  list for model weights and studio dependencies; workstation weights must stay inside
  it — "nothing outside it" (workstation.md §2). Sidecar exception: ComfyUI (GPL-3.0)
  + node packs run as a separate HTTP service only, never linked into the studio
  process. Conditional entries (RIFE, Stable Audio Open, Civitai camera LoRAs) need
  individual audit before reliance. — roadmap-v2 §6
- **Compliance C1–C6 (structural, hard)**: visible "Made with AI" watermark full
  duration (C1, EU AI Act Art. 50(4), applicable from 2026-08-02); `altered_content`
  on every upload (C2); Chatterbox audio watermark survives the encode chain (C3);
  provenance record per published video (C4); uploads land private, human review
  before public (C5); identity training/generation refuses identities without recorded
  consent (C6). Enforced in validators, tests, and hooks — never only in docs.
- **Schema single source**: `packages/schema/models.py`; TS types generated; state
  machine `queued → tts → lipsync → assemble → review → publishing → published`;
  every stage idempotent on `(job_id, stage)`. — pipeline-spec §3
- **Portability**: all I/O via S3 API; no `localhost` literals in worker code; addresses
  from env through `Settings`; workers stateless, designed for rented GPUs over
  Tailscale/WireGuard. — psd §2.2, pipeline-spec §7
- **ffmpeg assembly chain**: CFR-only ingest (reject VFR); loudnorm → watermark →
  captions → B-roll → `libx264 -crf 18 -pix_fmt yuv420p -movflags +faststart`. — pipeline-spec §4
- **Failure modes**: segment is the retry unit; never widen chunk windows on OOM retry;
  quota exhaustion ≠ failure; per-stage metrics for thermal-throttle detection. — pipeline-spec §5
- **Performance placeholders**: pipeline-spec §6 figures are estimates, not
  measurements — do not reason from them; runbook step 15 replaces them. — pipeline-spec §6

## Key Decisions

<decisions status="proposed">

<!-- 0 locked, 16 proposed — no ingested source carries `locked: true`. Recorded as proposed;
     full text and sources in .planning/intel/decisions.md. -->

| ID | Decision | Status |
|----|----------|--------|
| DEC-v1-stack | FastAPI + Pydantic v2, Redis+RQ, SQLModel+Alembic, native-venv GPU worker, Vite+React+TS, Compose for infra only | proposed |
| DEC-no-nextjs | No Next.js — Vite SPA served by FastAPI as static files, one origin | proposed |
| DEC-gpu-worker-native | GPU worker native venv locally; container is a CI build artefact only | proposed |
| DEC-rented-gpu-portability | S3-only I/O, env-only addresses, stateless workers, idempotent stages — rented-GPU-ready from M1 | proposed |
| DEC-broll-asset-library | B-roll is a pre-produced asset library, not a render stage (VRAM: Wan ≈ full card) | proposed |
| DEC-wan22 | Wan 2.2 (Apache 2.0) GGUF/INT8, never FP8; Hunyuan/LTX/Mochi rejections recorded | proposed |
| DEC-stock-providers | Pexels primary, Pixabay secondary (caching rights); Unsplash rejected | proposed |
| DEC-stock-people-policy | `has_identifiable_people` defaults true on ingest; flagged assets unselectable | proposed |
| DEC-immutable-profiles | VoiceProfile/BaseLoop immutable once referenced; re-clone = new version | proposed |
| DEC-structural-compliance | Compliance in validators/tests/hooks, never only in CLAUDE.md | proposed |
| DEC-v2-scope | v2 = Higgsfield-class aggregator + real multi-track studio; SaaS mechanics not cloned | proposed |
| DEC-provider-layer | One `GenerationProvider` interface; local / remote-gpu / api classes; keys env-only; cost tracked | proposed |
| DEC-licence-policy | MIT/Apache rule + binding §6 register; ComfyUI GPL sidecar exception (2026-07-31) | proposed |
| DEC-storyboard-first | Every video starts as a Storyboard of Shots; storyboard → timeline → render is one continuum | proposed |
| DEC-identity-consent | Identity training/generation consent-gated structurally (C6); provider role out of scope | proposed |
| DEC-comfyui-executor | ComfyUI headless as the wan-lane executor — decided and landed (M10) | proposed |

</decisions>

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Plain fetch polling accepted for the control panel (2026-08-02) | Shipped reality; TanStack Query is an optional future improvement, not a requirement | ✓ Good |
| docs/milestones.md is the authoritative completion record | psd §8 delegates progress authority to it; survives context resets | ✓ Good |
| Remaining work sequenced by docs/workstation.md §5 runbook | Every open box is a 3090-host task; the runbook is the ordered plan of record | — Pending |

---
*Last updated: 2026-08-02 after /gsd-new-project ingest (mode: new-project-from-ingest)*
