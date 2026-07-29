"""Timeline document -> ffmpeg command (M16).

Pure argument construction — no I/O here, so every graph shape is golden-
testable without running ffmpeg. The compliance decision is INSIDE the
compiler and has no off-switch: a timeline containing any generated shot gets
the C1 watermark overlaid bottom-right for the full duration; callers cannot
opt out, they can only fail to supply the overlay file, which raises.

Encode per docs/pipeline-spec.md: H.264 CRF 18, yuv420p, +faststart, AAC.
A silent stereo track is always present for platform compatibility; music
beds arrive with M18 and replace it.
"""

from __future__ import annotations

FPS = 25


def watermark_required(timeline: dict) -> bool:
    return any(shot.get("origin") == "generated" for shot in timeline["shots"])


def build_ffmpeg_args(
    timeline: dict,
    shot_paths: list[str],
    output_path: str,
    watermark_png: str | None,
    text_pngs: list[str] | None = None,
    ffmpeg_bin: str = "ffmpeg",
) -> list[str]:
    shots = timeline["shots"]
    if len(shot_paths) != len(shots):
        raise ValueError("one input path per shot required")
    texts = timeline.get("texts", [])
    text_pngs = text_pngs or []
    if len(text_pngs) != len(texts):
        raise ValueError("one pre-rendered png per text overlay required")
    width, height = timeline["width"], timeline["height"]
    needs_watermark = watermark_required(timeline)
    if needs_watermark and not watermark_png:
        raise ValueError("C1: timeline contains generated shots — watermark overlay is mandatory")

    transition_s = timeline.get("transition_ms", 0) / 1000
    durations = [shot["duration_ms"] / 1000 for shot in shots]
    use_xfade = transition_s > 0 and len(shots) > 1

    args: list[str] = [ffmpeg_bin, "-y", "-hide_banner", "-nostdin"]
    for shot, duration, path in zip(shots, durations, shot_paths):
        in_s = shot.get("in_ms", 0) / 1000
        if in_s > 0:
            args += ["-ss", f"{in_s:.3f}"]
        args += ["-t", f"{duration:.3f}", "-i", path]

    input_count = len(shots)
    wm_index = None
    if needs_watermark:
        wm_index = input_count
        args += ["-i", watermark_png]
        input_count += 1

    text_indices = []
    for png in text_pngs:
        text_indices.append(input_count)
        args += ["-i", png]
        input_count += 1

    total_s = sum(durations)
    if use_xfade:
        total_s -= transition_s * (len(shots) - 1)
    audio_index = input_count
    args += [
        "-f", "lavfi",
        "-t", f"{total_s:.3f}",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
    ]

    filters: list[str] = []
    for i in range(len(shots)):
        filters.append(
            f"[{i}:v]fps={FPS},"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            f"setsar=1,setpts=PTS-STARTPTS[v{i}]"
        )

    if use_xfade:
        current = "v0"
        offset = 0.0
        for i in range(1, len(shots)):
            offset += durations[i - 1] - transition_s
            label = f"x{i}"
            filters.append(
                f"[{current}][v{i}]xfade=transition=fade:"
                f"duration={transition_s:.3f}:offset={offset:.3f}[{label}]"
            )
            current = label
        last = current
    elif len(shots) > 1:
        joined = "".join(f"[v{i}]" for i in range(len(shots)))
        filters.append(f"{joined}concat=n={len(shots)}:v=1:a=0[vcat]")
        last = "vcat"
    else:
        last = "v0"

    for n, (text, index) in enumerate(zip(texts, text_indices)):
        start_s = text["start_ms"] / 1000
        end_s = text["end_ms"] / 1000
        y_pct = text.get("y_pct", 0.8)
        label = f"vt{n}"
        filters.append(f"[{index}:v]format=rgba[t{n}]")
        filters.append(
            f"[{last}][t{n}]overlay=(W-w)/2:H*{y_pct:.3f}-h/2:"
            f"enable='between(t,{start_s:.3f},{end_s:.3f})'[{label}]"
        )
        last = label

    if needs_watermark:
        # C1: visible, bottom-right, full duration — no enable= window.
        # Applied AFTER text overlays so nothing can cover it.
        filters.append(f"[{wm_index}:v]format=rgba[wm]")
        filters.append(f"[{last}][wm]overlay=W-w-24:H-h-24[vout]")
        last = "vout"

    args += [
        "-filter_complex", ";".join(filters),
        "-map", f"[{last}]",
        "-map", f"{audio_index}:a",
        "-c:v", "libx264",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-c:a", "aac",
        "-b:a", "192k",
        "-t", f"{total_s:.3f}",
        output_path,
    ]
    return args
