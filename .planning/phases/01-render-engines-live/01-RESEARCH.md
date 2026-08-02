# Phase 1: Render Engines Live - Research

**Researched:** 2026-08-02
**Domain:** Direct in-process GPU model integration (TTS + lip-sync) on a single RTX 3090, replacing `NotImplementedError` stubs
**Confidence:** MEDIUM — the pipeline shape, interface contract, and licenses are HIGH confidence (read directly from source); exact dependency-version compatibility between Chatterbox and MuseTalk's mmlab stack, and both engines' real VRAM footprint, are LOW confidence and must be measured on the physical 3090 host (this research session runs on a CUDA-less Mac, per the project's own documented constraint).

<user_constraints>
## User Constraints (from CONTEXT.md)

No CONTEXT.md exists for this phase (`/gsd-discuss-phase` has not been run). No locked
decisions, discretion areas, or deferred ideas to carry forward. Constraints below come
from `CLAUDE.md` and `docs/*.md` instead, and are treated with the same authority.
</user_constraints>

## Project Constraints (from CLAUDE.md)

These are structural, non-negotiable for this phase (verbatim intent from `CLAUDE.md`,
`docs/pipeline-spec.md`, `docs/workstation.md`):

- **sm_86 / BF16 only — NO FP8.** Reject any Ada/Hopper-targeted build or FP8 code path. `scripts/verify_gpu.py` already asserts `torch.cuda.get_device_capability() == (8, 6)` [VERIFIED: /Users/karstenhaldan/Video-studio/scripts/verify_gpu.py:12,40-45 — `REQUIRED_CAPABILITY = (8, 6)` … `if capability != REQUIRED_CAPABILITY: return fail(...)`].
- **Models load once at worker boot and stay resident** — never per-job. `worker_gpu/stages.py` already caches engines at module level (`_engines` singleton) [VERIFIED: /Users/karstenhaldan/Video-studio/worker_gpu/stages.py:30,33-53].
- **GPU worker concurrency is 1.** Asserted in `tests/test_queue_topology.py::test_gpu_concurrency_is_one` [VERIFIED: /Users/karstenhaldan/Video-studio/tests/test_queue_topology.py:17-18 — `def test_gpu_concurrency_is_one(): assert GPU_WORKER_CONCURRENCY == 1`].
- **MIT/Apache-2.0 weights only.** Chatterbox (MIT) and MuseTalk (MIT, both code and weights) are the two models this phase installs — both confirmed against official sources below.
- **Worker portability**: all artefact I/O through `ObjectStore` (S3-compatible), all service addresses from `Settings` (env). No `localhost` literal, no local filesystem paths for persisted artefacts. Enforced by `tests/test_portability.py`.
- **No FP8 quantised checkpoints anywhere in this phase** — Chatterbox and MuseTalk both run BF16 dense weights, not GGUF/INT8 (that quantization path is Wan 2.2's, a different phase).

## Summary

Phase 1 replaces two `NotImplementedError` stubs — `worker_gpu/engines/tts.py`
(`ChatterboxEngine`) and `worker_gpu/engines/lipsync.py` (`MuseTalkEngine`) — with real
model loads that satisfy an interface contract already fully specified by
`worker_gpu/stages.py` and mirrored exactly by the dev placeholder engines in
`worker_gpu/engines/dev.py`. The stage functions, chunking math
(`packages/pipeline_core/chunking.py`), GPU locking, idempotency, and DB wiring are
already built and tested end-to-end against fake engines — this phase's job is narrowly
model integration, not pipeline architecture.

Chatterbox TTS is a normal `pip install chatterbox-tts` package (PyPI, MIT, official
`resemble-ai` org) with a clean `ChatterboxTTS.from_pretrained(device="cuda")` /
`model.generate(text, audio_prompt_path=..., exaggeration=..., cfg_weight=...)` API whose
two delivery parameters map exactly onto the values already hard-coded in
`packages/pipeline_core/emotions.py`'s `EMOTIONS` dict — no new mapping code is needed,
only wiring. It watermarks every output automatically via Resemble's Perth library (no
code required for C3), but its native output is 24 kHz mono — the engine must resample
to the project's 48 kHz stereo WAV convention before uploading, matching
`DevTTSEngine`'s existing behavior.

MuseTalk is architecturally different: it is **not a PyPI package**. It is a GitHub
clone (`TMElyralab/MuseTalk`, MIT code, MIT-equivalent weights) vendored into the
worker's Python path, and its own documented install pins (`torch==2.0.1`,
`mmcv==2.0.1`) actively **conflict** with Chatterbox's `torch>=2.6.0` requirement — both
must load in the *same* Python process (`worker_gpu` is single-process, concurrency 1).
This is the single highest-risk unknown in this phase and is not resolvable from a
research session off the GPU host; the mitigation researched below (let `openmim`
auto-resolve `mmcv`/`mmdet`/`mmpose` against whatever `torch` is actually installed,
rather than hard-pinning to MuseTalk's stale README versions) is the same pattern the
project already uses successfully for the unrelated ComfyUI-MuseTalk node pack
(`docs/workstation.md` §1), so it is a reasonable starting point — but it must be
verified live on the 3090 before the plan can call M0.2/M0.3 done.

MuseTalk also has no persisted latent cache yet (`worker_gpu/preprocess/loop_cache.py`
is Phase 2's stub, `BaseLoop.latents_uri`/`bbox_uri` are always `None` today) — Phase 1's
`MuseTalkEngine` must run MuseTalk's "preparation" step (face detection, bbox crop, VAE
encode) ad hoc per loop, in-memory only, not persisted to S3. That is in scope for this
phase; persisting/caching it is explicitly Phase 2's job.

**Primary recommendation:** Implement `ChatterboxEngine.load()`/`synthesize_segment()`
against the official `chatterbox-tts` PyPI package with an explicit resample-to-48kHz-
stereo step; implement `MuseTalkEngine.load()`/`sync_chunk()` against a vendored,
commit-pinned clone of `TMElyralab/MuseTalk` with an **unpinned** `mim install mmengine
mmcv mmdet mmpose` (let openmim resolve against the installed torch/CUDA rather than the
README's stale pins); add an explicit boot-time `get_engines()` call in
`worker_gpu/run.py:main()` before `worker.work()` so models are actually warm at boot
(currently lazy on first job — a real gap against M3's "warm at boot" requirement); and
treat the dependency-conflict resolution and both VRAM numbers as `checkpoint:human-verify`
gates on the physical 3090, not assumptions to bake into the plan.

## Architectural Responsibility Map

This project has no browser/CDN tiers — it is a batch backend pipeline. Tiers below are
adapted to its actual architecture (`api/`, `worker_gpu/`, `worker_cpu/`, `packages/`, DB/S3).

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| GPU capability assertion (sm_86) | GPU Worker (native process) | — | `scripts/verify_gpu.py` is a standalone preflight script run on the host before any worker starts |
| Chatterbox TTS load + inference | GPU Worker (native process) | — | Model must be resident in the same long-lived process as MuseTalk (`worker_gpu/engines/tts.py`); never per-job, never a sidecar |
| MuseTalk load + inference | GPU Worker (native process) | — | Same process as Chatterbox; direct Python import, not the ComfyUI sidecar path (that's a *different* MuseTalk integration for M28's `musetalk-image` talking-photo feature) |
| Emotion/delivery parameter mapping | packages/pipeline_core (shared) | GPU Worker | `emotions.py` already owns the preset→params mapping; the engine only consumes `emotion_params()` output, it does not own the mapping |
| Audio format normalization (48kHz stereo) | GPU Worker (engine) | worker_cpu (assemble) | Engine should emit the project convention directly (matches `DevTTSEngine`); `assemble.py`'s `aresample=48000,aformat=channel_layouts=stereo` is a safety net, not the primary contract |
| Chunk window derivation | packages/pipeline_core (shared) | — | Already implemented and tested in `chunking.py`; MuseTalk engine only consumes `(start_ms, end_ms)` windows, never computes them |
| VRAM budget verification | GPU Worker (native process) | Ops script (`scripts/bench.py`) | Must be measured in the same process both models are resident in; `bench.py --smoke` is the existing harness |
| Loop bbox/latent preparation (ad hoc, Phase 1) | GPU Worker (engine, in-memory) | Phase 2 (persisted cache) | `BaseLoop.latents_uri`/`bbox_uri` are unpopulated; Phase 1 must not depend on Phase 2's cache existing |
| Artifact storage (audio/video chunks) | Storage (S3/MinIO via `ObjectStore`) | — | Existing single interface; engines call `store.put_file()`, never local paths |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|---------------|
| `chatterbox-tts` | 0.1.7 (PyPI, confirmed 2026-08-02) [CITED: pypi.org/project/chatterbox-tts] | Chatterbox TTS + voice cloning | Official `resemble-ai` package; matches CLAUDE.md's MIT requirement and the licence register |
| MuseTalk (git clone, not pip) | pin to a specific commit SHA on `main` — no released version tags | Latent-space lip-sync inpainting | Official `TMElyralab/MuseTalk`; MIT code, commercially-usable weights |
| `torch` | Project already declares `torch>=2.3` under the `[gpu]` extra [VERIFIED: /Users/karstenhaldan/Video-studio/pyproject.toml:67-70 — `gpu = [\n    "torch>=2.3",\n]`] | Shared runtime for both models | Must satisfy Chatterbox's real pin (see Common Pitfalls — version conflict) |
| `openmim` | latest | Installs `mmcv`/`mmdet`/`mmpose`/`mmengine` with auto-resolved, torch-matched wheels | Avoids MuseTalk README's stale hard pins; same tool the project already uses for the ComfyUI-MuseTalk node pack |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `resemble-perth` | git (master, pulled transitively by `chatterbox-tts`) [CITED: raw pyproject.toml, resemble-ai/chatterbox] | Audio watermarking (C3) | Automatic — Chatterbox calls it internally on every `generate()`; no engine code needed, but pin the resolved commit for reproducibility |
| `mmengine`, `mmcv`, `mmdet`, `mmpose` | let `mim install` resolve against installed torch/CUDA (do NOT hard pin to MuseTalk README's `mmcv==2.0.1`) | Face detection / landmark / pose stack MuseTalk's preprocessing depends on | Required transitively by MuseTalk, not imported directly by engine code |
| `whisper-tiny`, `sd-vae-ft-mse`, `dwpose`, `resnet18`, `face-parse-bisent` weights | pinned per MuseTalk's official weight manifest | Auxiliary weights MuseTalk's preparation step needs (audio features, VAE, landmarks, face parsing) | Downloaded once at setup, not per job — same "pin the version, download via script" pattern as `docs/workstation.md` §2's Wan models |
| `torchaudio` | matches the `torch` version selected | Resample Chatterbox's native 24kHz mono output to 48kHz stereo | Already a transitive dep of `chatterbox-tts`; avoids a second ffmpeg round-trip in the engine |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Chatterbox (MIT) | XTTS v2, F5-TTS | Both explicitly rejected in `CLAUDE.md`/`docs/pipeline-spec.md` for licence (CPML / CC-BY-NC) — not viable for this commercial product |
| MuseTalk (MIT) | Wav2Lip | Rejected: research-only licence per `docs/pipeline-spec.md` §2 |
| Direct in-process MuseTalk load | Route lip-sync through the existing ComfyUI-MuseTalk sidecar node pack (`comfy_nodes.py`) | Architecturally wrong for this phase: the render lane loads models directly in one resident process (`worker_gpu`), the wan lane uses ComfyUI as a separate sidecar. Mixing the two would break the "models resident once, never per-job" invariant and add an HTTP round-trip inside the render lane's tight VRAM budget |
| Hard-pinning MuseTalk's documented `torch==2.0.1`/`mmcv==2.0.1` | Unpinned `mim install`, matching the currently-required `torch>=2.3` for the wider project | Hard-pinning would force downgrading torch project-wide, likely breaking Chatterbox (`torch>=2.6.0`) and any other GPU-extra dependency — this is the phase's central risk, see Common Pitfalls |

**Installation (indicative — verify exact versions on the 3090 host):**
```bash
# Chatterbox — normal pip install, MIT
pip install chatterbox-tts

# MuseTalk — clone + vendor, NOT pip installable
git clone https://github.com/TMElyralab/MuseTalk.git third_party/MuseTalk
cd third_party/MuseTalk && git rev-parse HEAD   # record and pin this SHA

# mmlab stack — let mim resolve against whatever torch is installed;
# do NOT copy MuseTalk README's `mmcv==2.0.1` pin verbatim (conflicts w/ Chatterbox torch>=2.6)
pip install -U openmim
mim install mmengine mmcv mmdet mmpose
```

**Version verification:** `chatterbox-tts==0.1.7` was confirmed live against the PyPI
project page on 2026-08-02 [CITED: pypi.org/project/chatterbox-tts]. This research
session runs on a CUDA-less Mac (no `pip`/CUDA toolchain reachable per this
environment — see Environment Availability) so the actual `mim install` wheel
resolution for `mmcv`/`mmdet`/`mmpose` against the exact torch/CUDA combination the
3090 host will run **could not be executed or confirmed** in this session; treat it as
`[ASSUMED]` and gate it behind on-host verification before considering M0.2 done.

## Package Legitimacy Audit

> The `gsd-tools query package-legitimacy check` seam is not available in this
> environment's installed CLI version (`Unknown command: research-plan` /
> `package-legitimacy` also absent). The table below is a manual best-effort audit
> against official sources; **the planner should still gate first-install of each
> package behind a `checkpoint:human-verify` task**, per the protocol's fallback rule
> for unverified findings.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|--------------|---------|-------------|
| `chatterbox-tts` | PyPI | Confirmed live, official `resemble-ai` org (established commercial TTS company) | Not measured (seam unavailable) | `github.com/resemble-ai/chatterbox` | OK (manual) | Approved — pin `==0.1.7`, re-confirm on host |
| MuseTalk (git clone) | N/A — GitHub only, no package registry | Official `TMElyralab` (Tencent Music Entertainment) org, long-established repo | N/A | `github.com/TMElyralab/MuseTalk` | OK (manual) | Approved — pin to a specific commit SHA at install time |
| `mmengine`/`mmcv`/`mmdet`/`mmpose` | PyPI (via `mim`) | Official OpenMMLab ecosystem, long-established | Not measured | `github.com/open-mmlab/*` | OK (manual) | Approved |
| `openmim` | PyPI | Official OpenMMLab package manager | Not measured | `github.com/open-mmlab/mim` | OK (manual) | Approved |
| `resemble-perth` | Git (unpinned `master` branch per Chatterbox's own `pyproject.toml`) [CITED: raw pyproject.toml, resemble-ai/chatterbox] | Same org as Chatterbox | N/A | `github.com/resemble-ai/perth` (transitive) | OK (manual), flag the unpinned ref | Approved — planner should pin the resolved commit SHA once installed, consistent with the project's "pinned versions, scripted download" convention (`docs/workstation.md` §2) |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** none outright, but `resemble-perth`'s
unpinned git dependency and the overall torch/mmcv version resolution are flagged
`[ASSUMED]` pending on-host confirmation — the planner should add
`checkpoint:human-verify` before the first `pip install` / `mim install` run on the
3090 host.

## Architecture Patterns

### System Architecture Diagram

```text
                         RenderJob.status = queued
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │  GPU Worker (1 process)  │   worker_gpu/run.py
                    │  concurrency = 1          │   — boot: get_engines()
                    │                           │      should warm BOTH
                    │  ┌─────────────────────┐  │      models here (gap
                    │  │ ChatterboxEngine     │  │      today — see Pitfall 4)
                    │  │  .load() [boot]      │  │
                    │  │  .synthesize_segment │◄─┼── tts_stage(job_id)
                    │  │   (text, seed,       │  │     for each pending Segment
                    │  │    emotion) →        │  │     under gpu_lock(HOLDER_RENDER)
                    │  │   (uri, duration_ms) │  │
                    │  └──────────┬───────────┘  │
                    │             │ 48kHz stereo  │
                    │             ▼ WAV → S3      │
                    │  ┌─────────────────────┐  │
                    │  │ MuseTalkEngine       │  │
                    │  │  .load() [boot]      │◄─┼── lipsync_stage(job_id)
                    │  │  .sync_chunk(loop_id,│  │     windows from chunk_windows()
                    │  │   start_ms, end_ms)  │  │     (60-90s, pipeline_core/chunking.py)
                    │  │   → chunk video uri   │  │     under gpu_lock(HOLDER_RENDER)
                    │  └──────────┬───────────┘  │
                    │             │ per-chunk mp4 │
                    └─────────────┼───────────────┘
                                  ▼ → S3
                    worker_cpu: assemble_stage
                    (concat chunks, loudnorm, C1 watermark, captions, encode)
                                  │
                                  ▼
                         RenderJob.status = review
```

Face/bbox/latent preparation for a given `BaseLoop` happens **inside**
`MuseTalkEngine.sync_chunk` (or a lazily-populated in-memory cache keyed by
`loop_id` inside the engine instance) — not as a separate persisted stage — because
`worker_gpu/preprocess/loop_cache.py` (Phase 2) has not landed and
`BaseLoop.latents_uri`/`bbox_uri` are always `None` today
[VERIFIED: /Users/karstenhaldan/Video-studio/worker_gpu/preprocess/loop_cache.py:1-15 —
`raise NotImplementedError("M2: seam detection ... + latent cache")`].

### Recommended Project Structure

```
worker_gpu/
├── engines/
│   ├── tts.py          # ChatterboxEngine — fill in load()/synthesize_segment()
│   ├── lipsync.py       # MuseTalkEngine — fill in load()/sync_chunk()
│   └── dev.py           # unchanged — reference for the exact contract shape
third_party/
└── MuseTalk/            # vendored clone, commit-pinned, NOT a pip package
scripts/
├── verify_gpu.py         # unchanged — run first, always
└── bench.py              # unchanged — --smoke is this phase's acceptance gate
```

### Pattern 1: Engine load() guards CUDA, then loads real weights

**What:** Both stub engines already assert `torch.cuda.is_available()` before raising
`NotImplementedError`. Keep that guard; replace only the `raise` line.
**When to use:** Both `ChatterboxEngine.load()` and `MuseTalkEngine.load()`.
**Example (Chatterbox, based on the official API)** [CITED: github.com/resemble-ai/chatterbox]:
```python
def load(self) -> None:
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("ChatterboxEngine requires a CUDA device — run scripts/verify_gpu.py first")
    from chatterbox.tts import ChatterboxTTS
    self._model = ChatterboxTTS.from_pretrained(device="cuda")
```

### Pattern 2: Emotion params flow straight through — no new mapping code

**What:** `worker_gpu/stages.py::tts_stage` already calls
`tts_engine.synthesize_segment(job_id, segment.idx, segment.text, segment.seed,
emotion=emotion_params(segment.emotion))`
[VERIFIED: /Users/karstenhaldan/Video-studio/worker_gpu/stages.py:86-89]. The `emotion`
dict it receives is exactly `{"exaggeration": float, "cfg_weight": float}`
[VERIFIED: /Users/karstenhaldan/Video-studio/packages/pipeline_core/emotions.py:19-26 —
`EMOTIONS: dict[str, dict[str, float]] = {"neutral": {"exaggeration": 0.5, "cfg_weight": 0.5}, "excited": {"exaggeration": 0.9, "cfg_weight": 0.35}, "calm": {"exaggeration": 0.3, "cfg_weight": 0.6}, "serious": {"exaggeration": 0.4, "cfg_weight": 0.55}, "warm": {"exaggeration": 0.6, "cfg_weight": 0.5}, "urgent": {"exaggeration": 0.8, "cfg_weight": 0.3}}`],
which is the same parameter naming Chatterbox's own `generate()` signature uses
(`exaggeration`, `cfg_weight`) [CITED: github.com/resemble-ai/chatterbox]. All of these
values fall inside Chatterbox's documented valid ranges (exaggeration 0.25–2.0,
cfg_weight 0.2–1.0). **Do not build a translation layer** — pass the dict straight into
`model.generate(**emotion)`.
```python
def synthesize_segment(self, job_id, segment_idx, text, seed, emotion=None):
    import torch, torchaudio
    params = emotion or {"exaggeration": 0.5, "cfg_weight": 0.5}
    torch.manual_seed(seed)
    wav = self._model.generate(
        text=text,
        audio_prompt_path=self._reference_audio_path,  # from the job's VoiceProfile
        exaggeration=params["exaggeration"],
        cfg_weight=params["cfg_weight"],
    )
    wav_48k_stereo = torchaudio.functional.resample(wav, self._model.sr, 48000).repeat(2, 1)
    # ... write to a temp wav (pcm_s16le), then self.store.put_file(...)
```

### Pattern 3: In-process bbox/latent cache, keyed by loop_id, not persisted (Phase 1 scope)

**What:** Since `BaseLoop.latents_uri`/`bbox_uri` are unpopulated, `MuseTalkEngine`
should memoize MuseTalk's face-detection/VAE-encode preparation step per `loop_id`
inside the engine instance (a plain `dict`), so repeated chunks/jobs against the same
loop within one worker's uptime don't repeat the expensive prep — without pretending to
solve Phase 2's persisted cache.
**When to use:** `MuseTalkEngine.sync_chunk()`.
```python
def sync_chunk(self, job_id, loop_id, chunk_start_ms, chunk_end_ms):
    if loop_id not in self._prepared_loops:  # in-memory only, not S3
        self._prepared_loops[loop_id] = self._prepare_avatar(loop_id)  # bbox + latents
    avatar = self._prepared_loops[loop_id]
    # ... run MuseTalk's UNet+VAE-decode over the audio-conditioned window
```

### Anti-Patterns to Avoid

- **Loading either model inside `synthesize_segment`/`sync_chunk`:** Both must load
  exactly once in `load()`, called from the boot-time `get_engines()` singleton — never
  per-call. This is already enforced by the existing `_engines` module-level cache in
  `stages.py`.
- **Routing avatar-lane MuseTalk through the ComfyUI sidecar:** The wan lane's
  `ComfyUI-MuseTalk` node pack (`comfy_nodes.py`) is for a *different* feature (M28's
  `musetalk-image` talking-photo kind, run via HTTP against a separate ComfyUI process).
  The render lane's `MuseTalkEngine` must import MuseTalk directly in-process — mixing
  these two integration paths would add HTTP latency and complexity, and there's no
  existing sidecar wiring for the render lane's tight VRAM/latency budget.
- **Copying MuseTalk's README `mmcv==2.0.1`/`torch==2.0.1` pins verbatim:** These predate
  the project's `torch>=2.3` floor and Chatterbox's `torch>=2.6.0` requirement — a
  verbatim copy will very likely fail wheel resolution or silently install a
  torch downgrade that breaks Chatterbox. Let `mim install` resolve instead.
- **Persisting ad hoc bbox/latents to `BaseLoop.latents_uri`/`bbox_uri` from this
  phase's engine code:** That column and its lifecycle belong to Phase 2
  (`worker_gpu/preprocess/loop_cache.py`); writing to it early would create a
  half-implemented cache with no invalidation logic and confuse Phase 2's scope.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Zero-shot voice cloning from reference audio | A custom speaker-embedding/cloning pipeline | Chatterbox's built-in `audio_prompt_path` | Already a first-class, documented parameter of `generate()` |
| Audio watermarking for C3 | A custom inaudible watermark scheme | Chatterbox's automatic Perth watermarking | Applied internally on every `generate()` call; the project's own C3 test already treats "near-ultrasonic content survives the encode chain" as the compliance bar, matching Perth's approach |
| Face detection / landmark / mouth-region cropping for lip-sync | A custom face-crop + landmark model | MuseTalk's own preprocessing (DWPose + face-parse-bisent + resnet18), installed as documented | Reinventing this is a multi-week research project on its own; MuseTalk already ships it |
| Chunk window math for 60–90s lip-sync spans | Recomputing windows inside the engine | `pipeline_core.chunking.chunk_windows()` | Already implemented, pure-function, and tested; the engine receives `(start_ms, end_ms)` and must not recompute them |
| GPU exclusivity / locking | A custom mutex around CUDA calls | `pipeline_core.locks.gpu_lock(redis, HOLDER_RENDER)` | Already implemented, tested, TTL-safe; the stage functions already wrap engine calls in it |

**Key insight:** Everything upstream and downstream of the two engine classes
(idempotency, locking, chunking, DB state machine, S3 I/O, emotion mapping) is already
built and tested against fake engines. This phase's actual surface area is exactly two
methods per engine (`load`, `synthesize_segment`/`sync_chunk`) — resist the temptation to
touch `stages.py`, `chunking.py`, or `locks.py`.

## Common Pitfalls

### Pitfall 1: torch version collision between Chatterbox and MuseTalk

**What goes wrong:** Chatterbox's `pyproject.toml` requires `torch==2.6.0` for Python
<3.14 [CITED: raw pyproject.toml, resemble-ai/chatterbox], while MuseTalk's own README
documents `torch==2.0.1`+`mmcv==2.0.1` on CUDA 11.8
[CITED: raw README.md, TMElyralab/MuseTalk]. Both models load in the **same Python
process** (single GPU worker). Installing Chatterbox's torch pin second (or vice versa)
can silently downgrade/upgrade torch under the other package, or `mim install
mmcv==2.0.1` may find no pre-built wheel for a newer torch and either fail or attempt a
slow from-source build that may not succeed without the matching CUDA toolkit
installed [CITED: github.com/open-mmlab/mmcv installation docs; community reports of
long "dependency hell" resolving this stack, e.g. medium.com/@ammanakhtar8].
**Why it happens:** MuseTalk's README predates the newer torch releases Chatterbox
requires; `mmcv`'s pre-built-wheel index is versioned per exact torch+CUDA combination.
**How to avoid:** Do not pin `mmcv` in the plan. Install torch first (matching
Chatterbox's real requirement), then run `mim install mmengine mmcv mmdet mmpose`
unpinned and let openmim select a compatible pre-built wheel for the torch actually
installed; if no pre-built wheel exists for that exact torch/CUDA pair, fall back to the
newest `mmcv` release that does have one, and confirm MuseTalk's inference code doesn't
depend on the specific removed/renamed mmcv APIs between those versions. **This must be
verified live on the 3090** — plan a `checkpoint:human-verify` task around this before
declaring M0.2/M0.3 satisfied.
**Warning signs:** `pip install` reports a resolved torch version different from what
you expect after installing the second package; `mim install` falls back to building
from source (very slow, or fails outright); `ImportError` for CUDA ops inside `mmcv` at
runtime (mismatched compiled CUDA version vs installed toolkit).

### Pitfall 2: `worker_gpu/run.py` doesn't actually warm models at boot today

**What goes wrong:** M3's milestone requires "models warm at boot, never unloaded"
[CITED: docs/milestones.md M3], but `worker_gpu/run.py:main()` never calls
`get_engines()` — it only starts the RQ worker loop
[VERIFIED: /Users/karstenhaldan/Video-studio/worker_gpu/run.py:23-33 — `def main() -> None: assert GPU_WORKER_CONCURRENCY == 1, ...` through `worker.work()`, no `get_engines()` call present]. Today, engines load lazily on the **first job's** `tts_stage` call, via `stages.py::get_engines()`'s module-level singleton [VERIFIED: /Users/karstenhaldan/Video-studio/worker_gpu/stages.py:33-53]. This means the first real job pays full model-load latency inline, and a worker that never receives a job never proves its models even load.
**Why it happens:** The lazy-singleton pattern was sufficient for CI (dev engines load
near-instantly), but doesn't literally satisfy "warm at boot" for real multi-GB models.
**How to avoid:** Add an explicit `get_engines()` call in `worker_gpu/run.py:main()`
before `worker.work()`, so the boot log shows both models loaded and resident before the
worker starts consuming jobs — this is also what makes `M0.2`/`M0.3` ("Chatterbox loads
and produces a 10s clip", "MuseTalk loads and lip-syncs 5s") and `M3.1` ("models warm at
boot") independently checkable outside of `bench.py --smoke`.
**Warning signs:** First job after worker restart takes dramatically longer than
subsequent jobs; nothing in the boot log confirms both models loaded before jobs start
arriving.

### Pitfall 3: Chatterbox's native output isn't the project's 48kHz stereo convention

**What goes wrong:** Chatterbox's `HiFTGenerator` vocoder outputs 24kHz audio
[CITED: deepwiki.com/resemble-ai/chatterbox — "24kHz (S3GEN_SR) sample rate is used for
the final audio output"], and Chatterbox's models are single-channel. If the engine
writes this WAV directly, it diverges from `DevTTSEngine`'s convention (48kHz stereo,
explicit `-ar 48000 -ac 2`) [VERIFIED: /Users/karstenhaldan/Video-studio/worker_gpu/engines/dev.py:82-83].
`worker_cpu/ffmpeg/assemble.py` does defensively resample every input track
(`aresample=48000,aformat=channel_layouts=stereo`)
[VERIFIED: /Users/karstenhaldan/Video-studio/worker_cpu/ffmpeg/assemble.py:52 — `filters.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS[s{i}]")`],
so this is not a hard failure — but leaving it unresampled at the engine layer means the
`.wav` files sitting in S3 per-segment are a different format than what dev-mode
produces, which could confuse debugging, and skips an opportunity to detect a bad
resample early via `worker_cpu/ffmpeg/ingest.py::probe()`.
**Why it happens:** Chatterbox's native sample rate is a training-time property of the
model, unrelated to this project's convention.
**How to avoid:** Resample+upmix explicitly in `synthesize_segment` (via `torchaudio` or
an `ffmpeg` subprocess, matching `DevTTSEngine`'s pattern) before `store.put_file()`.
**Warning signs:** Segment `.wav` files in S3 show 24kHz mono in `ffprobe`/`probe()`
output instead of 48kHz stereo.

### Pitfall 4: The C3 audio-watermark test today only proves a synthetic proxy signal survives

**What goes wrong:** `tests/test_assemble.py`'s C3 check verifies that "the near-ultrasonic
band survived loudnorm + AAC 192k" [VERIFIED: /Users/karstenhaldan/Video-studio/tests/test_assemble.py:230 — `# C3 proxy: the near-ultrasonic band survived loudnorm + AAC 192k`],
using a synthetic tone, not Chatterbox's actual Perth watermark. Once real Chatterbox
audio flows through the pipeline in this phase, the *real* Perth watermark's frequency
characteristics have never been round-tripped through this project's specific loudnorm+
AAC 192k chain.
**Why it happens:** The CI test suite runs without CUDA, so it could never have used a
real Chatterbox output — the proxy was the only option available at M4/M5.
**How to avoid:** Not a REQ-gpu-environment/REQ-gpu-worker acceptance item per se, but
worth a manual spot-check during this phase's `bench.py --smoke` or first real render:
extract the watermark from an assembled MP4's audio track with
`perth.PerthImplicitWatermarker().get_watermark(...)` and confirm it still reads `1.0`
after the full encode chain, not just the CI proxy signal.
**Warning signs:** None automated today — this is a manual verification gap the planner
should flag, potentially as a UAT checkpoint rather than a blocking task (it belongs to
C3 compliance rather than REQ-gpu-environment/REQ-gpu-worker's letter, but the risk
surfaces for the first time in this phase).

### Pitfall 5: MuseTalk is not `pip install`-able — treat it like a vendored dependency, not a package

**What goes wrong:** Attempting `pip install musetalk` or adding `musetalk` to
`pyproject.toml`'s `gpu` extra will fail — there is no such PyPI package
[CITED: WebSearch across MuseTalk's official repo, HuggingFace mirror, and community
install guides — no `setup.py`/`pyproject.toml` for PyPI distribution found].
**Why it happens:** MuseTalk ships as a research-repo layout (`scripts/`, `musetalk/`
importable via `sys.path`), not a packaged library.
**How to avoid:** Vendor the repo (e.g., `git submodule` or a plain clone into
`third_party/MuseTalk`, commit-pinned) and add it to the worker's `PYTHONPATH`, or copy
the relevant `musetalk/` package into the project structure. Record the exact commit SHA
the same way `docs/workstation.md` §2 already records exact model weight versions.
**Warning signs:** `ModuleNotFoundError: No module named 'musetalk'` after a normal
`pip install -e ".[gpu]"`.

## Code Examples

### ObjectStore usage (already the established pattern; engines must follow it)

```python
# Source: /Users/karstenhaldan/Video-studio/packages/pipeline_core/storage.py
# (methods confirmed present: put_bytes, get_bytes, put_file, get_file, parse_uri, ensure_bucket)
key = f"jobs/{job_id}/tts/{segment_idx}.wav"
uri = self.store.put_file(key, wav_path)   # returns the s3:// uri to persist on Segment.audio_uri
```

### Duration probe (reuse, don't reimplement)

```python
# Source: /Users/karstenhaldan/Video-studio/worker_cpu/ffmpeg/ingest.py:26-40
from worker_cpu.ffmpeg.ingest import probe
duration_ms = probe(ffmpeg_bin, wav_path)["duration_ms"]
```

### GPU lock usage (already wraps every engine call from stages.py — do not duplicate inside the engine)

```python
# Source: /Users/karstenhaldan/Video-studio/worker_gpu/stages.py:84,124
with gpu_lock(get_redis(), HOLDER_RENDER):
    audio_uri, duration_ms = tts_engine.synthesize_segment(...)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|-------------------|---------------|--------|
| Wav2Lip for lip-sync | MuseTalk (latent-space inpainting) | Already the project's decision (`docs/pipeline-spec.md` §2) | Wav2Lip's research-only licence made it a non-starter for this commercial product regardless of technical merit |
| XTTS v2 / F5-TTS for TTS | Chatterbox | Already the project's decision | Licence: CPML / CC-BY-NC, both non-commercial |
| MuseTalk v1.0 (single-frame generation) | MuseTalk v1.5 (documented as clearer, less jitter) | Per MuseTalk's own README | Prefer v1.5 checkpoints/config over v1.0 if choosing between them at weight-download time |

**Deprecated/outdated:**
- MuseTalk's documented `torch==2.0.1`/CUDA 11.8 install path is stale relative to this
  project's `torch>=2.3` floor and Chatterbox's `torch>=2.6.0` requirement — do not follow
  it verbatim (see Pitfall 1).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `mim install mmengine mmcv mmdet mmpose` (unpinned) will resolve a working wheel set against whatever torch version Chatterbox actually requires on the 3090 host | Standard Stack, Pitfall 1 | If wrong, mmcv falls back to a from-source build that may fail without the exact CUDA toolkit, or MuseTalk's inference code hits removed/renamed APIs in a newer mmcv — blocking M0.2/M0.3 |
| A2 | Chatterbox's real-world VRAM footprint is roughly 4–6 GB and MuseTalk's is a few GB (based on community reports and MuseTalk's own "4GB minimum tested" README claim), so both resident together stay well under the 20 GB budget | Summary, VRAM budget reasoning | If wrong (e.g., MuseTalk's face-parsing/DWPose auxiliary models add several more GB than expected, or Chatterbox's KV-cache grows with long segments), `bench.py --smoke` fails and the plan needs a VRAM-reduction task (fp16 auxiliary models, offloading auxiliary weights to CPU, etc.) |
| A3 | `chatterbox-tts==0.1.7` (confirmed via a live PyPI page fetch) is the correct package to pin, and its `torch>=2.6.0`/`torchaudio>=2.6.0` requirement is a hard minimum, not a loose default | Standard Stack | If the version drifts by the time this phase executes, or the operator misreads `torch==2.6.0` as an exact pin, install may fail; re-confirm on the actual host before locking the plan's dependency versions |
| A4 | `worker_gpu/run.py:main()` should call `get_engines()` before `worker.work()` to satisfy "models warm at boot" | Common Pitfalls #2 | Low risk if wrong — worst case is a redundant `get_engines()` call (idempotent given the module-level singleton) |
| A5 | MuseTalk v1.5 (not v1.0) is the correct version to target, given its documented clarity/jitter improvements | State of the Art | Low risk — v1.0 vs v1.5 is a checkpoint/config choice, not an interface change; easy to switch later |

## Open Questions

1. **Does `mmcv`/`mmdet`/`mmpose` have a pre-built wheel for the exact torch+CUDA
   combination Chatterbox forces on the 3090?**
   - What we know: `mmcv==2.1.0` has pre-built wheels through torch 2.1/CUDA 12.1;
     `mmcv==2.2.0` extends to torch 2.3/CUDA 12.1 [CITED: mmcv.readthedocs.io — search
     result summary, not independently re-verified against the live compatibility
     matrix]. Chatterbox needs `torch>=2.6.0`.
   - What's unclear: whether any `mmcv` release has a pre-built wheel for torch 2.6.x,
     or whether the plan needs to accept a from-source `mmcv` build on the workstation.
   - Recommendation: treat as a `checkpoint:human-verify` task early in the plan — attempt
     the unpinned `mim install` on the actual 3090 host before writing any code that
     imports MuseTalk, so a from-source build (or a version-pin compromise) is discovered
     before the rest of the plan is built on top of it.

2. **What is the real combined VRAM footprint once both models plus MuseTalk's auxiliary
   weights (whisper-tiny, DWPose, face-parse-bisent, resnet18, sd-vae-ft-mse) are all
   resident?**
   - What we know: individually, both models are documented as lightweight
     (Chatterbox ~0.5B params; MuseTalk's README claims a 4GB-VRAM card works).
   - What's unclear: MuseTalk's auxiliary weight stack (5 additional models) is not
     costed in any figure found during this research.
   - Recommendation: `scripts/bench.py --smoke` (already built, already asserts the
     20GB budget) is the correct and only way to answer this — no further desk research
     will substitute for the measurement.

3. **Does the project want MuseTalk v1.0 or v1.5 checkpoints?**
   - What we know: v1.5 is documented as an improvement (less jitter, better clarity).
   - What's unclear: nothing project-specific rules this out; v1.5 appears to be the
     straightforward default.
   - Recommendation: default to v1.5 unless discuss-phase surfaces a reason otherwise.

## Environment Availability

This research session ran on a CUDA-less macOS machine — the project's own documented
constraint is that **all** GPU verification/bench work requires physical access to the
RTX 3090 host (`.planning/STATE.md` Blockers: "All 6 phases require physical access to
the RTX 3090 workstation"). Availability below reflects this research machine, not the
target execution host.

| Dependency | Required By | Available (this research machine) | Version | Fallback |
|------------|--------------|--------------------------------------|---------|----------|
| CUDA / `nvidia-smi` | `scripts/verify_gpu.py`, `scripts/bench.py`, both engines | ✗ (macOS, no NVIDIA GPU) | — | None — must execute on the 3090 host |
| `torch` w/ CUDA build | Both engines, `verify_gpu.py` | ✗ | — | None — same as above |
| `python3` | General | ✓ | 3.14.6 | — |
| `ffmpeg` | Dev engines, assemble, probe | ✓ | 8.1.2 | — (present here, will also be present on the workstation host) |
| `docker` | Postgres/Redis/MinIO in dev-compose | ✓ | 28.5.1 | Not needed on the GPU host itself — those services run centrally per `docs/workstation.md` |
| `pip` | Package install verification | ✗ (not on PATH in this session) | — | Could not run `pip index versions` / `pip download` locally; relied on PyPI web page fetch instead |

**Missing dependencies with no fallback:**
- CUDA / RTX 3090 access — every acceptance criterion in this phase (M0.1–M0.4, M3.1,
  M3.4) can only be verified on the physical host. This research produces the plan;
  it cannot produce measured numbers.

**Missing dependencies with fallback:**
- `pip` unavailable locally — worked around via direct PyPI/GitHub web fetches for
  version/dependency confirmation instead of `pip index versions`.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest ≥8.0 [VERIFIED: /Users/karstenhaldan/Video-studio/pyproject.toml:30 — `"pytest>=8.0",`] |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — `testpaths = ["tests"]`, `pythonpath = [".", "packages"]` [VERIFIED: /Users/karstenhaldan/Video-studio/pyproject.toml:97-100] |
| Quick run command | `pytest tests/test_dev_engines.py tests/test_queue_topology.py -x` |
| Full suite command | `pytest` |

### Phase Requirements → Test Map

Real-engine acceptance for this phase is **inherently workstation-manual** — no CUDA
means no CI substitute exists or should be built for the actual model loads. The table
below distinguishes what is (and should be) automated from what is manual by necessity.

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|---------------------|-------------|
| REQ-gpu-environment | `verify_gpu.py` asserts sm_86 | manual-only (no CUDA in CI) | `python scripts/verify_gpu.py` | ✅ (script exists, unrunnable off-host) |
| REQ-gpu-environment | Chatterbox+MuseTalk resident, peak VRAM < 20GB | manual-only | `python scripts/bench.py --smoke` | ✅ (harness exists, blocked on engine implementation) |
| REQ-gpu-worker | `get_engines()` selects real engines by default, dev engines only opt-in | unit (CPU-provable) | `pytest tests/test_dev_engines.py::test_real_engines_remain_the_default -x` | ✅ Existing — already passes today (raises before reaching real CUDA code) |
| REQ-gpu-worker | GPU worker concurrency stays 1 | unit | `pytest tests/test_queue_topology.py::test_gpu_concurrency_is_one -x` | ✅ Existing |
| REQ-gpu-worker | Chunked lip-sync window math (60-90s) unaffected by engine change | unit | `pytest tests/test_pipeline_flow.py -x` (fake-engine e2e) | ✅ Existing — should stay green as a regression guard while wiring real engines |
| REQ-gpu-worker | Real engine's `synthesize_segment`/`sync_chunk` return shape matches the interface contract | unit (mockable) | New test recommended: assert method signatures/return types against `DevTTSEngine`/`DevLipsyncEngine`'s contract without requiring CUDA | ❌ Wave 0 — recommend adding a lightweight contract test |
| M3.4 (chunked, >90s script) | End-to-end unattended `queued → review` including a >90s script | manual UAT (panel) | Submit a script in the panel, watch job status | N/A — inherently a workstation acceptance step per `docs/workstation.md` §5 step 3 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_dev_engines.py tests/test_queue_topology.py tests/test_pipeline_flow.py -x` (CPU-only regression guard — proves the interface contract and surrounding orchestration didn't break while engine internals changed)
- **Per wave merge:** full `pytest` suite (CPU-only; still cannot exercise real CUDA paths)
- **Phase gate:** `python scripts/verify_gpu.py && python scripts/bench.py --smoke` on the physical 3090 host — this is the actual phase acceptance criterion per `docs/workstation.md` §5 steps 1–2, and cannot be satisfied any other way

### Wave 0 Gaps
- [ ] A lightweight contract test asserting `ChatterboxEngine`/`MuseTalkEngine` expose the
      same method signatures (`load`, `synthesize_segment`/`sync_chunk`) and return types
      as `DevTTSEngine`/`DevLipsyncEngine`, runnable without CUDA (mock `torch.cuda` calls) —
      covers the interface-contract risk without needing the GPU host
- [ ] No framework install needed — pytest and its config already exist

*(No test-framework install gap: pytest is already fully configured for this project.)*

## Security Domain

No `.planning/config.json` exists, so `security_enforcement` is treated as enabled
(absent = enabled) per protocol — but this phase has essentially no attack surface of
its own: it loads two ML models into an already-locked-down, single-user, localhost
worker process. No new network endpoints, no new user input parsing beyond what already
flows through `RenderJobCreate`/`Segment` validators (unchanged in this phase).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|----------------|---------|--------------------|
| V2 Authentication | No | Single-user localhost tool, unchanged by this phase |
| V3 Session Management | No | Unchanged |
| V4 Access Control | No | Unchanged |
| V5 Input Validation | Indirect — yes | `Segment.text`/`emotion` are already validated at the API edge (`pipeline_core.emotions.emotion_params` raises `EmotionError` on an unknown preset); the engine must not accept a raw, unvalidated emotion dict from anywhere else |
| V6 Cryptography | No | No new crypto surface — Chatterbox's watermarking is steganographic, not cryptographic, and is out of this phase's threat model |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|-----------------------|
| Untrusted/oversized script text driving unbounded GPU memory/time in `synthesize_segment` | Denial of Service | Already mitigated structurally — this is a single-user, localhost tool with no external input path; not a new risk this phase introduces |
| A malformed/adversarial reference audio file crashing or exploiting the TTS model's audio-decoding path | Denial of Service / Tampering | Reference audio comes from `VoiceProfile.reference_audio_uri`, created only through the existing validated API — this phase does not add a new audio-upload path |
| Supply-chain risk from an unpinned git dependency (`resemble-perth`, MuseTalk's own clone) | Tampering | Pin exact commit SHAs for both, per this project's existing "pinned versions, scripted download" convention (`docs/workstation.md` §2) |

## Sources

### Primary (HIGH confidence — read directly from this repository this session)
- `/Users/karstenhaldan/Video-studio/worker_gpu/engines/{tts,lipsync,dev}.py` — engine interface contract
- `/Users/karstenhaldan/Video-studio/worker_gpu/stages.py` — call sites, singleton caching, GPU locking
- `/Users/karstenhaldan/Video-studio/packages/pipeline_core/{chunking,emotions,locks,storage}.py` — shared utilities the engines must use, not reimplement
- `/Users/karstenhaldan/Video-studio/packages/schema/models.py` — `Segment`, `BaseLoop`, `VoiceProfile` field definitions
- `/Users/karstenhaldan/Video-studio/scripts/{verify_gpu,bench}.py` — acceptance harnesses
- `/Users/karstenhaldan/Video-studio/tests/{test_dev_engines,test_queue_topology,test_assemble}.py` — existing test contracts and the C3 proxy-test gap
- `/Users/karstenhaldan/Video-studio/docs/{workstation,milestones,pipeline-spec}.md`, `/Users/karstenhaldan/Video-studio/CLAUDE.md` — project constraints

### Secondary (MEDIUM confidence — official docs/repos fetched this session)
- github.com/resemble-ai/chatterbox (README + `pyproject.toml` fetched directly) — API, licence, torch pin
- pypi.org/project/chatterbox-tts — live version confirmation (0.1.7)
- github.com/TMElyralab/MuseTalk (README + `requirements.txt` fetched directly) — install steps, hardware notes, licence
- mmcv.readthedocs.io — installation/compatibility page (partial; the "latest" page resolved inconsistently between fetches — see Open Question 1)

### Tertiary (LOW confidence — WebSearch summaries only, not independently re-verified)
- Community VRAM estimates for Chatterbox (~4–6GB) and MuseTalk ("4GB minimum tested" is from the official README, but broader community VRAM claims are unverified)
- mmcv/torch compatibility matrix specifics beyond what the official docs page confirmed
- One WebSearch result citing a suspiciously generic PyTorch GitHub issue number was discarded as likely a search-summary artefact, not re-used

## Metadata

**Confidence breakdown:**
- Standard stack (package names, licences, official APIs): HIGH — confirmed against official GitHub/PyPI sources this session
- Architecture (interface contract, chunking, locking): HIGH — read directly from the codebase this session
- Dependency version compatibility (torch/mmcv/mmdet/mmpose resolution): LOW — genuinely unresolvable without the physical 3090 host; flagged for `checkpoint:human-verify`
- VRAM budget: LOW — no authoritative combined figure exists; `bench.py --smoke` is the only real answer
- Pitfalls: MEDIUM-HIGH — several (boot-time warming, sample-rate convention, MuseTalk not being pip-installable, C3 proxy-test gap) are derived directly from reading the existing code, not speculation

**Research date:** 2026-08-02
**Valid until:** 2026-08-16 (14 days — fast-moving dependency ecosystem: torch/mmcv/mmdet release cadence and Chatterbox's own version could shift the exact pins before execution; re-verify package versions immediately before running the plan on the 3090 host)
