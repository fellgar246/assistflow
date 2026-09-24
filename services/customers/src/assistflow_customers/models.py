"""Customer and command-idempotency tables."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from assistflow_customers.db import Base, UtcDateTime


class CustomerRow(Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_customers_tenant_email"),
        Index("ix_customers_tenant_created", "tenant_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class CommandIdempotencyRow(Base):
    __tablename__ = "command_idempotency"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "command_name",
            "idempotency_key",
            name="uq_command_idempotency_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    command_name: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    arguments_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
