"""Thin async client over the studio's HTTP API.

Every MCP tool goes through here, and here goes through the API — the same
routes the panel uses, with the same validators and compliance gates. The
base URL comes from STUDIO_API_URL (default: the local studio). Tests
inject an httpx transport wired straight to the FastAPI app.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_API_URL = "http://localhost:8000"


class StudioError(Exception):
    """API-level failure, with the server's detail message when present."""


class StudioClient:
    def __init__(self, base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(
            base_url=base_url or os.environ.get("STUDIO_API_URL", DEFAULT_API_URL),
            transport=transport,
            timeout=60,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise StudioError(f"studio API unreachable: {exc}") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise StudioError(f"{response.status_code}: {detail}")
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return response.text

    async def get(self, path: str, **params: Any) -> Any:
        return await self._request("GET", path, params={k: v for k, v in params.items() if v is not None})

    async def post(self, path: str, json: Any | None = None) -> Any:
        return await self._request("POST", path, json=json)
