"""Latent cache builder for base loops (M2).

Downloads the source via ObjectStore, builds the MuseTalk latent cache and
face bounding boxes, uploads both, and records their uris on the BaseLoop.
Idempotent: if latents_uri already exists for the loop, this is a no-op.
"""

from __future__ import annotations

from pipeline_core.storage import ObjectStore


def build_loop_cache(store: ObjectStore, loop_id: str) -> None:
    raise NotImplementedError("M2: seam detection (perceptual hash, ping-pong fallback) + latent cache")
