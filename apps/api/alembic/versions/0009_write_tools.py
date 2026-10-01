"""Tool idempotency and ticket notes.

A tool write is unique per tenant and client key. Notes stay on the ticket.

Revision ID: 0009_write_tools
Revises: 0008_runtime_invocation
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_write_tools"
down_revision: str | None = "0008_runtime_invocation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_idempotency",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("tool_name", sa.String(length=80), nullable=False),
        sa.Column("arguments_hash", sa.String(length=64), nullable=False),
        sa.Column("result_summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_tool_idempotency_tenant_key",
        ),
    )
    op.create_table(
        "ticket_notes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("body", sa.String(length=2000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_ticket_notes_tenant_ticket",
        "ticket_notes",
        ["tenant_id", "ticket_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ticket_notes_tenant_ticket", table_name="ticket_notes")
    op.drop_table("ticket_notes")
    op.drop_table("tool_idempotency")
