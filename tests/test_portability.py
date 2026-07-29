"""M1 acceptance: the worker packages must be portable to rented GPUs.

No localhost / hardcoded service addresses, no local artefact paths, no direct
boto3 use (everything goes through pipeline_core.storage.ObjectStore), no
open() on artefacts. Greps every .py file under worker_gpu/ and worker_cpu/
with comments stripped.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER_PACKAGES = ("worker_gpu", "worker_cpu")

FORBIDDEN = [
    (r"localhost", "hardcoded localhost — addresses come from Settings/env"),
    (r"127\.0\.0\.1", "hardcoded loopback address"),
    (r"0\.0\.0\.0", "hardcoded bind address"),
    (r"redis://", "hardcoded redis url — use Settings.redis_url"),
    (r"postgres(ql)?(\+\w+)?://", "hardcoded database url — use Settings.database_url"),
    (r"https?://", "hardcoded http endpoint — endpoints come from Settings/env"),
    (r"\bboto3\b", "direct boto3 use — go through pipeline_core.storage.ObjectStore"),
    (r"\bopen\s*\(", "open() on a path — artefacts go through ObjectStore, scratch via tempfile"),
    (r"[\"'](/home|/data|/mnt|/srv|/var|/tmp)\b", "absolute local path — workers are stateless"),
]


def worker_files() -> list[Path]:
    files: list[Path] = []
    for package in WORKER_PACKAGES:
        files.extend(sorted((REPO_ROOT / package).rglob("*.py")))
    assert files, "worker packages are missing"
    return files


def strip_comments(source: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in source.splitlines())


@pytest.mark.parametrize("pattern,reason", FORBIDDEN, ids=[p for p, _ in FORBIDDEN])
def test_workers_contain_no_forbidden_literals(pattern, reason):
    regex = re.compile(pattern)
    hits = []
    for path in worker_files():
        code = strip_comments(path.read_text(encoding="utf-8"))
        for lineno, line in enumerate(code.splitlines(), start=1):
            if regex.search(line):
                hits.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert not hits, f"{reason}\n" + "\n".join(hits)


def test_workers_do_not_define_endpoint_defaults():
    """Workers must consume Settings, never declare their own service defaults."""
    for path in worker_files():
        code = strip_comments(path.read_text(encoding="utf-8"))
        assert "BaseSettings" not in code, f"{path}: workers must import Settings from pipeline_core"
