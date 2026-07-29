"""Final assembly (M4): loudness, b-roll insertion, encode.

Chain: two-pass loudnorm to -14 LUFS -> b-roll overlays at beat timestamps ->
libx264 CRF 18, yuv420p, +faststart, AAC 192k. The Chatterbox audio watermark
must survive this chain (compliance C3, verified by the encode test).
Sources arrive and results leave via ObjectStore; scratch space comes from
tempfile, never a hardcoded path.
"""

from __future__ import annotations

from pipeline_core.storage import ObjectStore


def assemble(store: ObjectStore, job_id: str) -> str:
    raise NotImplementedError("M4")
