"""Local database URL wiring."""

from assistflow_api.config import load_settings
from assistflow_api.db import create_db_engine


def test_engine_uses_the_local_database_url() -> None:
    settings = load_settings(
        {"DATABASE_URL": "postgresql+psycopg://assistflow:assistflow@localhost:5432/assistflow"}
    )

    engine = create_db_engine(settings.database_url)
    try:
        assert engine.url.host == "localhost"
        assert engine.url.database == "assistflow"
        assert engine.url.drivername == "postgresql+psycopg"
    finally:
        engine.dispose()
