"""Prompt catalog (M27) — prompt engineering as data, like every registry in
this codebase (presets/styles/effects/emotions). Entries are techniques and
vocabulary distilled from published prompt guides — each carries its source
attribution; none are verbatim copies.

Sources studied (July 2026):
- Wan 2.2 prompt structure + camera guides: veed.io/learn/wan-2-2-prompting-guide,
  wan27.org/blog/wan-2-2-prompt-guide, instasd.com (Wan camera movements),
  mimicpc.com Wan prompt examples
- SDXL style/lighting vocabulary: github.com/roblaughter/style-reference (MIT,
  artist-free styles), thesephist's SD modifier gist, AI-art lighting galleries

Two entry shapes:
- category "structure": full templates with a {subject} slot
- everything else: appendable fragments the panel/MCP can stack onto a prompt
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PromptTemplate:
    id: str
    title: str
    category: str  # structure | camera | motion | lighting | style | composition | negative | music
    kind: str      # video | image | music | any
    template: str
    tags: tuple[str, ...] = ()
    source_url: str = ""
    notes: str = ""


_V = "video"
_I = "image"
_A = "any"

_WAN_GUIDE = "https://wan27.org/blog/wan-2-2-prompt-guide"
_VEED = "https://www.veed.io/learn/wan-2-2-prompting-guide"
_INSTASD = "https://www.instasd.com/post/mastering-prompt-writing-for-wan-2-1-in-comfyui-a-comprehensive-guide"
_STYLEREF = "https://github.com/roblaughter/style-reference"
_MODIFIERS = "https://gist.github.com/thesephist/376afed2cbfce35d4b37d985abe6d0a1"

CATALOG: tuple[PromptTemplate, ...] = (
    # --- structure: full frames with a {subject} slot ------------------------
    PromptTemplate(
        "wan-shot-frame", "Wan shot frame", "structure", _V,
        "{subject}. The camera slowly pushes in as the main motion unfolds; "
        "soft window light shapes the scene, shallow depth of field. "
        "Background details drift naturally. Steady pacing, no sudden cuts.",
        ("wan", "i2v", "t2v"), _WAN_GUIDE,
        "The 80-120 word frame: subject -> motion -> camera -> environment -> pacing.",
    ),
    PromptTemplate(
        "wan-sequential-motion", "Chained motion beats", "structure", _V,
        "{subject} walks toward the camera, stops, and turns to look left; "
        "the camera holds, then drifts right to follow the glance.",
        ("motion", "beats"), _VEED,
        "Chain 2-3 sequential motions — each verb gives the model a transition point.",
    ),
    PromptTemplate(
        "product-hero", "Product hero shot", "structure", _V,
        "{subject} on a seamless studio sweep, slow 180-degree orbit, "
        "specular highlights rolling across the surface, soft gradient "
        "background, premium commercial look.",
        ("product", "commercial"), _VEED, "",
    ),
    PromptTemplate(
        "still-portrait", "Editorial portrait", "structure", _I,
        "Portrait of {subject}, 85mm lens look, shallow depth of field, "
        "single soft key light, neutral seamless backdrop, editorial framing "
        "with generous negative space.",
        ("portrait", "sdxl", "z-image"), _STYLEREF, "",
    ),
    # --- camera language -----------------------------------------------------
    PromptTemplate("cam-push-in", "Slow push-in", "camera", _V,
                   "the camera slowly pushes in toward the subject",
                   ("dolly",), _INSTASD, "Speed-qualified verbs beat bare nouns."),
    PromptTemplate("cam-pull-back", "Pull back reveal", "camera", _V,
                   "the camera slowly pulls back, revealing the wider scene",
                   ("reveal",), _INSTASD, ""),
    PromptTemplate("cam-orbit", "Orbit", "camera", _V,
                   "the camera orbits smoothly around the subject, left to right",
                   ("orbit",), _INSTASD, ""),
    PromptTemplate("cam-pan", "Whip-free pan", "camera", _V,
                   "the camera pans briskly from left to right, holding the horizon level",
                   ("pan",), _INSTASD, ""),
    PromptTemplate("cam-tilt-reveal", "Tilt-up reveal", "camera", _V,
                   "the camera tilts up slowly from the ground to the subject's face",
                   ("tilt",), _INSTASD, ""),
    PromptTemplate("cam-handheld", "Handheld energy", "camera", _V,
                   "handheld camera with subtle natural shake, documentary feel",
                   ("handheld", "docu"), _VEED, ""),
    PromptTemplate("cam-locked", "Locked tripod", "camera", _V,
                   "locked-off tripod shot, completely static camera; only the subject moves",
                   ("static",), _WAN_GUIDE,
                   "Stops unwanted camera drift on I2V."),
    # --- motion qualifiers ---------------------------------------------------
    PromptTemplate("mo-slow", "Slow and deliberate", "motion", _V,
                   "all motion is slow and deliberate", ("pacing",), _WAN_GUIDE, ""),
    PromptTemplate("mo-direction", "Explicit direction", "motion", _V,
                   "moving briskly from left to right across the frame",
                   ("direction",), _WAN_GUIDE,
                   "Explicit speed + direction outperforms generic verbs."),
    PromptTemplate("mo-loop-friendly", "Loop-friendly ambience", "motion", _V,
                   "gentle continuous ambient motion, ending close to the opening pose",
                   ("loop", "b-roll"), _VEED, ""),
    # --- lighting ------------------------------------------------------------
    PromptTemplate("li-golden", "Golden hour", "lighting", _A,
                   "warm golden-hour sunlight, long soft shadows", ("warm",), _STYLEREF, ""),
    PromptTemplate("li-rembrandt", "Rembrandt key", "lighting", _A,
                   "Rembrandt lighting, single warm key with a soft triangle of light on the cheek",
                   ("portrait",), _MODIFIERS, ""),
    PromptTemplate("li-volumetric", "Volumetric rays", "lighting", _A,
                   "volumetric light rays through haze", ("atmosphere",), _MODIFIERS, ""),
    PromptTemplate("li-neon", "Neon night", "lighting", _A,
                   "neon signage reflections, wet asphalt, cyan and magenta rim light",
                   ("night", "city"), _STYLEREF, ""),
    PromptTemplate("li-overcast", "Soft overcast", "lighting", _A,
                   "soft overcast daylight, diffuse shadows, muted contrast",
                   ("soft",), _STYLEREF, ""),
    # --- style / film stock --------------------------------------------------
    PromptTemplate("st-16mm", "16mm film", "style", _A,
                   "shot on 16mm film, visible grain, slightly lifted blacks, handmade feel",
                   ("film",), _STYLEREF, ""),
    PromptTemplate("st-noir", "Cinematic noir", "style", _A,
                   "high-contrast black and white, hard shadows, venetian-blind light patterns",
                   ("noir",), _STYLEREF, ""),
    PromptTemplate("st-anamorphic", "Anamorphic look", "style", _A,
                   "anamorphic lens look, oval bokeh, subtle horizontal flares, 2.39:1 framing",
                   ("cinema",), _MODIFIERS, ""),
    PromptTemplate("st-documentary", "Vérité documentary", "style", _V,
                   "observational documentary style, available light, unposed moments",
                   ("docu",), _VEED, ""),
    # --- composition ---------------------------------------------------------
    PromptTemplate("co-thirds", "Rule of thirds", "composition", _A,
                   "subject placed on the right third, generous negative space left",
                   ("framing",), _MODIFIERS, ""),
    PromptTemplate("co-low-angle", "Low-angle hero", "composition", _A,
                   "low-angle shot looking up at the subject, imposing presence",
                   ("angle",), _MODIFIERS, ""),
    PromptTemplate("co-closeup", "Detail close-up", "composition", _A,
                   "extreme close-up on the defining detail, shallow focus falloff",
                   ("macro",), _MODIFIERS, ""),
    # --- negative prompts ----------------------------------------------------
    PromptTemplate(
        "neg-video-standard", "Standard video negative", "negative", _V,
        "morphing, warping, face deformation, flickering, duplicated limbs, "
        "jittery motion, sudden cuts, watermark text, subtitles",
        ("negative",), _WAN_GUIDE,
        "The standard anti-artifact set for Wan-family video.",
    ),
    PromptTemplate(
        "neg-image-standard", "Standard image negative", "negative", _I,
        "lowres, blurry, extra fingers, deformed hands, text artifacts, "
        "oversaturated, jpeg artifacts",
        ("negative",), _MODIFIERS, "",
    ),
    # --- music (ACE-Step tags) ----------------------------------------------
    PromptTemplate("mu-lofi", "Lo-fi bed", "music", "music",
                   "lo-fi hip hop, mellow, vinyl crackle, 70 bpm, instrumental",
                   ("bed",), "", "ACE-Step responds to comma-separated tags."),
    PromptTemplate("mu-cinematic", "Cinematic swell", "music", "music",
                   "cinematic orchestral, slow build, strings and low brass, emotional, instrumental",
                   ("score",), "", ""),
    PromptTemplate("mu-synthwave", "Synthwave drive", "music", "music",
                   "synthwave, analog synth arpeggios, driving beat, 100 bpm, instrumental",
                   ("retro",), "", ""),
)

CATEGORIES: tuple[str, ...] = tuple(
    dict.fromkeys(entry.category for entry in CATALOG)
)


def catalog(category: str | None = None, kind: str | None = None) -> list[PromptTemplate]:
    entries = list(CATALOG)
    if category:
        entries = [e for e in entries if e.category == category]
    if kind:
        entries = [e for e in entries if e.kind in (kind, "any")]
    return entries


def get_template(template_id: str) -> PromptTemplate:
    for entry in CATALOG:
        if entry.id == template_id:
            return entry
    raise KeyError(f"unknown prompt template {template_id!r}")
