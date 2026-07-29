"""Caption burn-in (M4): faster-whisper word timings -> ASS subtitles filter."""

from __future__ import annotations

from pipeline_core.storage import ObjectStore


def burn_captions(store: ObjectStore, job_id: str) -> str:
    raise NotImplementedError("M4")
