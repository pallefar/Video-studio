from __future__ import annotations

import pytest

from pipeline_core.chunking import MAX_WINDOW_MS, MIN_WINDOW_MS, chunk_windows


def test_short_job_is_one_window():
    assert chunk_windows([10_000, 20_000]) == [(0, 30_000)]


def test_windows_are_contiguous_and_cover_everything():
    spans = [40_000] * 7  # 280 s total
    windows = chunk_windows(spans)
    assert windows[0][0] == 0
    for (_, prev_end), (start, _) in zip(windows, windows[1:]):
        assert start == prev_end
    assert windows[-1][1] == sum(spans)


def test_windows_respect_max():
    windows = chunk_windows([40_000] * 7)
    assert all(end - start <= MAX_WINDOW_MS for start, end in windows)


def test_only_last_window_may_undershoot_min():
    windows = chunk_windows([40_000] * 7)
    for start, end in windows[:-1]:
        assert end - start >= MIN_WINDOW_MS


def test_single_overlong_span_gets_own_window():
    windows = chunk_windows([120_000, 30_000, 40_000])
    assert windows[0] == (0, 120_000)
    assert all(end - start <= MAX_WINDOW_MS for start, end in windows[1:])


def test_rejects_negative_spans():
    with pytest.raises(ValueError):
        chunk_windows([1_000, -1])
