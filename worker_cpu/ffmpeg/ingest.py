"""Asset ingest derivatives (M14): probe, 720p proxy, scrub sprites + WebVTT,
waveform peaks. All ffmpeg-native; duration/stream info is parsed from
`ffmpeg -i` stderr so no separate ffprobe binary is needed (the static
imageio-ffmpeg build ships only ffmpeg).
"""

from __future__ import annotations

import math
import re
import subprocess
from array import array
from pathlib import Path

PROXY_HEIGHT = 720
SPRITE_THUMB_W = 160
SPRITE_COLS = 10
MAX_THUMBS = 100

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)")
_VIDEO_RE = re.compile(r"Stream #.*Video:.* (\d{2,5})x(\d{2,5})")
_FPS_RE = re.compile(r"(\d+(?:\.\d+)?) fps")
_AUDIO_RE = re.compile(r"Stream #.*Audio:")


def probe(ffmpeg_bin: str, path: Path) -> dict:
    """Parse duration/resolution/fps/audio presence from ffmpeg -i stderr."""
    result = subprocess.run([ffmpeg_bin, "-hide_banner", "-i", str(path)], capture_output=True)
    stderr = result.stderr.decode(errors="replace")

    info: dict = {"duration_ms": None, "width": None, "height": None, "fps": None, "has_audio": False}
    if match := _DURATION_RE.search(stderr):
        h, m, s, frac = match.groups()
        info["duration_ms"] = ((int(h) * 3600 + int(m) * 60 + int(s)) * 1000) + int(frac.ljust(3, "0")[:3])
    if match := _VIDEO_RE.search(stderr):
        info["width"], info["height"] = int(match.group(1)), int(match.group(2))
    if match := _FPS_RE.search(stderr):
        info["fps"] = float(match.group(1))
    info["has_audio"] = bool(_AUDIO_RE.search(stderr))
    return info


def make_proxy(ffmpeg_bin: str, src: Path, dst: Path, has_audio: bool) -> Path:
    """720p short-GOP H.264 proxy for snappy editor seeking."""
    args = [
        ffmpeg_bin, "-y", "-hide_banner", "-nostdin", "-i", str(src),
        "-vf", f"scale=-2:'min({PROXY_HEIGHT},ih)'",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-g", "30",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
    ]
    args += ["-c:a", "aac", "-b:a", "128k"] if has_audio else ["-an"]
    args.append(str(dst))
    subprocess.run(args, check=True, capture_output=True)
    return dst


def make_poster(ffmpeg_bin: str, src: Path, dst: Path, duration_ms: int) -> Path:
    """Single poster frame (~25% in) — the library/dashboard thumbnail.
    The sprite sheet is a tiled mosaic and reads as a grid when used as a
    thumb; this is the one-frame answer."""
    at_s = max(0.0, (duration_ms / 1000) * 0.25)
    subprocess.run(
        [ffmpeg_bin, "-y", "-hide_banner", "-nostdin", "-ss", f"{at_s:.3f}",
         "-i", str(src), "-frames:v", "1", "-vf", "scale=480:-2",
         "-q:v", "4", str(dst)],
        check=True, capture_output=True,
    )
    return dst


def sprite_plan(duration_ms: int, width: int, height: int) -> dict:
    interval_s = max(1, math.ceil(duration_ms / 1000 / MAX_THUMBS))
    count = max(1, math.ceil(duration_ms / 1000 / interval_s))
    thumb_h = max(2, round(SPRITE_THUMB_W * height / width / 2) * 2)
    rows = math.ceil(count / SPRITE_COLS)
    return {
        "interval_s": interval_s,
        "count": count,
        "thumb_w": SPRITE_THUMB_W,
        "thumb_h": thumb_h,
        "cols": SPRITE_COLS,
        "rows": rows,
    }


def make_sprites(ffmpeg_bin: str, src: Path, dst: Path, plan: dict) -> Path:
    subprocess.run(
        [
            ffmpeg_bin, "-y", "-hide_banner", "-nostdin", "-i", str(src),
            "-vf",
            f"fps=1/{plan['interval_s']},scale={plan['thumb_w']}:{plan['thumb_h']},"
            f"tile={plan['cols']}x{plan['rows']}",
            "-frames:v", "1", "-q:v", "4", str(dst),
        ],
        check=True, capture_output=True,
    )
    return dst


def _vtt_time(ms: int) -> str:
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def make_vtt(plan: dict, duration_ms: int, sprite_name: str = "sprite.jpg") -> str:
    lines = ["WEBVTT", ""]
    step = plan["interval_s"] * 1000
    for i in range(plan["count"]):
        start = i * step
        end = min((i + 1) * step, duration_ms)
        if start >= duration_ms:
            break
        x = (i % plan["cols"]) * plan["thumb_w"]
        y = (i // plan["cols"]) * plan["thumb_h"]
        lines += [
            f"{_vtt_time(start)} --> {_vtt_time(end)}",
            f"{sprite_name}#xywh={x},{y},{plan['thumb_w']},{plan['thumb_h']}",
            "",
        ]
    return "\n".join(lines)


def waveform_peaks(ffmpeg_bin: str, src: Path, buckets: int = 400) -> list[float]:
    """Normalised per-bucket peak levels from mono 8 kHz PCM. Empty when the
    source has no audio stream."""
    result = subprocess.run(
        [ffmpeg_bin, "-hide_banner", "-nostdin", "-i", str(src),
         "-map", "a:0?", "-f", "s16le", "-ac", "1", "-ar", "8000", "-"],
        capture_output=True,
    )
    data = result.stdout
    if len(data) < 2:
        return []
    samples = array("h")
    samples.frombytes(data[: len(data) - (len(data) % 2)])
    if not samples:
        return []
    bucket_size = max(1, len(samples) // buckets)
    peaks = []
    for i in range(0, len(samples), bucket_size):
        chunk = samples[i : i + bucket_size]
        peaks.append(max(abs(v) for v in chunk) / 32768)
    return peaks[:buckets]
