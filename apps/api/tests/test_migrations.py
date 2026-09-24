"""Schema revisions apply without a cloud account."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_support_migration_applies_and_downgrades(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api_root = Path(__file__).resolve().parents[1]
    database = tmp_path / "support.db"
    url = "sqlite+pysqlite:///" + database.as_posix()
    monkeypatch.chdir(api_root)
    monkeypatch.setenv("DATABASE_URL", url)

    config = Config(str(api_root / "alembic.ini"))
    command.upgrade(config, "head")

    engine = create_engine(url)
    names = set(inspect(engine).get_table_names())
    assert {
        "customers",
        "orders",
        "shipments",
        "return_requests",
        "refund_requests",
        "tickets",
        "command_idempotency",
        "conversations",
        "messages",
        "audit_events",
    } <= names
    columns = {column["name"] for column in inspect(engine).get_columns("orders")}
    assert "tenant_id" in columns
    assert "order_number" in columns
    message_indexes = {index["name"] for index in inspect(engine).get_indexes("messages")}
    assert "ix_messages_conversation_created" in message_indexes

    command.downgrade(config, "base")
    remaining = set(inspect(engine).get_table_names())
    assert "customers" not in remaining
    assert "orders" not in remaining
    engine.dispose()
