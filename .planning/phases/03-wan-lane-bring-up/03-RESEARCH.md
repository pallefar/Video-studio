# Phase 3: Wan Lane Bring-Up - Research

**Researched:** 2026-08-02
**Domain:** ComfyUI headless wan-lane executor bring-up (Wan 2.1/2.2 video generation on RTX 3090 / rented sm_86 CUDA), GGUF quantised model roster, GPU-lane exclusivity, camera-preset LoRA licensing.
**Confidence:** HIGH on template correctness (verified against node-pack source), MEDIUM on the A14B MoE VRAM footprint (documented architecture, not yet measured on this project's hardware), MEDIUM on WanVideoWrapper (uni3c/recammaster) wiring (class types verified in M11, full I/O signatures not re-verified this session).

## Summary

REQ-generative-broll-lane is 80% shipped in code (lanes, locks, gates, provider registry, ComfyUI client, node-pack manifest) and blocked only on M9.1 "first real Wan clip" plus M10.6 "Fun-Camera A14B benchmark decides 14B vs 5B". This research confirms the phase's stated central risk is real and worse than a single bug: **every wan2.2 workflow template that uses `UnetLoaderGGUF` (wan2.2-t2v, wan2.2-i2v, wan2.2-fun-camera, wan2.2-vace-fun, wan2.1-vace-1.3b, and — outside this phase's direct scope but sharing the same root cause — qwen-image) wires CLIP and VAE from output indices 1 and 2 of a node that has exactly one output, `MODEL`.** This was verified by reading `city96/ComfyUI-GGUF`'s `nodes.py` directly (not assumed): `UnetLoaderGGUF.RETURN_TYPES = ("MODEL",)`, `CLIPLoaderGGUF.RETURN_TYPES = ("CLIP",)` — two distinct node classes, confirmed by the studio's own `comfy_nodes.py` manifest which already lists them as two separate `provides` entries. ComfyUI will reject these graphs at `/prompt` submission (no output index 1/2 on that node) before any GPU work starts — this is a 100% CPU-provable, deterministic failure, not a flaky one. The one proven-working template, `wan2.1-t2v-1.3b.json`, avoids the bug entirely by using three separate loaders (native `UNETLoader` + `CLIPLoaderGGUF` + `VAELoader`) — that split is the fix pattern to copy into every broken template.

A second, independently verified defect compounds the first: **every wan2.2 GGUF template also omits `loop_count`, `pingpong`, and `save_output` on its `VHS_VideoCombine` node**, which are `required` (not optional-with-default) inputs per `Kosinkadink/ComfyUI-VideoHelperSuite`'s own `INPUT_TYPES()` — confirmed by reading that node's source. This matches the project's own hard-won prior knowledge (HTTP 400 `prompt_outputs_failed_validation` against a real server) and is the same three-line fix, already present in `wan2.1-t2v-1.3b.json`, needed in five other templates (plus `musetalk-image.json`, outside this phase's scope but worth a one-line fix while touching the same code).

A third defect is architectural, not a wiring typo: **Wan2.2 A14B (T2V/I2V/Fun-Camera/VACE-Fun) is a two-expert MoE** — a high-noise expert for early denoising steps and a low-noise expert for late steps — confirmed via ComfyUI's own official docs (`docs.comfy.org/tutorials/video/wan/wan2_2`) and the QuantStack GGUF model cards. Native ComfyUI wiring needs **two separate `UnetLoaderGGUF` nodes and two sequential `KSampler` passes** with a step-boundary handoff. Every current wan2.2-A14B template loads a single file (e.g. `wan2.2-t2v-a14b-Q5_K_M.gguf`) into one loader and samples once — this does not match how QuantStack actually ships the model (separate `*_high_noise*` / `*_low_noise*` GGUF files) and would need to be rebuilt as a two-loader/two-sampler graph, not just patched. This is the single biggest risk to plan around: it is real engineering work, not a config fix, and it is exactly the kind of "quality/speed disappoints" scenario roadmap-v2 §9 already anticipated when it named the 5B model the fallback.

That fallback path has its own gap worth surfacing now: **no `wan2.2-ti2v-5b` `ModelSpec` and no template exist yet anywhere in the codebase.** TI2V-5B is architecturally simple by comparison — a single dense model, one loader, matching the proven `wan2.1-t2v-1.3b.json` pattern exactly (`Comfy-Org/Wan_2.2_ComfyUI_Repackaged` ships both `split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors` and QuantStack ships GGUF quants down to 1.85 GB at Q2_K, ~3.4–3.8 GB at Q4/Q5_K_M). If the 3090 benchmark decides in favor of 5B, or if the planner wants a true side-by-side for M10.6's decision, this scaffolding needs to be built from scratch, not fixed.

Everything above is CPU-provable now: template JSON structure, node-pack manifest accuracy, and the wiring fix can all be verified by `pytest tests/test_comfy.py` plus reading node-pack source, with zero GPU access. What genuinely needs the 3090 (or a rented sm_86 box via `scripts/vast_comfyui.sh`) is: confirming the fixed graphs actually execute against a live ComfyUI, measuring real device-level VRAM for the A14B two-pass MoE load (the existing `scripts/bench.py::_nvidia_smi_used_gb` pattern is the template to reuse), and the M10.6 Fun-Camera + 4-step LoRA latency/VRAM benchmark that decides 14B vs 5B.

**Primary recommendation:** Fix the wan2.2 templates' loader wiring and VHS_VideoCombine fields as pure CPU work first (structural, test-provable, zero GPU risk), rebuild the A14B templates as genuine two-expert two-sampler graphs before any workstation session, scaffold a `wan2.2-ti2v-5b` ModelSpec+template so the 14B-vs-5B benchmark has something real to compare against, and reuse `scripts/bench.py`'s device-level `nvidia-smi` VRAM measurement pattern (not `torch.cuda.max_memory_allocated()`) for the M10.6 benchmark — same "measure, don't trust estimates" rule the project already applied in M0.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Workflow template correctness (node wiring, required fields) | ComfyUI sidecar (graph definition, owned by studio as package data) | — | Templates are studio-owned data (`packages/pipeline_core/workflows/*.json`) that describe a graph ComfyUI executes; the studio is the source of truth even though ComfyUI is the runtime |
| GGUF/model-weight loading, sampling, VAE decode | ComfyUI sidecar (GPU process) | — | ComfyUI owns all tensor/VRAM work; the studio never touches CUDA directly (CLAUDE.md: worker runs native, ComfyUI is a service dependency like MinIO) |
| Submit/poll/fetch orchestration, timeout bounding | API/Backend (`pipeline_core.comfy.ComfyUIClient`) | — | HTTP client talking to the sidecar; already implemented and CPU-tested |
| Exclusive GPU lock (render lane vs wan lane) | API/Backend (`pipeline_core.locks`, Redis) | — | Cross-process coordination primitive; already implemented and proven against real Redis |
| Wan-lane job dispatch, idempotency | API/Backend (`worker_gpu.stages.generation_stage_local`, `worker_gpu.run_wan`) | — | Already implemented; this phase only needs the executor underneath it to work |
| Node-pack presence / drift detection | API/Backend (`pipeline_core.comfy_nodes`, `GET /config/comfy`) | ComfyUI sidecar (actual `/object_info`) | Studio owns the manifest as data; ComfyUI is the ground truth it diffs against |
| Model weights, GGUF quant selection | Filesystem / model zoo on the GPU host | — | Never enters git (CLAUDE.md); lives in ComfyUI's `models/` tree, downloaded by script |
| Civitai LoRA licence audit | Human/process (structural gate in `pipeline_core.presets`) | — | `CameraPresetRead.loras[].license_audited` is a data flag a human sets after manual review — not automatable the way `package-legitimacy check` audits npm/PyPI packages |
| VRAM/latency benchmark measurement | GPU host (`scripts/bench.py` pattern) | — | Must be measured on real hardware; device-level `nvidia-smi`, not torch counters (established in Phase 1) |

## Standard Stack

### Core

| Component | Version/Pin | Purpose | Why Standard |
|---|---|---|---|
| ComfyUI | latest via `git clone --depth 1` (no pin recorded) | Headless wan-lane executor (M10 decision) | Already the project's chosen executor; workflow maturity for camera/VACE beat diffusers (roadmap-v2 §9.1) |
| ComfyUI-GGUF | `city96/ComfyUI-GGUF`, Apache-2.0 | GGUF quantised checkpoint + CLIP loading (`UnetLoaderGGUF`, `CLIPLoaderGGUF`) | sm_86-appropriate quantisation without FP8 (CLAUDE.md hard constraint) [VERIFIED: github.com/city96/ComfyUI-GGUF nodes.py — `UnetLoaderGGUF.RETURN_TYPES = ("MODEL",)`, `CLIPLoaderGGUF.RETURN_TYPES = ("CLIP",)`] |
| ComfyUI-VideoHelperSuite | `Kosinkadink/ComfyUI-VideoHelperSuite`, GPL-3.0 (sidecar-only) | `VHS_VideoCombine` output stage for every video template | [VERIFIED: github.com/Kosinkadink/ComfyUI-VideoHelperSuite nodes.py — `loop_count`, `pingpong`, `save_output` are `required` INPUT_TYPES] |
| `Comfy-Org/Wan_2.1_ComfyUI_repackaged` | HF repo, split_files layout | Source for `wan2.1_t2v_1.3B_fp16.safetensors` + `wan_2.1_vae.safetensors` | Already the proven-working source ([hard-won]: M30 real generation succeeded against these weights) |
| `Comfy-Org/Wan_2.2_ComfyUI_Repackaged` | HF repo, split_files layout | Native-format Wan2.2 VAE (`split_files/vae/wan2.2_vae.safetensors`, ~1.41 GB) and the dense `wan2.2_ti2v_5B_fp16.safetensors` | [CITED: huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged] — sibling repo to the already-proven 2.1 source, same publisher/naming convention |
| `city96/umt5-xxl-encoder-gguf` | HF repo | Text encoder shared by Wan 2.1 and 2.2 (`umt5-xxl-encoder-Q5_K_M.gguf`) | Already proven in `wan2.1-t2v-1.3b.json` and `scripts/vast_comfyui.sh`; native ComfyUI Wan2.2 docs use the same umt5-xxl family (fp8-scaled safetensors variant), GGUF quant is the sm_86/no-FP8-compliant equivalent |
| `QuantStack/Wan2.2-T2V-A14B-GGUF`, `Wan2.2-I2V-A14B-GGUF` | HF repo, Apache-2.0 | GGUF quants of the A14B expert pair | [CITED: huggingface.co/QuantStack/Wan2.2-T2V-A14B-GGUF] — ships **separate high-noise/low-noise files per quant level**, not a single combined file |
| `QuantStack/Wan2.2-TI2V-5B-GGUF` | HF repo, Apache-2.0 | GGUF quants of the dense 5B fallback | [CITED: huggingface.co/QuantStack/Wan2.2-TI2V-5B-GGUF] — Q4_K_M 3.43 GB, Q5_K_M 3.81 GB, Q8_0 5.4 GB; single file, no MoE split |
| `lightx2v/Wan2.2-Lightning` | HF repo, Apache-2.0 | 4-step distillation LoRA — the M10.6 benchmark's "4-step LoRA" | [CITED: huggingface.co/lightx2v/Wan2.2-Lightning] — HF-hosted, Apache-2.0, **not** a Civitai LoRA, so it does NOT require the per-LoRA Civitai licence audit that camera-motion LoRAs in `pipeline_core.presets` need |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits` | n/a (system tool) | Device-level VRAM measurement | Reuse verbatim for the M10.6 benchmark and any A14B two-pass VRAM measurement — [VERIFIED: scripts/bench.py:62-84 `_nvidia_smi_used_gb()`] "Device-level VRAM in use right now, sampled via `nvidia-smi --query-gpu=memory.used`. This is the figure the 20 GB budget is judged against: torch's own counters (allocated/reserved) cover only its caching allocator and exclude the CUDA context..." |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Two-loader/two-sampler A14B graph | Kijai's `ComfyUI-WanVideoWrapper` `WanVideoModelLoader` (single node, may internally handle expert switching) | Wrapper nodes are CUDA-first (project's own stated reason for preferring native nodes on Mac/MPS); on the 3090 (CUDA) the wrapper is viable, but native GGUF loaders keep VRAM lower and match the already-proven 2.1 pattern — recommend native unless the wrapper path is specifically needed for a feature GGUF doesn't support |
| 5B GGUF quant | 5B fp16 safetensors (`wan2.2_ti2v_5B_fp16.safetensors`, native `UNETLoader`, no GGUF node needed) | fp16 is ~4x larger on disk/VRAM than Q4_K_M GGUF but simpler to wire (no `CLIPLoaderGGUF` dependency) and matches the exact pattern of `wan2.1-t2v-1.3b.json`'s non-CLIP-GGUF unet loader; GGUF quant is the better default given the project's declared "no FP8, GGUF/INT8 preferred" rule pairs naturally with quantisation in general, but the unet weight itself doesn't have to be GGUF to satisfy "no FP8" — plain BF16/FP16 is also compliant. Either is CLAUDE.md-compliant; GGUF saves VRAM headroom. |

**Installation:** No new pip/npm packages for this phase — the ComfyUI node-pack roster is already fully declared in `pipeline_core/comfy_nodes.py` and cloned by `scripts/install_comfyui.sh`. Model weights are downloaded via `curl`/HF resolve URLs directly into ComfyUI's `models/` tree (never through a package manager, never into git — CLAUDE.md).

**Version verification:** ComfyUI itself and every node pack are pinned only by `git clone --depth 1` (floating HEAD) — no commit SHA pin recorded anywhere in `scripts/install_comfyui.sh` or `comfy_nodes.py`, unlike `MUSETALK_COMMIT` in Phase 1's `scripts/install_engines.sh`. This is a gap worth a `checkpoint:human-verify` or at minimum a documented "record the resolved SHA after install" step, since `ComfyUI-GGUF`'s `RETURN_TYPES` (verified above) is exactly the kind of thing that could silently change upstream between workstation sessions.

## Package Legitimacy Audit

No new pip/npm/crates packages are introduced by this phase. The phase's external dependencies are (a) ComfyUI + its custom-node packs, already governed by the existing `pipeline_core/comfy_nodes.py` manifest and the roadmap-v2 §6 licence register's "sidecar exception" (GPL-3.0 packs are fine because ComfyUI is reached over HTTP, never linked into the studio process), and (b) HuggingFace-hosted model weights, governed by the same licence register, not by `package-legitimacy check` (which targets code-execution supply-chain risk, not model weights).

| Package/Repo | Registry | Notes | Verdict | Disposition |
|---|---|---|---|---|
| `city96/ComfyUI-GGUF` | GitHub (cloned by install script) | Already in `NODE_PACKS` manifest, Apache-2.0 | OK | Approved — already shipped |
| `Kosinkadink/ComfyUI-VideoHelperSuite` | GitHub | Already in `NODE_PACKS` manifest, GPL-3.0 sidecar-exception | OK | Approved — already shipped |
| `QuantStack/Wan2.2-T2V-A14B-GGUF`, `Wan2.2-I2V-A14B-GGUF`, `Wan2.2-TI2V-5B-GGUF` | HuggingFace | Community GGUF conversion of an Apache-2.0 upstream model; conversion itself carries no separate restrictive licence per the model card ("all original licensing terms... remain in effect") | OK — but `[ASSUMED]` provenance (discovered via WebSearch/WebFetch, not `npm view`-equivalent registry check; no automated legitimacy tool exists for HF repos) | Approved for planning; recommend a `checkpoint:human-verify` before the first real download on the workstation, consistent with how Phase 1 gated MuseTalk's commit pin |
| `Comfy-Org/Wan_2.2_ComfyUI_Repackaged` | HuggingFace | Official Comfy-Org repackage, sibling to the already-used `Wan_2.1_ComfyUI_repackaged` | OK — `[ASSUMED]` provenance (WebSearch-discovered) | Approved for planning; same `checkpoint:human-verify` recommendation |
| `lightx2v/Wan2.2-Lightning` | HuggingFace | 4-step accelerator LoRA, Apache-2.0, needed for M10.6 benchmark | OK — `[ASSUMED]` provenance | Approved for planning; NOT subject to the Civitai per-LoRA audit gate (`pipeline_core.presets.license_audited`) since it is not a Civitai asset and carries an explicit Apache-2.0 licence |
| Any Civitai camera-motion LoRA (future, M11 scope, not this phase) | Civitai | Per-model licence varies (roadmap-v2 §6: "audit each LoRA's licence individually") | Cannot be blanket-approved | Each individual LoRA requires a human `checkpoint:human-verify` reading its Civitai "Permissions" panel before `license_audited=true`; this is out of Phase 3's REQ-generative-broll-lane scope but the gate mechanism (`presets.py`) already exists |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** none — all discovered repos are official/well-known publishers (Comfy-Org, city96, QuantStack, lightx2v), but see the `[ASSUMED]` provenance note above; the planner should still gate the first real download behind human confirmation since no automated npm/PyPI-style legitimacy check exists for HuggingFace model repos.

## Architecture Patterns

### System Architecture Diagram

```
                        ┌─────────────────────────────┐
                        │   API layer (FastAPI)        │
                        │   POST /generations           │
                        └──────────────┬────────────────┘
                                       │ enqueue (provider_class=local → lane from ModelSpec.lane)
                                       ▼
                        ┌─────────────────────────────┐
                        │  Redis queue: "wan" (exclusive) │
                        │  or "gpu" (shared render lane)   │
                        └──────────────┬────────────────┘
                                       │ RQ worker picks up job
                                       ▼
                    ┌──────────────────────────────────────┐
                    │ worker_gpu.stages.generation_stage_*   │
                    │  with gpu_lock(redis, HOLDER_WAN|RENDER)│ ◄── exclusive: render lane
                    └──────────────────┬───────────────────┘      and wan lane can never
                                       │                            both hold this lock
                                       ▼
                    ┌──────────────────────────────────────┐
                    │ pipeline_core.comfy.run_comfy_generation│
                    │  1. load_template(model)  — read JSON   │
                    │  2. build_values(generation, ...)        │
                    │     — uploads source image/video/audio   │
                    │       to ComfyUI via /upload/image        │
                    │  3. inject(template, values) — deep-copy │
                    │     graph, patch value paths, validate    │
                    │     required inputs                        │
                    │  4. client.submit(graph) → POST /prompt    │
                    │  5. client.wait(prompt_id) → poll          │
                    │     /history/{id} until outputs/error       │
                    │  6. client.collect_output → GET /view       │
                    └──────────────────┬───────────────────────┘
                                       │ HTTP, localhost:8188 or SSH tunnel
                                       ▼
                    ┌──────────────────────────────────────┐
                    │  ComfyUI headless sidecar (own venv)   │
                    │  ┌──────────────────────────────────┐ │
                    │  │ Graph execution (this phase's risk)│ │
                    │  │ UnetLoaderGGUF(x1 or x2 for MoE)   │ │
                    │  │  → CLIPLoaderGGUF (separate node!)  │ │
                    │  │  → VAELoader (separate node!)        │ │
                    │  │  → CLIPTextEncode (pos/neg)           │ │
                    │  │  → KSampler (x1, or x2 for A14B MoE)  │ │
                    │  │  → VAEDecode → VHS_VideoCombine        │ │
                    │  │    (needs loop_count/pingpong/         │ │
                    │  │     save_output or 400s)                │ │
                    │  └──────────────────────────────────┘ │
                    └──────────────────┬───────────────────┘
                                       │ Asset bytes
                                       ▼
                    ┌──────────────────────────────────────┐
                    │ ObjectStore (S3/MinIO) — Asset row      │
                    │ origin='generated', approved=false       │
                    │ (gate before selectability, already shipped)│
                    └──────────────────────────────────────┘
```

### Recommended Project Structure

No new directories needed — this phase edits existing files:

```
packages/pipeline_core/workflows/     # fix wan2.2-*.json + wan2.1-vace-1.3b.json;
                                       # ADD wan2.2-ti2v-5b.json (new, if 5B scaffolding is in scope)
packages/pipeline_core/providers.py   # ADD ModelSpec for wan2.2-ti2v-5b if scaffolding is in scope
packages/pipeline_core/comfy_nodes.py # update NODE_PACKS.needed_for if templates change node types
tests/test_comfy.py                   # extend COMFY_MODELS + structural assertions for any fix
scripts/bench.py                      # pattern to copy for a new wan-lane VRAM/latency benchmark script
docs/workstation.md                   # step 7/8 acceptance runbook already names the right order
```

### Pattern 1: Three-loader split for GGUF checkpoints (the proven-working pattern)
**What:** Native `UNETLoader` (or `UnetLoaderGGUF` for the diffusion weights) + a *separate* `CLIPLoaderGGUF` + a *separate* `VAELoader`, never assuming a GGUF unet loader outputs anything but `MODEL`.
**When to use:** Every template currently using `UnetLoaderGGUF` and wiring `clip`/`vae` from its output indices 1/2 (wan2.2-t2v, wan2.2-i2v, wan2.2-fun-camera, wan2.2-vace-fun, wan2.1-vace-1.3b; also qwen-image, outside this phase).
**Example (the working reference, verbatim from the repo):**
```json
// Source: packages/pipeline_core/workflows/wan2.1-t2v-1.3b.json (proven M30)
"37": { "class_type": "UNETLoader", "inputs": { "unet_name": "wan2.1_t2v_1.3B_fp16.safetensors", "weight_dtype": "default" } },
"38": { "class_type": "CLIPLoaderGGUF", "inputs": { "clip_name": "umt5-xxl-encoder-Q5_K_M.gguf", "type": "wan" } },
"39": { "class_type": "VAELoader", "inputs": { "vae_name": "wan_2.1_vae.safetensors" } },
"6":  { "class_type": "CLIPTextEncode", "inputs": { "text": "", "clip": ["38", 0] } },
"8":  { "class_type": "VAEDecode", "inputs": { "samples": ["3", 0], "vae": ["39", 0] } }
```
Compare to the broken pattern currently in `wan2.2-t2v.json` (verified against `city96/ComfyUI-GGUF` source — `UnetLoaderGGUF.RETURN_TYPES = ("MODEL",)`, no index 1 or 2 exists):
```json
// BROKEN — Source: packages/pipeline_core/workflows/wan2.2-t2v.json (as shipped)
"2": { "class_type": "UnetLoaderGGUF", "inputs": { "ckpt_name": "wan2.2-t2v-a14b-Q5_K_M.gguf" } },
"6": { "class_type": "CLIPTextEncode", "inputs": { "text": "", "clip": ["2", 1] } },   // no output index 1
"8": { "class_type": "VAEDecode", "inputs": { "samples": ["3", 0], "vae": ["2", 2] } } // no output index 2
```

### Pattern 2: VHS_VideoCombine's three silently-required fields
**What:** `loop_count`, `pingpong`, `save_output` must be present in the submitted graph even though they have client-side defaults, because ComfyUI's `/prompt` validation checks the node's `INPUT_TYPES()["required"]` dict against the submitted graph, not against the node class's Python defaults.
**When to use:** Every `VHS_VideoCombine` node in every template (currently correct only in `wan2.1-t2v-1.3b.json`; missing in wan2.2-t2v/i2v/fun-camera/vace-fun, wan2.1-vace-1.3b, uni3c, recammaster, and `musetalk-image.json` outside this phase).
**Example:**
```json
// Source: packages/pipeline_core/workflows/wan2.1-t2v-1.3b.json (proven M30)
"60": {
  "class_type": "VHS_VideoCombine",
  "inputs": {
    "images": ["8", 0], "frame_rate": 16, "format": "video/h264-mp4",
    "filename_prefix": "studio",
    "loop_count": 0, "pingpong": false, "save_output": true
  }
}
```

### Pattern 3: Wan2.2 A14B two-expert MoE (new pattern — does not exist yet in this repo)
**What:** Two `UnetLoaderGGUF` nodes (one loading the `*_high_noise*` GGUF, one loading `*_low_noise*`), two `KSampler` (or `KSamplerAdvanced`) nodes chained by latent, with steps split at a boundary (commonly documented as an early portion of total steps on the high-noise expert, the remainder on the low-noise expert — exact step-split ratio was not confirmed to source-level detail this session; treat as `[ASSUMED — needs workstation verification]`).
**When to use:** wan2.2-t2v, wan2.2-i2v, wan2.2-fun-camera, wan2.2-vace-fun — every template currently loading a single `*-a14b-*.gguf` file.
**Source:** `[CITED: docs.comfy.org/tutorials/video/wan/wan2_2]` — "The 14B variants use a dual-expert MoE architecture... Two separate UNETLoader nodes are required... These models divide expert models according to denoising timesteps... CLIP loader and VAE loader are separate, dedicated loader nodes — not wired from the UNETLoader nodes." This is architectural guidance to implement, not a code example that exists in-repo yet.

### Anti-Patterns to Avoid
- **Assuming a loader's output count from its position in a "standard" 3-output pattern (MODEL/CLIP/VAE):** `CheckpointLoaderSimple` genuinely has 3 outputs (used correctly in z-image-turbo/qwen-image's CLIP-VAE half/sdxl/ace-step — those are fine); `UnetLoaderGGUF` does not. Always check the specific node class's `RETURN_TYPES`, never assume by analogy.
- **Treating a single-file A14B GGUF checkpoint name as sufficient:** QuantStack ships high/low noise as separate files per quant level; a template referencing one filename for an A14B model is referencing something that likely doesn't exist as a single combined file at that quant level, or is silently using only one expert.
- **Judging VRAM by `torch.cuda.max_memory_allocated()`:** already identified and fixed in Phase 1 (`scripts/bench.py`) for the render lane — the same trap applies to the wan lane's A14B two-pass load; always sample `nvidia-smi --query-gpu=memory.used`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| GGUF quantised model loading | A custom GGUF parser/loader | `ComfyUI-GGUF`'s `UnetLoaderGGUF`/`CLIPLoaderGGUF` | Already the project's chosen dependency, Apache-2.0, actively maintained |
| Video assembly from frames | A custom ffmpeg-wrapping node | `VHS_VideoCombine` | Already the project's chosen dependency; the fix here is supplying its required fields, not replacing it |
| Node-pack presence detection | Manual "did the workstation install X" checklist | `pipeline_core.comfy_nodes.missing_node_types()` diffed against a live `/object_info` | Already implemented and tested; extend the manifest, don't build a parallel mechanism |
| Per-LoRA licence tracking | An ad hoc "trusted LoRA list" | `CameraPresetRead.loras[].license_audited` structural gate | Already implemented in `pipeline_core.presets`; this phase should not need new licence-tracking machinery, only ensure the 4-step accelerator LoRA path doesn't accidentally route through this Civitai-specific gate when it doesn't need to (it's HF-hosted Apache-2.0) |
| VRAM measurement | A new measurement helper | `scripts/bench.py::_nvidia_smi_used_gb` pattern (copy, don't reimplement) | Already solved the exact "torch counters lie" problem this phase will hit again with the A14B two-pass load |

**Key insight:** Nothing in this phase requires new third-party dependencies. The work is (a) fixing data (JSON template files) using a pattern the codebase already proves works, (b) possibly adding one new template + ModelSpec for the 5B fallback using that same proven pattern, and (c) a benchmark script that copies an existing measurement helper. The temptation to hand-roll would most likely appear as "write a custom GGUF metadata sniffer to detect which quant a filename resolves to" — resist it; `nvidia-smi` + reading the actual ComfyUI console/log output during the benchmark is sufficient and matches the project's existing "measure, don't trust estimates" ethic.

## Common Pitfalls

### Pitfall 1: Fixing the CLIP/VAE wiring bug but not the MoE architecture gap
**What goes wrong:** A quick fix that changes `["2", 1]`/`["2", 2]` to point at new `CLIPLoaderGGUF`/`VAELoader` nodes (Pattern 1) makes the graph *structurally valid* and passing `pytest tests/test_comfy.py`'s existing structural audit — but if the `ckpt_name` still points at a single-file A14B checkpoint, the graph will likely still fail at ComfyUI runtime (file not found, since QuantStack ships split high/low files) or silently produce a wrong/degraded result if some third-party repackage happens to offer a combined file.
**Why it happens:** The structural audit in `tests/test_comfy.py::test_every_model_has_a_structurally_valid_template` only checks that `inputs` paths resolve inside the graph — it cannot check that a referenced *filename* corresponds to a real file with the right shape, because that information lives outside the JSON (in ComfyUI's `models/` directory and in the upstream model's actual packaging).
**How to avoid:** Treat the A14B templates as needing Pattern 3 (two loaders, two samplers) from the start, not a smaller patch. Rebuild them, don't just relink two indices.
**Warning signs:** A template that structurally passes `test_every_model_has_a_structurally_valid_template` but references a `ckpt_name` string that doesn't match any file the model card actually publishes.

### Pitfall 2: Assuming the wan2.2-fun-camera i2v path works because `ModelSpec.kinds` declares `image_to_video`
**What goes wrong:** `LocalWanProvider.models()` declares `wan2.2-fun-camera`'s kinds as `frozenset({GenerationKind.text_to_video, GenerationKind.image_to_video})` (verified: `providers.py` line 92, `video = frozenset({GenerationKind.text_to_video, GenerationKind.image_to_video})`), but `wan2.2-fun-camera.json`'s `required` list is only `["prompt"]` and its `inputs` mapping has no `source_image` path at all — no `LoadImage` node exists in the graph. `build_values()` would still upload the source image (it doesn't check the template first), but `inject()` silently drops it because the docstring's own rule applies: "params without a mapping are ignored." An i2v camera-preset request would silently generate from noise/prompt alone, ignoring the uploaded image, with no error.
**Why it happens:** `inject()`'s permissive "ignore unmapped params" design (correct and necessary for the general case — many params are legitimately optional per-model) hides a template-completeness bug instead of surfacing it, because there is no assertion that a kind the ModelSpec claims to support actually has the graph wiring to honor it.
**How to avoid:** Either (a) add a `source_image` node + input mapping to `wan2.2-fun-camera.json` so it's a genuine i2v-capable graph, matching `wan2.2-i2v.json`'s pattern, or (b) narrow `ModelSpec.kinds` for `wan2.2-fun-camera` to `text_to_video` only until the i2v wiring exists, and add a regression test that every kind a `ModelSpec` claims has a corresponding required-or-optional input path in its template.
**Warning signs:** A `ModelSpec.kinds` value with no matching `template["inputs"]` key covering the parameters that kind implies (`source_image` for `image_to_video`, `source_video` for `video_to_video`).

### Pitfall 3: Trusting `git clone --depth 1` for node packs across workstation sessions
**What goes wrong:** `scripts/install_comfyui.sh` clones `city96/ComfyUI-GGUF` and friends at whatever HEAD is current at install time, with no commit pin recorded anywhere (unlike Phase 1's `MUSETALK_COMMIT` pin). If the upstream repo changes `UnetLoaderGGUF`'s `RETURN_TYPES` — or renames a node, or changes required-input semantics — between the CPU-side template fix (this research session) and the actual workstation bring-up session, the fix verified here could silently stop matching reality.
**Why it happens:** No pin, no drift detection beyond `tests/test_comfy.py::test_install_script_clones_every_manifest_pack` (which only checks the repo URL string is present, not a commit SHA).
**How to avoid:** Record the resolved commit SHA of each cloned node pack after the workstation install (the way Phase 1 recorded `MUSETALK_COMMIT=0a89dec4...`), and re-run `client.object_info()` diffed against the templates (already-built machinery: `pipeline_core.comfy_nodes.missing_node_types`) as the very first workstation step before trusting any CPU-side fix.
**Warning signs:** A workstation session where `GET /config/comfy`'s `missing` list is non-empty for a node type this research confirmed exists.

### Pitfall 4: Confusing "class type exists" with "wiring is correct" for uni3c/recammaster
**What goes wrong:** `comfy_nodes.py`'s `WanVideoWrapper` pack notes say node *names* were "schema-verified against the installed pack's `/object_info` on the workstation, like chatterbox (M29)" — that only proves the class types (`WanVideoModelLoader`, `WanVideoTextEncode`, etc.) exist on a running ComfyUI. It does not prove `uni3c.json`/`recammaster.json`'s specific *input wiring* (e.g., whether `WanVideoTextEncode` genuinely needs no `clip`/`t5` input, or whether `WanVideoModelLoader` handles A14B's high/low-noise split internally) is correct, the same way this session's `UnetLoaderGGUF` audit found a wiring bug despite the node class being real and correctly named.
**Why it happens:** Class-type existence and input-wiring correctness are two different failure modes, and only the first was checked for the wrapper-based templates.
**How to avoid:** Apply the same "read the node pack's actual `INPUT_TYPES`/`RETURN_TYPES`" audit this research applied to `ComfyUI-GGUF` and `VideoHelperSuite` to `ComfyUI-WanVideoWrapper` before relying on `uni3c.json`/`recammaster.json` — out of scope for REQ-generative-broll-lane's 5s-clip acceptance criterion (M11 territory), but flag it so the plan doesn't assume M11's templates are more trustworthy than M9/M10's turned out to be.
**Warning signs:** Any workstation submission of `uni3c`/`recammaster` graphs that fails with a ComfyUI validation error naming a missing/mistyped required input.

## Code Examples

### Structural audit test pattern (already exists — extend, don't replace)
```python
# Source: tests/test_comfy.py (existing, verified by Read)
def test_every_model_has_a_structurally_valid_template():
    for model in COMFY_MODELS:
        template = load_template(model)
        graph = template["graph"]
        assert template["output"]["node"] in graph, model
        assert template["output"]["kind"] in ("video", "image", "audio"), model
        for param, path in template["inputs"].items():
            node = graph
            for step in path[:-1]:
                assert step in node, f"{model}: {param} path breaks at {step}"
                node = node[step]
            assert path[-1] in node, f"{model}: {param} final field missing"
```
This audit will pass on the *current, broken* wan2.2 templates because it only checks path resolution inside the graph JSON, not against real node signatures — it cannot catch the `UnetLoaderGGUF` output-index bug on its own. A new test asserting `VHS_VideoCombine` nodes carry `loop_count`/`pingpong`/`save_output`, and that `clip`/`vae` edges never originate from a `UnetLoaderGGUF` node, would close this gap and should be added alongside the template fixes.

### VRAM measurement to copy for the M10.6 benchmark
```python
# Source: scripts/bench.py:62-84 (verified by Read)
def _nvidia_smi_used_gb() -> float | None:
    """Device-level VRAM in use right now, sampled via `nvidia-smi
    --query-gpu=memory.used`. This is the figure the 20 GB budget is judged
    against: torch's own counters (allocated/reserved) cover only its
    caching allocator and exclude the CUDA context and MuseTalk's mmlab CUDA
    ops, both of which occupy real space on the card. Returns None — never
    raises — when nvidia-smi is unavailable, so callers fall back."""
    import subprocess
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return None
```
The wan lane has no 20 GB *budget* per se (it's the exclusive lane, so it can use the whole card), but the same "sample device-level VRAM, don't trust torch counters" discipline directly answers research_focus #3's "how to measure VRAM honestly."

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Diffusers-based direct Wan inference | Headless ComfyUI as the executor | M10 decision (2026-07-29) | Already landed; this phase builds on it, does not revisit it |
| Single-loader assumption for all Wan checkpoints | Wan2.2 A14B requires two-expert MoE wiring | Confirmed this session via `docs.comfy.org` — the templates in this repo predate this being wired correctly | Every wan2.2-A14B template needs a structural rebuild, not a patch |
| `torch.cuda.max_memory_allocated()` for VRAM budgets | `nvidia-smi --query-gpu=memory.used` device-level sampling | Phase 1 (M0 bench.py rewrite) | Directly reusable for this phase's benchmark |

**Deprecated/outdated:** Nothing in the wan-lane domain itself is deprecated; the "old approach" rows above are project-internal assumptions this research found were never actually correct, not things that used to work and later changed upstream.

## Runtime State Inventory

Not applicable — this is not a rename/refactor/migration phase. Skipped per the trigger condition.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Exact step-boundary ratio for the A14B high-noise→low-noise handoff (e.g. "first N of 20 steps on high-noise") was not confirmed to precise numeric detail from an authoritative source this session | Architecture Patterns, Pattern 3 | Wrong split ratio degrades output quality but does not crash the graph; needs workstation-side tuning regardless (docs/workstation.md §3 already frames template tuning as "content work, not code work") |
| A2 | `QuantStack/Wan2.2-T2V-A14B-GGUF` and `Wan2.2-I2V-A14B-GGUF` genuinely ship separate `*_high_noise*`/`*_low_noise*` files per quant level (not confirmed by listing the actual file tree, only inferred from the general Wan2.2-A14B MoE documentation plus the native ComfyUI docs' filename convention) | Standard Stack, Summary | If the file layout differs from the native-safetensors convention, the download URLs in a bring-up script would need adjusting — low risk, easily caught on first `curl` 404 |
| A3 | `Comfy-Org/Wan_2.2_ComfyUI_Repackaged`'s `wan2.2_vae.safetensors` is the correct/only VAE needed for the native GGUF wan2.2 templates (as opposed to a different VAE per T2V vs I2V vs Fun-Camera variant) | Standard Stack | Wrong VAE produces visibly broken decode output (very detectable, not silent) |
| A4 | The 4-step LoRA benchmark (`lightx2v/Wan2.2-Lightning`) is compatible with the GGUF-quantised A14B checkpoints specifically (as opposed to only the fp8/fp16 safetensors releases) — not independently confirmed | Standard Stack, Package Legitimacy Audit | If incompatible, M10.6's benchmark would need the non-GGUF checkpoint variant instead, changing the VRAM math measured |
| A5 | Package-legitimacy provenance for all HF repos in this document is `[ASSUMED]` per the provenance rule — no automated registry-equivalent check exists for HuggingFace the way `npm view`/`gsd-tools query package-legitimacy check` exists for npm | Package Legitimacy Audit | Standard model-weight supply-chain risk; mitigated by all sources being well-known official publishers (Comfy-Org, city96, QuantStack, lightx2v), not obscure/anonymous uploads |

## Open Questions

1. **Should the 5B ModelSpec/template scaffolding be built in this phase, or is it purely a benchmark-decision follow-up?**
   - What we know: No `wan2.2-ti2v-5b` entry exists anywhere in `providers.py` or `packages/pipeline_core/workflows/`. Roadmap-v2 §9 names 5B as the fallback "if quality/speed disappoints" on the A14B benchmark.
   - What's unclear: Whether REQ-generative-broll-lane's acceptance criteria (a real 5s clip generates; the M10.6 benchmark decides 14B vs 5B) can be satisfied by benchmarking A14B alone and treating 5B as a *future* fallback only exercised if A14B disappoints, or whether the "decides 14B vs 5B default" framing implies both need to exist and be compared side-by-side in this phase.
   - Recommendation: Build the 5B template using the proven `wan2.1-t2v-1.3b.json` pattern (cheap — it's a dense model, no MoE complexity) as a low-cost insurance policy regardless; it directly reuses Pattern 1 and needs no new architecture, unlike the A14B fix.

2. **Exact A14B step-boundary handoff value.**
   - What we know: Two experts, switched by denoising timestep, native ComfyUI needs two `KSampler` passes.
   - What's unclear: The precise step-count split (e.g. is it configurable via a "boundary" parameter on a dedicated node, or is it two independently-configured `KSampler` `steps`/`start_at_step`/`end_at_step` values a human tunes by eye).
   - Recommendation: This is genuinely workstation/tuning work per `docs/workstation.md §3`'s own stated rule ("Build the workflow in the ComfyUI UI until output quality is right... template tuning is content work, not code work") — the plan should build the graph *shape* (two loaders, two samplers, correct edges) as code/structural work, and treat the exact split ratio as a tunable default with a sane starting guess, not a blocking research gap.

3. **Whether `wan2.2-fun-camera.json`'s missing i2v wiring (Pitfall 2) should be fixed in this phase or is out of scope.**
   - What we know: `ModelSpec` currently over-declares support (`image_to_video` in `kinds` with no corresponding graph wiring).
   - What's unclear: Whether the Fun-Camera preset feature is meant to support image-to-video generation at all in v1 scope, or whether t2v-only was always the intent and the `kinds` declaration is simply too broad.
   - Recommendation: Narrow `kinds` to `text_to_video` only as the minimal, safe fix within this phase (one line), and file the full i2v wiring as a follow-up if the product actually needs Fun-Camera-from-an-image.

## Environment Availability

| Dependency | Required By | Available (this Mac, dev session) | Version | Fallback |
|------------|------------|-----------|---------|----------|
| CUDA GPU (sm_86, RTX 3090 or rented equivalent) | Real generation, VRAM benchmark, all runtime verification | ✗ (macOS dev machine, per env block) | — | `scripts/rent_gpu.sh` + `scripts/vast_comfyui.sh` (documented, provider-agnostic SSH-tunnel path) |
| ComfyUI headless server | Submit/poll/fetch round-trip verification | ✗ locally (not installed on this dev machine per this session) | — | All template/wiring fixes in this phase are verifiable via `pytest tests/test_comfy.py` + reading node-pack source without a live server; only true execution needs one |
| `nvidia-smi` | M10.6 VRAM benchmark | ✗ (no NVIDIA GPU on this machine) | — | None needed for CPU-side work; required only on the GPU host, where it's standard |
| pytest | Structural template audit, node-pack manifest audit | ✓ (existing project test suite, `pyproject.toml` `[tool.pytest.ini_options]`) | project-pinned | — |

**Missing dependencies with no fallback:** None that block this phase's CPU-provable work. Real execution/measurement genuinely needs the 3090 or a rented sm_86 box — no fallback exists for that by design (the whole point of this phase).

**Missing dependencies with fallback:** GPU access has a documented, already-built fallback (`scripts/rent_gpu.sh`/`scripts/vast_comfyui.sh`) that this project's own `docs/mac-dev.md` and hard-won prior knowledge treat as first-class, not a workaround.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest, `[tool.pytest.ini_options]` in `pyproject.toml`: `testpaths = ["tests"]`, `pythonpath = [".", "packages"]`, `addopts = "-q"` [VERIFIED: pyproject.toml:95-98] |
| Config file | `pyproject.toml` |
| Quick run command | `pytest tests/test_comfy.py -x` |
| Full suite command | `pytest tests/test_comfy.py tests/test_gpu_exclusivity.py tests/test_queue_topology.py tests/test_providers.py -x` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REQ-generative-broll-lane (template correctness) | Every shipped template's `inputs`/`output` paths resolve inside its graph | unit/structural | `pytest tests/test_comfy.py::test_every_model_has_a_structurally_valid_template -x` | ✅ exists, but insufficient alone (see Pitfall 1) — extend with a node-signature-aware assertion, Wave 0 gap below |
| REQ-generative-broll-lane (node-pack manifest accuracy) | Manifest `provides`/`needed_for` stay in sync with actual template node usage | unit | `pytest tests/test_comfy.py::test_node_pack_manifest_is_audited tests/test_comfy.py::test_every_custom_node_type_maps_to_a_pack -x` | ✅ exists |
| REQ-generative-broll-lane (GPU exclusivity, already shipped) | Render lane and wan lane never hold the GPU lock simultaneously | integration (real Redis) | `pytest tests/test_gpu_exclusivity.py -x` | ✅ exists, green |
| REQ-generative-broll-lane (real 5s clip generates) | End-to-end submit→poll→fetch against a *real* ComfyUI produces a playable clip | manual/workstation-only | N/A — requires live GPU host, cannot be automated in CI | ❌ — inherently workstation-only, no Wave 0 gap to fill in CPU-side test suite; document as the acceptance-day runbook step (`docs/workstation.md` step 7, already written) |
| REQ-generative-broll-lane (M10.6 benchmark decides 14B vs 5B) | Measured latency + device-level VRAM for Fun-Camera A14B + 4-step LoRA | manual/workstation-only, scripted | New script following `scripts/bench.py`'s pattern, run on the GPU host | ❌ Wave 0 gap — no benchmark script exists yet for the wan lane (bench.py currently covers only the render lane's Chatterbox+MuseTalk) |

### Sampling Rate
- **Per task commit:** `pytest tests/test_comfy.py -x`
- **Per wave merge:** `pytest tests/test_comfy.py tests/test_gpu_exclusivity.py tests/test_queue_topology.py tests/test_providers.py -x`
- **Phase gate:** Full suite green before `/gsd-verify-work`; real-hardware verification (5s clip, M10.6 benchmark) happens on the GPU host per `docs/workstation.md`'s acceptance runbook, outside CI

### Wave 0 Gaps
- [ ] A new structural test asserting no `clip`/`vae` edge originates from a `UnetLoaderGGUF` node's output index >0 (closes the gap `test_every_model_has_a_structurally_valid_template` cannot catch — see Pitfall 1)
- [ ] A new structural test asserting every `VHS_VideoCombine` node's `inputs` dict includes `loop_count`, `pingpong`, `save_output`
- [ ] A new structural test asserting every `ModelSpec.kinds` value has corresponding template wiring (closes the `wan2.2-fun-camera` i2v gap from Pitfall 2)
- [ ] A wan-lane VRAM/latency benchmark script (`scripts/bench.py`'s pattern, new file, GPU-host-only) for the M10.6 decision — no framework gap, just doesn't exist yet

*(Framework itself — pytest, config, fixtures — is fully in place; all gaps above are new test *cases*, not new infrastructure.)*

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | ComfyUI has no auth by design; access is restricted structurally by binding to `127.0.0.1` and requiring an SSH tunnel for remote hosts — already documented and correctly implemented in `scripts/vast_comfyui.sh` ("NEVER map port 8188 publicly — ComfyUI has no auth; the tunnel is the auth") |
| V3 Session Management | No | Stateless HTTP submit/poll/fetch; no sessions |
| V4 Access Control | Partial | C6 identity-consent re-check already happens at `worker_gpu.stages.identity_training_stage` (Phase 5 territory, not this phase); this phase's generations are not identity/face-bearing by default |
| V5 Input Validation | Yes | `inject()`'s required-field check (`ComfyUIError` on missing required input) already provides basic validation; the template-correctness fixes in this phase are themselves a V5-adjacent concern (a malformed graph is a form of invalid input reaching the sidecar) — no new validator needed, just correct data |
| V6 Cryptography | No | Not applicable to this phase |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| ComfyUI's unauthenticated `/prompt` endpoint reachable from outside localhost | Elevation of Privilege / Tampering | Already mitigated structurally: bind to `127.0.0.1`, reach remote hosts only via SSH tunnel (`scripts/vast_comfyui.sh`, `scripts/rent_gpu.sh`) — no code change needed in this phase, but the plan should not introduce any convenience shortcut (e.g. binding `--listen 0.0.0.0`) while fixing templates |
| A GPU-lock holder that crashes without releasing, bricking the wan lane | Denial of Service | Already mitigated: Redis `SET NX EX` TTL + compare-and-delete release (`pipeline_core.locks`), proven by `tests/test_gpu_exclusivity.py::test_lock_has_a_ttl` and `test_stale_holder_cannot_release_the_next_lock` |
| Uploaded source assets (image/video/audio for i2v/v2v) reaching ComfyUI's `/upload/image` without a source that can be trusted | Tampering | Out of scope for this phase — assets originate from the studio's own `ObjectStore`, already access-controlled upstream; ComfyUI receives only studio-selected bytes, not arbitrary user-supplied URLs |

## Sources

### Primary (HIGH confidence)
- `city96/ComfyUI-GGUF` `nodes.py` (fetched directly) — `UnetLoaderGGUF.RETURN_TYPES = ("MODEL",)`, `CLIPLoaderGGUF.RETURN_TYPES = ("CLIP",)`
- `Kosinkadink/ComfyUI-VideoHelperSuite` `videohelpersuite/nodes.py` (fetched directly) — `VideoCombine.INPUT_TYPES()` required fields including `loop_count`, `pingpong`, `save_output`
- In-repo reads: `packages/pipeline_core/comfy.py`, `comfy_nodes.py`, `providers.py`, `locks.py`, all 13 `workflows/*.json` templates, `worker_gpu/stages.py`, `worker_gpu/run_wan.py`, `tests/test_comfy.py`, `tests/test_gpu_exclusivity.py`, `tests/test_queue_topology.py`, `scripts/install_comfyui.sh`, `scripts/vast_comfyui.sh`, `scripts/rent_gpu.sh`, `scripts/bench.py` (lines 55-84), `packages/pipeline_core/presets.py`, `packages/pipeline_core/queues.py`, `packages/pipeline_core/settings.py`, `packages/schema/models.py` (GenerationKind), `pyproject.toml`, `docs/milestones.md` (M9/M10/M30), `docs/workstation.md`, `docs/roadmap-v2.md` (§5, §6, §9), `CLAUDE.md`, `.planning/REQUIREMENTS.md`, `.planning/STATE.md`

### Secondary (MEDIUM confidence)
- `docs.comfy.org/tutorials/video/wan/wan2_2` — Wan2.2 A14B two-loader/two-KSampler MoE wiring, TI2V-5B single-loader confirmation, separate CLIP/VAE loader confirmation (WebFetch summary of official ComfyUI docs, not independently cross-checked against a second source)
- `huggingface.co/QuantStack/Wan2.2-T2V-A14B-GGUF`, `Wan2.2-TI2V-5B-GGUF` — quant file sizes and licence
- `huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged` — native VAE and 5B fp16 source (WebSearch-discovered, not fetched in full)
- `huggingface.co/lightx2v/Wan2.2-Lightning` — 4-step LoRA licence (WebSearch-discovered)

### Tertiary (LOW confidence)
- `blog.comfy.org/p/wan22-day-0-support-in-comfyui` — general MoE description corroborating the docs.comfy.org finding, but the fetch itself returned limited actionable detail
- Various WebSearch aggregator results (wan27.org, ojambo.com, civitai.com model pages) used only to triangulate quant sizes and confirm the Lightning LoRA's existence — not treated as authoritative on their own, all claims cross-checked against at least one HF/comfy.org source before inclusion above

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every node-pack claim was verified against actual source code, not assumed
- Architecture (template fixes): HIGH — the CLIP/VAE and VHS_VideoCombine bugs are verified against node-pack source, not inferred
- Architecture (A14B MoE rebuild): MEDIUM — the need for two loaders/two samplers is well-documented, but the exact step-split parameterization was not confirmed to implementation-ready precision
- Pitfalls: HIGH — all four pitfalls trace to a specific, cited/verified finding in this session, not speculation

**Research date:** 2026-08-02
**Valid until:** 14 days for the ComfyUI/node-pack specifics (fast-moving, unpinned upstream — see Package Legitimacy Audit's pinning gap); 30 days for the Wan model-weight licensing and architecture facts (Apache-2.0 family, stable)
