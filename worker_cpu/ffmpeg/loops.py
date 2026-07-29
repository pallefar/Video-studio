"""Loop preprocessing primitives (M2).

- VFR detection via ffmpeg's vfrdet filter (works on the static build — no
  ffprobe needed). VFR sources are rejected at ingest, never discovered as
  A/V drift at assembly (docs/pipeline-spec.md §5).
- Seam detection: perceptual hash (dHash) distance between the loop's first
  and last frame. A visible pop at the loop boundary shows up as a large
  hamming distance; the fallback is ping-pong playback (forward + reversed),
  which is seamless by construction.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

VFR_MAX_RATIO = 0.05   # tolerate container jitter, reject real VFR
SEAM_MAX_SCORE = 0.25  # normalized dHash hamming distance above this = pop

_VFR_RE = re.compile(r"VFR:([0-9.]+)")


def _run(args: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(args, capture_output=True, text=True, errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"{args[0]} failed: {result.stderr[-500:]}")
    return result


def vfr_ratio(ffmpeg_bin: str, source: Path) -> float:
    """Fraction of frames with irregular timestamps, from the vfrdet filter."""
    result = subprocess.run(
        [ffmpeg_bin, "-hide_banner", "-nostdin", "-i", str(source),
         "-vf", "vfrdet", "-an", "-f", "null", "-"],
        capture_output=True, text=True, errors="replace",
    )
    match = None
    for match in _VFR_RE.finditer(result.stderr):
        pass  # keep the last report (printed at stream end)
    if result.returncode != 0 or match is None:
        raise RuntimeError(f"vfrdet failed: {result.stderr[-500:]}")
    return float(match.group(1))


def _extract_frame(ffmpeg_bin: str, source: Path, out_png: Path, last: bool) -> Path:
    args = [ffmpeg_bin, "-y", "-hide_banner", "-nostdin"]
    if last:
        args += ["-sseof", "-0.2"]
    args += ["-i", str(source), "-frames:v", "1", "-update", "1", str(out_png)]
    _run(args)
    return out_png


def seam_score(ffmpeg_bin: str, source: Path, scratch_dir: Path) -> float:
    """Perceptual distance between the loop's first and last frame — the
    comparison itself lives in pipeline_core.seam."""
    from pipeline_core.seam import frames_distance

    first = _extract_frame(ffmpeg_bin, source, scratch_dir / "seam_first.png", last=False)
    last = _extract_frame(ffmpeg_bin, source, scratch_dir / "seam_last.png", last=True)
    return frames_distance(first, last)


def make_ping_pong(ffmpeg_bin: str, source: Path, output: Path) -> Path:
    """Forward + reversed copy: the loop boundary becomes a mirror point,
    seamless by construction. Video-only — base loops carry no audio."""
    _run(
        [ffmpeg_bin, "-y", "-hide_banner", "-nostdin", "-i", str(source),
         "-filter_complex", "[0:v]split[fwd][tail];[tail]reverse[rev];[fwd][rev]concat=n=2:v=1:a=0[v]",
         "-map", "[v]", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(output)]
    )
    return output
