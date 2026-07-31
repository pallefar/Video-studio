"""Dev generation executor (DEV_ENGINES=1) — local generation without CUDA.

The generation-lane counterpart of worker_gpu/engines/dev.py: placeholder
output with the real pipeline shape. Every kind produces genuine bytes at
the requested dimensions/duration/seed — a prompt card rendered with Pillow
(never drawtext: the repo is deliberately fontconfig-free) looped into an
H.264 clip for video kinds, the card itself for images, a synthesized bed
for music, a real 2x scale for upscales — so presets, effects, storyboards,
music, and the MCP workflows run end-to-end on machines without a GPU.

Opt-in via env only, announced loudly, never the default.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

import structlog

from pipeline_core.providers import ProviderResult
from pipeline_core.storage import ObjectStore
from schema.models import Generation, GenerationKind

log = structlog.get_logger()

DEFAULT_VIDEO = (832, 480)
MAX_CLIP_S = 5.0  # dev clips stay tiny — this is plumbing proof, not content


def _find_ffmpeg() -> str:
    binary = shutil.which("ffmpeg")
    if binary:
        return binary
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(args: list[str]) -> None:
    result = subprocess.run(args, capture_output=True, text=True, errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"{args[0]} failed: {result.stderr[-400:]}")


def _dims(params: dict) -> tuple[int, int]:
    width = params.get("width")
    height = params.get("height")
    if not (width and height):
        width, height = DEFAULT_VIDEO
        if params.get("aspect") == "9:16":
            width, height = height, width
    # yuv420p needs even dimensions
    return int(width) // 2 * 2, int(height) // 2 * 2


def _prompt_card(path: Path, prompt: str, width: int, height: int, seed: int) -> Path:
    """Seeded gradient + wrapped prompt text, rendered with Pillow."""
    from PIL import Image, ImageDraw, ImageFont

    hue = seed % 360
    import colorsys

    top = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(hue / 360, 0.65, 0.55))
    bottom = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(((hue + 40) % 360) / 360, 0.7, 0.25))
    image = Image.new("RGB", (width, height))
    for y in range(height):
        t = y / max(1, height - 1)
        image.paste(
            tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)),
            (0, y, width, y + 1),
        )
    draw = ImageDraw.Draw(image)
    font_size = max(14, height // 16)
    try:
        font = ImageFont.load_default(size=font_size)
    except TypeError:
        font = ImageFont.load_default()
    lines = textwrap.wrap(prompt, width=max(10, width // (font_size // 2 + 1)))[:6]
    y = height // 6
    for line in ["DEV PLACEHOLDER", *lines]:
        draw.text((width // 12, y), line, font=font, fill=(255, 255, 255))
        y += int(font_size * 1.4)
    image.save(path)
    return path


class DevGenerationExecutor:
    """Placeholder local generation matching the GenerationProvider result
    contract; run_generation handles everything downstream."""

    def __init__(self, store: ObjectStore | None = None):
        self.store = store or ObjectStore()
        log.warning("DEV ENGINES ACTIVE — placeholder generation, not production output")

    def generate(self, generation: Generation) -> ProviderResult:
        params = generation.params or {}
        seed = int(params.get("seed") or (generation.id.int % (2**31)))
        kind = generation.kind
        external_id = f"dev-{generation.id}"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            if kind == GenerationKind.image:
                width, height = _dims({**params, "width": params.get("width", 1024),
                                       "height": params.get("height", 1024)})
                card = _prompt_card(tmp_path / "card.png", generation.prompt, width, height, seed)
                return ProviderResult(
                    data=card.read_bytes(), content_type="image/png",
                    external_id=external_id, cost=0.0,
                )

            if kind == GenerationKind.music:
                duration_s = min(float(params.get("duration_s", 8)), 12.0)
                base = 220 + seed % 220
                wav = tmp_path / "bed.wav"
                _run([_find_ffmpeg(), "-y", "-hide_banner",
                      "-f", "lavfi", "-i", f"sine=frequency={base}:sample_rate=44100:duration={duration_s:.1f}",
                      "-f", "lavfi", "-i", f"sine=frequency={base * 3 // 2}:sample_rate=44100:duration={duration_s:.1f}",
                      "-filter_complex",
                      "[0:a][1:a]amix=inputs=2:normalize=0,tremolo=f=4:d=0.5,volume=0.4[a]",
                      "-map", "[a]", "-c:a", "pcm_s16le", str(wav)])
                return ProviderResult(
                    data=wav.read_bytes(), content_type="audio/wav",
                    external_id=external_id, cost=0.0,
                )

            if kind == GenerationKind.upscale:
                source_uri = params.get("source_asset_uri")
                if not source_uri:
                    raise ValueError("upscale needs params.source_asset_uri")
                _, key = self.store.parse_uri(source_uri)
                source = tmp_path / "source"
                self.store.get_file(key, source)
                output = tmp_path / "up.mp4"
                _run([_find_ffmpeg(), "-y", "-hide_banner", "-i", str(source),
                      "-vf", "scale=iw*2:ih*2:flags=lanczos",
                      "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", str(output)])
                return ProviderResult(
                    data=output.read_bytes(), content_type="video/mp4",
                    external_id=external_id, cost=0.0,
                )

            # t2v / i2v / v2v: prompt card looped into a short clip
            width, height = _dims(params)
            duration_s = min(float(params.get("duration_s", 3)), MAX_CLIP_S)
            card = _prompt_card(tmp_path / "card.png", generation.prompt, width, height, seed)
            clip = tmp_path / "clip.mp4"
            _run([_find_ffmpeg(), "-y", "-hide_banner", "-loop", "1", "-i", str(card),
                  "-t", f"{duration_s:.2f}", "-r", "16",
                  "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p", str(clip)])
            return ProviderResult(
                data=clip.read_bytes(), content_type="video/mp4",
                external_id=external_id, cost=0.0,
            )
