"""MuseTalk lip-sync engine. Loads ONCE at worker boot, stays resident (M3).

BF16 on sm_86. Lip-sync runs in 60-90 s chunks to bound VRAM and keep
retries cheap; chunks are stitched at assembly (M4).
"""

from __future__ import annotations

from pipeline_core.storage import ObjectStore


class MuseTalkEngine:
    def __init__(self, store: ObjectStore):
        self.store = store
        self._model = None

    def load(self) -> None:
        import torch  # lazy: GPU host only, installed via the [gpu] extra

        if not torch.cuda.is_available():
            raise RuntimeError("MuseTalkEngine requires a CUDA device — run scripts/verify_gpu.py first")
        raise NotImplementedError("M3: load MuseTalk weights (pinned version) in BF16")

    def sync_chunk(self, job_id: str, loop_id: str, chunk_start_ms: int, chunk_end_ms: int) -> str:
        """Lip-sync one 60-90 s window against the cached loop latents,
        upload via ObjectStore, return the s3 uri. Idempotent per chunk:
        chunk windows derive deterministically from segment durations, and a
        chunk whose key already exists in the store is skipped."""
        raise NotImplementedError("M3")
