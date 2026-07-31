"""M28 media kinds: image animation (cheap b-roll), talking/singing photos
(C6-gated), standalone voiceovers, and the dev executor's placeholder
synthesis for each — plus /config's live ComfyUI reachability flag."""

from __future__ import annotations

import io
import subprocess
import uuid

import pytest
from moto import mock_aws
from sqlmodel import Session

from pipeline_core.dev_generation import DevGenerationExecutor, _find_ffmpeg
from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore
from schema.models import (
    Asset,
    AssetOrigin,
    Generation,
    GenerationKind,
    Identity,
    VoiceProfile,
    utcnow,
)


def _image_asset(session: Session, uri="s3://avatar-pipeline/still.png") -> Asset:
    asset = Asset(origin=AssetOrigin.generated, uri=uri, caption="portrait still",
                  has_identifiable_people=True, approved=True)
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def _identity(session: Session, consented=True) -> Identity:
    identity = Identity(
        name="owner", reference_asset_ids=[],
        consent_recorded_by="karsten" if consented else None,
        consent_at=utcnow() if consented else None,
    )
    session.add(identity)
    session.commit()
    session.refresh(identity)
    return identity


# --- /images/animate ---------------------------------------------------------


def test_animate_creates_i2v_from_image(client, session, dispatcher):
    asset = _image_asset(session)
    response = client.post("/images/animate", json={"asset_id": str(asset.id)})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "image_to_video"
    assert body["params"]["source_asset_uri"] == asset.uri
    assert body["source_asset_id"] == str(asset.id)  # provenance chain
    queue, _, args, _ = dispatcher.calls[-1]
    assert queue == "wan"  # wan2.2-i2v takes the exclusive lane


def test_animate_refuses_non_image(client, session, dispatcher):
    asset = _image_asset(session, uri="s3://avatar-pipeline/clip.mp4")
    assert client.post("/images/animate", json={"asset_id": str(asset.id)}).status_code == 422


# --- /images/talk (C6) -------------------------------------------------------


def test_talk_requires_consented_identity(client, session, dispatcher):
    asset = _image_asset(session)
    unconsented = _identity(session, consented=False)
    response = client.post("/images/talk", json={
        "asset_id": str(asset.id), "identity_id": str(unconsented.id),
        "script": "hello world",
    })
    assert response.status_code == 422
    assert "consent" in response.json()["detail"].lower()


def test_talk_script_makes_talking_photo(client, session, dispatcher):
    asset = _image_asset(session)
    identity = _identity(session)
    voice = VoiceProfile(name="k", reference_audio_uri="s3://t/v.wav")
    session.add(voice)
    session.commit()
    session.refresh(voice)

    response = client.post("/images/talk", json={
        "asset_id": str(asset.id), "identity_id": str(identity.id),
        "script": "welcome to the studio", "voice_profile_id": str(voice.id),
    })
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "talking_image"
    assert body["params"]["script"] == "welcome to the studio"
    assert body["identity_id"] == str(identity.id)
    queue, _, _, _ = dispatcher.calls[-1]
    assert queue == "gpu"  # MuseTalk is a render-lane resident (shared lane)


def test_talk_audio_makes_singing_photo(client, session, dispatcher):
    asset = _image_asset(session)
    identity = _identity(session)
    song = Asset(origin=AssetOrigin.own, uri="s3://avatar-pipeline/vocal.wav",
                 caption="vocal", has_identifiable_people=False, approved=True)
    session.add(song)
    session.commit()
    session.refresh(song)

    response = client.post("/images/talk", json={
        "asset_id": str(asset.id), "identity_id": str(identity.id),
        "audio_asset_id": str(song.id),
    })
    assert response.status_code == 201, response.text
    assert response.json()["params"]["audio_asset_uri"] == song.uri


def test_talk_requires_exactly_one_source(client, session):
    asset = _image_asset(session)
    identity = _identity(session)
    base = {"asset_id": str(asset.id), "identity_id": str(identity.id)}
    assert client.post("/images/talk", json=base).status_code == 422  # neither
    assert client.post("/images/talk", json={
        **base, "script": "hi", "audio_asset_id": str(uuid.uuid4()),
    }).status_code == 422  # both


# --- /music/voice ------------------------------------------------------------


def test_voiceover_generates_on_render_lane(client, session, dispatcher):
    response = client.post("/music/voice", json={"text": "hello there, welcome back"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "voice"
    assert body["params"]["asset_license"] == "Generated (Chatterbox, MIT)"
    queue, _, _, _ = dispatcher.calls[-1]
    assert queue == "gpu"


# --- dev executor placeholders ----------------------------------------------


@pytest.fixture()
def dev_store():
    with mock_aws():
        store = ObjectStore(Settings(s3_endpoint="", s3_bucket="devmedia"))
        store.ensure_bucket()
        yield store


def _png_bytes() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (320, 240), (200, 60, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


def _probe_streams(data: bytes, suffix: str, tmp_path) -> str:
    path = tmp_path / f"probe{suffix}"
    path.write_bytes(data)
    result = subprocess.run(
        [_find_ffmpeg(), "-hide_banner", "-i", str(path)],
        capture_output=True, text=True,
    )
    return result.stderr


def test_dev_i2v_animates_the_actual_still(dev_store, tmp_path):
    uri = dev_store.put_bytes("stills/red.png", _png_bytes(), content_type="image/png")
    generation = Generation(
        provider="local", model="wan2.2-i2v", kind=GenerationKind.image_to_video,
        prompt="bring to life",
        params={"source_asset_uri": uri, "duration_s": 2, "width": 320, "height": 240},
    )
    result = DevGenerationExecutor(store=dev_store).generate(generation)
    assert result.content_type == "video/mp4"
    assert b"ftyp" in result.data[:32]
    assert "Video:" in _probe_streams(result.data, ".mp4", tmp_path)


def test_dev_talking_image_muxes_video_and_audio(dev_store, tmp_path):
    uri = dev_store.put_bytes("stills/face.png", _png_bytes(), content_type="image/png")
    generation = Generation(
        provider="local", model="musetalk-image", kind=GenerationKind.talking_image,
        prompt="talking photo",
        params={"source_asset_uri": uri, "script": "hello world how are you"},
    )
    result = DevGenerationExecutor(store=dev_store).generate(generation)
    assert result.content_type == "video/mp4"
    stderr = _probe_streams(result.data, ".mp4", tmp_path)
    assert "Video:" in stderr and "Audio:" in stderr  # a real mux, not a slate


def test_dev_voice_produces_wav(dev_store):
    generation = Generation(
        provider="local", model="chatterbox", kind=GenerationKind.voice,
        prompt="a short spoken line for the studio", params={},
    )
    result = DevGenerationExecutor(store=dev_store).generate(generation)
    assert result.content_type == "audio/wav"
    assert result.data[:4] == b"RIFF"


# --- /config comfy_online ----------------------------------------------------


def test_config_reports_comfy_offline_when_unreachable(client, monkeypatch):
    monkeypatch.setenv("COMFY_URL", "http://127.0.0.1:1")  # nothing there
    body = client.get("/config").json()
    assert body["comfy_configured"] is True
    assert body["comfy_online"] is False


def test_config_reports_comfy_online(client, monkeypatch):
    monkeypatch.setenv("COMFY_URL", "http://comfy-host:8188")

    class FakeResponse:
        status_code = 200

    monkeypatch.setattr("httpx.get", lambda url, timeout: FakeResponse())
    body = client.get("/config").json()
    assert body["comfy_online"] is True
