"""Final assembly (M4): voice bus -> two-pass loudnorm -> chunk concat ->
b-roll overlays -> caption burn-in -> C1 watermark -> encode.

Chain order per docs/pipeline-spec.md §4: two-pass loudnorm to -14 LUFS
(I=-14:TP=-1.5:LRA=11, YouTube's normalisation target), then the video graph:
lipsync chunks concatenated, b-roll overlaid at beat timestamps (avatar audio
continues underneath), captions from word timings, and the C1 watermark LAST
so nothing can cover it — full duration, bottom-right, no off-switch: avatar
output is always synthetic media. Encode: libx264 CRF 18, yuv420p,
+faststart, AAC 192k. The Chatterbox audio watermark must survive this chain
(C3) — near-ultrasonic content is preserved through loudnorm + AAC 192k,
verified by the encode round-trip test.

Sources arrive and results leave via ObjectStore; scratch space comes from
tempfile, never a hardcoded path.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import structlog

from pipeline_core.storage import ObjectStore
from worker_cpu.ffmpeg.captions import CaptionLine, caption_lines, word_timings
from worker_cpu.ffmpeg.overlay import make_text_png, make_watermark_png
from worker_cpu.ffmpeg.progress import run_ffmpeg_with_progress

log = structlog.get_logger()

FPS = 25
WIDTH, HEIGHT = 1920, 1080
LOUDNORM = "loudnorm=I=-14:TP=-1.5:LRA=11"
BROLL_MAX_MS = 4000  # a b-roll insert never covers more than 4 s of avatar


def build_voice_args(
    wav_paths: list[str], pauses_ms: list[int], output_path: str, ffmpeg_bin: str = "ffmpeg"
) -> list[str]:
    """Concatenate segment wavs with their trailing pauses into one voice
    track (48 kHz stereo pcm). Pure argument construction."""
    if len(wav_paths) != len(pauses_ms):
        raise ValueError("one pause per segment required")
    args: list[str] = [ffmpeg_bin, "-y", "-hide_banner", "-nostdin"]
    for path in wav_paths:
        args += ["-i", path]
    filters, labels = [], []
    for i, pause_ms in enumerate(pauses_ms):
        filters.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS[s{i}]")
        labels.append(f"[s{i}]")
        if pause_ms > 0:
            filters.append(
                f"anullsrc=channel_layout=stereo:sample_rate=48000,atrim=0:{pause_ms / 1000:.3f}[p{i}]"
            )
            labels.append(f"[p{i}]")
    filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[voice]")
    args += ["-filter_complex", ";".join(filters), "-map", "[voice]",
             "-c:a", "pcm_s16le", output_path]
    return args


def measure_loudness(voice_path: str, ffmpeg_bin: str = "ffmpeg") -> dict:
    """Pass one of two-pass loudnorm: measure and parse the stats JSON."""
    result = subprocess.run(
        [ffmpeg_bin, "-hide_banner", "-nostdin", "-i", voice_path,
         "-af", f"{LOUDNORM}:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, errors="replace",
    )
    stderr = result.stderr
    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if result.returncode != 0 or start == -1 or end == -1:
        raise RuntimeError(f"loudnorm measure failed: {stderr[-500:]}")
    return json.loads(stderr[start : end + 1])


def normalize_voice(
    voice_path: str, output_path: str, measured: dict, ffmpeg_bin: str = "ffmpeg"
) -> None:
    """Pass two: apply loudnorm with the measured values (linear mode)."""
    applied = (
        f"{LOUDNORM}"
        f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}:linear=true"
    )
    result = subprocess.run(
        [ffmpeg_bin, "-y", "-hide_banner", "-nostdin", "-i", voice_path,
         "-af", f"{applied},aresample=48000", "-c:a", "pcm_s16le", output_path],
        capture_output=True, text=True, errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"loudnorm apply failed: {result.stderr[-500:]}")


def build_assemble_args(
    chunk_paths: list[str],
    voice_path: str,
    watermark_png: str,
    output_path: str,
    captions: list[CaptionLine] | None = None,
    caption_pngs: list[str] | None = None,
    broll: list[dict] | None = None,  # {path, start_ms, end_ms}
    total_ms: int = 0,
    width: int = WIDTH,
    height: int = HEIGHT,
    ffmpeg_bin: str = "ffmpeg",
) -> list[str]:
    """The final render command. Pure argument construction — golden-testable.

    Input order: chunks, watermark png, caption pngs, b-roll videos, voice.
    Overlay order: b-roll -> captions -> watermark (C1 is applied LAST and has
    no enable= window: full duration, nothing may cover it).
    """
    if not chunk_paths:
        raise ValueError("assembly needs at least one lipsync chunk")
    captions = captions or []
    caption_pngs = caption_pngs or []
    if len(captions) != len(caption_pngs):
        raise ValueError("one pre-rendered png per caption line required")
    broll = broll or []

    args: list[str] = [ffmpeg_bin, "-y", "-hide_banner", "-nostdin"]
    for path in chunk_paths:
        args += ["-i", path]
    wm_index = len(chunk_paths)
    args += ["-i", watermark_png]
    caption_start = wm_index + 1
    for png in caption_pngs:
        args += ["-i", png]
    broll_start = caption_start + len(caption_pngs)
    for clip in broll:
        args += ["-i", clip["path"]]
    voice_index = broll_start + len(broll)
    args += ["-i", voice_path]

    filters: list[str] = []
    for i in range(len(chunk_paths)):
        filters.append(
            f"[{i}:v]fps={FPS},scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,setpts=PTS-STARTPTS[c{i}]"
        )
    if len(chunk_paths) > 1:
        joined = "".join(f"[c{i}]" for i in range(len(chunk_paths)))
        filters.append(f"{joined}concat=n={len(chunk_paths)}:v=1:a=0[base]")
        last = "base"
    else:
        last = "c0"

    # B-roll cutaways: full-frame overlay windows; the voice bus continues.
    for j, clip in enumerate(broll):
        index = broll_start + j
        start_s, end_s = clip["start_ms"] / 1000, clip["end_ms"] / 1000
        filters.append(
            f"[{index}:v]fps={FPS},scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
            f"setpts=PTS-STARTPTS+{start_s:.3f}/TB[b{j}]"
        )
        filters.append(
            f"[{last}][b{j}]overlay=0:0:enable='between(t,{start_s:.3f},{end_s:.3f})':eof_action=pass[o{j}]"
        )
        last = f"o{j}"

    for t, line in enumerate(captions):
        index = caption_start + t
        start_s, end_s = line.start_ms / 1000, line.end_ms / 1000
        filters.append(f"[{index}:v]format=rgba[t{t}]")
        filters.append(
            f"[{last}][t{t}]overlay=(W-w)/2:H*0.88-h/2:"
            f"enable='between(t,{start_s:.3f},{end_s:.3f})'[ct{t}]"
        )
        last = f"ct{t}"

    # C1: watermark LAST, full duration — deliberately no enable= window.
    filters.append(f"[{wm_index}:v]format=rgba[wm]")
    filters.append(f"[{last}][wm]overlay=W-w-24:H-h-24[vout]")

    args += [
        "-filter_complex", ";".join(filters),
        "-map", "[vout]",
        "-map", f"{voice_index}:a",
        "-c:v", "libx264",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-c:a", "aac",
        "-b:a", "192k",
    ]
    if total_ms > 0:
        args += ["-t", f"{total_ms / 1000:.3f}"]
    args.append(output_path)
    return args


def chunk_keys_for_job(store: ObjectStore, job_id: str) -> list[str]:
    """Lipsync chunk keys ordered by window start ({start}_{end}.mp4)."""
    prefix = f"jobs/{job_id}/lipsync/"
    keys = [k for k in store.list_keys(prefix) if k.endswith(".mp4")]

    def window_start(key: str) -> int:
        stem = key.rsplit("/", 1)[-1].removesuffix(".mp4")
        try:
            return int(stem.split("_")[0])
        except ValueError:
            return 0

    return sorted(keys, key=window_start)


def assemble(
    store: ObjectStore,
    job_id: str,
    segments: list[dict],
    broll: list[dict] | None = None,  # {uri, start_ms, end_ms}
    ffmpeg_bin: str = "ffmpeg",
    width: int = WIDTH,
    height: int = HEIGHT,
    on_progress=None,
) -> str:
    """Run the full chain and return the uploaded final.mp4 uri."""
    chunk_keys = chunk_keys_for_job(store, job_id)
    if not chunk_keys:
        raise RuntimeError(f"job {job_id}: no lipsync chunks in store")
    missing = [s["idx"] for s in segments if not s.get("audio_uri")]
    if missing:
        raise RuntimeError(f"job {job_id}: segments without audio: {missing}")

    total_ms = sum((s.get("duration_ms") or 0) + s.get("pause_after_ms", 0) for s in segments)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        wav_paths = []
        for segment in segments:
            _, key = store.parse_uri(segment["audio_uri"])
            local = tmp_path / f"seg_{segment['idx']}.wav"
            store.get_file(key, local)
            wav_paths.append(str(local))

        chunk_paths = []
        for n, key in enumerate(chunk_keys):
            local = tmp_path / f"chunk_{n}.mp4"
            store.get_file(key, local)
            chunk_paths.append(str(local))

        # 1) voice bus, 2) measure, 3) apply -14 LUFS
        voice_raw = str(tmp_path / "voice_raw.wav")
        pauses = [s.get("pause_after_ms", 0) for s in segments]
        run_ffmpeg_with_progress(
            build_voice_args(wav_paths, pauses, voice_raw, ffmpeg_bin),
            label=f"voice bus {job_id}",
        )
        measured = measure_loudness(voice_raw, ffmpeg_bin)
        voice_norm = str(tmp_path / "voice.wav")
        normalize_voice(voice_raw, voice_norm, measured, ffmpeg_bin)
        log.info("assemble_loudnorm", job_id=job_id, input_i=measured.get("input_i"))

        # 4) captions from word timings
        lines = caption_lines(word_timings(segments, voice_norm))
        caption_pngs = [
            str(make_text_png(tmp_path / f"cap_{n}.png", line.text, height, scale=22))
            for n, line in enumerate(lines)
        ]

        # 5) b-roll downloads
        broll_local = []
        for n, clip in enumerate(broll or []):
            _, key = store.parse_uri(clip["uri"])
            local = tmp_path / f"broll_{n}.mp4"
            store.get_file(key, local)
            broll_local.append(
                {"path": str(local), "start_ms": clip["start_ms"], "end_ms": clip["end_ms"]}
            )

        watermark = str(make_watermark_png(tmp_path / "watermark.png", width, height))
        output = tmp_path / "final.mp4"
        args = build_assemble_args(
            chunk_paths, voice_norm, watermark, str(output),
            captions=lines, caption_pngs=caption_pngs, broll=broll_local,
            total_ms=total_ms, width=width, height=height, ffmpeg_bin=ffmpeg_bin,
        )
        run_ffmpeg_with_progress(args, on_progress=on_progress, label=f"assemble {job_id}")
        uri = store.put_file(f"jobs/{job_id}/final.mp4", output)

    log.info("assemble_done", job_id=job_id, uri=uri, captions=len(lines), broll=len(broll_local))
    return uri
