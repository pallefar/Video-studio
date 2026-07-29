"""Stock providers behind one interface, parsed from mocked API responses."""

from __future__ import annotations

import httpx
import pytest

from pipeline_core.settings import Settings
from pipeline_core.stock import PexelsProvider, PixabayProvider, download, get_providers

PEXELS_VIDEO_RESPONSE = {
    "videos": [
        {
            "id": 101,
            "url": "https://www.pexels.com/video/office-101/",
            "image": "https://images.pexels.com/101/preview.jpg",
            "duration": 12,
            "alt": "Hands typing on a keyboard in an office",
            "video_files": [
                {"width": 3840, "link": "https://videos.pexels.com/101/uhd.mp4"},
                {"width": 1920, "link": "https://videos.pexels.com/101/hd.mp4"},
                {"width": 640, "link": "https://videos.pexels.com/101/sd.mp4"},
            ],
        }
    ]
}

PIXABAY_VIDEO_RESPONSE = {
    "hits": [
        {
            "id": 202,
            "pageURL": "https://pixabay.com/videos/city-202/",
            "tags": "city, timelapse, night",
            "duration": 20,
            "videos": {
                "large": {"url": "https://cdn.pixabay.com/202/large.mp4"},
                "tiny": {"url": "https://cdn.pixabay.com/202/tiny.mp4"},
            },
        }
    ]
}


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_pexels_video_search_parses_and_persists_provenance():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.pexels.com"
        assert request.headers["Authorization"] == "pexels-key"
        return httpx.Response(200, json=PEXELS_VIDEO_RESPONSE)

    results = PexelsProvider("pexels-key", _client(handler)).search("office keyboard")
    assert len(results) == 1
    result = results[0]
    assert result.provider == "pexels"
    assert result.license == "Pexels License"
    assert result.source_url == "https://www.pexels.com/video/office-101/"
    assert result.download_url == "https://videos.pexels.com/101/hd.mp4"  # capped at 1920
    assert result.duration_ms == 12_000
    assert "keyboard" in result.caption


def test_pixabay_video_search_parses_and_persists_provenance():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "pixabay.com"
        assert request.url.params["key"] == "pixabay-key"
        return httpx.Response(200, json=PIXABAY_VIDEO_RESPONSE)

    results = PixabayProvider("pixabay-key", _client(handler)).search("city night")
    assert len(results) == 1
    result = results[0]
    assert result.provider == "pixabay"
    assert result.license == "Pixabay Content License"
    assert result.source_url == "https://pixabay.com/videos/city-202/"
    assert result.download_url == "https://cdn.pixabay.com/202/large.mp4"


def test_registry_excludes_providers_without_keys():
    assert get_providers(Settings(pexels_api_key="", pixabay_api_key="")) == []
    providers = get_providers(Settings(pexels_api_key="k", pixabay_api_key=""))
    assert [p.name for p in providers] == ["pexels"]
    providers = get_providers(Settings(pexels_api_key="k", pixabay_api_key="k2"))
    assert [p.name for p in providers] == ["pexels", "pixabay"]


def test_search_error_propagates():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    with pytest.raises(httpx.HTTPStatusError):
        PexelsProvider("k", _client(handler)).search("anything")


def test_download_follows_and_returns_bytes():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"video-bytes")

    assert download("https://cdn.example/clip.mp4", _client(handler)) == b"video-bytes"
