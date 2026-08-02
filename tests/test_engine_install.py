"""Phase 1 (render engines): CPU-only assertions on scripts/install_engines.sh's
shape and on the Settings/env wiring it depends on. This is deliberately a text/
structure lock, not an execution test — the actual install can only run on the
RTX 3090 host (no CUDA/pip-CUDA-toolchain reachable here); see
.planning/phases/01-render-engines-live/01-RESEARCH.md "Environment Availability".
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from pipeline_core.settings import Settings

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "install_engines.sh"


def _script_text() -> str:
    return SCRIPT.read_text()


def test_install_script_exists_and_is_executable():
    assert SCRIPT.exists(), "scripts/install_engines.sh is missing"
    assert os.access(SCRIPT, os.X_OK), "scripts/install_engines.sh must be executable"


def test_install_script_runs_under_pipefail():
    assert "set -euo pipefail" in _script_text()


def test_mim_line_installs_all_four_mmlab_packages_unpinned():
    text = _script_text()
    mim_lines = [line for line in text.splitlines() if re.search(r"\bmim install\b", line)]
    assert mim_lines, "no `mim install` line found"
    mim_line = mim_lines[0]
    for pkg in ("mmengine", "mmcv", "mmdet", "mmpose"):
        assert pkg in mim_line, f"mim install line is missing {pkg}: {mim_line!r}"
        assert f"{pkg}==" not in mim_line, (
            f"mim install line pins {pkg} with `==` — RESEARCH.md Pitfall 1: "
            "openmim must resolve against whatever torch Chatterbox left installed"
        )


def test_install_script_references_the_official_musetalk_repo():
    assert "TMElyralab/MuseTalk" in _script_text()


def test_install_script_honours_musetalk_commit_env_override():
    assert 'MUSETALK_COMMIT="${MUSETALK_COMMIT:-' in _script_text()


def test_install_script_honours_chatterbox_version_env_override():
    assert 'CHATTERBOX_VERSION="${CHATTERBOX_VERSION:-' in _script_text()


def test_install_script_calls_verify_gpu():
    assert "scripts/verify_gpu.py" in _script_text()


def test_install_script_prints_a_resolved_versions_report():
    assert "RESOLVED VERSIONS" in _script_text()


def test_install_script_dry_run_is_exercisable_without_gpu_host():
    text = _script_text()
    assert "--dry-run" in text
    assert "nvidia-smi" in text


def test_settings_musetalk_root_defaults_to_empty_string():
    assert Settings().musetalk_root == ""


def test_musetalk_root_documented_in_env_example():
    example = (REPO / ".env.example").read_text()
    assert "MUSETALK_ROOT=" in example
