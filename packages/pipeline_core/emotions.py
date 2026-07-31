"""Speak-style emotion presets for Chatterbox TTS segments (M18).

Data, not code — each preset maps to Chatterbox's two delivery controls:
`exaggeration` (emotional intensity, 0..1, neutral 0.5) and `cfg_weight`
(pacing/adherence, lower = faster and looser). Tuning a preset is content
work; new moods are drops, not code changes. The segment stores the preset
id so a re-render reproduces the same delivery alongside its pinned seed.
"""

from __future__ import annotations


class EmotionError(Exception):
    pass


DEFAULT_EMOTION = "neutral"

EMOTIONS: dict[str, dict[str, float]] = {
    "neutral": {"exaggeration": 0.5, "cfg_weight": 0.5},
    "excited": {"exaggeration": 0.9, "cfg_weight": 0.35},
    "calm": {"exaggeration": 0.3, "cfg_weight": 0.6},
    "serious": {"exaggeration": 0.4, "cfg_weight": 0.55},
    "warm": {"exaggeration": 0.6, "cfg_weight": 0.5},
    "urgent": {"exaggeration": 0.8, "cfg_weight": 0.3},
}


def emotion_params(name: str | None) -> dict[str, float]:
    """Engine parameters for a preset; None falls back to neutral."""
    key = name or DEFAULT_EMOTION
    params = EMOTIONS.get(key)
    if params is None:
        raise EmotionError(f"unknown emotion preset {key!r}")
    return dict(params)


def list_emotions() -> list[dict]:
    return [{"id": name, **params} for name, params in EMOTIONS.items()]
