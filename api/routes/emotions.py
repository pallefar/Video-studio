from __future__ import annotations

from fastapi import APIRouter

from pipeline_core.emotions import list_emotions

router = APIRouter(tags=["emotions"])


@router.get("/emotions")
async def get_emotions():
    """Speak-style delivery presets for TTS segments (M18) — data-driven,
    served for the panel's per-segment emotion picker."""
    return list_emotions()
