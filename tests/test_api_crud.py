from __future__ import annotations

from tests.conftest import make_job_payload, make_uuid


# --- Voice profiles --------------------------------------------------------


def test_voice_crud(client):
    created = client.post(
        "/voices",
        json={"name": "karsten", "version": 1, "reference_audio_uri": "s3://b/ref.wav"},
    )
    assert created.status_code == 201, created.text
    voice_id = created.json()["id"]

    assert client.get(f"/voices/{voice_id}").json()["name"] == "karsten"
    assert len(client.get("/voices").json()) == 1

    updated = client.put(
        f"/voices/{voice_id}",
        json={"name": "karsten", "version": 2, "reference_audio_uri": "s3://b/ref2.wav"},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2

    assert client.delete(f"/voices/{voice_id}").status_code == 204
    assert client.get(f"/voices/{voice_id}").status_code == 404


def test_voice_immutable_once_referenced(client, voice, loop):
    assert client.post("/jobs", json=make_job_payload(voice, loop)).status_code == 201
    body = {"name": "karsten", "version": 9, "reference_audio_uri": "s3://b/new.wav"}
    assert client.put(f"/voices/{voice.id}", json=body).status_code == 409
    assert client.delete(f"/voices/{voice.id}").status_code == 409


# --- Base loops ------------------------------------------------------------


def test_loop_crud(client):
    created = client.post(
        "/loops",
        json={"name": "desk", "source_uri": "s3://b/l.mp4", "fps": 25.0, "frame_count": 750},
    )
    assert created.status_code == 201, created.text
    loop_id = created.json()["id"]

    assert client.get(f"/loops/{loop_id}").json()["fps"] == 25.0
    assert client.delete(f"/loops/{loop_id}").status_code == 204


def test_loop_immutable_once_referenced(client, voice, loop):
    assert client.post("/jobs", json=make_job_payload(voice, loop)).status_code == 201
    body = {"name": "desk", "source_uri": "s3://b/other.mp4", "fps": 30.0, "frame_count": 900}
    assert client.put(f"/loops/{loop.id}", json=body).status_code == 409
    assert client.delete(f"/loops/{loop.id}").status_code == 409


# --- Jobs ------------------------------------------------------------------


def test_job_create_defaults_are_compliant(client, voice, loop):
    response = client.post("/jobs", json=make_job_payload(voice, loop))
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["status"] == "queued"
    assert job["watermark"]["persistent"] is True
    assert job["watermark"]["position"] == "bottom_right"
    assert job["publish"]["altered_content"] is True
    assert job["publish"]["visibility"] == "private"


def test_job_create_splits_script_into_seeded_segments(client, voice, loop):
    job = client.post("/jobs", json=make_job_payload(voice, loop)).json()
    segments = job["segments"]
    assert [s["text"] for s in segments] == ["First sentence.", "Second sentence."]
    assert [s["idx"] for s in segments] == [0, 1]
    assert all(s["seed"] is not None for s in segments)
    assert all(s["audio_uri"] is None for s in segments)


def test_job_create_enqueues_render(client, voice, loop, dispatcher):
    job = client.post("/jobs", json=make_job_payload(voice, loop)).json()
    assert len(dispatcher.calls) == 1
    queue_name, func_path, args, job_key = dispatcher.calls[0]
    assert queue_name == "gpu"
    assert func_path == "worker_gpu.stages.tts_stage"
    assert args == (job["id"],)
    assert job_key == f"{job['id']}-tts"


def test_retry_transition_reenqueues(client, voice, loop, dispatcher):
    job_id = client.post("/jobs", json=make_job_payload(voice, loop)).json()["id"]
    client.post(f"/jobs/{job_id}/transition", json={"status": "tts"})
    client.post(f"/jobs/{job_id}/transition", json={"status": "failed", "error": "boom"})
    dispatcher.calls.clear()
    assert client.post(f"/jobs/{job_id}/transition", json={"status": "queued"}).status_code == 200
    assert [c[0] for c in dispatcher.calls] == ["gpu"]


def test_job_create_requires_existing_references(client, voice, loop):
    missing_voice = make_job_payload(voice, loop, voice_profile_id=make_uuid())
    assert client.post("/jobs", json=missing_voice).status_code == 404
    missing_loop = make_job_payload(voice, loop, base_loop_id=make_uuid())
    assert client.post("/jobs", json=missing_loop).status_code == 404


def test_job_valid_transition_chain(client, voice, loop):
    job_id = client.post("/jobs", json=make_job_payload(voice, loop)).json()["id"]
    for status in ("tts", "lipsync", "assemble", "review"):
        response = client.post(f"/jobs/{job_id}/transition", json={"status": status})
        assert response.status_code == 200, response.text
        assert response.json()["status"] == status


def test_job_invalid_transition_rejected(client, voice, loop):
    job_id = client.post("/jobs", json=make_job_payload(voice, loop)).json()["id"]
    response = client.post(f"/jobs/{job_id}/transition", json={"status": "published"})
    assert response.status_code == 409
    assert "invalid transition" in response.json()["detail"]


def test_job_retry_loop(client, voice, loop):
    job_id = client.post("/jobs", json=make_job_payload(voice, loop)).json()["id"]
    assert client.post(f"/jobs/{job_id}/transition", json={"status": "tts"}).status_code == 200
    failed = client.post(
        f"/jobs/{job_id}/transition", json={"status": "failed", "error": "CUDA OOM"}
    )
    assert failed.status_code == 200
    assert failed.json()["error"] == "CUDA OOM"
    assert client.post(f"/jobs/{job_id}/transition", json={"status": "queued"}).status_code == 200


# --- Assets ----------------------------------------------------------------


def test_stock_asset_requires_provenance(client):
    response = client.post("/assets", json={"origin": "stock", "uri": "s3://b/clip.mp4"})
    assert response.status_code == 422

    response = client.post(
        "/assets",
        json={
            "origin": "stock",
            "uri": "s3://b/clip.mp4",
            "license": "Pexels License",
            "source_url": "https://example.com/video/1",
        },
    )
    assert response.status_code == 201, response.text
    asset = response.json()
    # Stock footage is assumed to contain identifiable people until cleared.
    assert asset["has_identifiable_people"] is True
    assert asset["approved"] is False


def test_own_asset_needs_no_provenance(client):
    response = client.post("/assets", json={"origin": "own", "uri": "s3://b/mine.mp4"})
    assert response.status_code == 201, response.text


def test_asset_approve_and_flag(client):
    asset_id = client.post("/assets", json={"origin": "own", "uri": "s3://b/a.mp4"}).json()["id"]

    approved = client.post(f"/assets/{asset_id}/approve").json()
    assert approved["approved"] is True
    assert approved["has_identifiable_people"] is False

    flagged = client.post(f"/assets/{asset_id}/flag").json()
    assert flagged["approved"] is False
    assert flagged["has_identifiable_people"] is True


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}
