"""In-memory support database for API and command tests."""

from collections.abc import Iterator

import pytest
from assistflow_customers.db import Base
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from assistflow_api.config import load_settings
from assistflow_api.main import create_app
from assistflow_api.schema import load_models
from assistflow_api.seed import seed_support_domain


@pytest.fixture
def support_engine() -> Iterator[Engine]:
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

    load_models()
    Base.metadata.create_all(engine)
    seed_support_domain(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def support_client(support_engine: Engine) -> Iterator[TestClient]:
    app = create_app(load_settings({}), engine=support_engine)
    with TestClient(app) as client:
        yield client
