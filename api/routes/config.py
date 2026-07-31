"""Config visibility for the Settings tab: WHICH capabilities are configured,
never their values. Every field in the response is a boolean — asserted by
tests/test_reliability.py so a secret can never leak through this route."""

from __future__ import annotations

from fastapi import APIRouter

from pipeline_core.settings import Settings

router = APIRouter(tags=["config"])


@router.get("/config")
async def config_status() -> dict[str, bool]:
    settings = Settings()
    return {
        "dev_engines": bool(settings.dev_engines),
        "comfy_configured": bool(settings.comfy_url),
        "fal_configured": bool(settings.fal_api_key),
        "pexels_configured": bool(settings.pexels_api_key),
        "pixabay_configured": bool(settings.pixabay_api_key),
        "youtube_configured": bool(
            settings.youtube_client_id
            and settings.youtube_client_secret
            and settings.youtube_refresh_token
        ),
        "qwen_configured": bool(settings.qwen_model_path),
    }
