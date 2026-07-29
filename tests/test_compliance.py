"""C1-C5 compliance gate — schema and API level (M1 slice of M5).

Frame-sampling (watermark pixels at 10/50/90% of duration) and the audio
watermark encode test (C3) land with M4/M5 when there is rendered output to
sample. Everything checkable at the schema/API level is checked here, with
negative cases.
"""

from __future__ import annotations

import typing

import pytest
from pydantic import ValidationError

from api.validators.compliance import ComplianceError, check_publishable
from schema.models import (
    JobStatus,
    PublishConfig,
    PublishRecordCreate,
    RenderJob,
    RenderJobCreate,
    WatermarkConfig,
)
from tests.conftest import make_job_payload


# --- C1: watermark persistent, full duration ------------------------------


def test_c1_watermark_rejects_non_persistent():
    with pytest.raises(ValidationError, match="C1"):
        WatermarkConfig(persistent=False)


def test_c1_default_is_persistent():
    assert WatermarkConfig().persistent is True


def test_c1_job_create_rejects_non_persistent_watermark():
    with pytest.raises(ValidationError, match="C1"):
        RenderJobCreate(
            title="t",
            script="s",
            voice_profile_id="8f7c9c2e-6a1b-4f0e-9a3d-2b5f8d1c4e77",
            base_loop_id="8f7c9c2e-6a1b-4f0e-9a3d-2b5f8d1c4e77",
            watermark={"persistent": False},
        )


# --- C2: altered_content on every upload ----------------------------------


def test_c2_publish_config_rejects_undisclosed():
    with pytest.raises(ValidationError, match="C2"):
        PublishConfig(altered_content=False)


def test_c2_provenance_record_rejects_undisclosed():
    with pytest.raises(ValidationError, match="C2"):
        PublishRecordCreate(altered_content=False, reviewed_by="karsten")


# --- C5: uploads land private — no path sets public -----------------------


def test_c5_visibility_public_is_unrepresentable():
    with pytest.raises(ValidationError):
        PublishConfig(visibility="public")


def test_c5_schema_only_allows_private():
    annotation = PublishConfig.model_fields["visibility"].annotation
    assert typing.get_origin(annotation) is typing.Literal
    assert typing.get_args(annotation) == ("private",)


# --- The publish gate (validator layer) -----------------------------------


def _job(status: JobStatus, **overrides) -> RenderJob:
    # Table classes skip validation by design — this builds the tampered
    # states the gate must catch.
    defaults = dict(
        title="t",
        script="s",
        status=status,
        watermark=WatermarkConfig(),
        publish=PublishConfig(),
    )
    defaults.update(overrides)
    return RenderJob(**defaults)


def test_gate_passes_a_reviewed_compliant_job():
    check_publishable(_job(JobStatus.review))


def test_gate_rejects_unreviewed_job():
    with pytest.raises(ComplianceError, match="C5"):
        check_publishable(_job(JobStatus.assemble))


def test_gate_rejects_tampered_watermark():
    job = _job(JobStatus.review)
    job.watermark = {"text": "Made with AI", "position": "bottom_right", "persistent": False}
    with pytest.raises(ComplianceError, match="C1"):
        check_publishable(job)


def test_gate_rejects_tampered_disclosure():
    job = _job(JobStatus.review)
    job.publish = {"altered_content": False, "visibility": "private"}
    with pytest.raises(ComplianceError, match="C2"):
        check_publishable(job)


def test_gate_rejects_tampered_visibility():
    job = _job(JobStatus.review)
    job.publish = {"altered_content": True, "visibility": "public"}
    with pytest.raises(ComplianceError, match="C[25]"):
        check_publishable(job)


# --- C4 + gate at the API layer -------------------------------------------


def _create_reviewed_job(client, voice, loop) -> str:
    job_id = client.post("/jobs", json=make_job_payload(voice, loop)).json()["id"]
    for status in ("tts", "lipsync", "assemble", "review"):
        response = client.post(f"/jobs/{job_id}/transition", json={"status": status})
        assert response.status_code == 200, response.text
    return job_id


def test_c4_publish_creates_provenance_record(client, voice, loop):
    job_id = _create_reviewed_job(client, voice, loop)
    response = client.post(f"/jobs/{job_id}/publish", json={"reviewed_by": "karsten"})
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["job_id"] == job_id
    assert record["altered_content"] is True
    assert record["reviewed_by"] == "karsten"

    assert client.get(f"/jobs/{job_id}").json()["status"] == "publishing"
    assert client.get(f"/jobs/{job_id}/publish").json()["id"] == record["id"]


def test_c4_publish_is_single_shot(client, voice, loop):
    job_id = _create_reviewed_job(client, voice, loop)
    assert client.post(f"/jobs/{job_id}/publish", json={"reviewed_by": "karsten"}).status_code == 201
    # A second record for the same job is a provenance violation.
    retry = client.post(f"/jobs/{job_id}/publish", json={"reviewed_by": "karsten"})
    assert retry.status_code in (409, 422)


def test_publish_rejected_before_review(client, voice, loop):
    job_id = client.post("/jobs", json=make_job_payload(voice, loop)).json()["id"]
    response = client.post(f"/jobs/{job_id}/publish", json={"reviewed_by": "karsten"})
    assert response.status_code == 422
    assert "C5" in response.json()["detail"]
    assert client.get(f"/jobs/{job_id}/publish").status_code == 404
