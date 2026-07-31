"""Studio dashboard stats (panel home tab): entity counts, queue states,
storage use, recent renders, and recent stage durations — the single-user
replacement for a metrics stack.

Polled every 5 s by the panel, so it must stay cheap: counts are SQL
aggregates (never full-table ORM hydrations — Asset rows carry embedding
vectors), and the full-bucket storage listing is cached for a TTL instead
of hitting the store on every poll.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlmodel import Session, select

from api.db import get_session
from api.routes.assets import get_object_store
from pipeline_core.storage import ObjectStore
from schema.models import (
    Asset,
    Generation,
    Identity,
    Metric,
    Project,
    RenderJob,
    Storyboard,
)

router = APIRouter(tags=["stats"])

_USAGE_TTL_S = 30
_usage_cache: dict = {"at": 0.0, "value": None}


def _cached_usage(store: ObjectStore) -> dict:
    now = time.monotonic()
    if _usage_cache["value"] is None or now - _usage_cache["at"] > _USAGE_TTL_S:
        try:
            value = store.usage()
        except Exception:  # dashboard must render even with the store offline
            value = {"objects": 0, "bytes": 0}
        _usage_cache["at"] = now
        _usage_cache["value"] = value
    return _usage_cache["value"]


def _group_counts(session: Session, column) -> dict[str, int]:
    rows = session.exec(select(column, func.count()).group_by(column)).all()
    return {
        (key.value if hasattr(key, "value") else str(key)): count for key, count in rows
    }


def _count(session: Session, model, *where) -> int:
    stmt = select(func.count()).select_from(model)
    for clause in where:
        stmt = stmt.where(clause)
    return session.exec(stmt).one()


def _worker_health() -> dict:
    """RQ worker liveness + queue depths straight from redis. Degrades to
    unavailable instead of failing the dashboard — same rule as the store."""
    try:
        from redis import Redis
        from rq import Queue, Worker

        from pipeline_core.queues import ALL_QUEUES
        from pipeline_core.settings import Settings

        connection = Redis.from_url(Settings().redis_url)
        now = datetime.now(timezone.utc)
        workers = []
        for worker in Worker.all(connection=connection):
            heartbeat = worker.last_heartbeat
            if heartbeat is not None and heartbeat.tzinfo is None:
                heartbeat = heartbeat.replace(tzinfo=timezone.utc)
            workers.append({
                "name": worker.name,
                "queues": worker.queue_names(),
                "state": str(worker.get_state()),
                "heartbeat_age_s": (
                    round((now - heartbeat).total_seconds(), 1) if heartbeat else None
                ),
            })
        queues = {name: Queue(name, connection=connection).count for name in ALL_QUEUES}
        return {"available": True, "workers": workers, "queues": queues}
    except Exception:
        return {"available": False, "workers": [], "queues": {}}


def _iso_utc(value: datetime) -> str:
    """Columns are naive-UTC (sa.DateTime without timezone) — say so
    explicitly instead of making clients guess."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


@router.get("/stats")
async def studio_stats(
    session: Session = Depends(get_session),
    store: ObjectStore = Depends(get_object_store),
):
    from datetime import timedelta

    now = datetime.now(timezone.utc).replace(tzinfo=None)  # columns are naive UTC
    total_cost = session.exec(
        select(func.coalesce(func.sum(Generation.cost), 0.0))
    ).one()
    month_cost = session.exec(
        select(func.coalesce(func.sum(Generation.cost), 0.0)).where(
            Generation.created_at >= now - timedelta(days=30)
        )
    ).one()
    cost_by_provider = {
        provider: round(value, 4)
        for provider, value in session.exec(
            select(Generation.provider, func.sum(Generation.cost))
            .where(Generation.cost != None)  # noqa: E711
            .group_by(Generation.provider)
        ).all()
    }
    cost_by_project = {
        str(title): round(value, 4)
        for title, value in session.exec(
            select(Project.title, func.sum(Generation.cost))
            .select_from(Generation)
            .join(Project, Project.id == Generation.project_id)
            .where(Generation.cost != None)  # noqa: E711
            .group_by(Project.title)
        ).all()
    }

    recent_assets = session.exec(
        select(Asset.id, Asset.caption, Asset.origin, Asset.approved, Asset.created_at)
        .order_by(Asset.created_at.desc())
        .limit(8)
    ).all()
    recent_metrics = session.exec(
        select(Metric).order_by(Metric.created_at.desc()).limit(12)
    ).all()

    return {
        "assets": {
            "total": _count(session, Asset),
            "approved": _count(session, Asset, Asset.approved == True),  # noqa: E712
            "by_origin": _group_counts(session, Asset.origin),
        },
        "generations": _group_counts(session, Generation.status),
        "jobs": _group_counts(session, RenderJob.status),
        "identities": {
            "total": _count(session, Identity),
            "consented": _count(session, Identity, Identity.consent_recorded_by != None),  # noqa: E711
        },
        "projects": _count(session, Project),
        "storyboards": _count(session, Storyboard),
        "storage": _cached_usage(store),
        "health": _worker_health(),
        "costs": {
            "total": round(total_cost, 4),
            "last_30d": round(month_cost, 4),
            "by_provider": cost_by_provider,
            "by_project": cost_by_project,
        },
        "recent_assets": [
            {
                "id": str(asset_id),
                "caption": caption,
                "origin": origin.value if hasattr(origin, "value") else str(origin),
                "approved": approved,
                "created_at": _iso_utc(created_at),
            }
            for asset_id, caption, origin, approved, created_at in recent_assets
        ],
        "recent_stages": [
            {
                "stage": m.stage,
                "ref": m.ref,
                "duration_ms": m.duration_ms,
                "created_at": _iso_utc(m.created_at),
            }
            for m in recent_metrics
        ],
    }
