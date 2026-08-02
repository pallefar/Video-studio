"""Shared CUDA-free contract layer for the render engines (Chatterbox TTS +
MuseTalk lip-sync) and their dev-mode placeholders.

Owns everything both the real and dev engines need, so each contract has
exactly one definition in the codebase: the project's audio convention, the
ffmpeg binary lookup, the artefact key shapes, and the lip-sync window audio
reconstruction. None of this touches a model or a GPU — it is fully
verifiable with real ffmpeg on a machine with no CUDA device.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from pipeline_core.storage import ObjectStore

# The project's audio convention: 48 kHz stereo. The assembler's voice-bus
# build already resamples every input defensively to this rate as a safety
# net (worker_cpu/ffmpeg/assemble.py::build_voice_args) — engines emit the
# convention directly at the source instead of leaning on that net.
PROJECT_SAMPLE_RATE = 48000
PROJECT_CHANNELS = 2


def find_ffmpeg() -> str:
    """Locate an ffmpeg binary: system PATH first, else the bundled
    imageio_ffmpeg static build."""
    binary = shutil.which("ffmpeg")
    if binary:
        return binary
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(args: list[str]) -> None:
    """Run an ffmpeg command, raising with the tail of stderr on failure."""
    result = subprocess.run(args, capture_output=True, text=True, errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"{args[0]} failed: {result.stderr[-400:]}")


def tts_segment_key(job_id: str, segment_idx: int) -> str:
    """The artefact key for one segment's synthesized WAV."""
    return f"jobs/{job_id}/tts/{segment_idx}.wav"


def lipsync_chunk_key(job_id: str, start_ms: int, end_ms: int) -> str:
    """The artefact key for one lip-sync chunk MP4.

    CONSUMER CONTRACT: the assembler's chunk-key lookup globs
    `jobs/{job_id}/lipsync/*.mp4` and sorts chunks by the integer before the
    first underscore in the filename stem. This shape is load bearing, not a
    naming preference — any other shape silently drops or misorders chunks
    at assembly time.
    """
    return f"jobs/{job_id}/lipsync/{start_ms}_{end_ms}.mp4"


def write_project_wav(ffmpeg_bin: str, src: Path, dst: Path) -> Path:
    """Re-encode any WAV to the project convention (48 kHz stereo,
    pcm_s16le). Chatterbox emits 24 kHz mono; this is where that becomes the
    project's format, at the engine layer, rather than being papered over
    downstream."""
    run_ffmpeg(
        [
            ffmpeg_bin, "-y", "-hide_banner", "-nostdin", "-i", str(src),
            "-ar", str(PROJECT_SAMPLE_RATE), "-ac", str(PROJECT_CHANNELS),
            "-c:a", "pcm_s16le", str(dst),
        ]
    )
    return dst


def build_window_audio(
    ffmpeg_bin: str,
    store: ObjectStore,
    segments: list[dict],
    start_ms: int,
    end_ms: int,
    dst: Path,
) -> Path:
    """Reconstruct the audio for one lip-sync window from segment WAVs.

    `segments` is a list of plain dicts carrying idx, audio_uri, duration_ms
    and pause_after_ms — free of DB/schema imports so this stays trivially
    testable. Each segment's audio is laid on the concatenated timeline at
    the offset implied by the running sum of `duration_ms + pause_after_ms`
    (the same spans the lip-sync stage feeds to `chunk_windows()`), with
    silence inserted for each trailing pause. The full timeline is padded up
    to its declared total length (never trimmed short by a source that
    encoded a few ms shorter than its declared duration), then the window
    [start_ms, end_ms) is trimmed out and re-encoded to the project
    convention. The output is exactly `end_ms - start_ms` long.
    """
    total_ms = sum((s.get("duration_ms") or 0) + s.get("pause_after_ms", 0) for s in segments)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        wav_paths: list[str] = []
        pauses: list[int] = []
        for segment in segments:
            _, key = store.parse_uri(segment["audio_uri"])
            local = tmp_path / f"seg_{segment['idx']}.wav"
            store.get_file(key, local)
            wav_paths.append(str(local))
            pauses.append(segment.get("pause_after_ms", 0))

        full = tmp_path / "full_timeline.wav"
        args = [ffmpeg_bin, "-y", "-hide_banner", "-nostdin"]
        for path in wav_paths:
            args += ["-i", path]

        filters: list[str] = []
        labels: list[str] = []
        for i, pause_ms in enumerate(pauses):
            filters.append(
                f"[{i}:a]aresample={PROJECT_SAMPLE_RATE},"
                f"aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS[s{i}]"
            )
            labels.append(f"[s{i}]")
            if pause_ms > 0:
                filters.append(
                    f"anullsrc=channel_layout=stereo:sample_rate={PROJECT_SAMPLE_RATE},"
                    f"atrim=0:{pause_ms / 1000:.3f}[p{i}]"
                )
                labels.append(f"[p{i}]")
        filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[joined]")
        total_s = total_ms / 1000
        filters.append(f"[joined]apad=whole_dur={total_s:.3f}[full]")
        args += [
            "-filter_complex", ";".join(filters),
            "-map", "[full]", "-c:a", "pcm_s16le", str(full),
        ]
        run_ffmpeg(args)

        start_s = start_ms / 1000
        duration_s = (end_ms - start_ms) / 1000
        run_ffmpeg(
            [
                ffmpeg_bin, "-y", "-hide_banner", "-nostdin", "-i", str(full),
                "-ss", f"{start_s:.3f}", "-t", f"{duration_s:.3f}",
                "-af", "asetpts=PTS-STARTPTS",
                "-ar", str(PROJECT_SAMPLE_RATE), "-ac", str(PROJECT_CHANNELS),
                "-c:a", "pcm_s16le", str(dst),
            ]
        )

    return dst
