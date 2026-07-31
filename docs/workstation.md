# Workstation setup — the RTX 3090 host

The GPU host runs three native processes (never containerised) plus one
sidecar service. Everything else (API, CPU worker, panel, Postgres/Redis/
MinIO) can live anywhere that reaches the same env-configured services.

```
worker_gpu/run.py        # render lane: Chatterbox + MuseTalk (queue: gpu)
worker_gpu/run_wan.py    # wan lane: generation + LoRA training (queue: wan)
ComfyUI (headless)       # the wan-lane executor — sidecar service on :8188
```

Hard constraints (docs/pipeline-spec.md): `sm_86` only — **no FP8**, BF16
inference, GGUF/INT8 quantised checkpoints. `python scripts/verify_gpu.py`
first, always.

## 1. ComfyUI headless (the M10 executor)

ComfyUI is a service dependency exactly like MinIO: our worker submits an
API-format node graph (`POST /prompt`), polls `/history/{prompt_id}`, and
downloads outputs via `/view`. Install it in its **own venv**, run it
headless, point the studio at it:

```bash
git clone https://github.com/comfyanonymous/ComfyUI ~/comfyui && cd ~/comfyui
python -m venv .venv && .venv/bin/pip install -r requirements.txt
# custom nodes (pinned by commit when you install them):
#   ComfyUI-GGUF            — GGUF UNet loaders (UnetLoaderGGUF)
#   ComfyUI-VideoHelperSuite — VHS_LoadVideo / VHS_VideoCombine
#   ComfyUI-WanVideoWrapper  — Wan 2.x + Fun-Camera embeddings
#   (VACE + ACE-Step nodes ship with current ComfyUI core)
.venv/bin/python main.py --listen 127.0.0.1 --port 8188   # headless: no browser needed
```

Studio side (`.env`):

```
COMFY_URL=http://127.0.0.1:8188
COMFY_TIMEOUT_S=3600      # bounds how long a wan job may hold the GPU lock
```

Unset `COMFY_URL` → local generations fail with a config hint (and any
declared API fallback still completes). `DEV_ENGINES=1` → placeholder
output instead (Mac/CI mode, docs/mac-dev.md).

## 2. Model weights

Licences per the register in docs/roadmap-v2.md §6 — nothing outside it.

| Model (registry id) | File → ComfyUI dir | Licence |
|---|---|---|
| wan2.2-t2v / i2v | `wan2.2-{t2v,i2v}-a14b-Q5_K_M.gguf` → `models/unet/` | Apache-2.0 |
| wan2.2-fun-camera | `wan2.2-fun-camera-a14b-Q5_K_M.gguf` → `models/unet/` | Apache-2.0 |
| wan2.2-vace-fun | `wan2.2-vace-fun-a14b-Q5_K_M.gguf` → `models/unet/` | Apache-2.0 |
| wan2.1-vace-1.3b | `wan2.1-vace-1.3b-bf16.safetensors` → `models/unet/` | Apache-2.0 |
| z-image-turbo | `z-image-turbo.safetensors` → `models/checkpoints/` | Apache-2.0 |
| qwen-image | `qwen-image-20b-Q4_K_M.gguf` → `models/unet/` | Apache-2.0 |
| sdxl | `sd_xl_base_1.0.safetensors` → `models/checkpoints/` | OpenRAIL++-M |
| ace-step | `ace_step_v1_3.5b.safetensors` → `models/checkpoints/` | Apache-2.0 |

Plus the matching text encoders/VAEs each workflow references. Pin exact
versions; weights never enter git.

**Identity LoRAs**: the M17 trainer writes weights to
`s3://…/identities/{id}/lora.safetensors`; sync them into ComfyUI's
`models/loras/` (the workflow references the file by basename). Automating
that sync is an open item.

## 3. Workflow templates

`packages/pipeline_core/workflows/*.json` — one per model, in the sidecar
path-map format (see pipeline_core/comfy.py docstring). The shipped graphs
are **structurally valid skeletons**; tune them on the workstation:

1. Build the workflow in the ComfyUI UI until output quality is right.
2. Export with **Save (API Format)** — not the default UI format.
3. Replace the template's `graph`, update the `inputs` paths and
   `output.node` for your node ids.
4. `pytest tests/test_comfy.py` — the structural audit validates every
   input path resolves and the output node exists.

Template tuning is content work, not code work — same rule as presets.

## 4. Bring-up order

```bash
python scripts/verify_gpu.py                  # sm_86 or refuse
python scripts/bench.py --smoke               # M0: Chatterbox+MuseTalk resident, <20 GB
# wan lane, smallest first:
#   z-image-turbo still → wan2.2-t2v 5 s → fun-camera preset → VACE preview
python worker_gpu/run.py &                    # render lane
python worker_gpu/run_wan.py &                # wan lane
```

Then the M10 benchmark checkbox: Fun-Camera A14B GGUF + 4-step LoRA latency
and VRAM — decides the 14B vs 5B default (docs/milestones.md).
