"""YouTube publish (M6) — Data API v3 with OAuth refresh token.

Structural rules, enforced here as well as at the API gate:
- Uploads land PRIVATE, always. `PRIVACY` is the only value this module can
  send — there is deliberately no parameter for it (C5).
- `containsSyntheticMedia` (the altered-content disclosure) is always true
  on our uploads (C2).
- Quota exhaustion is distinguished from real failures: back off to the
  next quota window instead of retry-hammering (docs/pipeline-spec.md §5).

The real client wraps google-api-python-client lazily (installed on the
workstation via the [publish] extra); tests inject fakes through
worker_cpu.stages.get_youtube_client.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import structlog

from pipeline_core.settings import Settings

log = structlog.get_logger()

PRIVACY = "private"  # C5: the only privacy status this codebase can emit
UPLOAD_MAX_ATTEMPTS = 4
BACKOFF_BASE_S = 2.0


class QuotaExceededError(Exception):
    """Daily quota exhausted — retry at the next window, do not hammer."""


@dataclass
class UploadResult:
    video_id: str


class YouTubeClient(Protocol):
    def upload(self, path: Path, title: str, description: str) -> UploadResult: ...


class YouTubeDataApiClient:
    """google-api-python-client wrapper. Refresh-token OAuth: the one-time
    consent flow runs on the workstation; the refresh token lives in env."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._service = None

    def _build(self):
        from google.oauth2.credentials import Credentials  # lazy: [publish] extra
        from googleapiclient.discovery import build

        credentials = Credentials(
            token=None,
            refresh_token=self._settings.youtube_refresh_token,
            client_id=self._settings.youtube_client_id,
            client_secret=self._settings.youtube_client_secret,
            token_uri=self._settings.youtube_token_uri,
        )
        return build("youtube", "v3", credentials=credentials)

    def upload(self, path: Path, title: str, description: str) -> UploadResult:
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        if self._service is None:
            self._service = self._build()
        body = {
            "snippet": {"title": title, "description": description},
            "status": {
                "privacyStatus": PRIVACY,  # C5 — never parameterised
                "selfDeclaredMadeForKids": False,
                "containsSyntheticMedia": True,  # C2 — altered content, always
            },
        }
        try:
            request = self._service.videos().insert(
                part="snippet,status",
                body=body,
                media_body=MediaFileUpload(str(path), mimetype="video/mp4", resumable=True),
            )
            response = request.execute()
        except HttpError as exc:
            if _is_quota_error(exc):
                raise QuotaExceededError(str(exc)) from exc
            raise
        return UploadResult(video_id=response["id"])


def _is_quota_error(exc) -> bool:
    reasons = []
    try:
        for detail in exc.error_details or []:
            reasons.append(detail.get("reason", ""))
    except Exception:
        pass
    text = f"{reasons} {exc}".lower()
    return "quotaexceeded" in text.replace("_", "").replace("-", "")


def build_client(settings: Settings | None = None) -> YouTubeClient | None:
    """None when OAuth isn't configured — the publish stage waits, it does
    not fail (same posture as a missing ffmpeg binary)."""
    settings = settings or Settings()
    if not (
        settings.youtube_client_id
        and settings.youtube_client_secret
        and settings.youtube_refresh_token
    ):
        return None
    return YouTubeDataApiClient(settings)
