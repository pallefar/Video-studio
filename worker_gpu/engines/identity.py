"""Identity LoRA trainer (M17) — SDXL/Z-Image LoRA from ~20 reference photos,
run on the wan lane as an overnight batch under the exclusive GPU lock.

Loads ONCE per worker process like every other engine. The real training loop
is the workstation task (kohya/diffusers decision alongside the M10 executor);
the interface and the consent gate around it are fixed here.
"""

from __future__ import annotations

from pipeline_core.storage import ObjectStore


class IdentityLoraTrainer:
    def __init__(self, store: ObjectStore):
        self.store = store
        self._pipeline = None

    def load(self) -> None:
        import torch  # lazy: GPU host only, installed via the [gpu] extra

        if not torch.cuda.is_available():
            raise RuntimeError("IdentityLoraTrainer requires a CUDA device — run scripts/verify_gpu.py first")
        raise NotImplementedError("M17 workstation task: SDXL/Z-Image LoRA training pipeline")

    def train(self, identity_id: str, reference_asset_ids: list[str]) -> str:
        """Train a LoRA from the reference assets, upload the weights via
        ObjectStore, and return the s3 uri. Idempotent on identity_id: weights
        land at identities/{identity_id}/lora.safetensors, overwritten on retrain.
        """
        raise NotImplementedError("M17 workstation task")
