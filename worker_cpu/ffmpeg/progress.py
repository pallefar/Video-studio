"""ffmpeg -progress parsing (M16): live in-render progress.

ffmpeg's `-progress pipe:1` emits key=value lines in blocks terminated by a
`progress=continue|end` line. The runner inserts the flags, streams stdout,
and invokes a callback with rendered output milliseconds per block — the
export stage records those into the metrics table so the panel can poll a
render's position while it is still encoding.

stderr goes to a spool file (not a pipe) so a chatty encode can never
deadlock the stdout reader; on failure its tail becomes the error message.
"""

from __future__ import annotations

import subprocess
import tempfile
from typing import Callable, Iterator, TextIO

ProgressCallback = Callable[[int], None]


def parse_progress_blocks(lines: Iterator[str]) -> Iterator[dict[str, str]]:
    """Group `key=value` lines into blocks; `progress=` closes each block."""
    block: dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        block[key] = value
        if key == "progress":
            yield block
            block = {}
    if block:
        yield block


def rendered_ms(block: dict[str, str]) -> int | None:
    """Output position in ms. out_time_us is authoritative; out_time_ms is a
    misnomer (ffmpeg reports microseconds there too) kept as the fallback."""
    for key in ("out_time_us", "out_time_ms"):
        raw = block.get(key)
        if raw is None:
            continue
        try:
            return max(0, int(raw) // 1000)
        except ValueError:
            continue
    return None


def run_ffmpeg_with_progress(
    args: list[str], on_progress: ProgressCallback | None = None, label: str = "ffmpeg"
) -> None:
    """Run an ffmpeg command with `-progress pipe:1 -nostats` injected,
    invoking on_progress(rendered_ms) per progress block. Raises RuntimeError
    with the stderr tail on a non-zero exit, like a checked run."""
    full_args = [args[0], "-progress", "pipe:1", "-nostats", *args[1:]]
    with tempfile.TemporaryFile(mode="w+", errors="replace") as stderr_spool:
        process = subprocess.Popen(
            full_args, stdout=subprocess.PIPE, stderr=stderr_spool, text=True, errors="replace"
        )
        assert process.stdout is not None
        try:
            for block in parse_progress_blocks(process.stdout):
                position = rendered_ms(block)
                if position is not None and on_progress is not None:
                    on_progress(position)
        finally:
            process.stdout.close()
            returncode = process.wait()
        if returncode != 0:
            raise RuntimeError(f"{label} failed: {_tail(stderr_spool)}")


def _tail(spool: TextIO, limit: int = 800) -> str:
    spool.seek(0)
    return spool.read()[-limit:]
