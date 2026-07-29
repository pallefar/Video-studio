"""Caption/beat text embeddings for the asset resolver (M8).

Default is a deterministic, dependency-free feature-hashing embedder — good
enough for lexical matching over a few hundred captions. Install the [embed]
extra to swap in a real sentence-transformer (loaded lazily, runs on CPU).
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

EMBED_DIM = 256

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


class HashingEmbedder:
    """Stable bag-of-words feature hashing with signed buckets, L2-normalised."""

    dim = EMBED_DIM

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in _TOKEN_RE.findall(text.lower()):
            digest = hashlib.md5(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            return vector
        return [v / norm for v in vector]


def get_embedder() -> Embedder:
    try:
        from sentence_transformers import SentenceTransformer  # [embed] extra
    except ImportError:
        return HashingEmbedder()

    class _SentenceTransformerEmbedder:
        def __init__(self):
            self._model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

        def embed(self, text: str) -> list[float]:
            return self._model.encode(text, normalize_embeddings=True).tolist()

    return _SentenceTransformerEmbedder()


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))  # inputs are L2-normalised
