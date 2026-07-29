"""ObjectStore — the one S3 interface. Tested against moto's virtual S3."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from moto import mock_aws

from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore


@pytest.fixture()
def store():
    with mock_aws():
        settings = Settings(
            s3_endpoint="",  # default AWS endpoint → intercepted by moto
            s3_access_key="testing",
            s3_secret_key="testing",
            s3_bucket="avatar-pipeline-test",
        )
        store = ObjectStore(settings)
        store.ensure_bucket()
        yield store


def test_put_get_bytes_roundtrip(store):
    uri = store.put_bytes("jobs/j1/tts/0.wav", b"audio-bytes", content_type="audio/wav")
    assert uri == "s3://avatar-pipeline-test/jobs/j1/tts/0.wav"
    assert store.get_bytes("jobs/j1/tts/0.wav") == b"audio-bytes"


def test_file_roundtrip(store, tmp_path: Path):
    src = tmp_path / "in.bin"
    src.write_bytes(b"\x00\x01\x02")
    store.put_file("jobs/j1/final.mp4", src)
    dest = store.get_file("jobs/j1/final.mp4", tmp_path / "out.bin")
    assert dest.read_bytes() == b"\x00\x01\x02"


def test_exists_and_list(store):
    assert store.exists("nope") is False
    store.put_bytes("loops/l1/latents.pt", b"x")
    store.put_bytes("loops/l1/bbox.json", b"y")
    assert store.exists("loops/l1/latents.pt") is True
    assert store.list_keys("loops/l1/") == ["loops/l1/bbox.json", "loops/l1/latents.pt"]


def test_uri_helpers(store):
    assert store.uri_for("a/b") == "s3://avatar-pipeline-test/a/b"
    assert ObjectStore.parse_uri("s3://bucket/key/path") == ("bucket", "key/path")
    with pytest.raises(ValueError):
        ObjectStore.parse_uri("/local/path")
    with pytest.raises(ValueError):
        ObjectStore.parse_uri("s3://bucket-only")


def test_presign_get(store):
    store.put_bytes("jobs/j1/preview.mp4", b"v")
    url = store.presign_get("jobs/j1/preview.mp4")
    assert "jobs/j1/preview.mp4" in url


def test_no_method_can_set_an_acl():
    """C5 by construction: the storage interface has no ACL surface at all."""
    for name, method in inspect.getmembers(ObjectStore, predicate=inspect.isfunction):
        params = inspect.signature(method).parameters
        assert not any("acl" in p.lower() for p in params), f"{name} exposes an ACL parameter"
    for name, _ in inspect.getmembers(ObjectStore, predicate=inspect.isfunction):
        assert "public" not in name.lower()
