"""Auto-captioning for library assets (M24, roadmap-v2 §2 "prompt
intelligence"): Florence-2 (MIT) describes the poster frame so the M8
resolver's cosine search works over what a clip actually shows, not just
whatever filename it arrived with.

Same lazy-extra pattern as embeddings/enhance: install the [caption] extra
to get the real model; the default Noop keeps every code path importable and
testable on machines without the weights. Runs on CPU — slow but fine for a
cpu-lane batch stage.
"""

from __future__ import annotations

import re
from typing import Optional, Protocol

FLORENCE_MODEL = "microsoft/Florence-2-base"  # MIT — licence register §6
_TASK = "<MORE_DETAILED_CAPTION>"

# Captions that carry no visual information: filenames, generation ids,
# upload defaults. If a caption looks like one of these, captioning (and
# re-captioning via --recaption) should replace it.
_PLACEHOLDER_RES = [
    re.compile(r"^\s*$"),
    re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I),
    re.compile(r"^\S+\.(mp4|mov|webm|mkv|png|jpe?g|wav|mp3|m4a)$", re.I),
    re.compile(r"^(untitled|upload|asset|clip|video|image)[\s_-]*\d*$", re.I),
]


def is_placeholder_caption(caption: Optional[str]) -> bool:
    if caption is None:
        return True
    return any(pattern.match(caption.strip()) for pattern in _PLACEHOLDER_RES)


class Captioner(Protocol):
    available: bool

    def caption(self, image_bytes: bytes) -> Optional[str]: ...


class NoopCaptioner:
    """Default when the [caption] extra is not installed: captions stay as
    they are, and the stage logs why instead of failing the queue."""

    available = False

    def caption(self, image_bytes: bytes) -> Optional[str]:
        return None


class Florence2Captioner:
    """microsoft/Florence-2-base <MORE_DETAILED_CAPTION> on CPU. Loaded once
    per process, like every model in this codebase."""

    available = True

    def __init__(self, model_id: str = FLORENCE_MODEL):
        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor

        self._torch = torch
        self._model = AutoModelForCausalLM.from_pretrained(
            model_id, trust_remote_code=True, torch_dtype=torch.float32
        )
        self._processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)

    def caption(self, image_bytes: bytes) -> Optional[str]:
        import io

        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        inputs = self._processor(text=_TASK, images=image, return_tensors="pt")
        with self._torch.no_grad():
            ids = self._model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=256,
                num_beams=3,
            )
        raw = self._processor.batch_decode(ids, skip_special_tokens=False)[0]
        parsed = self._processor.post_process_generation(
            raw, task=_TASK, image_size=image.size
        )
        text = (parsed.get(_TASK) or "").strip()
        return text or None


def get_captioner() -> Captioner:
    try:
        import transformers  # noqa: F401  — the [caption] extra
    except ImportError:
        return NoopCaptioner()
    try:
        return Florence2Captioner()
    except Exception:
        # weights unavailable/offline — degrade loudly but keep the lane alive
        import structlog

        structlog.get_logger().warning("florence2_load_failed_using_noop")
        return NoopCaptioner()
