from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlmodel import Session, create_engine

from pipeline_core.settings import Settings


@lru_cache(maxsize=1)
def get_engine():
    return create_engine(Settings().database_url)


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
