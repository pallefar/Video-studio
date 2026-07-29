"""Style template registry — curated looks applied across a storyboard
('Soul preset' equivalent). Prompt suffixes now; colour-grade/LUT params are
consumed by the M16 render compiler. Like camera presets, styles are data:
new looks are content drops, not code changes.
"""

from __future__ import annotations

from schema.models import StyleTemplateRead, VideoFormat


class StyleError(Exception):
    pass


def _style(id: str, label: str, description: str, prompt_suffix: str, **params) -> StyleTemplateRead:
    return StyleTemplateRead(
        id=id, label=label, description=description, prompt_suffix=prompt_suffix, params=params
    )


STYLE_TEMPLATES: list[StyleTemplateRead] = [
    _style("cinematic_noir", "Cinematic Noir", "High contrast, deep shadows, moody.",
           "cinematic noir look, high contrast, deep shadows, dramatic rim lighting, film grain",
           grade="noir"),
    _style("warm_ambient", "Warm Ambient", "Soft golden light, cosy tones.",
           "warm ambient lighting, soft golden tones, gentle bokeh, inviting atmosphere",
           grade="warm"),
    _style("golden_hour", "Golden Hour", "Low sun, long shadows, glow.",
           "golden hour sunlight, long soft shadows, warm rim light, atmospheric haze",
           grade="warm"),
    _style("neon_night", "Neon Night", "Cyberpunk city glow.",
           "neon-lit night scene, cyan and magenta glow, wet reflective surfaces, cyberpunk mood",
           grade="cool"),
    _style("film_16mm", "16mm Film", "Vintage grain and halation.",
           "shot on 16mm film, visible grain, halation, slightly faded colours, vintage cinema",
           grade="film"),
    _style("clean_corporate", "Clean Corporate", "Bright, neutral, product-safe.",
           "clean bright lighting, neutral colour palette, minimal modern setting, professional",
           grade="neutral"),
    _style("y2k", "Y2K", "Glossy retro-futurism.",
           "y2k aesthetic, glossy surfaces, chrome and translucent plastic, retro-futuristic",
           grade="pop"),
    _style("documentary", "Documentary", "Natural light, honest texture.",
           "natural available light, documentary realism, honest textures, unstaged feel",
           grade="neutral"),
]

_BY_ID = {style.id: style for style in STYLE_TEMPLATES}


def get_style(style_id: str) -> StyleTemplateRead:
    style = _BY_ID.get(style_id)
    if style is None:
        raise StyleError(f"unknown style template {style_id!r}")
    return style


# Format specs consumed by generation params and the M16 export compiler.
FORMAT_SPECS: dict[VideoFormat, dict] = {
    VideoFormat.long: {"width": 1920, "height": 1080, "aspect": "16:9", "max_duration_s": None},
    VideoFormat.short: {"width": 1080, "height": 1920, "aspect": "9:16", "max_duration_s": 60},
}


def format_spec(format: VideoFormat) -> dict:
    return dict(FORMAT_SPECS[format])
