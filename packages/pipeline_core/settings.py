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
