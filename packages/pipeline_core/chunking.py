"""Lip-sync chunk windows: 60-90 s, cut on segment boundaries.

Pure function of segment durations, so assembly can re-derive the exact same
windows the lip-sync stage rendered — no chunk list needs persisting.
"""

from __future__ import annotations

MIN_WINDOW_MS = 60_000
MAX_WINDOW_MS = 90_000


def chunk_windows(span_durations_ms: list[int]) -> list[tuple[int, int]]:
    """Greedily pack contiguous segment spans (duration + trailing pause) into
    windows of at most MAX_WINDOW_MS. A single span longer than the max gets a
    window of its own; only the final window may fall below MIN_WINDOW_MS."""
    windows: list[tuple[int, int]] = []
    start = 0
    acc = 0
    for span in span_durations_ms:
        if span < 0:
            raise ValueError("span durations must be non-negative")
        if acc > 0 and acc + span > MAX_WINDOW_MS:
            windows.append((start, start + acc))
            start += acc
            acc = 0
        acc += span
    if acc > 0:
        windows.append((start, start + acc))
    return windows
