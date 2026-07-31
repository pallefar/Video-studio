"""Dev engines (DEV_ENGINES=1) — the avatar pipeline without CUDA.

Purpose: testing the whole system on machines that can't run the real
models (Apple Silicon MacBooks, CI containers). The pipeline shape is
identical — same stages, same idempotency keys, same artefact layout — only
the model output is placeholder:

- DevTTSEngine: on macOS, real speech via the system `say` voice (emotion
  presets map to speaking rate); elsewhere, an amplitude-modulated tone with
  a realistic words-per-minute duration. Either way real wavs with real
  durations land in the store, so chunking, captions, and assembly behave
  exactly as they will with Chatterbox.
- DevLipsyncEngine: cycles the base loop to each chunk window with ffmpeg —
  a static avatar instead of a lip-synced one, at the exact window length
  MuseTalk would produce.

Never a production path: the engines announce themselves loudly at load and
the real engines remain the default. The sm_86 constraint applies to the
GPU host; dev engines exist precisely for hosts that aren't it.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
import uuid as uuidlib
from pathlib import Path

import structlog

from pipeline_core.storage import ObjectStore

log = structlog.get_logger()

WORDS_PER_MINUTE = 150  # fallback duration estimate when `say` is absent


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


class DevTTSEngine:
    """Placeholder Chatterbox: real speech on macOS (`say`), tone elsewhere."""

    def __init__(self, store: ObjectStore):
        self.store = store
        self._say = None

    def load(self) -> None:
        self._say = shutil.which("say") if platform.system() == "Darwin" else None
        log.warning(
            "DEV ENGINES ACTIVE — placeholder TTS, not production output",
            voice="macos-say" if self._say else "modulated-tone",
        )

    def synthesize_segment(
        self, job_id: str, segment_idx: int, text: str, seed: int, emotion: dict | None = None
    ) -> tuple[str, int]:
        ffmpeg = _find_ffmpeg()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wav = tmp_path / "segment.wav"
            if self._say:
                # emotion presets map to speaking rate: urgent talks faster
                cfg = (emotion or {}).get("cfg_weight", 0.5)
                rate = int(180 * (1.4 - cfg * 0.8))
                aiff = tmp_path / "segment.aiff"
                _run([self._say, "-r", str(rate), "-o", str(aiff), text])
                _run([ffmpeg, "-y", "-hide_banner", "-i", str(aiff),
                      "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(wav)])
            else:
                words = max(1, len(text.split()))
                duration_s = words * 60 / WORDS_PER_MINUTE
                base_freq = 180 + (seed or 0) % 80  # seed keeps re-renders stable
                exaggeration = (emotion or {}).get("exaggeration", 0.5)
                _run([ffmpeg, "-y", "-hide_banner",
                      "-f", "lavfi",
                      "-i", f"sine=frequency={base_freq}:sample_rate=48000:duration={duration_s:.2f}",
                      "-af", f"tremolo=f={3 + exaggeration * 5:.1f}:d=0.7,volume=0.5,aformat=channel_layouts=stereo",
                      "-c:a", "pcm_s16le", str(wav)])

            from worker_cpu.ffmpeg.ingest import probe

            duration_ms = probe(ffmpeg, wav)["duration_ms"] or 1000
            key = f"jobs/{job_id}/tts/{segment_idx}.wav"
            uri = self.store.put_file(key, wav)
        log.info("dev_tts_segment", job_id=job_id, idx=segment_idx, duration_ms=duration_ms)
        return uri, duration_ms


class DevLipsyncEngine:
    """Placeholder MuseTalk: the base loop cycled to the chunk window."""

    def __init__(self, store: ObjectStore):
        self.store = store

    def load(self) -> None:
        log.warning("DEV ENGINES ACTIVE — placeholder lipsync (static loop), not production output")

    def sync_chunk(self, job_id: str, loop_id: str, start_ms: int, end_ms: int) -> str:
        from pipeline_core.db import open_session
        from schema.models import BaseLoop

        with open_session() as session:
            loop = session.get(BaseLoop, uuidlib.UUID(loop_id))
            if loop is None:
                raise ValueError(f"loop {loop_id} not found")
            source_uri = loop.source_uri

        ffmpeg = _find_ffmpeg()
        duration_s = (end_ms - start_ms) / 1000
        _, key = self.store.parse_uri(source_uri)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "loop.mp4"
            self.store.get_file(key, source)
            chunk = tmp_path / "chunk.mp4"
            _run([ffmpeg, "-y", "-hide_banner", "-stream_loop", "-1", "-i", str(source),
                  "-t", f"{duration_s:.3f}", "-an",
                  "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p", str(chunk)])
            chunk_key = f"jobs/{job_id}/lipsync/{start_ms}_{end_ms}.mp4"
            uri = self.store.put_file(chunk_key, chunk)
        log.info("dev_lipsync_chunk", job_id=job_id, start_ms=start_ms, end_ms=end_ms)
        return uri
