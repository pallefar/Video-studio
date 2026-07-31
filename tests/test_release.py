"""Release packaging guards: the tag-triggered workflow, the packaging
script's no-leak guarantee (git archive = tracked files only), and the
milestone-log release notes."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_release_workflow_triggers_on_version_tags():
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert 'tags: ["v*"]' in text
    assert "workflow_dispatch" in text
    # the branch-push path: a "release:" commit cuts a release, so remote
    # sessions that cannot push tags can still ship one
    assert "startsWith(github.event.head_commit.message, 'release:')" in text
    assert "contents: write" in text
    assert "scripts/make_release.sh" in text
    assert "scripts/release_notes.py" in text
    assert "dist-release/*.zip" in text
    assert "SHA256SUMS.txt" in text


def test_make_release_stages_tracked_files_only():
    """`git archive` is the leak guard: .env, local databases and
    node_modules are untracked so they can never enter a bundle."""
    text = (ROOT / "scripts" / "make_release.sh").read_text()
    assert "git -C" in text and "archive HEAD" in text
    assert "web/dist" in text  # prebuilt panel ships — release users skip Node
    assert "for platform in macos windows" in text
    assert "GETTING-STARTED-$platform.txt" in text


def test_getting_started_matches_platform_scripts():
    macos = (ROOT / "scripts" / "release" / "GETTING-STARTED-macos.txt").read_text()
    windows = (ROOT / "scripts" / "release" / "GETTING-STARTED-windows.txt").read_text()
    assert "setup.sh --start" in macos
    assert "setup.ps1 -Start" in windows
    for text in (macos, windows):
        assert "Node is NOT required" in text
        assert ".env.example" in text
        assert "docs/workstation.md" in text  # GPU work is never claimed solved


def test_release_notes_prints_latest_milestone():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "release_notes.py")],
        capture_output=True, text=True, check=True,
    )
    match = re.match(r"## (M\d+)", result.stdout)
    assert match, result.stdout[:120]
    # the printed section is the HIGHEST milestone in the log
    all_ids = re.findall(r"^## (M\d+)", (ROOT / "docs" / "milestones.md").read_text(), re.M)
    assert match.group(1) == all_ids[-1]
    assert "**Accept:**" in result.stdout


def test_release_notes_selects_a_specific_milestone():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "release_notes.py"), "M28"],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.startswith("## M28")
    unknown = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "release_notes.py"), "M999"],
        capture_output=True, text=True,
    )
    assert unknown.returncode == 1
