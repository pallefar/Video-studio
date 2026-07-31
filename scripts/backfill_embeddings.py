"""Backfill resolver embeddings (and optionally captions) for existing assets.

Assets created before the embed-at-creation fix — or whose captions were
placeholders — are invisible to the resolver's cosine search. This walks the
library and repairs them in place:

    python scripts/backfill_embeddings.py               # embed missing vectors
    python scripts/backfill_embeddings.py --recaption   # also queue Florence-2
                                                        # captioning for
                                                        # placeholder captions

--recaption only *queues* cpu-lane caption jobs (a worker must be draining
the cpu queue); embedding runs inline, it needs no worker.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import structlog
from sqlmodel import Session, select

from pipeline_core.captioner import is_placeholder_caption
from pipeline_core.db import get_engine
from pipeline_core.dispatch import Dispatcher
from pipeline_core.embeddings import get_embedder
from pipeline_core.queues import QUEUE_CPU
from schema.models import Asset

log = structlog.get_logger()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recaption",
        action="store_true",
        help="queue Florence-2 captioning for assets whose caption is a placeholder",
    )
    args = parser.parse_args()

    embedder = get_embedder()
    dispatcher = Dispatcher() if args.recaption else None
    embedded = queued = 0

    with Session(get_engine()) as session:
        assets = session.exec(select(Asset)).all()
        for asset in assets:
            if asset.caption and not asset.embedding:
                asset.embedding = embedder.embed(asset.caption)
                session.add(asset)
                embedded += 1
            if dispatcher is not None and is_placeholder_caption(asset.caption):
                dispatcher.enqueue(
                    QUEUE_CPU,
                    "worker_cpu.stages.caption_stage",
                    str(asset.id),
                    True,  # force: the placeholder is the thing being replaced
                    job_key=f"caption-{asset.id}",
                )
                queued += 1
        session.commit()

    log.info("backfill_done", assets=len(assets), embedded=embedded, caption_jobs=queued)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
