#!/usr/bin/env python3
"""M0/M2 benchmark harness. Measure, don't trust estimates.

--smoke : load Chatterbox + MuseTalk together, render a real ~10 s TTS clip
          and a real 5 s lip-sync chunk through the engines' own public
          methods, log the card's actual peak VRAM occupancy (not just
          torch's allocator bookkeeping), and assert it stays under 20 GB.
          Its numbers replace the PLACEHOLDER table in docs/pipeline-spec.md §6.
          Selectors: --voice <id> / --base-loop <id> (default: most recently
          created row of each).
--loop  : (M2) render twice against one loop and report the latent-cache
          speedup; acceptance is a cached run >= 40% faster. Matches lipsync
          metric rows by loop via a shared ref-suffix helper (not a
          substring), so a pre-fix or other-loop row can never satisfy it.

Requires the GPU host: pip install -e ".[gpu]". Exits 1 with a clear message
anywhere else.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import uuid
from pathlib import Path

VRAM_BUDGET_GB = 20.0

# Roughly ten seconds of natural-pace speech (~2.5 words/s), kept as one
# sentence so pipeline_core.segmenting.make_segments yields exactly one
# segment — the smoke only needs to drive synthesize_segment once.
SMOKE_SCRIPT = (
    "This is bench dot pie's smoke test, rendering one real Chatterbox "
    "segment to measure the render lane's actual footprint on this card, "
    "spoken at a natural pace so the clip reaches roughly ten seconds in "
    "length."
)
TTS_MIN_DURATION_MS = 10_000
CHUNK_TARGET_DURATION_MS = 5_000
CHUNK_TOLERANCE_MS = 250
LIPSYNC_CHUNK_START_MS = 0
LIPSYNC_CHUNK_END_MS = 5_000


def _require_gpu():
    try:
        import torch
    except ImportError:
        print(
            'bench.py requires a CUDA device: install the GPU extra first — '
            'pip install -e ".[gpu]"',
            file=sys.stderr,
        )
        raise SystemExit(1)
    if not torch.cuda.is_available():
        print("bench.py requires a CUDA device — run scripts/verify_gpu.py first", file=sys.stderr)
        raise SystemExit(1)
    return torch


def _nvidia_smi_used_gb() -> float | None:
    """Device-level VRAM in use right now, sampled via `nvidia-smi
    --query-gpu=memory.used`. This is the figure the 20 GB budget is judged
    against: torch's own counters (allocated/reserved) cover only its
    caching allocator and exclude the CUDA context and MuseTalk's mmlab CUDA
    ops, both of which occupy real space on the card. Returns None — never
    raises — when nvidia-smi is unavailable, so callers fall back."""
    import subprocess

    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        return int(lines[0]) / 1024
    except ValueError:
        return None


def _resolve_render_inputs(voice_arg: str | None, base_loop_arg: str | None) -> tuple[uuid.UUID, uuid.UUID]:
    """Resolve the VoiceProfile and BaseLoop ids to render against,
    defaulting to the most recently created row of each. Runs before any
    model is loaded: a fresh host with neither entity created yet is the
    most likely first failure, and this fails in two seconds rather than
    after a multi-GB load."""
    from sqlmodel import Session, select

    from pipeline_core.db import get_engine
    from schema.models import BaseLoop, VoiceProfile

    with Session(get_engine()) as session:
        if voice_arg:
            voice = session.get(VoiceProfile, uuid.UUID(voice_arg))
        else:
            voice = session.exec(select(VoiceProfile).order_by(VoiceProfile.created_at.desc())).first()
        if voice is None:
            print(
                "bench --smoke: no voice profile found — create one with reference audio "
                "in the panel first, or pass --voice <id>",
                file=sys.stderr,
            )
            raise SystemExit(1)

        if base_loop_arg:
            base_loop = session.get(BaseLoop, uuid.UUID(base_loop_arg))
        else:
            base_loop = session.exec(select(BaseLoop).order_by(BaseLoop.created_at.desc())).first()
        if base_loop is None:
            print(
                "bench --smoke: no base loop found — create one in the panel first, "
                "or pass --base-loop <id>",
                file=sys.stderr,
            )
            raise SystemExit(1)

        return voice.id, base_loop.id


def _make_smoke_job(voice_id: uuid.UUID, base_loop_id: uuid.UUID) -> tuple[str, int, str, int]:
    """Create an ephemeral RenderJob + Segment shaped exactly like the real
    pipeline builds them (via make_segments), titled so it is recognisable
    as a bench artefact if it ever surfaces in the panel. Returns plain
    values (job_id, segment_idx, segment_text, segment_seed) — the caller
    must pair this with `_cleanup_smoke_job` in a finally block."""
    from sqlmodel import Session

    from pipeline_core.db import get_engine
    from pipeline_core.segmenting import make_segments
    from schema.models import RenderJob

    with Session(get_engine()) as session:
        job = RenderJob(
            title="[bench.py --smoke] ephemeral artefact — safe to delete",
            script=SMOKE_SCRIPT,
            voice_profile_id=voice_id,
            base_loop_id=base_loop_id,
        )
        session.add(job)
        session.commit()
        session.refresh(job)

        segment = make_segments(job.id, job.script)[0]
        session.add(segment)
        session.commit()

        return str(job.id), segment.idx, segment.text, segment.seed


def _cleanup_smoke_job(job_id: str) -> None:
    """Delete the ephemeral bench job and its segment(s) — runs on both
    success and failure, so a bench row is never mistaken for a stuck render
    in the panel. The S3 artefacts are left in place: they are the evidence
    the operator listens to and watches."""
    from sqlmodel import Session, select

    from pipeline_core.db import get_engine
    from schema.models import RenderJob, Segment

    with Session(get_engine()) as session:
        job_uuid = uuid.UUID(job_id)
        for segment in session.exec(select(Segment).where(Segment.job_id == job_uuid)).all():
            session.delete(segment)
        job = session.get(RenderJob, job_uuid)
        if job is not None:
            session.delete(job)
        session.commit()


def smoke(voice_arg: str | None = None, base_loop_arg: str | None = None) -> int:
    torch = _require_gpu()

    voice_id, base_loop_id = _resolve_render_inputs(voice_arg, base_loop_arg)
    job_id, segment_idx, segment_text, segment_seed = _make_smoke_job(voice_id, base_loop_id)

    try:
        torch.cuda.reset_peak_memory_stats()

        from pipeline_core.storage import ObjectStore
        from worker_cpu.ffmpeg.ingest import probe
        from worker_gpu.engines.audio import find_ffmpeg
        from worker_gpu.engines.lipsync import MuseTalkEngine
        from worker_gpu.engines.tts import ChatterboxEngine

        store = ObjectStore()
        ffmpeg_bin = find_ffmpeg()

        # Both engines stay resident for the whole run — the point of the
        # measurement is simultaneous residency, so neither may fall out of
        # scope before the VRAM figures below are sampled.
        tts_engine = ChatterboxEngine(store)
        tts_engine.load()
        lipsync_engine = MuseTalkEngine(store)
        lipsync_engine.load()

        # Real public methods only — never a private shortcut or a
        # re-implemented inference path, or this proves nothing about the
        # render lane.
        tts_uri, tts_reported_ms = tts_engine.synthesize_segment(
            job_id, segment_idx, segment_text, segment_seed, emotion=None
        )
        chunk_uri = lipsync_engine.sync_chunk(
            job_id, str(base_loop_id), LIPSYNC_CHUNK_START_MS, LIPSYNC_CHUNK_END_MS
        )

        # Sample device-level VRAM while both models are still resident,
        # then torch's own two counters for comparison.
        device_gb = _nvidia_smi_used_gb()
        torch_allocated_gb = torch.cuda.max_memory_allocated() / 1024**3
        torch_reserved_gb = torch.cuda.max_memory_reserved() / 1024**3

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _, tts_key = store.parse_uri(tts_uri)
            _, chunk_key = store.parse_uri(chunk_uri)
            tts_local = store.get_file(tts_key, tmp_path / "tts.wav")
            chunk_local = store.get_file(chunk_key, tmp_path / "chunk.mp4")

            tts_probe = probe(ffmpeg_bin, tts_local)
            chunk_probe = probe(ffmpeg_bin, chunk_local)

        ok = True

        tts_ms = tts_probe["duration_ms"]
        print(f"TTS clip: measured {tts_ms} ms (engine reported {tts_reported_ms} ms)")
        if tts_ms is None or tts_ms < TTS_MIN_DURATION_MS:
            print(f"FAIL: TTS clip is {tts_ms} ms, expected >= {TTS_MIN_DURATION_MS} ms", file=sys.stderr)
            ok = False

        chunk_ms = chunk_probe["duration_ms"]
        print(
            f"lip-sync chunk: measured {chunk_ms} ms, "
            f"{chunk_probe['width']}x{chunk_probe['height']} @ {chunk_probe['fps']} fps, "
            f"audio stream present: {chunk_probe['has_audio']}"
        )
        if chunk_ms is None or abs(chunk_ms - CHUNK_TARGET_DURATION_MS) > CHUNK_TOLERANCE_MS:
            print(
                f"FAIL: lip-sync chunk is {chunk_ms} ms, expected "
                f"{CHUNK_TARGET_DURATION_MS} ms +/- {CHUNK_TOLERANCE_MS} ms",
                file=sys.stderr,
            )
            ok = False

        print(f"VRAM (torch allocated peak): {torch_allocated_gb:.2f} GB")
        print(f"VRAM (torch reserved peak):  {torch_reserved_gb:.2f} GB")
        if device_gb is not None:
            print(f"VRAM (nvidia-smi device):    {device_gb:.2f} GB")
            budget_gb, budget_source = device_gb, "nvidia-smi device figure"
        else:
            print("VRAM (nvidia-smi device):    unavailable")
            budget_gb, budget_source = torch_reserved_gb, "torch reserved peak (nvidia-smi unavailable)"

        print(f"peak VRAM judged against budget: {budget_gb:.2f} GB — source: {budget_source} (budget {VRAM_BUDGET_GB} GB)")
        if budget_gb >= VRAM_BUDGET_GB:
            print("FAIL: over VRAM budget — both models must fit with headroom", file=sys.stderr)
            ok = False

        return 0 if ok else 1
    finally:
        _cleanup_smoke_job(job_id)


def bench_loop(loop_id: str) -> int:
    """M2 acceptance: the second render against a cached loop must be
    measurably (>= 40%) faster than the first. Measured from the metrics
    table — run two renders against the loop (first cold, second cached),
    then this compares the two most recent lipsync stage durations for it.
    Matches by the ref suffix pipeline_core.metrics.lipsync_ref_suffix
    defines (not a substring), so neither a different loop's row nor a
    pre-fix job-id-only row can ever satisfy the query. CPU-only logic:
    usable the moment the workstation has produced runs."""
    from sqlmodel import Session, select

    from pipeline_core.db import get_engine
    from pipeline_core.metrics import LIPSYNC_STAGE, lipsync_ref_suffix
    from schema.models import Metric

    suffix = lipsync_ref_suffix(loop_id)
    with Session(get_engine()) as session:
        rows = session.exec(
            select(Metric)
            .where(Metric.stage == LIPSYNC_STAGE, Metric.ref.endswith(suffix))
            .order_by(Metric.created_at.desc())
            .limit(2)
        ).all()
    if len(rows) < 2:
        print(
            f"bench --loop {loop_id}: need two lipsync runs recorded for this loop "
            f"(found {len(rows)}) — render the same job twice, or two different jobs "
            "against this loop. Runs recorded before this fix carry a ref naming only "
            "the job and are invisible to this query — re-render to get fresh, "
            "measurable rows.",
            file=sys.stderr,
        )
        return 1
    cached, cold = rows[0].duration_ms, rows[1].duration_ms
    speedup = 1 - (cached / cold) if cold else 0.0
    print(f"cold run:   {cold / 1000:.1f}s")
    print(f"cached run: {cached / 1000:.1f}s")
    print(f"speedup:    {speedup:.0%} (target >= 40%)")
    if speedup < 0.40:
        print("FAIL: latent cache under target — M2 acceptance not met", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--smoke", action="store_true", help="M0 smoke: both models resident, VRAM under budget")
    group.add_argument("--loop", metavar="LOOP_ID", help="M2: measure latent-cache speedup for a loop")
    parser.add_argument(
        "--voice",
        metavar="VOICE_ID",
        default=None,
        help="VoiceProfile id to render against with --smoke (default: most recently created)",
    )
    parser.add_argument(
        "--base-loop",
        metavar="BASE_LOOP_ID",
        default=None,
        help=(
            "BaseLoop id to lip-sync against with --smoke (default: most recently "
            "created). Deliberately not --loop — that name is the existing M2 "
            "cache-benchmark mode."
        ),
    )
    args = parser.parse_args()

    if args.smoke:
        return smoke(args.voice, args.base_loop)
    return bench_loop(args.loop)


if __name__ == "__main__":
    sys.exit(main())
