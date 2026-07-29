from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from api.db import get_session
from schema.models import Metric

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("")
async def list_metrics(
    session: Session = Depends(get_session), stage: str | None = None, limit: int = 100
):
    """Latest stage durations — throughput regressions here are how thermal
    throttling shows up."""
    stmt = select(Metric).order_by(Metric.created_at.desc()).limit(min(limit, 500))
    if stage:
        stmt = stmt.where(Metric.stage == stage)
    return [
        {
            "id": str(m.id),
            "stage": m.stage,
            "ref": m.ref,
            "duration_ms": m.duration_ms,
            "created_at": m.created_at.isoformat(),
        }
        for m in session.exec(stmt).all()
    ]
