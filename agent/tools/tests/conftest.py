"""Seeded support database for tool contract tests."""

from collections.abc import Iterator

import pytest
from assistflow_customers.db import Base
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from assistflow_api.schema import load_models
from assistflow_api.seed import seed_support_domain


@pytest.fixture
def support_session() -> Iterator[Session]:
    engine = _engine()
    load_models()
    Base.metadata.create_all(engine)
    seed_support_domain(engine)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine
