# Phase 2: Latent Cache - Research

**Researched:** 2026-08-02
**Domain:** Persisted MuseTalk avatar-preparation cache (bbox/landmark/VAE-latent), bridged from MuseTalk's own local-disk cache format onto `ObjectStore` (S3/MinIO), plus the missing dispatch wiring and a real bug in `bench.py`'s existing cache-speedup measurement.
**Confidence:** MEDIUM overall — the MuseTalk cache *format* is HIGH confidence (read directly from the exact pinned commit's source on GitHub this session); the *integration surface* with Phase 1's `MuseTalkEngine` is LOW confidence because that engine is still `NotImplementedError` and several integration choices are genuinely contingent on how Phase 1 resolves. See `## Phase 1 Contingent Assumptions` — read it before planning tasks.

<user_constraints>
## User Constraints (from CONTEXT.md)

No CONTEXT.md exists for this phase (`/gsd-discuss-phase` has not been run). No locked
decisions, discretion areas, or deferred ideas to carry forward from a discuss session.
The orchestrator's own task brief supplied a `<critical_planning_constraint>` that
functions with the same authority as a locked decision set — it is reproduced in full
under `## Phase 1 Contingent Assumptions` below, and every task the planner writes must
visibly account for it. `CLAUDE.md` constraints (below) are also treated as locked.
</user_constraints>

## Project Constraints (from CLAUDE.md)

- **Models load once at worker boot and stay resident — never per job.** The loop-cache
  build must not spin up a second, independent set of MuseTalk sub-models (VAE, face
  detector, face-parser); it should reuse whatever the resident `MuseTalkEngine` already
  loaded at boot, the same way `sync_chunk` does today in-memory (Phase 1 Pattern 3)
  [VERIFIED: /Users/karstenhaldan/Video-studio/CLAUDE.md:21].
- **GPU worker concurrency is 1**; the render lane and the wan lane are mutually
  exclusive via `gpu_lock` [VERIFIED: /Users/karstenhaldan/Video-studio/packages/pipeline_core/locks.py:26-27 — `HOLDER_RENDER = "render"` / `HOLDER_WAN = "wan"`]. A GPU-bound loop-cache build stage must acquire `gpu_lock(get_redis(), HOLDER_RENDER)` exactly like `tts_stage`/`lipsync_stage` do
  [VERIFIED: /Users/karstenhaldan/Video-studio/worker_gpu/stages.py:84,124].
- **Worker portability**: all artefact I/O through `ObjectStore`; no local filesystem
  paths for persisted artefacts, no `open()`, no hardcoded addresses — enforced by
  `tests/test_portability.py` against every `.py` file under `worker_gpu/`
  [VERIFIED: /Users/karstenhaldan/Video-studio/tests/test_portability.py:19-29]. MuseTalk's
  own cache format is disk-file-based (`coords.pkl`, `latents.pt`, PNG frames) — Phase 2's
  job is bridging that local-scratch format to `ObjectStore`, via `tempfile` scratch dirs
  exactly like `build_window_audio` already does, never a fixed path.
- **Every stage idempotent** — but this cache is **loop-scoped, not job-scoped**. The
  project's stated convention is "(job_id, stage)" [VERIFIED: /Users/karstenhaldan/Video-studio/CLAUDE.md:25],
  but `build_loop_cache`'s own docstring already establishes the correct model for this
  phase: idempotent on the **entity's own persisted state** (`BaseLoop.latents_uri`)
  [VERIFIED: /Users/karstenhaldan/Video-studio/worker_gpu/preprocess/loop_cache.py:5-6 —
  "Idempotent: if latents_uri already exists for the loop, this is a no-op."], the same
  pattern `loop_preprocess_stage` already uses (`if loop.ping_pong: ... return`)
  [VERIFIED: /Users/karstenhaldan/Video-studio/worker_cpu/stages.py:265-267].
- **MIT/Apache-2.0 weights only**; **sm_86, BF16, no FP8**. This phase introduces no new
  models — it reuses exactly the MuseTalk weights and sub-models Phase 1 already audited
  and pinned (see Package Legitimacy Audit).
- **B-roll/wan lane must never run concurrently with the render lane's GPU use**
  [VERIFIED: /Users/karstenhaldan/Video-studio/CLAUDE.md:43-45] — the loop-cache build is
  render-lane GPU use and must hold `HOLDER_RENDER`, not skip locking because it "isn't a
  render."

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REQ-loop-preprocessing | Latent cache built and persisted per loop; second render against a cached loop measurably faster (`bench.py --loop <id>` shows cached run ≥ 40% faster) | This document identifies exactly what MuseTalk's official preparation step produces and how to persist it via `ObjectStore` (`## MuseTalk's Cacheable Preparation Output`), the missing dispatch wiring that must be added for the cache to ever get built (`## Architecture Patterns` Pattern 1), and a **verified bug** in `bench.py`'s existing comparison logic that will make the 40%-faster acceptance criterion permanently unmeasurable unless fixed (`## Common Pitfalls` Pitfall 1) |
</phase_requirements>

## Summary

Phase 2's job sounds like "implement `build_loop_cache`," but the actual scope is three
distinct pieces of work, only one of which is MuseTalk-specific:

1. **Persist MuseTalk's own local-disk avatar-preparation cache through `ObjectStore`.**
   MuseTalk's official pinned commit (`0a89dec45a0192b824e3cf4daf96c239440c5ed8`, the exact
   SHA Phase 1 approved) already implements a complete, working local-disk cache: an
   `Avatar` class in `scripts/realtime_inference.py` that runs face detection + landmark
   extraction (`get_landmark_and_bbox`) + VAE encoding once, writes `coords.pkl`,
   `latents.pt`, `mask_coords.pkl`, and per-frame PNGs to a local directory, and on a
   subsequent run **skips all of that** and loads the same files back
   [VERIFIED: raw.githubusercontent.com/TMElyralab/MuseTalk/0a89dec45a0192b824e3cf4daf96c239440c5ed8/scripts/realtime_inference.py].
   Phase 2's actual job is bridging this already-working local cache to `ObjectStore` —
   build in a `tempfile` scratch dir (matching `build_window_audio`'s existing pattern),
   upload as one or more blobs, and reverse the process on cache hit — **not**
   reimplementing face detection, landmarking or VAE encoding by hand. This is a strong
   "Don't Hand-Roll" case.

2. **Wire the dispatch that currently doesn't exist.** Nothing in the codebase today
   ever calls `build_loop_cache` — not the API routes, not `loop_preprocess_stage`, not any
   GPU stage function [VERIFIED: grep across `api/routes/loops.py`, `worker_cpu/stages.py`,
   `worker_gpu/stages.py` found zero references to `build_loop_cache` or a `loop_cache`
   stage]. A new GPU-queue stage function must be added to `worker_gpu/stages.py`, and it
   must be **chained from `loop_preprocess_stage`'s successful completion** (mirroring the
   existing `tts_stage` → `lipsync_stage` chain), not dispatched from the API route at loop
   creation — because only after CPU preprocessing finishes does `BaseLoop.source_uri` and
   `frame_count` reflect the final, possibly ping-ponged, loop
   [VERIFIED: /Users/karstenhaldan/Video-studio/worker_cpu/stages.py:288-294 — the
   ping-pong fallback rewrites `loop.source_uri`/`loop.frame_count` inside
   `loop_preprocess_stage`]. Dispatching the cache build from the route instead would
   build the cache against the pre-ping-pong source half the time.

3. **Fix a real bug in `scripts/bench.py`'s existing `--loop` comparison**, which the
   roadmap's acceptance criterion depends on verbatim. `bench_loop()` queries
   `Metric.ref.contains(loop_id)` for `stage == "lipsync"`
   [VERIFIED: /Users/karstenhaldan/Video-studio/scripts/bench.py:74-75], but the only
   current writer of `stage="lipsync"` metrics is `lipsync_stage`'s `@timed_stage("lipsync")`
   decorator, which sets `ref = str(job_id)`
   [VERIFIED: /Users/karstenhaldan/Video-studio/packages/pipeline_core/metrics.py:17-23,
   /Users/karstenhaldan/Video-studio/worker_gpu/stages.py:107]. `job_id` and `loop_id` are
   independent, unrelated UUIDs — `Metric.ref.contains(loop_id)` will essentially never
   match a real row. As written today, **`bench.py --loop <id>` cannot find two rows for
   any loop, ever**, regardless of whether the cache works. This is not a hypothetical
   risk; it is a bug in code this session read directly, and REQ-loop-preprocessing's
   stated acceptance command depends on it. See Pitfall 1 for the fix.

**Primary recommendation:** Reuse MuseTalk's own `Avatar`/preparation code path (via the
same vendored `third_party/MuseTalk` clone Phase 1 installs) inside a new
`worker_gpu/stages.py::loop_cache_stage(loop_id)` GPU-queue function, chained from
`loop_preprocess_stage`'s completion; persist exactly the small, cheap-to-move artifacts
(`coords.pkl`, `mask_coords.pkl`, `latents.pt`) via `ObjectStore`, regenerating the larger
per-frame PNGs from the loop's own source video on cache-hit rather than persisting them;
record `BaseLoop.latents_uri`/`bbox_uri` only after a successful upload; and fix
`bench.py`'s metric `ref` mismatch before relying on it as this phase's acceptance
mechanism.

## Phase 1 Contingent Assumptions

**This phase is being planned ahead of its dependency.** `worker_gpu/engines/lipsync.py`'s
`MuseTalkEngine.load()` and `.sync_chunk()` are still `NotImplementedError`
[VERIFIED: /Users/karstenhaldan/Video-studio/worker_gpu/engines/lipsync.py:17-29] — Phase 1
plans 01-04 and 01-05 (the GPU-host smoke test and the frame-continuity fix) have not
executed. The following claims this research and the eventual plan will rest on are
**contingent on Phase 1's outcome** and should be re-checked cheaply (grep + read, not a
full re-research pass) before Phase 2 execution begins:

| # | Contingent claim | Why it matters | Cheap re-check before executing |
|---|---|---|---|
| P1-A | `MuseTalkEngine` will expose its loaded VAE / face-detector / face-parser sub-models in a way the loop-cache build can call directly, rather than every model being buried as unexported locals inside `load()` | If the sub-models aren't reachable, the cache-build stage must either reload its own copies (violates "load once, stay resident," doubles VRAM briefly) or `MuseTalkEngine` needs a small refactor to expose an `ensure_loop_cache(loop_id)` method that owns both the in-memory Phase-1 memo and the Phase-2 persisted path | `grep -n "self\._" worker_gpu/engines/lipsync.py` once Phase 1 lands — confirm named, reusable attributes exist for the VAE/detector/parser, not just a single opaque `self._model` |
| P1-B | The MuseTalk commit Phase 1 pins (`0a89dec45a0192b824e3cf4daf96c239440c5ed8`) has an `Avatar` class whose paths are `{avatar_path}/coords.pkl`, `{avatar_path}/latents.pt`, `{avatar_path}/mask_coords.pkl`, `{avatar_path}/full_imgs/`, `{avatar_path}/mask/`, `{avatar_path}/avator_info.json`, and defaults to `version="v15"` | This is the exact file/directory contract Phase 2's ObjectStore bridge must reproduce | [VERIFIED: raw.githubusercontent.com/TMElyralab/MuseTalk/0a89dec45a0192b824e3cf4daf96c239440c5ed8/scripts/realtime_inference.py — fetched **at the exact pinned SHA**, not `main`, this session] — HIGH confidence, but re-confirm if plan 01-01 Task 4 ever re-pins a different SHA |
| P1-C | Whether mask generation (`mask_coords.pkl` + the `mask/` PNGs) requires re-running the face-parsing model (`face-parse-bisent`) or is derivable from `coords.pkl` by cheap bbox/crop math alone | Determines whether the cache must persist actual mask PNGs (expensive to store/move) or only `mask_coords.pkl` (cheap) and regenerate masks on cache-hit | **Not resolved by this research pass** — read `third_party/MuseTalk/musetalk/utils/blending.py` (or equivalent) on the GPU host once cloned. Tagged `[ASSUMED]`, see Assumptions Log A2 |
| P1-D | The torch/mmlab dependency-conflict resolution (Phase 1 plan 01-01 Task 4, options a/b/c vs option-d subprocess isolation) resolves to an **in-process** load (a/b/c), not option-d | Determines whether the loop-cache build can call into `MuseTalkEngine`'s live Python objects at all | **If option-d is chosen** (MuseTalk isolated in its own venv/subprocess): the persisted-cache *design* in this document still works largely unchanged, because it is file/blob-based, not shared-Python-object-based — see the explicit analysis directly below. But the **in-memory reuse optimization** (Phase 1 Pattern 3's `_prepared_loops` dict avoiding re-deserializing latents within one job's many chunks) would need re-design, since "resident in memory" stops meaning the same thing across a subprocess boundary |
| P1-E | `chunk_windows`/`sync_chunk`'s frame-continuity fix (Phase 1 plan 01-05, `loop_frame_offset`) lands before Phase 2, so a cached loop's frame indexing is stable and doesn't change again on top of the cache | If Phase 1 plan 01-05 is skipped or reordered, the loop-cache's stored latents are still valid (they're keyed by frame index into the full cycle list, not by window), but `MuseTalkEngine.sync_chunk`'s consumption of them would still need updating in lockstep — not a Phase 2 risk per se, just a sequencing note |

**If Phase 1 resolves to option-d (subprocess isolation) — does the design still work?**
Yes, with one caveat, and this is worth stating plainly because the orchestrator flagged
it as the question most likely to force a replan. The persisted cache this phase builds is
**file-based by construction** (matching MuseTalk's own native format): whichever process
actually runs face-detection/VAE-encode needs to produce `coords.pkl`/`latents.pt` files
in *some* local scratch directory, and uploading those files to `ObjectStore` is a
plain-Python operation that doesn't care which process wrote them. So the "build once,
persist to S3, download+deserialize on hit" architecture survives a subprocess boundary
unchanged. What does NOT survive unchanged is Phase 1's **in-memory** ad hoc memo
(`self._prepared_loops[loop_id]` holding live deserialized tensors across chunk calls
within one job) — if MuseTalk itself lives in a subprocess, "in the resident process's
memory" no longer means "immediately available to the next `sync_chunk` call" the same
way; each call would need to cross the subprocess boundary again (via RPC or by having the
subprocess hold its own memo). This is a real, if second-order, replan trigger: **if Phase
1 lands as option-d, add a task to Phase 2's plan (or a fast follow) verifying the
subprocess shim's own process retains a warm per-loop cache across chunks, not just across
jobs** — otherwise every chunk pays a full deserialize-from-disk cost even on a "cached"
loop, which would still likely clear the 40% bar (network+deserialize is far cheaper than
face-detection+VAE-encode) but by a smaller margin than an in-process design.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Loop-cache build trigger (dispatch) | worker_cpu (`loop_preprocess_stage`, chains on completion) | API route (`/loops` POST/`/preprocess`, indirect via the CPU stage it already enqueues) | Only the CPU stage knows the loop's *final* post-ping-pong `source_uri`/`frame_count`; the route only knows the pre-preprocessing state |
| Face detection / landmark / VAE-encode ("preparation") | GPU Worker (`worker_gpu`, reusing MuseTalk's own code + Phase 1's resident sub-models) | — | Requires CUDA + the same weight set the render lane already loads; must not become a second, independently-loaded model set |
| Cache persistence (`coords.pkl`/`latents.pt`/`mask_coords.pkl`) | Storage (`ObjectStore`) | — | Existing single interface; no local filesystem persistence, per portability rule |
| Cache invalidation on loop mutation (ping-pong doubling `frame_count`, `source_uri` swap) | worker_cpu (already mutates `BaseLoop` inside `loop_preprocess_stage`) + API (`update_loop` already resets `latents_uri`/`bbox_uri` to `None` on any PUT) | GPU Worker (idempotency check reads `BaseLoop.latents_uri`) | No new invalidation mechanism needed — the existing PUT route already blanket-overwrites `latents_uri`/`bbox_uri` to `None` unless a caller explicitly sets them, and the chain-after-CPU-preprocess ordering means the cache is always built against the final state |
| Cache-speedup measurement | Ops script (`scripts/bench.py`) | Storage (`Metric` table) | Already exists as `bench_loop()`, but its `ref` filter does not match what `lipsync_stage` records today — must be fixed in this phase, not deferred |
| GPU exclusivity while building the cache | GPU Worker (`gpu_lock(HOLDER_RENDER)`) | — | The build is render-lane GPU work; it must never run concurrently with a wan-lane generation |

## Standard Stack

No new external packages are introduced by this phase. It reuses exactly what Phase 1
already vendors and pins:

| Component | Version / pin | Purpose in this phase | Source |
|---|---|---|---|
| `third_party/MuseTalk` (vendored clone) | commit `0a89dec45a0192b824e3cf4daf96c239440c5ed8`, approved in Phase 1 [VERIFIED: /Users/karstenhaldan/Video-studio/.planning/phases/01-render-engines-live/01-01-SUMMARY.md:13] | Supplies `musetalk.utils.preprocessing.get_landmark_and_bbox`, the VAE wrapper, and the `Avatar` preparation/cache-format reference implementation this phase's ObjectStore bridge mirrors | Already audited MIT, Phase 1 Package Legitimacy Audit |
| `torch` | Whatever Phase 1 plan 01-01 Task 4 resolves (unresolved as of this research) | VAE encode, tensor serialization (`torch.save`/`torch.load`) | Same pin Phase 1 uses — no independent version needed here |
| `pillow` | `>=10.0` [VERIFIED: /Users/karstenhaldan/Video-studio/pyproject.toml:23] | Already a core dependency (used by `pipeline_core/seam.py`); no new install if frame-level image handling is needed | Already in `pyproject.toml` |
| `pickle` (stdlib) | n/a | `coords.pkl`/`mask_coords.pkl` serialization, matching MuseTalk's own format exactly rather than inventing a JSON re-encoding | stdlib |

**Installation:** none — no `pip install` step is needed for this phase beyond what Phase
1's `scripts/install_engines.sh` already installs.

## Package Legitimacy Audit

No new external packages are installed by this phase. The `Package Legitimacy Audit`
protocol is not applicable — every dependency this phase touches (`third_party/MuseTalk`,
`torch`, `pillow`) was already audited and approved in Phase 1
(`.planning/phases/01-render-engines-live/01-01-SUMMARY.md`, "Task 2: Package Legitimacy
Gate — APPROVED"). Do not re-run the gate for these; only re-run it if this phase's plan
introduces something genuinely new (e.g., a compression library for the cache bundle,
which is not currently recommended — see Architecture Patterns Pattern 2 for why a plain
multi-key upload is preferred over a tar/zip bundle).

## MuseTalk's Cacheable Preparation Output

Read directly from the exact pinned commit
(`0a89dec45a0192b824e3cf4daf96c239440c5ed8`) this session
[VERIFIED: raw.githubusercontent.com/TMElyralab/MuseTalk/0a89dec45a0192b824e3cf4daf96c239440c5ed8/scripts/realtime_inference.py]:

```python
# Avatar.__init__ path assignments (quoted verbatim from the fetch)
self.avatar_path = self.base_path
self.full_imgs_path = f"{self.avatar_path}/full_imgs"
self.coords_path = f"{self.avatar_path}/coords.pkl"
self.latents_out_path = f"{self.avatar_path}/latents.pt"
self.mask_out_path = f"{self.avatar_path}/mask"
self.mask_coords_path = f"{self.avatar_path}/mask_coords.pkl"
self.avatar_info_path = f"{self.avatar_path}/avator_info.json"
```

```python
# prepare_material persistence (quoted verbatim from the fetch)
with open(self.coords_path, 'wb') as f:
    pickle.dump(self.coord_list_cycle, f)

torch.save(self.input_latent_list_cycle,
           os.path.join(self.latents_out_path))
```

`get_landmark_and_bbox` is imported from `musetalk.utils.preprocessing` at this exact
commit, and the CLI defaults to `version="v15"`
[VERIFIED: same fetch]. `coord_list_cycle` is a list of `(x1, y1, x2, y2)` bounding boxes
(one placeholder `(0.0, 0.0, 0.0, 0.0)` per frame where detection failed) and
`input_latent_list_cycle` is a list of VAE-encoded latent tensors, one per frame, for the
**forward-plus-reversed cycle** (so a single-direction loop's latents are computed once
and mirrored, matching how MuseTalk plays a static avatar back and forth)
[CITED: same fetch, cross-referenced against the earlier `main`-branch fetch of the same
file, which described the same forward+reverse cycle construction].

**What is cheap to persist vs. expensive:**

| Artifact | Approx. size | Cheap to re-derive without re-running the expensive models? |
|---|---|---|
| `coords.pkl` | A few KB (4 floats × frame count) | No — regenerating requires re-running face detection, the exact cost this cache exists to avoid |
| `latents.pt` | Roughly 16 KB/frame at float32 for a 32×32×4 VAE latent (8× spatial downsample of a 256×256 crop) `[ASSUMED — standard sd-vae-ft-mse-style latent shape, not confirmed against this project's exact VAE config file]`. For a 10 s loop at 25 fps, forward+reverse ≈ 500 frames → **≈8 MB**; a doubled (ping-pong) 20 s loop → **≈16 MB** | No — regenerating requires re-running the VAE encoder |
| `mask_coords.pkl` | A few KB | Unclear — see Phase 1 Contingent Assumption P1-C |
| `full_imgs/*.png`, `mask/*.png` | Potentially **hundreds of MB** for a multi-second loop at source resolution (one PNG per frame) | **Yes for `full_imgs/`** — these are just decoded frames of the loop's own `source_uri` video, trivially re-extractable with `ffmpeg` (the same tool this project already uses everywhere) at cache-hit time. **Unclear for `mask/`** pending P1-C |

**Recommendation:** persist only `coords.pkl`, `latents.pt`, and (pending P1-C)
`mask_coords.pkl` through `ObjectStore`. Do not persist `full_imgs/` PNGs — regenerate them
from the loop's `source_uri` via ffmpeg frame extraction on cache-hit, the same category of
operation `worker_cpu/ffmpeg/loops.py::_extract_frame` already performs
[VERIFIED: /Users/karstenhaldan/Video-studio/worker_cpu/ffmpeg/loops.py:46-52]. This keeps
the cache artifact small (tens of MB, not hundreds) and fast to move over the network,
which matters directly for the ≥40%-faster acceptance criterion — a slow S3 round-trip on
a large blob could erode the margin the cache is supposed to create.

## Architecture Patterns

### System Architecture Diagram

```text
POST /loops                              POST /loops/{id}/preprocess (manual rerun)
        │                                              │
        └───────────────┬──────────────────────────────┘
                         ▼
        worker_cpu: loop_preprocess_stage(loop_id)   [EXISTING, unchanged: VFR reject,
        │                                              seam-score, ping-pong fallback]
        │  loop.error is None?
        │       │
        │       ▼ yes                                    ▼ no (VFR rejected)
        │  ┌─────────────────────────────┐          (stop — no cache build,
        │  │ NEW: dispatch to QUEUE_GPU    │           matches loop_preprocess_stage's
        │  │ "worker_gpu.stages            │           existing early return)
        │  │  .loop_cache_stage", loop_id  │
        │  └──────────────┬────────────────┘
        │                 ▼
        │   worker_gpu: loop_cache_stage(loop_id)   [NEW]
        │     under gpu_lock(HOLDER_RENDER)
        │     ┌─────────────────────────────────┐
        │     │ BaseLoop.latents_uri already set? │
        │     └───────┬─────────────────┬─────────┘
        │          yes│                 │no
        │             ▼                 ▼
        │        no-op (idempotent,   build_loop_cache(...):
        │        matches loop_cache.py │  1. download source_uri via ObjectStore
        │        docstring)            │  2. extract frames (ffmpeg, tempfile scratch)
        │                              │  3. reuse MuseTalk's own get_landmark_and_bbox
        │                              │     + VAE encode (Phase 1's resident sub-models)
        │                              │  4. write coords.pkl / latents.pt / mask_coords.pkl
        │                              │     to the scratch dir (MuseTalk's own format)
        │                              │  5. upload each file via store.put_file(...)
        │                              │  6. set BaseLoop.latents_uri / bbox_uri, commit
        ▼
  (later) a RenderJob referencing this loop reaches lipsync_stage → sync_chunk:
        MuseTalkEngine checks BaseLoop.latents_uri:
          set  → download + torch.load / pickle.load (fast path — THIS is the ≥40% saving)
          None → build ad hoc in-memory only (Phase 1 Pattern 3 fallback — should not
                 normally happen once this phase's dispatch chain is wired, but must not
                 crash if the loop somehow reaches lipsync_stage before its cache finishes)
```

### Recommended Project Structure

```
worker_gpu/
├── preprocess/
│   ├── loop_cache.py     # build_loop_cache(...) — fill in; reuses MuseTalk's own
│   │                     #   preparation code path, does not reimplement it
│   └── __init__.py       # already exists, empty
├── stages.py             # ADD: loop_cache_stage(loop_id) — GPU-queue entry point,
│                         #   gpu_lock(HOLDER_RENDER), idempotent no-op if cached
worker_cpu/
└── stages.py             # MODIFY: loop_preprocess_stage chains to QUEUE_GPU
                          #   loop_cache_stage on success (mirrors ingest_stage's
                          #   existing caption_stage chain pattern)
scripts/
└── bench.py              # FIX: bench_loop()'s Metric.ref filter (see Pitfall 1)
```

### Pattern 1: Chain the GPU cache build from CPU preprocessing completion, never from the route

**What:** `loop_preprocess_stage` already mutates `BaseLoop.source_uri`/`frame_count` for
the ping-pong fallback case, and already has an established chaining precedent elsewhere in
the codebase (`ingest_stage` chains to `caption_stage` on its own queue at its tail)
[VERIFIED: /Users/karstenhaldan/Video-studio/worker_cpu/stages.py:375-383]. A cross-package
chain (worker_cpu → worker_gpu) is also already an established pattern in the other
direction (`worker_gpu`'s `tts_stage` chains to `worker_cpu.stages.assemble_stage` via
`QUEUE_CPU`) [VERIFIED: /Users/karstenhaldan/Video-studio/worker_gpu/stages.py:135-137], so
chaining `worker_cpu` → `worker_gpu` via `QUEUE_GPU` is symmetric with existing precedent,
not a new architectural pattern.
**When to use:** At the very end of `loop_preprocess_stage`, only when `loop.error is
None` (a VFR-rejected loop must never get a cache built for it).
**Example (illustrative — matches the existing chain style exactly):**
```python
# worker_cpu/stages.py, end of loop_preprocess_stage, after the existing commit:
from pipeline_core.dispatch import Dispatcher
from pipeline_core.queues import QUEUE_GPU, stage_key

if loop.error is None:
    Dispatcher().enqueue(
        QUEUE_GPU, "worker_gpu.stages.loop_cache_stage", loop_id,
        job_key=stage_key(loop_id, "loop_cache"),
    )
```

### Pattern 2: Multiple small keys, not one bundled archive

**What:** Upload `coords.pkl`, `latents.pt`, and `mask_coords.pkl` as three separate
`ObjectStore` keys under a `loops/{loop_id}/cache/` prefix (matching the existing
`loops/{loop_id}/pingpong.mp4` key convention
[VERIFIED: /Users/karstenhaldan/Video-studio/worker_cpu/stages.py:290]), e.g.
`loops/{loop_id}/cache/coords.pkl`, `loops/{loop_id}/cache/latents.pt`,
`loops/{loop_id}/cache/mask_coords.pkl`. Record one of these (or a computed prefix) as
`BaseLoop.latents_uri` and another as `BaseLoop.bbox_uri` — the schema only has two URI
columns [VERIFIED: /Users/karstenhaldan/Video-studio/packages/schema/models.py:202-203 —
`latents_uri: Optional[str] = None` / `bbox_uri: Optional[str] = None`], so the plan must
decide whether `bbox_uri` covers both `coords.pkl` and `mask_coords.pkl` (e.g. store them
under one prefix and treat `bbox_uri` as "the bbox/mask prefix") or whether a migration
adding a third column is warranted. Given the two-column schema is already committed and
this is a small, cheap artifact set, the pragmatic recommendation is: **`latents_uri`
points at `latents.pt`; `bbox_uri` points at a `coords.pkl`+`mask_coords.pkl` prefix**
(e.g. `loops/{loop_id}/cache/bbox/`, with both files under it, retrieved via
`store.list_keys(prefix)` or two fixed sub-keys) rather than adding a migration for one
extra small file.
**Why not a tar/zip bundle:** a bundle requires an extra compress/decompress step and an
extra dependency decision (which archive format, which compression level) for artifacts
that are already only tens of MB total — the complexity is not justified. Three small
`put_file`/`get_file` calls are simpler, individually resumable, and match the project's
existing one-key-per-artifact convention everywhere else (`tts_segment_key`,
`lipsync_chunk_key`, `derived_prefix`).

### Pattern 3: Reuse MuseTalk's own preparation code, don't reimplement it

**What:** `get_landmark_and_bbox` (face detection + landmark → bbox) and the VAE encode
loop (`vae.get_latents_for_unet`) already exist in the vendored `third_party/MuseTalk`
clone Phase 1 installs. `build_loop_cache` should import and call these directly (the same
way `MuseTalkEngine.sync_chunk` will), then serialize their outputs with `pickle`/
`torch.save` into a `tempfile` scratch directory, then upload — not hand-roll a parallel
face-detection or VAE-encode implementation.
**When to use:** Inside `build_loop_cache`, for the cache-miss path only.
**Why:** MuseTalk's own weights (DWPose, face-parse-bisent, sd-vae-ft-mse per Phase 1's
Standard Stack table) and code are already the audited, pinned dependency — reimplementing
any part of this is a multi-week research project on its own (identical reasoning to
Phase 1 RESEARCH.md's "Don't Hand-Roll" entry for MuseTalk's own preprocessing).

### Anti-Patterns to Avoid

- **Persisting per-frame PNGs (`full_imgs/`, `mask/`) verbatim to S3.** These are the
  single largest artifact MuseTalk's own cache produces and the cheapest to regenerate
  (they're just decoded video frames plus — pending P1-C — possibly a cheap bbox-crop
  operation). Persisting them defeats the size/latency goal this cache exists to serve.
- **Dispatching the GPU cache build from the API route at loop creation time.** The route
  does not yet know the loop's final (possibly ping-ponged) `source_uri`/`frame_count` —
  only `loop_preprocess_stage`'s completion does.
- **Loading a second, independent set of MuseTalk sub-models just to build the cache.**
  Violates "models load once at worker boot, stay resident." If Phase 1's `MuseTalkEngine`
  doesn't yet expose reusable sub-model handles when this phase starts, that is a small
  Phase-1-adjacent refactor task to add, not a reason to duplicate the load.
- **Trusting `bench.py --loop <id>` unmodified.** Its `Metric.ref` filter does not match
  what `lipsync_stage` currently records (see Pitfall 1) — this phase's acceptance
  criterion is unmeasurable until this is fixed.
- **Writing `BaseLoop.latents_uri`/`bbox_uri` before the upload succeeds.** Match the
  existing convention elsewhere in this codebase (e.g. `ingest_stage` checks
  `store.exists(...)` before treating derivatives as present) — set the DB columns only
  after `store.put_file` returns, inside the same session/commit, so a crash mid-upload
  never leaves a `BaseLoop` pointing at a URI that doesn't exist.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Face detection, landmark extraction, bbox computation for a loop's frames | A custom face-detection/landmark pipeline | MuseTalk's own `musetalk.utils.preprocessing.get_landmark_and_bbox`, already vendored by Phase 1 | Already audited, pinned, and exactly matches what `MuseTalkEngine.sync_chunk` will consume — a second implementation could silently produce incompatible bbox conventions |
| VAE encoding of face crops into MuseTalk's latent space | A custom VAE wrapper | MuseTalk's own VAE loading + `get_latents_for_unet`-style call, reusing the sd-vae-ft-mse weights Phase 1 already downloads | The latent format must exactly match what the UNet inference step expects; MuseTalk's own code is the only source of truth for that contract |
| Local-disk cache format / skip-logic | A bespoke cache-manifest scheme | Mirror MuseTalk's own `coords.pkl`/`latents.pt`/`mask_coords.pkl` naming and structure | Keeps this phase's ObjectStore bridge a thin wrapper rather than a second competing cache-format design; also means any future direct use of MuseTalk's own `Avatar` class (e.g. if the render lane's `sync_chunk` implementation chooses to instantiate `Avatar` directly rather than re-deriving its own structures) can point straight at the downloaded scratch directory with `preparation=False` |
| Video frame extraction for cache-miss preparation | A custom frame decoder | `ffmpeg`, the project's existing tool (`worker_cpu/ffmpeg/loops.py::_extract_frame` is the exact pattern) | Already the project's standard, already proven against real clips in `tests/test_loop_preprocess.py` |

**Key insight:** Nearly everything this phase needs (the expensive computation, the local
cache format, the frame extraction tooling) already exists somewhere in this codebase or
in the vendored MuseTalk clone. The actual new code surface is the ObjectStore bridge, the
dispatch chain, and the `bench.py` fix — not a lip-sync-preprocessing reimplementation.

## Common Pitfalls

### Pitfall 1: `bench.py --loop <id>` cannot match any metric row as written today

**What goes wrong:** `bench_loop()` filters `Metric.ref.contains(loop_id)` for
`stage == "lipsync"` [VERIFIED: /Users/karstenhaldan/Video-studio/scripts/bench.py:74-75].
The only writer of `stage="lipsync"` metrics is `lipsync_stage`'s `@timed_stage("lipsync")`
decorator, whose `ref` is `str(job_id)` — the RenderJob's id, not the BaseLoop's id
[VERIFIED: /Users/karstenhaldan/Video-studio/packages/pipeline_core/metrics.py:17-23 —
`def wrapper(ref, *args, **kwargs): with timed(stage, str(ref)): ...`, called as
`lipsync_stage(job_id)`]. `job_id` and `loop_id` are independent UUID4 values; one
containing the other as a substring is astronomically unlikely. Run the benchmark exactly
as documented ("render the same job twice... `bench.py --loop <id>` shows cached run ≥ 40%
faster") and `rows` will have length 0 or the wrong rows, and the script will print "need
two lipsync runs recorded for this loop (found 0)" forever, regardless of whether the
cache actually speeds anything up.
**Why it happens:** The `timed_stage` decorator's contract ("first argument is the ref")
was written for `lipsync_stage(job_id)`, and nothing updated `bench_loop`'s query — or the
metric-writing side — to also be filterable by loop.
**How to avoid:** Two viable fixes; either is acceptable, pick one and apply it
consistently:
1. Stop using the blanket `@timed_stage("lipsync")` decorator on `lipsync_stage` and
   instead call `pipeline_core.metrics.timed("lipsync", f"{job_id}:{job.base_loop_id}")`
   manually once `job.base_loop_id` is in scope (after loading the job), so the `ref`
   column contains both ids and `bench_loop`'s `.contains(loop_id)` matches. Confirmed
   safe: nothing else in the codebase does an exact-match query against a `lipsync`-stage
   `ref` [VERIFIED: grep of `api/routes/metrics.py`/`api/routes/stats.py` — the only
   exact-match `Metric.ref ==` queries are for the unrelated `export`/`export_progress`
   stages; the dashboard's "recent_stages"/trend view groups by `stage` only, not `ref`,
   so changing the `ref` format is safe].
2. Change `bench_loop`'s query to first resolve which `RenderJob.id`s reference
   `loop_id` (`select(RenderJob.id).where(RenderJob.base_loop_id == loop_id)`), then filter
   `Metric.ref.in_(...)` against those job ids, `stage == "lipsync"`. This avoids touching
   the metric-writing side at all, at the cost of `bench_loop` needing to run two queries
   instead of one, and only working correctly if the same job is genuinely re-rendered
   twice (matching the existing docstring's instruction) rather than two different jobs
   both referencing the loop.
**Recommendation:** Option 1 is more robust (works whether the operator re-renders the
same job twice or renders two different jobs against the same loop) and is a smaller,
more local change. This phase's plan must include a task for this fix — it is not optional
polish, it is the acceptance mechanism REQ-loop-preprocessing depends on verbatim.
**Warning signs:** `bench.py --loop <id>` prints "need two lipsync runs recorded for this
loop (found 0)" even immediately after two real renders against that loop.

### Pitfall 2: Building the cache with a fresh model load defeats "load once, stay resident"

**What goes wrong:** If `build_loop_cache` (or the new `loop_cache_stage`) imports and
loads its own VAE/face-detector instances independently of whatever `MuseTalkEngine.load()`
already loaded at boot, the worker now has two copies of multi-GB weights resident at once
for the duration of the cache build — eroding the VRAM headroom Phase 1 measures (and
Phase 3's wan lane needs later, per Phase 1 RESEARCH.md's own cross-phase VRAM concern).
**Why it happens:** `build_loop_cache`'s current stub signature is `(store: ObjectStore,
loop_id: str)` with no engine parameter
[VERIFIED: /Users/karstenhaldan/Video-studio/worker_gpu/preprocess/loop_cache.py:13], so
the path of least resistance when filling it in is to construct fresh model objects
locally.
**How to avoid:** Route the cache build through the resident `MuseTalkEngine` singleton
(`worker_gpu.stages.get_engines()`), either by giving `build_loop_cache` an engine
parameter or by making it a method the engine exposes. This is Phase 1 Contingent
Assumption P1-A — flag it explicitly in the plan as needing Phase 1's actual `load()`
implementation before this can be finalized.
**Warning signs:** `nvidia-smi` shows VRAM usage spike well above the render lane's
established baseline specifically during loop-cache builds, not during normal renders.

### Pitfall 3: Invalidation silently already works for the PUT path, but the manual `/preprocess` rerun path doesn't chain the cache rebuild

**What goes wrong:** `update_loop` (the `PUT /loops/{id}` route) already blanket-overwrites
every `BaseLoopBase` field including `latents_uri`/`bbox_uri` from the request body
[VERIFIED: /Users/karstenhaldan/Video-studio/api/routes/loops.py:75-87 —
`for key, value in body.model_dump().items(): setattr(loop, key, value)`], and
`BaseLoopCreate` defaults `latents_uri`/`bbox_uri` to `None`
[VERIFIED: /Users/karstenhaldan/Video-studio/packages/schema/models.py:199-206]. So any
PUT to an unreferenced loop (the only kind that can be PUT — referenced loops 409) already
naturally nulls the persisted cache columns. But `POST /loops/{loop_id}/preprocess` (the
manual CPU-preprocessing rerun endpoint) only re-enqueues `loop_preprocess_stage`
[VERIFIED: /Users/karstenhaldan/Video-studio/api/routes/loops.py:53-62] — if Pattern 1's
chain is implemented correctly (chain lives inside `loop_preprocess_stage`, not the route),
this manual rerun automatically re-triggers the GPU cache rebuild too, for free. If instead
the chain is implemented as a second dispatch call bolted onto the route handlers
(duplicating the chain in both `create_loop` and `preprocess_loop`), it is easy to forget
one of the two call sites.
**How to avoid:** Put the chain exactly once, inside `loop_preprocess_stage` itself (worker
side), never in the route handlers. Both existing route handlers already funnel through
that one stage function.
**Warning signs:** A loop's source is replaced and re-preprocessed via the manual rerun
endpoint, but the render lane still uses stale cached latents from the old source — check
whether the chain lives in the stage or was duplicated (and possibly missed) in the routes.

## Code Examples

### Existing ping-pong / cache-column mutation pattern (the invalidation-relevant precedent)

```python
# Source: /Users/karstenhaldan/Video-studio/worker_cpu/stages.py:286-294
score = lp.seam_score(binary, source, tmp_path)
loop.seam_score = score
if score > lp.SEAM_MAX_SCORE:
    pingpong = lp.make_ping_pong(binary, source, tmp_path / "pingpong.mp4")
    uri = store.put_file(f"loops/{loop_id}/pingpong.mp4", pingpong)
    loop.source_uri = uri
    loop.frame_count = loop.frame_count * 2
    loop.ping_pong = True
```

### Existing cross-package stage chaining precedent (the pattern this phase's dispatch mirrors)

```python
# Source: /Users/karstenhaldan/Video-studio/worker_gpu/stages.py:135-137
Dispatcher().enqueue(
    QUEUE_CPU, "worker_cpu.stages.assemble_stage", job_id, job_key=stage_key(job_id, "assemble")
)
```

### Existing idempotent-on-entity-state pattern (what `build_loop_cache` should follow, not `stage_key(job_id, stage)`)

```python
# Source: /Users/karstenhaldan/Video-studio/worker_cpu/stages.py:264-267
loop = session.get(BaseLoop, uuid.UUID(loop_id))
if loop is None:
    raise ValueError(f"loop {loop_id} not found")
if loop.ping_pong:
    log.info("loop_preprocess_skip_idempotent", loop_id=loop_id)
    return
```

### MuseTalk's own preparation persistence (the format this phase's ObjectStore bridge mirrors)

```python
# Source: raw.githubusercontent.com/TMElyralab/MuseTalk (pinned commit
# 0a89dec45a0192b824e3cf4daf96c239440c5ed8), scripts/realtime_inference.py
with open(self.coords_path, 'wb') as f:
    pickle.dump(self.coord_list_cycle, f)
torch.save(self.input_latent_list_cycle, os.path.join(self.latents_out_path))
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|---|---|---|---|
| Ad hoc in-memory per-loop preparation, lost on worker restart (Phase 1's `MuseTalkEngine._prepared_loops` dict) | Persisted per-loop cache via `ObjectStore`, survives worker restarts and is shared across every job that reuses the loop | This phase (M2.3/M2.4) | The whole point of REQ-loop-preprocessing's "second render measurably faster" — a restart-durable cache is what makes the acceptance criterion meaningful across process lifetimes, not just within one worker's uptime |

**Deprecated/outdated:** none — this phase extends existing, already-correct code rather
than replacing a superseded approach.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `MuseTalkEngine` (once implemented) will expose its loaded VAE/face-detector/face-parser sub-models in a form the loop-cache build can call directly, without reloading | Phase 1 Contingent Assumptions P1-A, Pitfall 2 | If wrong, the loop-cache build must either reload models (VRAM/time cost, `checkpoint:human-verify` needed to confirm headroom) or Phase 1's engine needs a small refactor first — a sequencing dependency the plan should surface explicitly |
| A2 | Whether MuseTalk's `mask/` PNGs require re-running face-parsing (expensive) or are derivable from `mask_coords.pkl` by cheap crop math alone is unresolved from this research pass — assumed to require the model, so this phase should default to caching `mask_coords.pkl` and treating the actual mask images as regenerable-if-cheap, verified once on the GPU host | MuseTalk's Cacheable Preparation Output, P1-C | If wrong in the expensive direction (masks genuinely need face-parsing every time), the achieved speedup could fall short of the 40% target — the plan should measure this explicitly with `bench.py --loop`, not assume it in advance |
| A3 | A VAE latent at MuseTalk's 256×256 crop resolution is a 32×32×4 tensor (≈16 KB/frame at float32), giving a full loop's `latents.pt` in the single-digit-to-tens-of-MB range | MuseTalk's Cacheable Preparation Output | If wrong (e.g., a different VAE config with a different downsample factor or channel count), the cache artifact could be larger than estimated — this affects transfer-time margin against the 40% target but not correctness; verify by inspecting `latents.pt`'s actual file size on the first real build |
| A4 | Recording `latents_uri` → `latents.pt` and `bbox_uri` → a `coords.pkl`+`mask_coords.pkl` prefix (rather than adding a third schema column) is an acceptable mapping onto the existing two-column `BaseLoop` schema | Architecture Patterns Pattern 2 | If the planner instead wants a dedicated third column (e.g. `mask_uri`), that requires an Alembic migration — a bigger and more reversible-with-cost change than reusing the existing two columns; flag this as a decision point for `/gsd-discuss-phase` or the plan's own`checkpoint:decision` if there is any doubt |
| A5 | The torch/mmlab resolution from Phase 1 plan 01-01 Task 4 lands as an in-process option (a/b/c), not option-d (subprocess isolation), by the time Phase 2 executes | Phase 1 Contingent Assumptions P1-D | If option-d is chosen, the persisted-cache architecture (file/blob based) still works as designed, but the in-memory per-job chunk-reuse optimization needs a second look — see the explicit analysis in that section |

## Open Questions

1. **Does the resolved MuseTalk commit's mask generation need the face-parsing model, or
   is it cheap bbox math?**
   - What we know: `mask_coords.pkl` stores "mask crop box coordinates" separately from
     the actual mask PNGs; the coordinate extraction itself looks cheap, but whether the
     mask *image* (used for compositing the generated mouth region back into the frame)
     needs a face-parsing model pass is not established by this research pass.
   - What's unclear: the exact blending/masking code path in `third_party/MuseTalk`
     (likely `musetalk/utils/blending.py` or similar) was not fetched this session.
   - Recommendation: read that file directly once `third_party/MuseTalk` is cloned on the
     GPU host (Phase 1 already vendors it) — a five-minute check that resolves Assumption
     A2 with certainty before committing to what the cache persists.

2. **Should `bbox_uri` become a prefix (multiple files) or should the schema gain a third
   URI column?**
   - What we know: the schema currently has exactly two cache-URI columns
     (`latents_uri`, `bbox_uri`) [VERIFIED: models.py:202-203].
   - What's unclear: whether the project's owner would prefer a clean one-column-per-
     artifact schema (a small Alembic migration, following the project's existing
     migration cadence — e.g. migration 0013/0014 for other small additions) over reusing
     `bbox_uri` as a prefix.
   - Recommendation: default to reusing `bbox_uri` as a prefix (Assumption A4) since it
     avoids a migration for a phase that's otherwise pure worker-code — but this is a
     legitimate `discuss-phase` question if the user wants to weigh in.

## Environment Availability

This research session ran on the same CUDA-less macOS machine as Phase 1's research. All
GPU-bound work in this phase (face detection, VAE encode, `nvidia-smi`-observable VRAM
during cache builds) is unverifiable here for the same reason Phase 1's was.

| Dependency | Required By | Available (this research machine) | Version | Fallback |
|---|---|---|---|---|
| CUDA / `nvidia-smi` | Loop-cache build (face detection, VAE encode) | ✗ (macOS, no NVIDIA GPU) | — | None — must execute on the RTX 3090 host, same as Phase 1 |
| `third_party/MuseTalk` clone | Reusing `get_landmark_and_bbox` / VAE code | ✗ (not cloned on this machine; Phase 1's installer hasn't run here) | — | This research read the exact pinned commit directly from GitHub instead |
| `ffmpeg` | Frame extraction for cache-miss preparation, and for regenerating `full_imgs/` on cache-hit | ✓ | 8.1.2 | — |
| `python3` | General | ✓ | 3.14.6 | — |

**Missing dependencies with no fallback:**
- CUDA / RTX 3090 access — every measurement this phase needs (actual cache-build time,
  actual cache-hit speedup, actual artifact sizes) can only be produced on the physical
  host, exactly like Phase 1.

**Missing dependencies with fallback:**
- `third_party/MuseTalk` clone unavailable locally — worked around via direct GitHub raw
  fetches of the exact pinned commit's source files instead of reading a local checkout.

## Validation Architecture

### Test Framework

| Property | Value |
|---|---|
| Framework | pytest ≥8.0 [VERIFIED: /Users/karstenhaldan/Video-studio/pyproject.toml:30] |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/test_loop_preprocess.py tests/test_render_engines.py -x` |
| Full suite command | `pytest` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REQ-loop-preprocessing | `loop_preprocess_stage` chains to a GPU-queue `loop_cache_stage` on success, and does NOT chain when `loop.error` is set | unit (CPU-provable with a fake `Dispatcher`, moto S3, the existing `store_env`/`engine`/`session` fixtures from `tests/test_loop_preprocess.py`) | `pytest tests/test_loop_preprocess.py -x` (extended) | ❌ Wave 0 — new tests needed |
| REQ-loop-preprocessing | `build_loop_cache` is idempotent: a loop with `latents_uri` already set is a no-op that never touches the store or a model | unit (CPU-provable — inject a fake model/engine that raises if called) | New test in a new `tests/test_loop_cache.py` | ❌ Wave 0 |
| REQ-loop-preprocessing | `build_loop_cache`'s ObjectStore bridge round-trips MuseTalk's cache format: build against synthetic frames, upload, download, and the loaded `coords`/`latents` match what was uploaded, all without CUDA (mock the face-detect/VAE calls, test only the persistence bridge) | unit | New test in `tests/test_loop_cache.py` | ❌ Wave 0 |
| REQ-loop-preprocessing | `bench.py --loop <id>`'s `Metric.ref` fix: given two `Metric(stage="lipsync", ref=<fixed format>)` rows for the same loop, `bench_loop` finds both and computes the speedup percentage correctly | unit | New test in `tests/test_render_engines.py` or a new `tests/test_bench.py` | ❌ Wave 0 |
| REQ-loop-preprocessing | The real face-detection/VAE-encode build, and the actual ≥40% measured speedup | manual-only (no CUDA in CI) | `python scripts/bench.py --loop <id>` on the workstation, per `docs/workstation.md` §5 step 5 | ✅ (script exists, its bug must be fixed first — Pitfall 1) |

### Sampling Rate
- **Per task commit:** `pytest tests/test_loop_preprocess.py tests/test_loop_cache.py tests/test_render_engines.py tests/test_portability.py -x`
- **Per wave merge:** full `pytest` suite (CPU-only; cannot exercise the real CUDA path)
- **Phase gate:** `python scripts/bench.py --loop <id>` on the RTX 3090 host — this is the actual REQ-loop-preprocessing acceptance and cannot be satisfied any other way (`docs/workstation.md` §5 step 5)

### Wave 0 Gaps
- [ ] `tests/test_loop_cache.py` — does not exist yet; covers `build_loop_cache`'s
      idempotency and its ObjectStore round-trip, with the expensive model calls mocked
- [ ] Extend `tests/test_loop_preprocess.py` — cover the new dispatch chain from
      `loop_preprocess_stage` to `worker_gpu.stages.loop_cache_stage`
- [ ] A `bench.py` regression test — covers the `Metric.ref` fix from Pitfall 1
- [ ] No framework install needed — pytest is already fully configured

## Security Domain

No `.planning/config.json` exists, so `security_enforcement` is treated as enabled
(absent = enabled). This phase has a narrow attack surface: it adds no new HTTP input path
(the existing `/loops` routes are unchanged) and consumes only data already validated
elsewhere (`BaseLoop.source_uri`, populated at loop creation through the existing
`BaseLoopCreate` schema).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---|---|---|
| V2 Authentication | No | Unchanged — single-user localhost tool |
| V3 Session Management | No | Unchanged |
| V4 Access Control | No | Unchanged |
| V5 Input Validation | Indirect | `loop_id` arrives only from already-validated `BaseLoop` rows created via the existing `BaseLoopCreate` schema; this phase adds no new user-facing input field |
| V6 Cryptography | No | No new crypto surface |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---|---|---|
| A malformed/adversarial loop video crashing or exploiting MuseTalk's face-detection or VAE-decode path during cache build | Denial of Service / Tampering | The loop's `source_uri` comes only from the existing validated `BaseLoop` creation path; this phase adds no new upload route. Same disposition as Phase 1's equivalent threat for reference audio/loop video (RESEARCH.md 01, T-01-09) |
| A crashed/partial cache build leaving `BaseLoop.latents_uri` pointing at a URI that was never actually uploaded | Tampering / Denial of Service | Set `latents_uri`/`bbox_uri` only after `store.put_file` succeeds, inside the same session — see Architecture Patterns anti-pattern list |
| Two concurrent cache-build dispatches for the same loop (e.g. a duplicate manual `/preprocess` call while a build is already in flight) racing to write `BaseLoop.latents_uri` | Tampering | `stage_key(loop_id, "loop_cache")` as the RQ job id gives natural de-duplication at the queue level (a second enqueue with the same job_id is a no-op under RQ's default behavior — the same mechanism every other stage in this codebase already relies on for its own idempotency) |

## Sources

### Primary (HIGH confidence — read directly from this repository this session)
- `/Users/karstenhaldan/Video-studio/worker_gpu/preprocess/loop_cache.py` — the stub this phase implements
- `/Users/karstenhaldan/Video-studio/worker_gpu/engines/lipsync.py`, `tts.py`, `dev.py` — current engine state (still `NotImplementedError`), the dev/real contract
- `/Users/karstenhaldan/Video-studio/worker_gpu/stages.py`, `worker_cpu/stages.py` — existing stage/dispatch/chaining/idempotency conventions
- `/Users/karstenhaldan/Video-studio/packages/pipeline_core/{metrics,dispatch,locks,queues,chunking,storage,settings}.py`
- `/Users/karstenhaldan/Video-studio/packages/schema/models.py` — `BaseLoop` field definitions
- `/Users/karstenhaldan/Video-studio/scripts/bench.py` — the `bench_loop()` bug this phase must fix
- `/Users/karstenhaldan/Video-studio/api/routes/loops.py` — existing dispatch/invalidation behavior
- `/Users/karstenhaldan/Video-studio/tests/test_loop_preprocess.py`, `tests/test_portability.py`
- `.planning/phases/01-render-engines-live/{01-RESEARCH,01-01-SUMMARY,01-02-SUMMARY,01-03-SUMMARY,01-04-PLAN,01-05-PLAN}.md` — Phase 1's actual completion state and the exact pinned MuseTalk commit
- `docs/{milestones,workstation}.md`, `CLAUDE.md`, `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`, `.planning/STATE.md`

### Secondary (MEDIUM-HIGH confidence — official source fetched this session)
- `raw.githubusercontent.com/TMElyralab/MuseTalk/0a89dec45a0192b824e3cf4daf96c239440c5ed8/scripts/realtime_inference.py` — fetched at the **exact pinned commit** Phase 1 approved, not `main` — the `Avatar` class path/cache-format contract this phase's ObjectStore bridge mirrors
- `raw.githubusercontent.com/TMElyralab/MuseTalk/main/scripts/realtime_inference.py` — cross-referenced against the pinned-commit fetch; consistent

### Tertiary (LOW confidence — not independently re-verified)
- Exact VAE latent tensor shape/size estimate (Assumption A3) — inferred from standard
  sd-vae-ft-mse-style 8× downsampling, not confirmed against this project's exact VAE
  config file (not yet clonable locally)
- Whether mask-image generation needs the face-parsing model or is cheap bbox math
  (Assumption A2 / Open Question 1) — genuinely unresolved by this research pass

## Metadata

**Confidence breakdown:**
- MuseTalk cache format (files, paths, what's serialized): HIGH — read directly from the
  exact pinned commit's source this session
- Missing dispatch wiring and the `bench.py` metric-ref bug: HIGH — both are direct code
  reads with no external dependency, confirmed by tracing every call site
- Integration with Phase 1's `MuseTalkEngine` (model reuse, subprocess-boundary
  robustness): LOW — genuinely contingent on Phase 1 landing, which has not happened;
  see `## Phase 1 Contingent Assumptions`
- Artifact sizes and mask-generation cost (VRAM/time/disk): LOW — no GPU host available
  this session, same limitation Phase 1's research documented

**Research date:** 2026-08-02
**Valid until:** 2026-08-09 (7 days) — this phase's core assumptions are tied to Phase 1's
still-unresolved torch/mmlab decision and the still-`NotImplementedError` `MuseTalkEngine`;
re-verify the Phase 1 Contingent Assumptions table immediately once Phase 1 completes,
before trusting this document's integration recommendations.
