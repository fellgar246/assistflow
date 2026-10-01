"""Session memory and customer preferences.

Session rows expire with the conversation limit.
Preference rows store a purpose and a retention deadline.

Revision ID: 0011_memory
Revises: 0010_approvals
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_memory"
down_revision: str | None = "0010_approvals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_memory_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_session_memory_events_session",
        "session_memory_events",
        ["tenant_id", "conversation_id", "created_at", "id"],
    )
    op.create_table(
        "memory_preferences",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("preference_key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.String(length=32), nullable=False),
        sa.Column("purpose", sa.String(length=200), nullable=False),
        sa.Column("retention_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "customer_id",
            "preference_key",
            name="uq_memory_preferences_owner_key",
        ),
    )
    op.create_index(
        "ix_memory_preferences_owner",
        "memory_preferences",
        ["tenant_id", "customer_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_preferences_owner", table_name="memory_preferences")
    op.drop_table("memory_preferences")
    op.drop_index("ix_session_memory_events_session", table_name="session_memory_events")
    op.drop_table("session_memory_events")
