"""Camera preset registry (M11) — the Higgsfield signature, as data.

Preset-first UX: the user picks a move (or stacks up to three), drops in a
subject, and generates. Tuning presets is content work, not code work — this
registry is the merchandising surface.

Structural rule: a preset whose LoRA is not licence-audited cannot generate.
Civitai LoRAs carry individual licences; each is audited for commercial use
before `license_audited` may be set true.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from schema.models import CameraPresetRead, GenerationKind

MAX_STACK = 3

# Advanced mode (M11): custom trajectories via Uni3C (Apache 2.0) and
# re-shooting existing footage via ReCamMaster (MIT) — both through the
# WanVideoWrapper templates on the wan lane.
UNI3C_MODEL = "uni3c"
RECAM_MODEL = "recammaster"
MIN_TRAJECTORY_POINTS = 2
MAX_TRAJECTORY_POINTS = 16
RESHOOT_SUBJECT = "the original footage"


class PresetError(Exception):
    pass


def _preset(
    id: str,
    label: str,
    description: str,
    category: str,
    motion_code: str,
    prompt_template: str,
    stackable: bool = True,
) -> CameraPresetRead:
    return CameraPresetRead(
        id=id,
        label=label,
        description=description,
        category=category,
        motion_code=motion_code,
        prompt_template=prompt_template,
        stackable=stackable,
    )


# Motion codes follow the Wan2.2 Fun-Camera control vocabulary; templates are
# tuned iteratively on the workstation once the local executor lands.
CAMERA_PRESETS: list[CameraPresetRead] = [
    _preset("zoom_in", "Zoom In", "Slow push toward the subject.", "zoom", "Zoom In",
            "slow smooth zoom in toward {subject}, cinematic, steady"),
    _preset("zoom_out", "Zoom Out", "Pull back to reveal the scene.", "zoom", "Zoom Out",
            "slow zoom out revealing the scene around {subject}, cinematic"),
    _preset("crash_zoom_in", "Crash Zoom", "Aggressive, fast punch-in.", "zoom", "Zoom In",
            "rapid crash zoom punching in on {subject}, dramatic, high energy"),
    _preset("dolly_in", "Dolly In", "Camera physically tracks forward.", "dolly", "Pan Up",
            "camera dollies forward toward {subject}, shallow depth of field, cinematic"),
    _preset("dolly_zoom", "Dolly Zoom", "Vertigo shot — background stretches.", "dolly", "Zoom Out",
            "dolly zoom vertigo effect on {subject}, background warping away, hitchcock shot",
            stackable=False),
    _preset("orbit_360", "360 Orbit", "Full circle around the subject.", "orbit", "Pan Left",
            "camera orbits 360 degrees around {subject}, smooth arc, centered"),
    _preset("arc_right", "Arc Right", "Half-moon sweep to the right.", "orbit", "Pan Right",
            "camera arcs right around {subject} in a smooth half-moon curve, cinematic"),
    _preset("pan_left", "Pan Left", "Level sweep across the scene.", "pan", "Pan Left",
            "smooth pan left across the scene past {subject}"),
    _preset("whip_pan", "Whip Pan", "Blur-fast transition pan.", "pan", "Pan Right",
            "fast whip pan with motion blur across {subject}, energetic"),
    _preset("tilt_up", "Tilt Up", "Rise from ground to subject.", "tilt", "Tilt Up",
            "camera tilts up from the ground to reveal {subject}, imposing"),
    _preset("crane_up", "Crane Up", "Lift up and over the scene.", "crane", "Tilt Up",
            "crane shot rising above {subject}, establishing, sweeping"),
    _preset("fpv_drone", "FPV Drone", "Fast, banking drone flythrough.", "drone", "Zoom In",
            "fpv drone shot diving and banking toward {subject}, fast, immersive"),
    _preset("handheld", "Handheld", "Documentary shake and drift.", "style", "Static",
            "handheld camera with natural shake following {subject}, documentary feel"),
    _preset("bullet_time", "Bullet Time", "Frozen moment, sweeping camera.", "style", "Pan Left",
            "bullet time effect, {subject} frozen mid-motion while the camera sweeps around",
            stackable=False),
    _preset("hyperlapse", "Hyperlapse", "Time compressed, camera moving.", "style", "Zoom In",
            "hyperlapse moving toward {subject}, streaking clouds and light trails"),
    _preset("static", "Locked Off", "No camera motion, subject moves.", "style", "Static",
            "locked off static shot of {subject}, tripod, composed framing"),
]

_BY_ID = {preset.id: preset for preset in CAMERA_PRESETS}


def get_preset(preset_id: str) -> CameraPresetRead:
    preset = _BY_ID.get(preset_id)
    if preset is None:
        raise PresetError(f"unknown preset {preset_id!r}")
    return preset


def validate_stack(preset_ids: list[str]) -> list[CameraPresetRead]:
    if not preset_ids:
        raise PresetError("pick at least one preset")
    if len(preset_ids) > MAX_STACK:
        raise PresetError(f"at most {MAX_STACK} presets can be stacked")
    if len(set(preset_ids)) != len(preset_ids):
        raise PresetError("duplicate presets in stack")
    presets = [get_preset(pid) for pid in preset_ids]
    if len(presets) > 1:
        unstackable = [p.id for p in presets if not p.stackable]
        if unstackable:
            raise PresetError(f"presets not stackable: {unstackable}")
    for preset in presets:
        for lora in preset.loras:
            if not lora.license_audited:
                raise PresetError(
                    f"preset {preset.id!r} uses LoRA {lora.name!r} whose licence "
                    "is not audited for commercial use"
                )
    return presets


def compose(presets: list[CameraPresetRead], subject: str) -> tuple[str, dict]:
    """Build the generation prompt and Fun-Camera params from a preset stack."""
    clauses = [preset.prompt_template.format(subject=subject) for preset in presets]
    prompt = ". ".join(clauses)
    params = {
        "camera_motion": [preset.motion_code for preset in presets],
        "presets": [preset.id for preset in presets],
    }
    return prompt, params


def kind_for(image_uri: str | None) -> GenerationKind:
    return GenerationKind.image_to_video if image_uri else GenerationKind.text_to_video


# ---------------------------------------------------------------------------
# Advanced mode (M11): Uni3C trajectories + ReCamMaster re-shoot
# ---------------------------------------------------------------------------


class TrajectoryPoint(BaseModel):
    """One camera waypoint on a Uni3C trajectory. Position offsets are in
    scene units relative to the start pose; angles in degrees; zoom is a
    focal multiplier."""

    x: float = Field(default=0.0, ge=-10.0, le=10.0)
    y: float = Field(default=0.0, ge=-10.0, le=10.0)
    z: float = Field(default=0.0, ge=-10.0, le=10.0)
    pan: float = Field(default=0.0, ge=-180.0, le=180.0)
    tilt: float = Field(default=0.0, ge=-90.0, le=90.0)
    roll: float = Field(default=0.0, ge=-180.0, le=180.0)
    zoom: float = Field(default=1.0, ge=0.2, le=5.0)


def validate_trajectory(points: list[TrajectoryPoint | dict]) -> list[TrajectoryPoint]:
    if len(points) < MIN_TRAJECTORY_POINTS:
        raise PresetError(f"a trajectory needs at least {MIN_TRAJECTORY_POINTS} waypoints")
    if len(points) > MAX_TRAJECTORY_POINTS:
        raise PresetError(f"at most {MAX_TRAJECTORY_POINTS} waypoints")
    try:
        validated = [
            p if isinstance(p, TrajectoryPoint) else TrajectoryPoint.model_validate(p)
            for p in points
        ]
    except ValueError as exc:
        raise PresetError(f"invalid trajectory waypoint: {exc}") from exc
    if all(p == validated[0] for p in validated[1:]):
        raise PresetError("trajectory waypoints are all identical — the camera never moves")
    return validated


def compose_trajectory(points: list[TrajectoryPoint], subject: str) -> tuple[str, dict]:
    """Prompt + params for a Uni3C custom-trajectory generation."""
    prompt = (
        f"camera follows a custom {len(points)}-waypoint trajectory around {subject}, "
        "smooth 3d-consistent camera motion, cinematic"
    )
    params = {
        "trajectory": [point.model_dump() for point in points],
        "advanced": "uni3c",
    }
    return prompt, params


def compose_reshoot(presets: list[CameraPresetRead]) -> tuple[str, dict]:
    """Prompt + params for a ReCamMaster re-shoot: the validated preset stack
    supplies the new camera move; the source footage supplies everything else."""
    prompt, params = compose(presets, RESHOOT_SUBJECT)
    return f"re-shoot: {prompt}", {**params, "advanced": "recammaster"}
