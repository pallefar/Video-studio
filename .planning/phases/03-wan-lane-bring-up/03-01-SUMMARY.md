---
phase: 03-wan-lane-bring-up
plan: 01
subsystem: infra
tags: [comfyui, wan2.2, gguf, structural-audit, tdd, node-signatures]

requires:
  - phase: 02
    provides: node-pack manifest (comfy_nodes.py NodePack registry), the M30-proven wan2.1-t2v-1.3b template
provides:
  - "NodeSignature/NODE_SIGNATURES/audit_graph() in comfy_nodes.py — a signature-driven structural audit closing three blind spots the old path-resolution-only test had (output-index bounds, required-input presence, node reachability)"
  - "wan2.2-ti2v-5b: ModelSpec, workflow template, node-pack manifest entries — the missing second arm for the M10.6 14B-vs-5B benchmark decision"
  - "AWAITING_REPAIR: an 11-template shrink-only ratchet (10 anticipated + ace-step, independently discovered) that plans 03-02/03-04 must empty"
  - "input_mapping_paths() + multi-path inject() — one studio parameter can now drive several graph nodes"
affects: [03-02, 03-04, 03-05]

actuals:
  tokens: 13419
  tasks: 3
  commits: 5

tech-stack:
  added: []
  patterns:
    - "Registry-as-data node signatures with mandatory provenance strings, nullable fields for declared-unverified blind spots"
    - "Structural graph audit (dangling-edge / output-index / required-input / coverage / reachability) as a pure function over a defaulted signature map, so tests can inject a wrong map to prove the checks aren't hardcoded"
    - "Shrink-only ratchet asserted bidirectionally (every listed template dirty, every unlisted template clean) so a repair that forgets to shrink the list, or an entry that silently starts passing, fails the suite"

key-files:
  created:
    - packages/pipeline_core/workflows/wan2.2-ti2v-5b.json
  modified:
    - packages/pipeline_core/comfy_nodes.py
    - packages/pipeline_core/comfy.py
    - packages/pipeline_core/providers.py
    - tests/test_comfy.py

key-decisions:
  - "wan2.2-ti2v-5b stays text-to-video only (not hybrid T+I2V) even though the real Wan22ImageToVideoLatent node supports an optional start_image — an untested LoadImage node with an empty default filename risks a real ComfyUI validation failure this audit can't catch; keeping the tracer's proven-pattern parity with wan2.1-t2v-1.3b exact was judged the safer thin slice"
  - "5B defaults (1280x704, fps 24, cfg 5.0, uni_pc/simple) taken from ComfyUI's own officially shipped Wan2.2 TI2V-5B workflow (Comfy-Org/workflow_templates, fetched live) rather than mirroring wan2.1-t2v-1.3b's 832x480/fps16/cfg6 — these are the model's own tuned defaults, not arbitrary"
  - "ace-step added to AWAITING_REPAIR — not on this phase's research-time 10-template list, found only by reading comfy_extras/nodes_ace.py directly; the critical_requirement's instruction to record what is ACTUALLY dirty, not what was anticipated, is honored over adjusting the list to match the plan's prose"
  - "MuseTalkRun and FL_ChatterboxTTS signatures were fetched and verified from source rather than declared unverified, even though Task 2's action text didn't name them explicitly — using real fetched data beats declaring a blind spot when the fetch is one curl away, and it's what surfaced MuseTalkRun's contract mismatch"

requirements-completed: [REQ-generative-broll-lane]

duration: ~50min
completed: 2026-08-02
status: complete
---

# Phase 3 Plan 1: Signature-Driven Graph Audit + Wan2.2 TI2V-5B Path Summary

**Built a node-signature registry with provenance and a five-check structural audit (dangling edges, output-index bounds, required-input presence, signature coverage, backward reachability) that proves 11 of 15 shipped ComfyUI templates are broken today — one more than research anticipated — and used it to build a complete wan2.2-ti2v-5b fallback path end to end.**

## Performance

- **Duration:** ~50 min
- **Completed:** 2026-08-02
- **Tasks:** 3 (1 tracer, 2 TDD auto)
- **Files modified:** 5 (1 created)

## What the audit checks, and where it lives

`packages/pipeline_core/comfy_nodes.py` now defines:

- **`NodeSignature`** (frozen dataclass): `outputs: tuple[str, ...] | None`, `required_inputs: tuple[str, ...] | None`, `provenance: str`. Nullable fields mean "not verified from source" — used for the 9 WanVideoWrapper classes (uni3c/recammaster) whose class *names* were only ever schema-verified against a running ComfyUI, never their wiring (research Pitfall 4).
- **`NODE_SIGNATURES`**: 34 entries. 25 verified against upstream source (fetched live: `comfyanonymous/ComfyUI`, `city96/ComfyUI-GGUF`, `Kosinkadink/ComfyUI-VideoHelperSuite`, `filliptm/ComfyUI_Fill-ChatterBox`, `chaojie/ComfyUI-MuseTalk`), 9 declared unverified (`ComfyUI-WanVideoWrapper`, matching that pack's own `provides` tuple exactly — asserted by `test_declared_blind_spots_are_visible_and_bounded`).
- **`audit_graph(graph, signatures=None, output_node=None, template_inputs=None)`**: pure function, returns a list of defect strings.
  1. **Dangling edge** — a `[node_id, index]` reference to a node id absent from the graph.
  2. **Output index in bounds** — when the source node's class has a *verified* output tuple, the index must be within it. This is the check that catches `UnetLoaderGGUF`'s `clip`/`vae` wired from indices 1/2 of a node with exactly one output (`RETURN_TYPES = ("MODEL",)`, confirmed by reading `city96/ComfyUI-GGUF/nodes.py`).
  3. **Required inputs present** — when a class has a *verified* required-key tuple, every key must be a key of the node's own `inputs`. Also caught a second, independent defect the plan predicted might exist: `UnetLoaderGGUF`'s real required key is `unet_name`, not `ckpt_name` — every broken GGUF-loader template passes the wrong key.
  4. **Signature coverage** — any edge-source class type with *no entry at all* is a defect (the audit is blind to it); a declared-unverified entry is not a coverage defect.
  5. **Reachability** — backward walk from `output_node`; anything outside the closure is unreachable. When `template_inputs` is supplied, the defect names the inert studio parameter (`source_image`, `source_video`, `camera_motion`, `lora_name`) — proven against all 5 orphan-carrying templates.

## Observed dirty-list — run against today's (unrepaired) templates, not assumed

15 templates exist after this plan (14 shipped + the new 5B). **11 audit dirty, 4 audit clean:**

| Template | Status | Defects | Defect classes |
|---|---|---|---|
| wan2.2-t2v | DIRTY | 5 | required-input (`unet_name`) + output-index x3 (clip x2, vae x1) + required-input (VHS fields) |
| wan2.2-i2v | DIRTY | 6 | above + reachability (`source_image` inert) |
| wan2.2-fun-camera | DIRTY | 6 | above + reachability (`camera_motion` inert) |
| wan2.2-vace-fun | DIRTY | 7 | above + `VHS_LoadVideo` required-input (5 missing keys) + reachability (`source_video` inert) |
| wan2.1-vace-1.3b | DIRTY | 7 | same as wan2.2-vace-fun |
| qwen-image | DIRTY | 4 | required-input (`unet_name`) + output-index x3 (no VHS node, so no VHS defect) |
| sdxl | DIRTY | 1 | reachability only (`lora_name` inert — orphan `LoraLoader`) |
| ace-step | DIRTY | 1 | **new finding** — `TextEncodeAceStepAudio` required-input (`lyrics_strength`) |
| musetalk-image | DIRTY | 2 | **new finding** — `MuseTalkRun` required-input (real signature takes `video_path`/`audio_path`/`batch_size`, template supplies none of them) + VHS fields |
| uni3c | DIRTY | 1 | VHS fields only (WanVideoWrapper wiring is a declared blind spot) |
| recammaster | DIRTY | 2 | **new finding** — `VHS_LoadVideo` required-input (5 missing keys) + VHS fields |
| wan2.1-t2v-1.3b | clean | 0 | M30-proven, unchanged |
| wan2.2-ti2v-5b | clean | 0 | new, built to audit clean |
| z-image-turbo | clean | 0 | confirmed clean once `CheckpointLoaderSimple`/`EmptyLatentImage` were verified |
| chatterbox | clean | 0 | confirmed clean once `FL_ChatterboxTTS` was verified |

**`AWAITING_REPAIR`** (`tests/test_comfy.py`) is exactly this 11-template dirty set. `test_templates_off_the_ratchet_audit_clean` and `test_templates_on_the_ratchet_audit_dirty` assert both directions.

**Ratchet-removal experiment (run and reverted, per acceptance criteria):** removing `"wan2.2-t2v"` from `AWAITING_REPAIR` and running `pytest tests/test_comfy.py -q` fails `test_templates_off_the_ratchet_audit_clean` with:
```
AssertionError: wan2.2-t2v: ["node 2 (UnetLoaderGGUF) is missing required input(s) ['unet_name'] ...",
"node 6 (CLIPTextEncode) input 'clip' reads output index 1 of node 2 (UnetLoaderGGUF), which has 1 output(s): ('MODEL',)",
"node 7 (CLIPTextEncode) input 'clip' reads output index 1 of node 2 (UnetLoaderGGUF), which has 1 output(s): ('MODEL',)",
"node 8 (VAEDecode) input 'vae' reads output index 2 of node 2 (UnetLoaderGGUF), which has 1 output(s): ('MODEL',)",
"node 60 (VHS_VideoCombine) is missing required input(s) ['loop_count', 'pingpong', 'save_output'] ..."]
```
List restored immediately after; `git diff --stat tests/test_comfy.py` is clean.

## Signatures recorded — verbatim outputs/required keys, with source

| Class | Outputs | Required inputs | Source |
|---|---|---|---|
| `UnetLoaderGGUF` | `("MODEL",)` | `("unet_name",)` | `city96/ComfyUI-GGUF/nodes.py` |
| `CLIPLoaderGGUF` | `("CLIP",)` | `("clip_name","type")` | `city96/ComfyUI-GGUF/nodes.py` |
| `UNETLoader` | `("MODEL",)` | `("unet_name","weight_dtype")` | `comfyanonymous/ComfyUI/nodes.py` |
| `VAELoader` | `("VAE",)` | `("vae_name",)` | `comfyanonymous/ComfyUI/nodes.py` |
| `ModelSamplingSD3` | `("MODEL",)` | `("model","shift")` | `comfy_extras/nodes_model_advanced.py` |
| `CLIPTextEncode` | `("CONDITIONING",)` | `("text","clip")` | `comfyanonymous/ComfyUI/nodes.py` |
| `EmptyHunyuanLatentVideo` | `("LATENT",)` | `("width","height","length","batch_size")` | `comfy_extras/nodes_hunyuan.py` |
| `Wan22ImageToVideoLatent` | `("LATENT",)` | `("vae","width","height","length","batch_size")` | `comfy_extras/nodes_wan.py` |
| `KSampler` | `("LATENT",)` | 10 keys (model..denoise) | `comfyanonymous/ComfyUI/nodes.py` |
| `VAEDecode` | `("IMAGE",)` | `("samples","vae")` | `comfyanonymous/ComfyUI/nodes.py` |
| `VHS_VideoCombine` | `("VHS_FILENAMES",)` | 7 keys incl. `loop_count`,`pingpong`,`save_output` | `videohelpersuite/nodes.py::VideoCombine` |
| `VHS_LoadVideo` | 4 outputs | 7 keys | `videohelpersuite/load_video_nodes.py::LoadVideoUpload` |
| `CheckpointLoaderSimple` | `("MODEL","CLIP","VAE")` | `("ckpt_name",)` | `comfyanonymous/ComfyUI/nodes.py` |
| `LoraLoader` | `("MODEL","CLIP")` | 5 keys | `comfyanonymous/ComfyUI/nodes.py` |
| `EmptyLatentImage` | `("LATENT",)` | `("width","height","batch_size")` | `comfyanonymous/ComfyUI/nodes.py` |
| `SaveImage` | `("IMAGE",)` | `("images","filename_prefix")` | `comfyanonymous/ComfyUI/nodes.py` |
| `LoadImage` | `("IMAGE","MASK")` | `("image",)` | `comfyanonymous/ComfyUI/nodes.py` |
| `LoadAudio` | `("AUDIO",)` | `("audio",)` | `comfy_extras/nodes_audio.py` |
| `SaveAudio` | `("AUDIO",)` | `("audio","filename_prefix")` | `comfy_extras/nodes_audio.py` |
| `VAEDecodeAudio` | `("AUDIO",)` | `("samples","vae")` | `comfy_extras/nodes_audio.py` |
| `TextEncodeAceStepAudio` | `("CONDITIONING",)` | `("clip","tags","lyrics","lyrics_strength")` | `comfy_extras/nodes_ace.py` |
| `EmptyAceStepLatentAudio` | `("LATENT",)` | `("seconds","batch_size")` | `comfy_extras/nodes_ace.py` |
| `WanCameraEmbedding` | 4 outputs | `("camera_pose","width","height","length")` | `comfy_extras/nodes_camera_trajectory.py` |
| `FL_ChatterboxTTS` | `("AUDIO","STRING")` | 5 keys | `filliptm/ComfyUI_Fill-ChatterBox/chatterbox_node.py::FL_ChatterboxTTSNode` |
| `MuseTalkRun` | `("IMAGE",)` | `("video_path","audio_path","bbox_shift","batch_size")` | `chaojie/ComfyUI-MuseTalk/nodes.py` |
| 9x `WanVideo*` classes | `None` (unverified) | `None` (unverified) | `kijai/ComfyUI-WanVideoWrapper` — names only, Phase 4 owns wiring verification |

**Two facts confirmed by reading source, not assumed:** (1) `UnetLoaderGGUF`/`CLIPLoaderGGUF` really are two distinct classes with one output each — the research's central claim, now backed by a live fetch. (2) The required-input key mismatch the plan flagged as a possible second defect is real: every broken GGUF template passes `ckpt_name`, upstream declares `unet_name`.

## wan2.2-ti2v-5b artefacts

- **`packages/pipeline_core/workflows/wan2.2-ti2v-5b.json`** — three-loader split (`UnetLoaderGGUF` + `CLIPLoaderGGUF` + `VAELoader`) copied node-id-for-node-id from `wan2.1-t2v-1.3b.json`, with the latent node swapped: **`Wan22ImageToVideoLatent`, not `EmptyHunyuanLatentVideo`** — resolved from source (`comfy_extras/nodes_wan.py`), confirmed against ComfyUI's own officially shipped `Comfy-Org/workflow_templates:templates/video_wan2_2_5B_ti2v.json` (fetched live). The 5B's VAE uses 16x16 spatial / 4x temporal compression and 48 latent channels vs Wan2.1's 8x8/16 — the class this task predicted would be uncertain genuinely is different, and it also requires a `vae` input even for text-only generation. Model filename `Wan2.2-TI2V-5B-Q5_K_M.gguf` confirmed via the HF repo's file listing API (not guessed). VAE `wan2.2_vae.safetensors` and defaults (1280x704, fps 24, cfg 5.0, `uni_pc`/`simple`, length 121) all taken from the official workflow. `VHS_VideoCombine` output stage kept (not the official example's `CreateVideo`/`SaveVideo`) per the plan's explicit instruction to mirror the proven pattern.
- **`ModelSpec`** (`providers.py`): `wan2.2-ti2v-5b`, `text_to_video` only (kept simple — see key-decisions), Apache-2.0, `est_cost=0.0`.
- **Node-pack manifest** (`comfy_nodes.py`): `wan2.2-ti2v-5b` added to both `ComfyUI-VideoHelperSuite` and `ComfyUI-GGUF`'s `needed_for` tuples.

## Multi-path input mapping

`packages/pipeline_core/comfy.py`: `input_mapping_paths(mapping)` normalizes an `inputs` entry (single path = list of strings, multi-path = list of lists) to a list of concrete paths; `inject()`'s existing walk-and-assign body is now driven per-path with no duplicated logic. An unresolvable path raises `ComfyUIError` naming the parameter and the failing path — no shipped template changed in this task; the mechanism lands proven against fixtures, plan 03-02 wires `wan2.2-fun-camera`'s camera-embedding node into it.

## Tests added (39 total in `tests/test_comfy.py`, up from 26)

- `test_signature_driven_audit_passes_the_proven_templates`
- `test_templates_off_the_ratchet_audit_clean` / `test_templates_on_the_ratchet_audit_dirty`
- `test_every_edge_source_class_has_a_signature_entry` (coverage)
- `test_declared_blind_spots_are_visible_and_bounded`
- `test_audit_graph_mutation_guard_output_index_reads_the_signature`
- `test_audit_graph_mutation_guard_required_input_reads_the_signature`
- `test_audit_graph_flags_dangling_edge_reference`
- `test_audit_graph_mutation_guard_reachability_and_inert_param_naming`
- `test_structural_audit_validates_both_single_and_multi_path_mappings`
- `test_inject_backward_compatible_with_single_path_mappings`
- `test_inject_multi_path_patches_both_locations_in_one_call`
- `test_inject_multi_path_unresolvable_path_raises_without_partial_patch`
- `test_inject_required_check_unaffected_by_multi_path_shape`

`pytest tests/test_comfy.py -q -k mutation` selects exactly 3 (renamed to carry "mutation" in the test name, matching the plan's stated verify command literally).

## Task Commits

Each task was committed atomically (Tasks 2 and 3 are `tdd="true"`: RED then GREEN):

1. **Task 1: signature audit + wan2.2-ti2v-5b (tracer)** — `a2af8ff` (feat)
2. **Task 2: full signature coverage + shrink-only ratchet** — `a54375b` (test, RED) → `a3fb05e` (feat, GREEN)
3. **Task 3: multi-path input mapping in inject()** — `50e1909` (test, RED) → `30cede6` (feat, GREEN)

No REFACTOR commits — both TDD tasks landed clean on GREEN.

## Files Created/Modified

- `packages/pipeline_core/workflows/wan2.2-ti2v-5b.json` — new: the dense 5B fallback template
- `packages/pipeline_core/comfy_nodes.py` — `NodeSignature`, `NODE_SIGNATURES` (34 entries), `audit_graph()`, `needed_for` tuple updates
- `packages/pipeline_core/comfy.py` — `input_mapping_paths()`, multi-path-aware `inject()`, docstring
- `packages/pipeline_core/providers.py` — `wan2.2-ti2v-5b` `ModelSpec`
- `tests/test_comfy.py` — `COMFY_MODELS` +1, `AWAITING_REPAIR`, 13 new tests

## Decisions Made

See `key-decisions` in frontmatter.

## Deviations from Plan

### Auto-fixed / Rule-driven

None — no Rule 1/2/3 bugs found in existing code during this plan; all work was net-new (audit machinery, new template, new injector capability).

### Findings beyond the plan's anticipated scope (not auto-fixed — repair is explicitly out of this plan's scope)

**1. ace-step.json is broken — not on this phase's research-time 10-template list**
- **Found during:** Task 2, while fetching `TextEncodeAceStepAudio`'s real signature for coverage
- **Issue:** `comfy_extras/nodes_ace.py::TextEncodeAceStepAudio` declares `lyrics_strength` in its required inputs regardless of its default value (confirmed via `comfy_api/latest/_io.py::add_to_dict_v1` — `optional=False` is the default, and a default value does not imply `optional=True`). `ace-step.json`'s node 6 does not supply it.
- **Action taken:** Added `ace-step` to `AWAITING_REPAIR`. NOT repaired (out of scope — "Do NOT repair the broken templates in this plan").
- **Files modified:** `tests/test_comfy.py` (ratchet membership only)

**2. musetalk-image.json's MuseTalkRun wiring doesn't match the real upstream contract at all**
- **Found during:** Task 2, fetching `chaojie/ComfyUI-MuseTalk`'s actual `nodes.py`
- **Issue:** The real `MuseTalkRun.INPUT_TYPES()["required"]` is `video_path`/`audio_path`/`bbox_shift`/`batch_size` — filesystem path strings. `musetalk-image.json` wires `image`/`audio` as IMAGE/AUDIO graph connections, which share no key names with the real contract except `bbox_shift`. This is a deeper defect than research's "missing VHS fields" finding; musetalk-image was already on the anticipated broken list for that reason, so ratchet membership doesn't change, but the *severity* is understated by the original research.
- **Action taken:** Recorded accurately in `NODE_SIGNATURES` provenance and in this summary. NOT repaired (out of scope).

**3. VHS_LoadVideo has 7 required keys, not the 2 the shipped templates supply**
- **Found during:** Task 2, fetching `videohelpersuite/load_video_nodes.py::LoadVideoUpload`
- **Issue:** `wan2.1-vace-1.3b`, `wan2.2-vace-fun`, and `recammaster` all supply only `video` and `frame_load_cap`; the real required set also includes `force_rate`, `custom_width`, `custom_height`, `skip_first_frames`, `select_every_nth`. All three templates were already on the ratchet for other reasons, so this adds defect detail, not ratchet membership.
- **Action taken:** Recorded in `NODE_SIGNATURES`. NOT repaired (out of scope).

---
**Total deviations:** 0 auto-fixed; 3 findings recorded and left for the designated repair plans (03-02/03-04) or Phase 4 (WanVideoWrapper wiring).
**Impact on plan:** None of these change this plan's own deliverables or tests — they strengthen the ratchet's accuracy, which is exactly what "prove it, don't assume it" was asking for.

## Issues Encountered

None — network access was available for all upstream source fetches (ComfyUI core, ComfyUI-GGUF, ComfyUI-VideoHelperSuite, ComfyUI_Fill-ChatterBox, ComfyUI-MuseTalk, and the official Comfy-Org/workflow_templates repo), so no signature had to be left unverified by necessity rather than by the WanVideoWrapper's genuine M11-era class-name-only precedent.

## Known Stubs

None.

## User Setup Required

None — no external service configuration required. (Real GPU execution of `wan2.2-ti2v-5b` still requires the workstation/rented-GPU bring-up covered by later plans in this phase; this plan's acceptance is CPU-provable structural correctness only, per its own must_haves.)

## Next Phase Readiness

- Plans 03-02 and 03-04 have a precise, source-verified 11-item repair list (`AWAITING_REPAIR`) with per-template defect classes already enumerated in this summary — they no longer need to rediscover what's broken, only fix it and shrink the list.
- `wan2.2-ti2v-5b` exists end to end (ModelSpec → template → manifest → test roster) so M10.6's benchmark has two real arms; only real hardware execution remains, out of this plan's CPU-only scope.
- `input_mapping_paths()`/multi-path `inject()` is proven and ready for plan 03-02 to wire `wan2.2-fun-camera`'s camera-embedding node into it.
- musetalk-image's MuseTalkRun mismatch is more severe than research assumed — whichever plan repairs musetalk-image should budget for a real re-wire (path-based upload flow), not a small patch.

---
*Phase: 03-wan-lane-bring-up*
*Completed: 2026-08-02*

## Self-Check: PASSED

All 5 created/modified files confirmed present on disk; all 5 commit hashes (`a2af8ff`, `a54375b`, `a3fb05e`, `50e1909`, `30cede6`) confirmed in `git log`.
