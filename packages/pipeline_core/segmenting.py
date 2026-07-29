"""Script -> segments at job ingest.

The segment is the retry unit: each gets a pinned seed at creation so a
re-render reproduces the same take (or is deliberately re-seeded via the
per-segment re-render flow at M7).
"""

from __future__ import annotations

import re
import secrets
import uuid

from schema.models import Segment

SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]*")
DEFAULT_PAUSE_MS = 300
SEED_MAX = 2**31 - 1


def split_script(script: str) -> list[str]:
    sentences = [match.group(0).strip() for match in SENTENCE_RE.finditer(script)]
    return [s for s in sentences if s]


def make_segments(job_id: uuid.UUID, script: str) -> list[Segment]:
    sentences = split_script(script)
    segments = []
    for idx, text in enumerate(sentences):
        is_last = idx == len(sentences) - 1
        segments.append(
            Segment(
                job_id=job_id,
                idx=idx,
                text=text,
                pause_after_ms=0 if is_last else DEFAULT_PAUSE_MS,
                seed=secrets.randbelow(SEED_MAX),
            )
        )
    return segments
