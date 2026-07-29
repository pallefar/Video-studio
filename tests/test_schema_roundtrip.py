"""M1 acceptance: every exported model survives JSON serialisation round-trip,
DB persistence round-trips the JSON-column configs, and the TS export is
deterministic and covers every exported model."""

from __future__ import annotations

import pytest
from sqlmodel import Session

from schema.export_ts import generate
from schema.models import (
    EXPORTED_ENUMS,
    EXPORTED_MODELS,
    AssetCreate,
    AssetOrigin,
    AssetRead,
    GenerationCreate,
    GenerationRead,
    GenerationTarget,
    BaseLoopCreate,
    BaseLoopRead,
    PublishConfig,
    PublishRecordCreate,
    PublishRecordRead,
    RenderJob,
    RenderJobCreate,
    RenderJobRead,
    SegmentRead,
    VoiceProfileCreate,
    VoiceProfileRead,
    WatermarkConfig,
    utcnow,
)

_UUID = "8f7c9c2e-6a1b-4f0e-9a3d-2b5f8d1c4e77"

SAMPLES = {
    WatermarkConfig: {},
    PublishConfig: {},
    VoiceProfileCreate: {"name": "karsten", "reference_audio_uri": "s3://b/v.wav"},
    VoiceProfileRead: {
        "name": "karsten",
        "reference_audio_uri": "s3://b/v.wav",
        "id": _UUID,
        "created_at": utcnow(),
    },
    BaseLoopCreate: {"name": "desk", "source_uri": "s3://b/l.mp4", "fps": 25.0, "frame_count": 750},
    BaseLoopRead: {
        "name": "desk",
        "source_uri": "s3://b/l.mp4",
        "fps": 25.0,
        "frame_count": 750,
        "id": _UUID,
        "created_at": utcnow(),
    },
    SegmentRead: {"idx": 0, "text": "Hello.", "id": _UUID, "job_id": _UUID, "seed": 421337},
    RenderJobCreate: {
        "title": "t",
        "script": "s",
        "voice_profile_id": _UUID,
        "base_loop_id": _UUID,
    },
    RenderJobRead: {
        "title": "t",
        "script": "s",
        "voice_profile_id": _UUID,
        "base_loop_id": _UUID,
        "id": _UUID,
        "status": "review",
        "watermark": {},
        "publish": {},
        "created_at": utcnow(),
        "updated_at": utcnow(),
    },
    PublishRecordCreate: {"reviewed_by": "karsten"},
    PublishRecordRead: {
        "reviewed_by": "karsten",
        "id": _UUID,
        "job_id": _UUID,
        "created_at": utcnow(),
    },
    AssetCreate: {
        "origin": "stock",
        "uri": "s3://b/a.mp4",
        "license": "Pexels License",
        "source_url": "https://example.com/clip",
    },
    AssetRead: {
        "origin": "own",
        "uri": "s3://b/a.mp4",
        "id": _UUID,
        "created_at": utcnow(),
    },
    GenerationTarget: {"provider": "fal", "model": "fal-ai/flux/schnell"},
    GenerationCreate: {
        "provider": "local",
        "model": "wan2.2-t2v",
        "kind": "text_to_video",
        "prompt": "crash zoom on a coffee cup",
        "fallback": [{"provider": "fal", "model": "fal-ai/kling-video/v2/master/text-to-video"}],
    },
    GenerationRead: {
        "provider": "local",
        "model": "wan2.2-t2v",
        "kind": "text_to_video",
        "prompt": "crash zoom on a coffee cup",
        "id": _UUID,
        "status": "queued",
        "created_at": utcnow(),
        "updated_at": utcnow(),
    },
}


def test_every_exported_model_has_a_sample():
    missing = [m.__name__ for m in EXPORTED_MODELS if m not in SAMPLES]
    assert not missing, f"add roundtrip samples for: {missing}"


@pytest.mark.parametrize("model_cls", EXPORTED_MODELS, ids=lambda m: m.__name__)
def test_json_roundtrip(model_cls):
    instance = model_cls.model_validate(SAMPLES[model_cls])
    reloaded = model_cls.model_validate_json(instance.model_dump_json())
    assert reloaded == instance
    assert reloaded.model_dump() == instance.model_dump()


def test_db_roundtrip_json_configs(engine, session: Session, voice, loop):
    job = RenderJob(
        title="t",
        script="s",
        voice_profile_id=voice.id,
        base_loop_id=loop.id,
        watermark=WatermarkConfig(text="Made with AI"),
        publish=PublishConfig(),
    )
    session.add(job)
    session.commit()
    job_id = job.id
    session.expunge_all()

    fresh = session.get(RenderJob, job_id)
    assert isinstance(fresh.watermark, WatermarkConfig)
    assert fresh.watermark.persistent is True
    assert fresh.watermark.position == "bottom_right"
    assert isinstance(fresh.publish, PublishConfig)
    assert fresh.publish.altered_content is True
    assert fresh.publish.visibility == "private"


def test_ts_export_is_deterministic():
    assert generate() == generate()


def test_ts_export_covers_every_model_and_enum():
    output = generate()
    for enum_cls in EXPORTED_ENUMS:
        assert f"export type {enum_cls.__name__} = " in output
    for model_cls in EXPORTED_MODELS:
        assert f"export interface {model_cls.__name__} {{" in output
    assert "do not edit" in output


def test_committed_ts_file_matches_generator():
    """A schema change that isn't re-exported fails here (and in CI)."""
    from pathlib import Path

    ts_path = Path(__file__).resolve().parents[1] / "web" / "src" / "types" / "schema.ts"
    assert ts_path.exists(), "run: python packages/schema/export_ts.py"
    assert ts_path.read_text(encoding="utf-8") == generate(), (
        "web/src/types/schema.ts is stale — run: python packages/schema/export_ts.py"
    )
