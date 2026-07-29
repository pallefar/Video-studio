"""CPU stage functions consumed from the cpu queue."""

from __future__ import annotations

import uuid

import structlog

from pipeline_core.db import advance_job, fail_job, open_session
from pipeline_core.storage import ObjectStore
from schema.models import JobStatus, RenderJob

log = structlog.get_logger()


def assemble_stage(job_id: str) -> None:
    from worker_cpu.ffmpeg.assemble import assemble

    with open_session() as session:
        job = session.get(RenderJob, uuid.UUID(job_id))
        if job is None:
            raise ValueError(f"job {job_id} not found")
        if job.status != JobStatus.assemble:
            log.info("assemble_skip_idempotent", job_id=job_id, status=job.status.value)
            return
        try:
            assemble(ObjectStore(), job_id)
        except NotImplementedError:
            # M4 lands the ffmpeg chain; until then the job waits in assemble.
            log.info("assemble_pending_m4", job_id=job_id)
            return
        except Exception as exc:
            fail_job(session, job, f"assemble: {exc}")
            raise
        advance_job(session, job, JobStatus.review)
