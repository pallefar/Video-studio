#!/usr/bin/env python3
"""M0/M2 benchmark harness. Measure, don't trust estimates.

--smoke : load Chatterbox + MuseTalk together, render a 10 s TTS clip and a
          5 s lip-sync, log peak VRAM and assert it stays under 20 GB.
          Its numbers replace the PLACEHOLDER table in docs/pipeline-spec.md §6.
--loop  : (M2) render twice against one loop and report the latent-cache
          speedup; acceptance is a cached run >= 40% faster.

Requires the GPU host: pip install -e ".[gpu]". Exits 1 with a clear message
anywhere else.
"""

from __future__ import annotations

import argparse
import sys

VRAM_BUDGET_GB = 20.0


def _require_gpu():
    try:
        import torch
    except ImportError:
        print('bench.py requires the GPU host: pip install -e ".[gpu]"', file=sys.stderr)
        raise SystemExit(1)
    if not torch.cuda.is_available():
        print("bench.py requires a CUDA device — run scripts/verify_gpu.py first", file=sys.stderr)
        raise SystemExit(1)
    return torch


def smoke() -> int:
    torch = _require_gpu()
    torch.cuda.reset_peak_memory_stats()

    # M0 wiring lands when the engines gain real load/synthesize implementations
    # on the workstation: render 10 s of Chatterbox TTS, lip-sync 5 s with
    # MuseTalk, both models resident simultaneously.
    try:
        from pipeline_core.storage import ObjectStore
        from worker_gpu.engines.lipsync import MuseTalkEngine
        from worker_gpu.engines.tts import ChatterboxEngine

        store = ObjectStore()
        ChatterboxEngine(store).load()
        MuseTalkEngine(store).load()
    except NotImplementedError as exc:
        print(f"bench --smoke is blocked on engine implementation: {exc}", file=sys.stderr)
        return 1

    peak_gb = torch.cuda.max_memory_allocated() / 1024**3
    print(f"peak VRAM: {peak_gb:.2f} GB (budget {VRAM_BUDGET_GB} GB)")
    if peak_gb >= VRAM_BUDGET_GB:
        print("FAIL: over VRAM budget — both models must fit with headroom", file=sys.stderr)
        return 1
    return 0


def bench_loop(loop_id: str) -> int:
    """M2 acceptance: the second render against a cached loop must be
    measurably (>= 40%) faster than the first. Measured from the metrics
    table — run two renders against the loop (first cold, second cached),
    then this compares the two most recent lipsync stage durations for it.
    CPU-only logic: usable the moment the workstation has produced runs."""
    from sqlmodel import Session, select

    from pipeline_core.db import get_engine
    from schema.models import Metric

    with Session(get_engine()) as session:
        rows = session.exec(
            select(Metric)
            .where(Metric.stage == "lipsync", Metric.ref.contains(loop_id))
            .order_by(Metric.created_at.desc())
            .limit(2)
        ).all()
    if len(rows) < 2:
        print(
            f"bench --loop {loop_id}: need two lipsync runs recorded for this loop "
            f"(found {len(rows)}) — render the same job twice first",
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
    args = parser.parse_args()

    if args.smoke:
        return smoke()
    return bench_loop(args.loop)


if __name__ == "__main__":
    sys.exit(main())
