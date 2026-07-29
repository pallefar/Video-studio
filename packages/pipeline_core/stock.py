"""Stock media providers behind one interface (M8).

Pexels primary (video-first), Pixabay secondary (explicitly permissive about
caching/serving from own infrastructure). Assets are downloaded into MinIO and
served from there; `license` and `source_url` are persisted at ingest, always.
API keys come from Settings — a provider without a key configured simply is
not registered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import httpx

from pipeline_core.settings import Settings

StockKind = Literal["video", "photo"]


@dataclass(frozen=True)
class StockResult:
    provider: str
    external_id: str
    kind: StockKind
    caption: str
    download_url: str
    preview_url: str
    source_url: str
    license: str
    duration_ms: Optional[int] = None


class PexelsProvider:
    name = "pexels"
    license = "Pexels License"

    def __init__(self, api_key: str, client: Optional[httpx.Client] = None):
        self._client = client or httpx.Client(timeout=30)
        self._headers = {"Authorization": api_key}

    def search(self, query: str, kind: StockKind = "video", limit: int = 10) -> list[StockResult]:
        if kind == "video":
            response = self._client.get(
                "https://api.pexels.com/videos/search",
                params={"query": query, "per_page": limit},
                headers=self._headers,
            )
            response.raise_for_status()
            results = []
            for video in response.json().get("videos", []):
                files = sorted(
                    (f for f in video.get("video_files", []) if f.get("width")),
                    key=lambda f: f["width"],
                )
                usable = [f for f in files if f["width"] <= 1920] or files
                if not usable:
                    continue
                results.append(
                    StockResult(
                        provider=self.name,
                        external_id=str(video["id"]),
                        kind="video",
                        caption=video.get("alt") or query,
                        download_url=usable[-1]["link"],
                        preview_url=video.get("image", ""),
                        source_url=video.get("url", ""),
                        license=self.license,
                        duration_ms=int(video.get("duration", 0)) * 1000 or None,
                    )
                )
            return results

        response = self._client.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "per_page": limit},
            headers=self._headers,
        )
        response.raise_for_status()
        return [
            StockResult(
                provider=self.name,
                external_id=str(photo["id"]),
                kind="photo",
                caption=photo.get("alt") or query,
                download_url=photo["src"]["large2x"],
                preview_url=photo["src"].get("medium", ""),
                source_url=photo.get("url", ""),
                license=self.license,
            )
            for photo in response.json().get("photos", [])
        ]


class PixabayProvider:
    name = "pixabay"
    license = "Pixabay Content License"

    def __init__(self, api_key: str, client: Optional[httpx.Client] = None):
        self._client = client or httpx.Client(timeout=30)
        self._api_key = api_key

    def search(self, query: str, kind: StockKind = "video", limit: int = 10) -> list[StockResult]:
        if kind == "video":
            response = self._client.get(
                "https://pixabay.com/api/videos/",
                params={"key": self._api_key, "q": query, "per_page": limit},
            )
            response.raise_for_status()
            results = []
            for hit in response.json().get("hits", []):
                videos = hit.get("videos", {})
                variant = videos.get("large") or videos.get("medium") or videos.get("small")
                if not variant or not variant.get("url"):
                    continue
                results.append(
                    StockResult(
                        provider=self.name,
                        external_id=str(hit["id"]),
                        kind="video",
                        caption=hit.get("tags", query),
                        download_url=variant["url"],
                        preview_url=videos.get("tiny", {}).get("url", ""),
                        source_url=hit.get("pageURL", ""),
                        license=self.license,
                        duration_ms=int(hit.get("duration", 0)) * 1000 or None,
                    )
                )
            return results

        response = self._client.get(
            "https://pixabay.com/api/",
            params={"key": self._api_key, "q": query, "per_page": limit},
        )
        response.raise_for_status()
        return [
            StockResult(
                provider=self.name,
                external_id=str(hit["id"]),
                kind="photo",
                caption=hit.get("tags", query),
                download_url=hit.get("largeImageURL", hit.get("webformatURL", "")),
                preview_url=hit.get("previewURL", ""),
                source_url=hit.get("pageURL", ""),
                license=self.license,
            )
            for hit in response.json().get("hits", [])
            if hit.get("largeImageURL") or hit.get("webformatURL")
        ]


def get_providers(
    settings: Optional[Settings] = None, client: Optional[httpx.Client] = None
) -> list:
    settings = settings or Settings()
    providers = []
    if settings.pexels_api_key:
        providers.append(PexelsProvider(settings.pexels_api_key, client))
    if settings.pixabay_api_key:
        providers.append(PixabayProvider(settings.pixabay_api_key, client))
    return providers


def download(url: str, client: Optional[httpx.Client] = None) -> bytes:
    owns_client = client is None
    client = client or httpx.Client(timeout=120, follow_redirects=True)
    try:
        response = client.get(url)
        response.raise_for_status()
        return response.content
    finally:
        if owns_client:
            client.close()
