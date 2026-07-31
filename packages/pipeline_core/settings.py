"""All service addresses come from env — the worker packages never hold literals.

The localhost defaults below exist for developer ergonomics on the workstation
(matching docker-compose.yml) and live ONLY here. tests/test_portability.py
enforces that worker_gpu/ and worker_cpu/ never declare their own endpoints.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://avatar:avatar@localhost:5432/avatar"
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "avatar-pipeline"
    s3_region: str = "us-east-1"

    # Stock providers (M8): a provider with no key configured is not registered.
    pexels_api_key: str = ""
    pixabay_api_key: str = ""

    # Generation providers (M10): same rule — no key, not registered.
    fal_api_key: str = ""
    # ElevenLabs direct API (roadmap-v2 §3): voice/SFX/music generation as
    # network jobs. Configuring the key is the per-provider data-egress
    # decision — prompts/scripts are sent to ElevenLabs when used.
    elevenlabs_api_key: str = ""

    # YouTube publish (M6): OAuth refresh-token flow. Unconfigured -> the
    # publish stage waits instead of failing, like a missing ffmpeg.
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_refresh_token: str = ""
    youtube_token_uri: str = "https://oauth2.googleapis.com/token"

    # Prompt enhancement (M18): path to the Qwen3.5-4B GGUF; empty -> the
    # deterministic heuristic enhancer is used.
    qwen_model_path: str = ""

    # Dev engines (DEV_ENGINES=1): placeholder TTS/lipsync/generation so the
    # full pipeline runs end-to-end on machines without CUDA (Apple Silicon,
    # CI). Output is watchable but NOT production.
    dev_engines: bool = False

    # ComfyUI headless — the M10 wan-lane executor. Unconfigured -> local
    # generation raises a config hint (and declared fallbacks still run).
    comfy_url: str = ""
    comfy_poll_interval_s: float = 2.0
    comfy_timeout_s: int = 3600
