"""Chatterbox TTS engine. Loads ONCE at worker boot, stays resident (M3).

BF16 on sm_86. Chatterbox emits an inaudible audio watermark that must
survive the encode chain (compliance C3).
"""

from __future__ import annotations

from pipeline_core.storage import ObjectStore


class ChatterboxEngine:
    def __init__(self, store: ObjectStore):
        self.store = store
        self._model = None

    def load(self) -> None:
        import torch  # lazy: GPU host only, installed via the [gpu] extra

        if not torch.cuda.is_available():
            raise RuntimeError("ChatterboxEngine requires a CUDA device — run scripts/verify_gpu.py first")
        raise NotImplementedError("M3: load Chatterbox weights (pinned version) in BF16")

    def synthesize_segment(self, job_id: str, segment_idx: int, text: str, seed: int) -> str:
        """Render one segment to audio, upload via ObjectStore, return the s3 uri.

        Idempotent on stage_key(job_id, "tts", segment_idx); the seed is pinned
        and persisted so a retry reproduces the same take.
        """
        raise NotImplementedError("M3")
