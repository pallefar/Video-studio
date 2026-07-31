"""Caption burn-in support (M4): word timings -> caption lines.

Word-level timings come from faster-whisper when it is installed (int8 on
CPU per the pipeline spec). Until the model lands, a deterministic fallback
distributes each segment's measured duration evenly across its words —
segment durations are real (from TTS), so lines still appear in sync.

Captions are burned as Pillow-rendered PNG overlays with enable= windows
(same fontconfig-free approach as the C1 watermark and M16 text overlays)
instead of a libass subtitles filter, so static ffmpeg builds render
identically on rented boxes.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

log = structlog.get_logger()

MAX_LINE_CHARS = 38


@dataclass(frozen=True)
class Word:
    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class CaptionLine:
    text: str
    start_ms: int
    end_ms: int


def word_timings(segments: list[dict], voice_wav: str | None = None) -> list[Word]:
    """Word-level timings for the whole voice track.

    segments: ordered dicts with text, duration_ms, pause_after_ms.
    Tries faster-whisper on the assembled voice track first; falls back to
    the even-split estimator when the model isn't available.
    """
    if voice_wav is not None:
        try:
            return _whisper_timings(voice_wav)
        except ImportError:
            log.info("captions_fallback_even_split", reason="faster-whisper not installed")
        except Exception as exc:  # model load/transcribe failure must not kill assembly
            log.warning("captions_whisper_failed", error=str(exc))
    return even_split_timings(segments)


def _whisper_timings(voice_wav: str) -> list[Word]:
    from faster_whisper import WhisperModel  # lazy: optional dependency

    model = WhisperModel("small", device="cpu", compute_type="int8")
    result, _ = model.transcribe(voice_wav, word_timestamps=True)
    words: list[Word] = []
    for segment in result:
        for word in segment.words or []:
            words.append(Word(word.word.strip(), int(word.start * 1000), int(word.end * 1000)))
    if not words:
        raise RuntimeError("whisper returned no word timings")
    return words


def even_split_timings(segments: list[dict]) -> list[Word]:
    words: list[Word] = []
    clock_ms = 0
    for segment in segments:
        tokens = segment["text"].split()
        duration_ms = segment.get("duration_ms") or 0
        if tokens and duration_ms > 0:
            per_word = duration_ms / len(tokens)
            for n, token in enumerate(tokens):
                words.append(
                    Word(
                        token,
                        int(clock_ms + n * per_word),
                        int(clock_ms + (n + 1) * per_word),
                    )
                )
        clock_ms += duration_ms + segment.get("pause_after_ms", 0)
    return words


def caption_lines(words: list[Word], max_chars: int = MAX_LINE_CHARS) -> list[CaptionLine]:
    """Group words into readable lines; each line spans its words' timings."""
    lines: list[CaptionLine] = []
    current: list[Word] = []
    length = 0
    for word in words:
        added = len(word.text) + (1 if current else 0)
        if current and length + added > max_chars:
            lines.append(_line(current))
            current, length = [], 0
            added = len(word.text)
        current.append(word)
        length += added
    if current:
        lines.append(_line(current))
    return lines


def _line(words: list[Word]) -> CaptionLine:
    return CaptionLine(
        " ".join(w.text for w in words), words[0].start_ms, words[-1].end_ms
    )
