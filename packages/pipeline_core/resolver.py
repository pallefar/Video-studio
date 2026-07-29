"""Tier-1 asset resolution: match a script beat against the local library (M8).

Hard rules, enforced here and tested in tests/test_asset_resolver.py:
- an asset flagged has_identifiable_people is NEVER returned
- an unapproved asset is NEVER returned
- a sub-threshold best match returns None — the caller falls through to the
  next tier (stock search, then the generative lane)
"""

from __future__ import annotations

from typing import Optional

from sqlmodel import Session, select

from pipeline_core.embeddings import Embedder, cosine
from schema.models import Asset

DEFAULT_THRESHOLD = 0.35


def resolve_asset(
    session: Session,
    query: str,
    embedder: Embedder,
    threshold: float = DEFAULT_THRESHOLD,
) -> Optional[Asset]:
    query_vector = embedder.embed(query)
    candidates = session.exec(
        select(Asset).where(
            Asset.approved == True,  # noqa: E712 — SQLModel expression syntax
            Asset.has_identifiable_people == False,  # noqa: E712
        )
    ).all()

    best: Optional[Asset] = None
    best_score = threshold
    for asset in candidates:
        if not asset.embedding:
            continue
        score = cosine(query_vector, asset.embedding)
        if score >= best_score:
            best = asset
            best_score = score
    return best
