"""M25 ops: .env.example <-> Settings drift guard, bucket sync round-trip,
and service-unit sanity. Backup/restore shell scripts are exercised as a
drill against the live container stack (docs/ops.md), not in CI."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from moto import mock_aws

from pipeline_core.settings import Settings
from pipeline_core.storage import ObjectStore

REPO = Path(__file__).resolve().parent.parent


# --- .env.example drift guard ------------------------------------------------


def _example_keys() -> set[str]:
    keys = set()
    for line in (REPO / ".env.example").read_text().splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)=", line)
        if match:
            keys.add(match.group(1))
    return keys


def test_every_setting_appears_in_env_example():
    settings_keys = {name.upper() for name in Settings.model_fields}
    missing = settings_keys - _example_keys()
    assert not missing, (
        f".env.example is missing {sorted(missing)} — every Settings field "
        "must be documented there (docs/ops.md)"
    )


def test_env_example_has_no_stale_keys():
    settings_keys = {name.upper() for name in Settings.model_fields}
    stale = _example_keys() - settings_keys
    assert not stale, (
        f".env.example documents {sorted(stale)} which no Settings field "
        "reads — remove or wire them up"
    )


# --- Bucket sync (the object half of backup/restore) -------------------------


def test_sync_bucket_pull_push_roundtrip(tmp_path, monkeypatch):
    sys.path.insert(0, str(REPO / "scripts"))
    import sync_bucket

    with mock_aws():
        source = ObjectStore(Settings(s3_endpoint="", s3_bucket="ops-src"))
        source.ensure_bucket()
        source.put_bytes("jobs/1/tts/0.wav", b"wav-bytes")
        source.put_bytes("assets/derived/x/proxy.mp4", b"mp4-bytes")

        mirror = tmp_path / "bucket"
        assert sync_bucket.pull(source, mirror) == 2
        assert (mirror / "jobs/1/tts/0.wav").read_bytes() == b"wav-bytes"

        # pull is incremental: nothing re-downloads on the second run
        assert sync_bucket.pull(source, mirror) == 0

        # restore into a fresh bucket: push mirrors everything back
        target = ObjectStore(Settings(s3_endpoint="", s3_bucket="ops-dst"))
        target.ensure_bucket()
        assert sync_bucket.push(target, mirror) == 2
        assert target.get_bytes("assets/derived/x/proxy.mp4") == b"mp4-bytes"

        # push never clobbers keys that already exist (restore fills gaps)
        assert sync_bucket.push(target, mirror) == 0


# --- Backup scripts + service units ------------------------------------------


def test_backup_scripts_are_executable_shell():
    for name in ("backup.sh", "restore.sh"):
        script = REPO / "scripts" / name
        assert script.exists(), f"scripts/{name} missing"
        proc = subprocess.run(
            ["bash", "-n", str(script)], capture_output=True, text=True
        )
        assert proc.returncode == 0, f"{name} has a syntax error: {proc.stderr}"


def test_service_units_cover_every_lane():
    systemd = {p.name for p in (REPO / "deploy/systemd").glob("*.service")}
    assert systemd == {
        "studio-api.service",
        "studio-worker-cpu.service",
        "studio-worker-gpu.service",
        "studio-worker-wan.service",
        "studio-comfyui.service",
    }
    # the wan queue has a dedicated runner — without it nothing drains wan
    wan_unit = (REPO / "deploy/systemd/studio-worker-wan.service").read_text()
    assert "run_wan.py" in wan_unit

    launchd = {p.name for p in (REPO / "deploy/launchd").glob("*.plist")}
    assert launchd == {
        "com.studio.api.plist",
        "com.studio.worker-cpu.plist",
        "com.studio.worker-wan.plist",
    }
    # Mac dev mode: no CUDA render unit, and dev engines must be explicit
    for plist in (REPO / "deploy/launchd").glob("*.plist"):
        assert "DEV_ENGINES" in plist.read_text(), plist.name


def test_gpu_units_never_scale_out():
    """The render/wan lanes are concurrency-1 by hard constraint — the units
    must not be templated instances (studio-worker-gpu@.service would invite
    running two)."""
    names = [p.name for p in (REPO / "deploy/systemd").glob("*")]
    assert not any("@" in name for name in names)


def test_settings_parse_a_fresh_env_copied_from_example():
    """setup copies .env.example verbatim — blank values (DEV_ENGINES=) must
    mean 'use the default', never a bool/int parse error on typed fields."""
    settings = Settings(_env_file=str(REPO / ".env.example"))
    assert settings.dev_engines is False
    assert settings.comfy_timeout_s == 3600
