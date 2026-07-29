"""Database access shared by the API and the workers.

Workers open sessions through here so the engine is always built from
Settings (env) — never a literal.
"""

from __future__ import annotations

from functools import lru_cache

from sqlmodel import Session, create_engine

from pipeline_core.settings import Settings


@lru_cache(maxsize=1)
def get_engine():
    return create_engine(Settings().database_url)


def open_session() -> Session:
    return Session(get_engine())


def advance_job(session: Session, job, new_status) -> None:
    """Move a job through the state machine, rejecting invalid transitions."""
    from schema.models import VALID_TRANSITIONS, utcnow

    allowed = VALID_TRANSITIONS.get(job.status, set())
    if new_status not in allowed:
        raise ValueError(f"invalid transition {job.status.value} -> {new_status.value}")
    job.status = new_status
    job.updated_at = utcnow()
    session.add(job)
    session.commit()


def fail_job(session: Session, job, error: str) -> None:
    from schema.models import JobStatus

    advance_job(session, job, JobStatus.failed)
    job.error = error
    session.add(job)
    session.commit()
