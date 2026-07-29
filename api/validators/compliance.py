"""The hard compliance gate (docs/psd.md §6). C1–C5 live here and in tests,
never only in application logic.

SQLModel table instances skip Pydantic validation, so this gate re-validates
the persisted configs instead of trusting them.
"""

from __future__ import annotations

from pydantic import BaseModel, ValidationError

from schema.models import JobStatus, PublishConfig, RenderJob, WatermarkConfig


class ComplianceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _revalidate(model_cls: type[BaseModel], value: object, code: str) -> BaseModel:
    raw = value.model_dump() if isinstance(value, BaseModel) else value
    try:
        return model_cls.model_validate(raw)
    except ValidationError as exc:
        raise ComplianceError(code, str(exc)) from exc


def check_publishable(job: RenderJob) -> None:
    """Raise ComplianceError unless the job may proceed to publishing.

    C1: watermark persistent, full duration. C2: altered_content disclosed.
    C5: visibility private — nothing else validates. C4 (provenance record)
    is enforced by the publish route, which creates the PublishRecord in the
    same transaction that moves the job to publishing.
    """
    if job.status != JobStatus.review:
        raise ComplianceError("C5", "publish requires human review — job is not in review state")

    watermark = _revalidate(WatermarkConfig, job.watermark, "C1")
    if watermark.persistent is not True:  # belt and braces on top of the validator
        raise ComplianceError("C1", "watermark.persistent must be true")

    publish = _revalidate(PublishConfig, job.publish, "C2")
    if publish.altered_content is not True:
        raise ComplianceError("C2", "publish.altered_content must be true")
    if publish.visibility != "private":
        raise ComplianceError("C5", "uploads land private — no path publishes directly")
