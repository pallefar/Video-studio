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
            "wan2.1-vace-1.3b", "musetalk-image",
        ),
        notes="video load/combine nodes — every video template's output stage",
    ),
    NodePack(
        name="ComfyUI-GGUF",
        repo="https://github.com/city96/ComfyUI-GGUF",
        license="Apache-2.0",
        provides=("UnetLoaderGGUF",),
        needed_for=(
            "wan2.2-t2v", "wan2.2-i2v", "wan2.2-fun-camera", "wan2.2-vace-fun",
            "wan2.1-vace-1.3b", "qwen-image",
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
        provides=("WanVideoSampler", "WanVideoModelLoader"),
        needed_for=(),
        notes="advanced Wan workflows: Uni3C trajectories, ReCamMaster (M11)",
        optional=True,
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
