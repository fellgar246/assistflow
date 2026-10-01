"""Customer approvals for sensitive changes.

Each row binds one tool call to an arguments hash and an expiry.
The id is a random UUID, not a sequence.

Revision ID: 0010_approvals
Revises: 0009_write_tools
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_approvals"
down_revision: str | None = "0009_write_tools"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id"),
            nullable=False,
        ),
        sa.Column(
            "tool_execution_id",
            sa.Uuid(),
            sa.ForeignKey("tool_executions.id"),
            nullable=False,
        ),
        sa.Column("assistant_message_id", sa.Uuid(), sa.ForeignKey("messages.id"), nullable=True),
        sa.Column("action_type", sa.String(length=80), nullable=False),
        sa.Column("proposed_change", sa.JSON(), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("arguments_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_approval_requests_tenant_key",
        ),
    )
    op.create_index(
        "ix_approval_requests_tenant_conversation",
        "approval_requests",
        ["tenant_id", "conversation_id", "requested_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_approval_requests_tenant_conversation", table_name="approval_requests")
    op.drop_table("approval_requests")
