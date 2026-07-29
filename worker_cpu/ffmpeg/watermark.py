"""Watermark burn-in (M4): visible 'Made with AI', bottom-right, FULL duration.

Compliance C1 — never a timed overlay. M5's frame-sampling test asserts the
watermark pixels are present at 10%, 50% and 90% of duration.
"""

from __future__ import annotations

from pipeline_core.storage import ObjectStore


def burn_watermark(store: ObjectStore, job_id: str) -> str:
    raise NotImplementedError("M4")
