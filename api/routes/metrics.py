from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from api.db import get_session
from schema.models import Metric

router = APIRouter(prefix="/metrics", tags=["metrics"])

# Stage names the export worker writes progress snapshots under (M16).
EXPORT_PROGRESS_STAGE = "export_progress"
EXPORT_TOTAL_STAGE = "export_total"


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


@router.get("/exports/{ref}")
async def export_progress(ref: str, session: Session = Depends(get_session)):
    """Live render progress for one export (storyboard or timeline id):
    rendered position vs expected total, parsed from ffmpeg -progress by the
    export stage. The most recent export for the ref wins."""
    total_row = session.exec(
        select(Metric)
        .where(Metric.stage == EXPORT_TOTAL_STAGE, Metric.ref == ref)
        .order_by(Metric.created_at.desc())
    ).first()
    if total_row is None:
        raise HTTPException(status_code=404, detail="no export recorded for ref")

    progress_row = session.exec(
        select(Metric)
        .where(
            Metric.stage == EXPORT_PROGRESS_STAGE,
            Metric.ref == ref,
            Metric.created_at >= total_row.created_at,
        )
        .order_by(Metric.duration_ms.desc())
    ).first()

    total_ms = max(1, total_row.duration_ms)
    rendered_ms = min(progress_row.duration_ms, total_ms) if progress_row else 0
    updated = progress_row.created_at if progress_row else total_row.created_at
    return {
        "ref": ref,
        "total_ms": total_ms,
        "rendered_ms": rendered_ms,
        "pct": round(100 * rendered_ms / total_ms, 1),
        "done": rendered_ms >= total_ms,
        "updated_at": updated.isoformat(),
    }
