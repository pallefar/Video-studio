"""Effect preset registry (M13) — Higgsfield's Effects/Effects Mix, as data.

One-click VFX applied to existing library footage over the Wan2.2-VACE-Fun
v2v lane; Wan 2.1 VACE 1.3B serves the fast-preview path. Effects stack with
camera presets (the 'Mix' mechanic). Like camera presets and styles, tuning
templates is content work, not code work.
"""

from __future__ import annotations

from pipeline_core.presets import PresetError, validate_stack as validate_camera_stack
from schema.models import CameraPresetRead, EffectPresetRead

MAX_EFFECT_STACK = 3

# Model routing: full-quality vs fast preview (roadmap-v2 §2).
VACE_FULL = "wan2.2-vace-fun"
VACE_PREVIEW = "wan2.1-vace-1.3b"


class EffectError(Exception):
    pass


def _effect(
    id: str,
    label: str,
    description: str,
    category: str,
    prompt_template: str,
    stackable: bool = True,
) -> EffectPresetRead:
    return EffectPresetRead(
        id=id,
        label=label,
        description=description,
        category=category,
        prompt_template=prompt_template,
        stackable=stackable,
    )


EFFECT_PRESETS: list[EffectPresetRead] = [
    _effect("levitation", "Levitation", "Subject lifts gently off the ground.", "physics",
            "the subject slowly levitates off the ground, hovering weightlessly, hair and clothes drifting"),
    _effect("disintegrate", "Disintegrate", "Crumble into drifting particles.", "destruction",
            "the subject disintegrates into thousands of drifting particles carried away by the wind"),
    _effect("set_on_fire", "Set on Fire", "Engulfed in stylised flames.", "destruction",
            "stylised flames ignite and engulf the subject, embers rising, dramatic orange glow"),
    _effect("freeze", "Freeze", "Ice crystals crawl over everything.", "physics",
            "frost and ice crystals rapidly crawl across the subject and scene, cold blue tint"),
    _effect("ghost_trail", "Ghost Trail", "Motion echoes trail behind.", "motion",
            "translucent motion echoes trail behind the subject, long-exposure ghosting"),
    _effect("glitch", "Glitch", "Digital corruption sweeps the frame.", "digital",
            "digital glitch corruption sweeps across the frame, RGB channel splits, datamosh artifacts"),
    _effect("explode_out", "Explode Outward", "Blast apart, fragments outward.", "destruction",
            "the subject explodes outward into fragments in dramatic slow motion", stackable=False),
    _effect("restyle_anime", "Anime Restyle", "Re-render as hand-drawn anime.", "restyle",
            "restyle the footage as hand-drawn anime, cel shading, clean line art, vibrant flat colours",
            stackable=False),
    _effect("restyle_clay", "Claymation Restyle", "Stop-motion clay world.", "restyle",
            "restyle the footage as stop-motion claymation, visible fingerprints, handcrafted miniature look",
            stackable=False),
    _effect("restyle_watercolor", "Watercolour Restyle", "Living watercolour painting.", "restyle",
            "restyle the footage as a living watercolour painting, soft pigment bleeds, paper texture",
            stackable=False),
]

_BY_ID = {effect.id: effect for effect in EFFECT_PRESETS}


def validate_effect_stack(effect_ids: list[str]) -> list[EffectPresetRead]:
    if not effect_ids:
        raise EffectError("pick at least one effect")
    if len(effect_ids) > MAX_EFFECT_STACK:
        raise EffectError(f"at most {MAX_EFFECT_STACK} effects can be stacked")
    if len(set(effect_ids)) != len(effect_ids):
        raise EffectError("duplicate effects in the stack")
    effects = []
    for effect_id in effect_ids:
        effect = _BY_ID.get(effect_id)
        if effect is None:
            raise EffectError(f"unknown effect preset {effect_id!r}")
        effects.append(effect)
    if len(effects) > 1 and any(not effect.stackable for effect in effects):
        blocked = next(e.id for e in effects if not e.stackable)
        raise EffectError(f"effect {blocked!r} cannot be stacked with others")
    return effects


def compose_mix(
    effect_ids: list[str], camera_preset_ids: list[str] | None = None
) -> tuple[str, dict]:
    """Effects (+ optional camera moves — the 'Mix' mechanic) -> prompt and
    generation params. Camera stacking reuses the M11 rules unchanged."""
    effects = validate_effect_stack(effect_ids)
    fragments = [effect.prompt_template for effect in effects]

    cameras: list[CameraPresetRead] = []
    if camera_preset_ids:
        try:
            cameras = validate_camera_stack(camera_preset_ids)
        except PresetError as exc:
            raise EffectError(str(exc)) from exc
        fragments += [preset.prompt_template.format(subject="the scene") for preset in cameras]

    params = {
        "effects": [effect.id for effect in effects],
        "motion_codes": [preset.motion_code for preset in cameras],
    }
    return ", ".join(fragments), params
