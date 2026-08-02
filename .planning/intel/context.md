# Context

Topic-keyed notes from the DOCs (milestones.md, workstation.md) plus narrative/context
material from the hybrid PRD/SPEC docs that fits neither decisions, requirements, nor
constraints.

## Milestone progress — AUTHORITATIVE completion state
- source: /Users/karstenhaldan/Video-studio/docs/milestones.md
- Durable progress record M0–M30; Claude Code ticks boxes as work lands; survives context resets. Acceptance criteria are commands that exit zero (rationale: docs/psd.md §5, §8 — psd itself delegates progress authority to this file).
- 138 checkboxes total: 125 checked, 13 unchecked. Treat completion state as fact.
- The 13 unchecked boxes are ALL RTX-3090-workstation-only tasks:
  - M0 (all 4): verify_gpu on the 3090 host; Chatterbox 10 s clip; MuseTalk 5 s lip-sync; both resident < 20 GB
  - M2.3: latent cache built and persisted per loop; M2.4: cached re-render measurably faster
  - M3.1: real Chatterbox/MuseTalk loads warm at boot; M3.4: chunked lip-sync with real MuseTalk
  - M9.1: Wan 2.2 quantised loads and generates a 5 s clip
  - M10.6: Fun-Camera A14B GGUF + 4-step LoRA benchmark (decides 14B vs 5B default)
  - M11.2: Wan2.2-Fun-Control-Camera integration live; Civitai LoRAs individually licence-audited
  - M17.2: real identity LoRA trainer (`worker_gpu/engines/identity.py`), overnight run; M17.3: trained identity usable across image studio / storyboards / avatars
- Everything else (CI, tests, panel, MCP, M4–M8 CPU-side, M10–M30) is green in the repo. Notable landed items: ComfyUI executor (M10), 16 camera presets (M11), image studio v2 (M12/M28), VFX lane (M13), studio ingest (M14), timeline editor + v2 UX (M15/M23/M26), render compiler with structural C1 (M16), consent/C6 (M17), audio suite (M18), storyboards (M19), projects (M20), MCP surface with no publish/consent/approve tools (M21), cost tracking (M22), Florence-2 captioning (M24), ops backup/restore (M25), prompt catalog (M27), ComfyUI plugin installer + ElevenLabs (M29), macOS live generation on Wan2.1-T2V-1.3B/MPS (M30, asset 738a5389, 2026-08-01).

## Remaining work — the ordered workstation runbook
- source: /Users/karstenhaldan/Video-studio/docs/workstation.md (§5)
- "Acceptance day" runbook: every unchecked milestone box lives on the RTX 3090 host; run top to bottom; each step names the command that must exit 0 and the box it ticks. This list is the entire remaining gap.
- Steps 1–15: (1) `verify_gpu.py` → M0.1; (2) implement real engine loads then `bench.py --smoke` → M0.2–M0.4, M3.1; (3) first avatar render end-to-end → M3.4; (4) real latent cache build → M2.3; (5) `bench.py --loop <id>` → M2.4; (6) ComfyUI up + `COMFY_URL`; (7) first Wan 2.2 clip → M9.1; (8) Fun-Camera benchmark → M10.6; (9) camera presets live + Civitai LoRA audits → M11.2; (10) Uni3C/ReCamMaster trajectories (re-verify on hardware); (11) implement `engines/identity.py`, overnight LoRA run → M17.2; (12) trained identity flows → M17.3; (13) real enhancement + captions install (re-verify; box already ticked); (14) real-credential YouTube publish (M6 workstation acceptance); (15) paste measured numbers into pipeline-spec §6, delete the placeholder banner.

## Workstation setup — RTX 3090 host
- source: /Users/karstenhaldan/Video-studio/docs/workstation.md (§1–§4)
- Three native processes (never containerised) + one sidecar: `worker_gpu/run.py` (render lane, queue `gpu`), `worker_gpu/run_wan.py` (wan lane, queue `wan`), ComfyUI headless on :8188. Everything else can live anywhere reaching the same env-configured services.
- ComfyUI: one-command install (`scripts/install_comfyui.sh`) incl. node packs per the `pipeline_core/comfy_nodes.py` manifest (drift-guarded by `tests/test_comfy.py`); own venv; Settings tab shows live online state and diffs templates against `/object_info`. `COMFY_TIMEOUT_S` bounds how long a wan job may hold the GPU lock. MuseTalk node pack needs the mmlab stack — GPU-host install only.
- Model weights per the roadmap-v2 §6 register, nothing outside it: Wan 2.2 t2v/i2v/fun-camera/vace-fun A14B Q5_K_M GGUFs, wan2.1-vace-1.3b, z-image-turbo, qwen-image 20B Q4_K_M, SDXL base, ace-step 3.5b, plus matching encoders/VAEs. Pinned versions; weights never enter git. Identity LoRAs sync from `s3://…/identities/{id}/lora.safetensors` into ComfyUI `models/loras/` — automating that sync is an open item.
- Workflow templates are structurally valid skeletons; tune in the ComfyUI UI, export in API format, re-run the structural audit. Template tuning is content work, not code work.
- Bring-up order: `verify_gpu.py` → `bench.py --smoke` → wan lane smallest first (z-image still → wan2.2-t2v 5 s → fun-camera → VACE preview) → both workers.

## v2 background — Higgsfield teardown and open questions
- source: /Users/karstenhaldan/Video-studio/docs/roadmap-v2.md (§1, §2, §9)
- Higgsfield product identity: preset-first UX (50–70+ camera presets, stackable ≤3; ~23+ VFX presets), model aggregation, identity-as-asset (Soul ID), Speak talking avatars, marketing/UGC factory, dual-queue economics, no real NLE. v2 clones capabilities self-hosted and goes beyond with the studio; marketing/UGC factory and SaaS mechanics out of scope.
- Open questions/risks recorded: (1) ComfyUI vs diffusers — RESOLVED, ComfyUI landed (milestones M10); (2) 14B-on-24GB latency ~16–22 GB, benchmark early (open: M10.6), 5B variants fallback; (3) preset quality parity is content/tuning work (preset registry is data); (4) editor scope creep — MVP cut defined, keyframed effects/masks/speed ramps post-MVP; (5) disk: model zoo grows to ~150–300 GB, pinned versions + scripted download mandatory.
- Sequencing note in the header ("v1's M2–M7 render pipeline must ship before v2 work starts") is historical — see INGEST-CONFLICTS.md INFO.

## Working method and v1 out-of-scope
- source: /Users/karstenhaldan/Video-studio/docs/psd.md (§7–§9)
- One milestone per session; milestones.md is the durable progress record; acceptance criteria are commands; write compliance tests before implementation; CLAUDE.local.md (gitignored) for machine-specific paths; benchmark at M0 and replace pipeline-spec §6 estimates with measured numbers.
- Out of scope v1, deliberately: script generation, multi-language/dubbing, real-time/conversational rendering, Teams integration, multi-user/auth/SaaS. Rented GPU execution out of scope for v1 but designed for (§2.2). The fork worth naming: remote execution for yourself (config change) vs offering to other people (EU AI Act deployer → provider, materially heavier obligations — do not drift into it).
- Repo structure in psd §3 ("avatar-pipeline/") is the original sketch; the codebase has since grown `pipeline_core`, `studio_mcp`, `deploy/`, etc. — trust the codebase map over psd §3 for layout.

## Cross-doc reference map
- source: all five classification files in /Users/karstenhaldan/Video-studio/.planning/intel/classifications/
- In-set edges: psd → {pipeline-spec, milestones}; pipeline-spec → {psd}; roadmap-v2 → {psd, milestones}; milestones → {psd, roadmap-v2, workstation}; workstation → {pipeline-spec, roadmap-v2, milestones}. Out-of-set refs: docs/mcp.md, docs/ops.md, docs/mac-dev.md, code/test files. See INGEST-CONFLICTS.md WARNING for the cycle finding.
