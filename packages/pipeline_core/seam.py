"""Perceptual seam comparison (M2) — pure image logic, shared by the loop
preprocessing worker.

dHash catches structural pops at the loop boundary; the colour distance
catches flat-colour pops a gradient hash is blind to. The seam score is the
max of both: a pop in either dimension shows.
"""

from __future__ import annotations

from pathlib import Path


def dhash(image, hash_size: int = 8) -> int:
    """Difference hash: robust to encode noise, sensitive to structure."""
    grey = image.convert("L").resize((hash_size + 1, hash_size))
    pixels = list(grey.getdata())
    bits = 0
    for row in range(hash_size):
        for col in range(hash_size):
            left = pixels[row * (hash_size + 1) + col]
            right = pixels[row * (hash_size + 1) + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def hamming_distance(a: int, b: int, bits: int = 64) -> float:
    """Normalized hamming distance in [0, 1]."""
    return bin(a ^ b).count("1") / bits


def color_distance(a, b, size: int = 8) -> float:
    """Mean absolute RGB difference on downscaled frames, normalized [0, 1]."""
    small_a = a.convert("RGB").resize((size, size))
    small_b = b.convert("RGB").resize((size, size))
    pairs = zip(small_a.getdata(), small_b.getdata())
    total = sum(abs(ca - cb) for pa, pb in pairs for ca, cb in zip(pa, pb))
    return total / (size * size * 3 * 255)


def frames_distance(first_png: Path, last_png: Path) -> float:
    """Perceptual distance between two frame files: max of structure/colour."""
    from PIL import Image

    with Image.open(first_png) as a, Image.open(last_png) as b:
        return max(hamming_distance(dhash(a), dhash(b)), color_distance(a, b))
