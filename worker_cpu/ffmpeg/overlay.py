"""Watermark overlay rendered as a transparent PNG (C1).

Pre-rendered with Pillow instead of drawtext so the burn-in never depends on
system fontconfig — static ffmpeg builds and rented boxes render identically.
"""

from __future__ import annotations

from pathlib import Path

WATERMARK_TEXT = "Made with AI"


def make_watermark_png(path: Path, frame_width: int, frame_height: int) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    font_size = max(16, frame_height // 30)
    try:
        font = ImageFont.load_default(size=font_size)
    except TypeError:  # older Pillow without size kwarg
        font = ImageFont.load_default()

    probe = Image.new("RGBA", (4, 4))
    bbox = ImageDraw.Draw(probe).textbbox((0, 0), WATERMARK_TEXT, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]

    pad = font_size // 2
    image = Image.new("RGBA", (text_w + pad * 2, text_h + pad * 2), (0, 0, 0, 90))
    draw = ImageDraw.Draw(image)
    draw.text((pad - bbox[0], pad - bbox[1]), WATERMARK_TEXT, font=font, fill=(255, 255, 255, 230))
    image.save(path)
    return path
