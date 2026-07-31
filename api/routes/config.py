"""Config visibility for the Settings tab: WHICH capabilities are configured,
never their values. Every field in the response is a boolean — asserted by
tests/test_reliability.py so a secret can never leak through this route."""

from __future__ import annotations

from fastapi import APIRouter

from pipeline_core.settings import Settings

router = APIRouter(tags=["config"])


def _comfy_online(settings: Settings) -> bool:
    """Live reachability, not just configuration: pings ComfyUI's
    /system_stats with a short timeout so Settings can show connected vs
    merely configured."""
    if not settings.comfy_url:
        return False
    try:
        import httpx

        response = httpx.get(
            f"{settings.comfy_url.rstrip('/')}/system_stats", timeout=1.5
        )
        return response.status_code == 200
    except Exception:
        return False


@router.get("/config")
async def config_status() -> dict[str, bool]:
    settings = Settings()
    return {
        "comfy_online": _comfy_online(settings),
        "dev_engines": bool(settings.dev_engines),
        "comfy_configured": bool(settings.comfy_url),
        "fal_configured": bool(settings.fal_api_key),
        "elevenlabs_configured": bool(settings.elevenlabs_api_key),
        "openai_configured": bool(settings.openai_api_key),
        "gemini_configured": bool(settings.gemini_api_key),
        "pexels_configured": bool(settings.pexels_api_key),
        "pixabay_configured": bool(settings.pixabay_api_key),
        "youtube_configured": bool(
            settings.youtube_client_id
            and settings.youtube_client_secret
            and settings.youtube_refresh_token
        ),
        "qwen_configured": bool(settings.qwen_model_path),
    }


@router.get("/config/comfy")
async def comfy_detail() -> dict:
    """Node-pack view for the Settings tab: which custom-node packs the
    workflow templates need are actually installed on the running ComfyUI.
    Node class names and pack names only — no secrets live here."""
    settings = Settings()
    if not settings.comfy_url:
        return {"configured": False, "online": False, "packs": [], "missing": []}

    from pipeline_core.comfy import ComfyUIClient
    from pipeline_core.comfy_nodes import missing_node_types, pack_status

    try:
        import httpx

        client = ComfyUIClient(settings.comfy_url, client=httpx.Client(timeout=5))
        available = client.object_info()
    except Exception:
        return {"configured": True, "online": False, "packs": [], "missing": []}
    return {
        "configured": True,
        "online": True,
        "packs": pack_status(available),
        "missing": missing_node_types(available),
    }
