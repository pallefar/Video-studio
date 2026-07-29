from __future__ import annotations

from collections.abc import Iterator

from sqlmodel import Session

from pipeline_core.db import get_engine


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
