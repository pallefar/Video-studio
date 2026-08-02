"""ComfyUI custom-node packs the studio's workflow templates rely on.

Registry-as-data, like presets/styles/effects: each pack records its repo,
licence, the node class types it provides, and which workflow templates need
it. `scripts/install_comfyui.sh` clones this exact list (a drift test keeps
the two in sync) and `GET /config/comfy` diffs the running ComfyUI's
/object_info against the templates so Settings can say precisely which pack
is missing.

Licence note: ComfyUI itself is GPL-3.0 and so are some node packs. That is
fine HERE and only here — ComfyUI is a sidecar service the studio talks to
over HTTP (the same subprocess-isolation reasoning as audiowaveform in
roadmap-v2 §4); nothing from it is ever linked into the studio's process.
The MIT/Apache-only rule in CLAUDE.md governs model weights and studio
dependencies, not the sidecar's own plugin ecosystem.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources


@dataclass(frozen=True)
class NodePack:
    name: str
    repo: str
    license: str
    # Node class types this pack provides that our templates reference (also
    # used as presence probes against /object_info).
    provides: tuple[str, ...]
    # Workflow template models that break without it.
    needed_for: tuple[str, ...]
    notes: str = ""
    # Optional packs aren't referenced by any shipped template but are part
    # of the workstation roster (advanced Wan workflows, M11).
    optional: bool = False


NODE_PACKS: tuple[NodePack, ...] = (
    NodePack(
        name="ComfyUI-VideoHelperSuite",
        repo="https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite",
        license="GPL-3.0 (sidecar-only)",
        provides=("VHS_VideoCombine", "VHS_LoadVideo"),
        needed_for=(
            "wan2.2-t2v", "wan2.2-i2v", "wan2.2-fun-camera", "wan2.2-vace-fun",
            "wan2.1-vace-1.3b", "wan2.1-t2v-1.3b", "wan2.2-ti2v-5b",
            "musetalk-image", "uni3c", "recammaster",
        ),
        notes="video load/combine nodes — every video template's output stage",
    ),
    NodePack(
        name="ComfyUI-GGUF",
        repo="https://github.com/city96/ComfyUI-GGUF",
        license="Apache-2.0",
        provides=("UnetLoaderGGUF", "CLIPLoaderGGUF"),
        needed_for=(
            "wan2.2-t2v", "wan2.2-i2v", "wan2.2-fun-camera", "wan2.2-vace-fun",
            "wan2.1-vace-1.3b", "wan2.1-t2v-1.3b", "wan2.2-ti2v-5b",
            "qwen-image",
        ),
        notes="GGUF quantised checkpoint loaders — the sm_86 answer to FP8",
    ),
    NodePack(
        name="ComfyUI-MuseTalk",
        repo="https://github.com/chaojie/ComfyUI-MuseTalk",
        license="MIT",
        provides=("MuseTalkRun",),
        needed_for=("musetalk-image",),
        notes="talking/singing photo lipsync (M28)",
    ),
    NodePack(
        name="ComfyUI_Fill-ChatterBox",
        repo="https://github.com/filliptm/ComfyUI_Fill-ChatterBox",
        license="MIT",
        provides=("FL_ChatterboxTTS", "FL_ChatterboxVC"),
        needed_for=("chatterbox",),
        notes="Chatterbox TTS/voice-conversion nodes (node names verified "
              "against the installed pack's /object_info)",
    ),
    NodePack(
        name="ComfyUI-WanVideoWrapper",
        repo="https://github.com/kijai/ComfyUI-WanVideoWrapper",
        license="Apache-2.0",
        provides=(
            "WanVideoSampler", "WanVideoModelLoader", "WanVideoVAELoader",
            "WanVideoTextEncode", "WanVideoDecode", "WanVideoImageToVideoEncode",
            "WanVideoUni3C_ControlnetLoader", "WanVideoUni3C_embeds",
            "WanVideoReCamMasterCameraEmbed",
        ),
        needed_for=("uni3c", "recammaster"),
        notes="advanced Wan workflows: Uni3C trajectories, ReCamMaster (M11) — "
              "node names schema-verified against the installed pack's "
              "/object_info on the workstation, like chatterbox (M29)",
    ),
    NodePack(
        name="ComfyUI-KJNodes",
        repo="https://github.com/kijai/ComfyUI-KJNodes",
        license="GPL-3.0 (sidecar-only)",
        provides=("ImageResizeKJ",),
        needed_for=(),
        notes="helper nodes most community Wan workflows assume",
        optional=True,
    ),
)

# ACE-Step, the Wan camera embedding, and every Load/Save/KSampler node are
# ComfyUI core — no pack needed. Recorded so nobody goes hunting for one.
CORE_NODE_NOTES = (
    "ACE-Step (TextEncodeAceStepAudio, EmptyAceStepLatentAudio) and "
    "WanCameraEmbedding ship with ComfyUI core — no custom pack required."
)


@dataclass(frozen=True)
class NodeSignature:
    """A node class's I/O contract, copied verbatim from the pack's own
    source — never inferred by analogy. `CheckpointLoaderSimple` genuinely
    returns three values (MODEL, CLIP, VAE); `UnetLoaderGGUF` returns one.
    Only reading the source tells you which; guessing from a "standard"
    three-output pattern is the exact root cause `audit_graph` exists to
    catch (six shipped templates wire clip/vae from a GGUF loader's output
    indices 1 and 2, and it has neither).

    `outputs` and `required_inputs` are nullable. Null means "not verified
    from source yet" — that nullability is what lets this registry be
    honest about node classes nobody has read the source of (the
    WanVideoWrapper classes uni3c/recammaster use, M11) instead of
    pretending to knowledge it does not have. `audit_graph`'s output-index
    and required-input checks silently skip a node whose relevant field is
    null; its coverage check does NOT flag a null entry as missing — a
    declared blind spot is a different, smaller defect than an undeclared
    one.
    """

    outputs: tuple[str, ...] | None
    required_inputs: tuple[str, ...] | None
    provenance: str


NODE_SIGNATURES: dict[str, NodeSignature] = {
    # --- ComfyUI-GGUF (city96) -----------------------------------------
    # Both loaders return exactly ONE output each. This is the fact six
    # shipped templates violate: wan2.2-t2v/i2v/fun-camera/vace-fun,
    # wan2.1-vace-1.3b and qwen-image all wire `clip` from output index 1
    # and `vae` from output index 2 of the UnetLoaderGGUF node — a node
    # that has neither.
    "UnetLoaderGGUF": NodeSignature(
        outputs=("MODEL",),
        required_inputs=("unet_name",),
        provenance=(
            "city96/ComfyUI-GGUF nodes.py::UnetLoaderGGUF (fetched "
            "2026-08-02, main branch) — RETURN_TYPES = ('MODEL',); "
            "INPUT_TYPES()['required'] = {'unet_name': ...}. Every shipped "
            "template currently passes 'ckpt_name' to this node, not "
            "'unet_name' — a second, independent wiring defect this "
            "signature's required-input check surfaces on its own."
        ),
    ),
    "CLIPLoaderGGUF": NodeSignature(
        outputs=("CLIP",),
        required_inputs=("clip_name", "type"),
        provenance=(
            "city96/ComfyUI-GGUF nodes.py::CLIPLoaderGGUF (fetched "
            "2026-08-02, main branch) — RETURN_TYPES = ('CLIP',)."
        ),
    ),
    # --- ComfyUI core: loaders, sampling, latents -----------------------
    "UNETLoader": NodeSignature(
        outputs=("MODEL",),
        required_inputs=("unet_name", "weight_dtype"),
        provenance=(
            "comfyanonymous/ComfyUI nodes.py::UNETLoader (fetched "
            "2026-08-02, master branch)."
        ),
    ),
    "VAELoader": NodeSignature(
        outputs=("VAE",),
        required_inputs=("vae_name",),
        provenance=(
            "comfyanonymous/ComfyUI nodes.py::VAELoader (fetched "
            "2026-08-02, master branch)."
        ),
    ),
    "ModelSamplingSD3": NodeSignature(
        outputs=("MODEL",),
        required_inputs=("model", "shift"),
        provenance=(
            "comfyanonymous/ComfyUI comfy_extras/nodes_model_advanced.py::"
            "ModelSamplingSD3 (fetched 2026-08-02, master branch)."
        ),
    ),
    "CLIPTextEncode": NodeSignature(
        outputs=("CONDITIONING",),
        required_inputs=("text", "clip"),
        provenance=(
            "comfyanonymous/ComfyUI nodes.py::CLIPTextEncode (fetched "
            "2026-08-02, master branch)."
        ),
    ),
    "EmptyHunyuanLatentVideo": NodeSignature(
        outputs=("LATENT",),
        required_inputs=("width", "height", "length", "batch_size"),
        provenance=(
            "comfyanonymous/ComfyUI comfy_extras/nodes_hunyuan.py::"
            "EmptyHunyuanLatentVideo (fetched 2026-08-02, master branch) — "
            "the Wan2.1-class latent (8x8 spatial / 4x temporal "
            "compression, 16 channels), reused by Wan because it shares "
            "Hunyuan's latent format. NOT correct for Wan2.2 TI2V-5B — see "
            "Wan22ImageToVideoLatent below."
        ),
    ),
    "Wan22ImageToVideoLatent": NodeSignature(
        outputs=("LATENT",),
        required_inputs=("vae", "width", "height", "length", "batch_size"),
        provenance=(
            "comfyanonymous/ComfyUI comfy_extras/nodes_wan.py::"
            "Wan22ImageToVideoLatent (fetched 2026-08-02, master branch) — "
            "the TI2V-5B empty-latent node: 16x16 spatial / 4x temporal "
            "compression, 48 channels (vs EmptyHunyuanLatentVideo's 8x8/16 "
            "channels for Wan2.1). Confirmed against the official "
            "ComfyUI-shipped 5B workflow template, "
            "Comfy-Org/workflow_templates:templates/"
            "video_wan2_2_5B_ti2v.json (fetched 2026-08-02), which wires "
            "this exact node with width=1280, height=704, length=121. "
            "Requires a `vae` input even for text-only generation — the "
            "class needs it to build the correct latent format, not just "
            "for an optional start_image."
        ),
    ),
    "KSampler": NodeSignature(
        outputs=("LATENT",),
        required_inputs=(
            "model", "seed", "steps", "cfg", "sampler_name", "scheduler",
            "positive", "negative", "latent_image", "denoise",
        ),
        provenance=(
            "comfyanonymous/ComfyUI nodes.py::KSampler (fetched "
            "2026-08-02, master branch)."
        ),
    ),
    "VAEDecode": NodeSignature(
        outputs=("IMAGE",),
        required_inputs=("samples", "vae"),
        provenance=(
            "comfyanonymous/ComfyUI nodes.py::VAEDecode (fetched "
            "2026-08-02, master branch)."
        ),
    ),
    # --- ComfyUI-VideoHelperSuite (Kosinkadink) -------------------------
    # The three fields six shipped templates omit, even though ComfyUI's
    # /prompt validation checks INPUT_TYPES()['required'] against the
    # submitted graph — not against these fields' client-side defaults.
    "VHS_VideoCombine": NodeSignature(
        outputs=("VHS_FILENAMES",),
        required_inputs=(
            "images", "frame_rate", "loop_count", "filename_prefix",
            "format", "pingpong", "save_output",
        ),
        provenance=(
            "Kosinkadink/ComfyUI-VideoHelperSuite "
            "videohelpersuite/nodes.py::VideoCombine (fetched 2026-08-02, "
            "main branch; NODE_CLASS_MAPPINGS['VHS_VideoCombine'] = "
            "VideoCombine)."
        ),
    ),
    "VHS_LoadVideo": NodeSignature(
        outputs=("IMAGE", "INT", "AUDIO", "VHS_VIDEOINFO"),
        required_inputs=(
            "video", "force_rate", "custom_width", "custom_height",
            "frame_load_cap", "skip_first_frames", "select_every_nth",
        ),
        provenance=(
            "Kosinkadink/ComfyUI-VideoHelperSuite "
            "videohelpersuite/load_video_nodes.py::LoadVideoUpload (fetched "
            "2026-08-02, main branch; NODE_CLASS_MAPPINGS['VHS_LoadVideo'] "
            "= LoadVideoUpload). Five more required keys than the two "
            "shipped templates using this node supply — a second, "
            "independent defect on wan2.1-vace-1.3b/wan2.2-vace-fun "
            "(already on AWAITING_REPAIR for the orphan-node defect) and "
            "on recammaster (already on it for VHS_VideoCombine's missing "
            "fields)."
        ),
    ),
    # --- ComfyUI core: image/audio load-save, checkpoints, LoRA --------
    "CheckpointLoaderSimple": NodeSignature(
        outputs=("MODEL", "CLIP", "VAE"),
        required_inputs=("ckpt_name",),
        provenance=(
            "comfyanonymous/ComfyUI nodes.py::CheckpointLoaderSimple "
            "(fetched 2026-08-02, master branch) — genuinely 3 outputs, "
            "the pattern UnetLoaderGGUF is NOT (research Anti-Patterns: "
            "'never assume by analogy')."
        ),
    ),
    "LoraLoader": NodeSignature(
        outputs=("MODEL", "CLIP"),
        required_inputs=("model", "clip", "lora_name", "strength_model", "strength_clip"),
        provenance=(
            "comfyanonymous/ComfyUI nodes.py::LoraLoader (fetched "
            "2026-08-02, master branch). Never the source of an edge in "
            "sdxl.json — that IS the defect (see AWAITING_REPAIR)."
        ),
    ),
    "EmptyLatentImage": NodeSignature(
        outputs=("LATENT",),
        required_inputs=("width", "height", "batch_size"),
        provenance=(
            "comfyanonymous/ComfyUI nodes.py::EmptyLatentImage (fetched "
            "2026-08-02, master branch)."
        ),
    ),
    "SaveImage": NodeSignature(
        outputs=("IMAGE",),
        required_inputs=("images", "filename_prefix"),
        provenance=(
            "comfyanonymous/ComfyUI nodes.py::SaveImage (fetched "
            "2026-08-02, master branch)."
        ),
    ),
    "LoadImage": NodeSignature(
        outputs=("IMAGE", "MASK"),
        required_inputs=("image",),
        provenance=(
            "comfyanonymous/ComfyUI nodes.py::LoadImage (fetched "
            "2026-08-02, master branch)."
        ),
    ),
    "LoadAudio": NodeSignature(
        outputs=("AUDIO",),
        required_inputs=("audio",),
        provenance=(
            "comfyanonymous/ComfyUI comfy_extras/nodes_audio.py::LoadAudio "
            "(fetched 2026-08-02, master branch) — newer schema-based "
            "IO.ComfyNode API; legacy required-bucket membership confirmed "
            "via comfy_api/latest/_io.py::add_to_dict_v1 "
            "('optional' if i.optional else 'required' — a default value "
            "never makes a field optional on its own)."
        ),
    ),
    "SaveAudio": NodeSignature(
        outputs=("AUDIO",),
        required_inputs=("audio", "filename_prefix"),
        provenance=(
            "comfyanonymous/ComfyUI comfy_extras/nodes_audio.py::SaveAudio "
            "(fetched 2026-08-02, master branch)."
        ),
    ),
    "VAEDecodeAudio": NodeSignature(
        outputs=("AUDIO",),
        required_inputs=("samples", "vae"),
        provenance=(
            "comfyanonymous/ComfyUI comfy_extras/nodes_audio.py::"
            "VAEDecodeAudio (fetched 2026-08-02, master branch)."
        ),
    ),
    # --- ComfyUI core: ACE-Step (audio, M18) ----------------------------
    "TextEncodeAceStepAudio": NodeSignature(
        outputs=("CONDITIONING",),
        required_inputs=("clip", "tags", "lyrics", "lyrics_strength"),
        provenance=(
            "comfyanonymous/ComfyUI comfy_extras/nodes_ace.py::"
            "TextEncodeAceStepAudio (fetched 2026-08-02, master branch) — "
            "schema-based IO.ComfyNode; `lyrics_strength` has a default "
            "(1.0) but is NOT marked optional=True, so it lands in the "
            "legacy required bucket regardless (same "
            "comfy_api/latest/_io.py rule as LoadAudio above). "
            "ace-step.json's node 6 does not supply it — a real, "
            "independently-discovered defect (see AWAITING_REPAIR)."
        ),
    ),
    "EmptyAceStepLatentAudio": NodeSignature(
        outputs=("LATENT",),
        required_inputs=("seconds", "batch_size"),
        provenance=(
            "comfyanonymous/ComfyUI comfy_extras/nodes_ace.py::"
            "EmptyAceStepLatentAudio (fetched 2026-08-02, master branch)."
        ),
    ),
    # --- ComfyUI core: camera embedding ---------------------------------
    "WanCameraEmbedding": NodeSignature(
        outputs=("WAN_CAMERA_EMBEDDING", "INT", "INT", "INT"),
        required_inputs=("camera_pose", "width", "height", "length"),
        provenance=(
            "comfyanonymous/ComfyUI comfy_extras/nodes_camera_trajectory.py"
            "::WanCameraEmbedding (fetched 2026-08-02, master branch) — "
            "ships with ComfyUI core, no custom pack required "
            "(CORE_NODE_NOTES above). Not an edge source in "
            "wan2.2-fun-camera.json — that IS the orphan-node defect (see "
            "AWAITING_REPAIR)."
        ),
    ),
    # --- ComfyUI_Fill-ChatterBox (filliptm) -----------------------------
    "FL_ChatterboxTTS": NodeSignature(
        outputs=("AUDIO", "STRING"),
        required_inputs=("text", "exaggeration", "cfg_weight", "temperature", "seed"),
        provenance=(
            "filliptm/ComfyUI_Fill-ChatterBox chatterbox_node.py::"
            "FL_ChatterboxTTSNode (fetched 2026-08-02, main branch; "
            "NODE_CLASS_MAPPINGS['FL_ChatterboxTTS'] = "
            "FL_ChatterboxTTSNode). chatterbox.json wires this correctly — "
            "confirmed, not assumed, unlike the manifest's own "
            "'node names verified' caveat for this pack (comfy_nodes.py "
            "NodePack.notes)."
        ),
    ),
    # --- ComfyUI-MuseTalk (chaojie) --------------------------------------
    "MuseTalkRun": NodeSignature(
        outputs=("IMAGE",),
        required_inputs=("video_path", "audio_path", "bbox_shift", "batch_size"),
        provenance=(
            "chaojie/ComfyUI-MuseTalk nodes.py::MuseTalkRun (fetched "
            "2026-08-02, main branch). SURPRISING: the real upstream "
            "signature takes filesystem PATH STRINGS (video_path, "
            "audio_path), not IMAGE/AUDIO graph connections — "
            "musetalk-image.json wires `image`/`audio`/`seed`/`fps` "
            "instead, none of which match this contract except "
            "`bbox_shift`. A wiring mismatch this audit's required-input "
            "check now catches (see AWAITING_REPAIR), found only by "
            "reading the source — the node-pack manifest's class-name "
            "probe cannot see it."
        ),
    ),
    # --- ComfyUI-WanVideoWrapper (kijai) — DECLARED BLIND SPOT ----------
    # The manifest's own notes (NODE_PACKS above) already record that only
    # these classes' NAMES were schema-verified against a running
    # ComfyUI's /object_info on the workstation (M11) — never their I/O
    # wiring. Research Pitfall 4 names this explicitly: class-type
    # existence and input-wiring correctness are two different failure
    # modes, and only the first was checked for uni3c.json/recammaster.json.
    # Recording these as unverified (outputs=None, required_inputs=None)
    # means audit_graph's output-index and required-input checks correctly
    # skip them instead of guessing — and its coverage check does NOT flag
    # them as missing, because a declared blind spot is not the same
    # defect as an undeclared one. Phase 4 owns re-verifying this wiring
    # against real hardware (roadmap Phase 4).
    "WanVideoModelLoader": NodeSignature(
        outputs=None, required_inputs=None,
        provenance=(
            "kijai/ComfyUI-WanVideoWrapper — class name only, "
            "schema-verified against the installed pack's /object_info on "
            "the workstation (M11); full I/O signature not verified from "
            "source. Phase 4 owns verifying uni3c/recammaster wiring on "
            "hardware."
        ),
    ),
    "WanVideoVAELoader": NodeSignature(
        outputs=None, required_inputs=None,
        provenance=(
            "kijai/ComfyUI-WanVideoWrapper — class name only, "
            "schema-verified against the installed pack's /object_info on "
            "the workstation (M11); full I/O signature not verified from "
            "source. Phase 4 owns verifying uni3c/recammaster wiring on "
            "hardware."
        ),
    ),
    "WanVideoTextEncode": NodeSignature(
        outputs=None, required_inputs=None,
        provenance=(
            "kijai/ComfyUI-WanVideoWrapper — class name only, "
            "schema-verified against the installed pack's /object_info on "
            "the workstation (M11); full I/O signature not verified from "
            "source. Phase 4 owns verifying uni3c/recammaster wiring on "
            "hardware."
        ),
    ),
    "WanVideoDecode": NodeSignature(
        outputs=None, required_inputs=None,
        provenance=(
            "kijai/ComfyUI-WanVideoWrapper — class name only, "
            "schema-verified against the installed pack's /object_info on "
            "the workstation (M11); full I/O signature not verified from "
            "source. Phase 4 owns verifying uni3c/recammaster wiring on "
            "hardware."
        ),
    ),
    "WanVideoImageToVideoEncode": NodeSignature(
        outputs=None, required_inputs=None,
        provenance=(
            "kijai/ComfyUI-WanVideoWrapper — class name only, "
            "schema-verified against the installed pack's /object_info on "
            "the workstation (M11); full I/O signature not verified from "
            "source. Phase 4 owns verifying uni3c/recammaster wiring on "
            "hardware."
        ),
    ),
    "WanVideoUni3C_ControlnetLoader": NodeSignature(
        outputs=None, required_inputs=None,
        provenance=(
            "kijai/ComfyUI-WanVideoWrapper — class name only, "
            "schema-verified against the installed pack's /object_info on "
            "the workstation (M11); full I/O signature not verified from "
            "source. Phase 4 owns verifying uni3c/recammaster wiring on "
            "hardware."
        ),
    ),
    "WanVideoUni3C_embeds": NodeSignature(
        outputs=None, required_inputs=None,
        provenance=(
            "kijai/ComfyUI-WanVideoWrapper — class name only, "
            "schema-verified against the installed pack's /object_info on "
            "the workstation (M11); full I/O signature not verified from "
            "source. Phase 4 owns verifying uni3c/recammaster wiring on "
            "hardware."
        ),
    ),
    "WanVideoSampler": NodeSignature(
        outputs=None, required_inputs=None,
        provenance=(
            "kijai/ComfyUI-WanVideoWrapper — class name only, "
            "schema-verified against the installed pack's /object_info on "
            "the workstation (M11); full I/O signature not verified from "
            "source. Phase 4 owns verifying uni3c/recammaster wiring on "
            "hardware."
        ),
    ),
    "WanVideoReCamMasterCameraEmbed": NodeSignature(
        outputs=None, required_inputs=None,
        provenance=(
            "kijai/ComfyUI-WanVideoWrapper — class name only, "
            "schema-verified against the installed pack's /object_info on "
            "the workstation (M11); full I/O signature not verified from "
            "source. Phase 4 owns verifying uni3c/recammaster wiring on "
            "hardware."
        ),
    ),
}


def audit_graph(
    graph: dict,
    signatures: dict[str, NodeSignature] | None = None,
    output_node: str | None = None,
    template_inputs: dict | None = None,
) -> list[str]:
    """Structural audit of a ComfyUI API-format graph against recorded node
    signatures. Returns a list of human-readable defect strings, empty when
    the graph is sound.

    Four structural checks plus a reachability sweep, closing the blind
    spots `test_every_model_has_a_structurally_valid_template` has always
    had (it only checks that `inputs` paths resolve inside the graph, never
    that a referenced OUTPUT index exists, never that a node's declared
    `required` inputs are present, never that a node is reachable):

      1. Edge target exists: a dangling `[node_id, index]` reference is a
         defect.
      2. Output index in bounds: when the edge's source node's class has a
         recorded (verified) output tuple, the index must be within it —
         this is the check that catches a `clip`/`vae` edge taken from
         output index 1/2 of a GGUF loader that has exactly one output.
      3. Required inputs present: when a node's class has a recorded
         (verified) required-key tuple, every key must be present in the
         node's own `inputs` dict — this is the check that catches the
         missing VHS_VideoCombine fields and a wrong loader key name.
      4. Signature coverage: any class type used as the SOURCE of an edge
         with no entry at all in `signatures` is itself a defect — the
         audit is blind to it. A declared-unverified entry (outputs=None)
         is NOT a coverage defect; it is a declared blind spot.
      5. Reachability: walking edges backwards from `output_node`, any node
         outside the resulting closure is unreachable — nothing it computes
         can influence the result, so any value patched into it is
         discarded. Skipped when `output_node` is not supplied. When
         `template_inputs` (the template's own `{param: [node_id, ...]}`
         map) is supplied, the message also names the studio parameter that
         is thereby inert — the sentence a reader actually needs.

    `signatures` defaults to the module's `NODE_SIGNATURES` but is a real
    parameter (not baked in), so a test can drive this function with a
    deliberately wrong mapping and prove the audit reads the recorded
    signature rather than hardcoding a class name.
    """
    if signatures is None:
        signatures = NODE_SIGNATURES
    defects: list[str] = []

    def _is_edge(value) -> bool:
        return (
            isinstance(value, list)
            and len(value) == 2
            and isinstance(value[0], str)
        )

    edge_source_types: set[str] = set()

    for node_id, node in graph.items():
        class_type = node.get("class_type")
        inputs = node.get("inputs", {}) or {}
        sig = signatures.get(class_type)

        for field, value in inputs.items():
            if not _is_edge(value):
                continue
            src_id, out_idx = value
            if src_id not in graph:
                defects.append(
                    f"node {node_id} ({class_type}) input {field!r} "
                    f"references node {src_id!r}, which does not exist in "
                    f"the graph"
                )
                continue
            src_class = graph[src_id].get("class_type")
            edge_source_types.add(src_class)
            src_sig = signatures.get(src_class)
            if src_sig is not None and src_sig.outputs is not None:
                if not isinstance(out_idx, int) or not (0 <= out_idx < len(src_sig.outputs)):
                    defects.append(
                        f"node {node_id} ({class_type}) input {field!r} "
                        f"reads output index {out_idx} of node {src_id} "
                        f"({src_class}), which has {len(src_sig.outputs)} "
                        f"output(s): {src_sig.outputs}"
                    )

        if sig is not None and sig.required_inputs is not None:
            missing = [key for key in sig.required_inputs if key not in inputs]
            if missing:
                defects.append(
                    f"node {node_id} ({class_type}) is missing required "
                    f"input(s) {missing} — the class declares required: "
                    f"{sig.required_inputs}"
                )

    for class_type in sorted(edge_source_types):
        if class_type not in signatures:
            defects.append(
                f"{class_type} is used as the source of an edge but has no "
                f"entry in NODE_SIGNATURES — the audit is blind to its "
                f"output count and required inputs"
            )

    if output_node is not None and output_node in graph:
        reachable: set[str] = set()
        stack = [output_node]
        while stack:
            node_id = stack.pop()
            if node_id in reachable or node_id not in graph:
                continue
            reachable.add(node_id)
            for value in (graph[node_id].get("inputs", {}) or {}).values():
                if _is_edge(value) and value[0] in graph:
                    stack.append(value[0])

        def _inert_param(node_id: str) -> str | None:
            if not template_inputs:
                return None
            for param, path in template_inputs.items():
                if path and path[0] == node_id:
                    return param
            return None

        for node_id, node in graph.items():
            if node_id in reachable:
                continue
            class_type = node.get("class_type")
            inert_param = _inert_param(node_id)
            if inert_param is not None:
                defects.append(
                    f"node {node_id} ({class_type}) is unreachable from "
                    f"output node {output_node} — nothing consumes its "
                    f"result, so the studio parameter {inert_param!r} "
                    f"patched into it is silently discarded"
                )
            else:
                defects.append(
                    f"node {node_id} ({class_type}) is unreachable from "
                    f"output node {output_node} — nothing consumes its "
                    f"result, so any value patched into it is discarded"
                )

    return defects


def template_node_types() -> dict[str, set[str]]:
    """Node class types referenced by every shipped workflow template."""
    out: dict[str, set[str]] = {}
    workflows = resources.files("pipeline_core") / "workflows"
    for entry in workflows.iterdir():
        if not entry.name.endswith(".json"):
            continue
        template = json.loads(entry.read_text())
        out[entry.name.removesuffix(".json")] = {
            node["class_type"]
            for node in template.get("graph", {}).values()
            if node.get("class_type")
        }
    return out


def pack_for_type(class_type: str) -> NodePack | None:
    for pack in NODE_PACKS:
        if class_type in pack.provides:
            return pack
    return None


def missing_node_types(available: set[str]) -> list[dict]:
    """Diff template requirements against a running ComfyUI's /object_info.

    Returns one entry per missing node class type, with the pack that
    provides it (when known) and the templates that break without it."""
    missing: dict[str, list[str]] = {}
    for model, types in sorted(template_node_types().items()):
        for class_type in types - available:
            missing.setdefault(class_type, []).append(model)
    return [
        {
            "type": class_type,
            "models": sorted(models),
            "pack": pack.name if (pack := pack_for_type(class_type)) else None,
            "repo": pack.repo if pack else None,
        }
        for class_type, models in sorted(missing.items())
    ]


def pack_status(available: set[str]) -> list[dict]:
    """Installed/missing per pack, probed by its provided node types."""
    return [
        {
            "name": pack.name,
            "license": pack.license,
            "optional": pack.optional,
            "installed": any(t in available for t in pack.provides),
        }
        for pack in NODE_PACKS
    ]
