from __future__ import annotations

import uuid

from pipeline_core.segmenting import DEFAULT_PAUSE_MS, SEED_MAX, make_segments, split_script


def test_split_on_sentence_boundaries():
    assert split_script("First sentence. Second one! A third?") == [
        "First sentence.",
        "Second one!",
        "A third?",
    ]


def test_split_handles_newlines_and_whitespace():
    assert split_script("One.\n\n  Two.  \nThree without period") == [
        "One.",
        "Two.",
        "Three without period",
    ]


def test_split_empty_script():
    assert split_script("") == []
    assert split_script("   \n ") == []


def test_make_segments_pins_seeds_and_pauses():
    job_id = uuid.uuid4()
    segments = make_segments(job_id, "One. Two. Three.")
    assert [s.idx for s in segments] == [0, 1, 2]
    assert all(s.job_id == job_id for s in segments)
    assert all(s.seed is not None and 0 <= s.seed < SEED_MAX for s in segments)
    assert [s.pause_after_ms for s in segments] == [DEFAULT_PAUSE_MS, DEFAULT_PAUSE_MS, 0]
    assert all(s.audio_uri is None and s.duration_ms is None for s in segments)
