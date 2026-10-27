from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

import src.models
from src.db import make_engine, session_factory
from src.models import Base

del src.models


@pytest.fixture
def session() -> Iterator[Session]:
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = session_factory(engine)
    with factory() as db:
        yield db
