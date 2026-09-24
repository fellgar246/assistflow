"""Tool execution records.

Each row stores the arguments hash, risk level, status, and a safe summary.
It does not store raw tool payloads.

Revision ID: 0005_tool_executions
Revises: 0004_agent_traces
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_tool_executions"
down_revision: str | None = "0004_agent_traces"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_executions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("correlation_id", sa.String(length=200), nullable=False),
        sa.Column("assistant_message_id", sa.Uuid(), sa.ForeignKey("messages.id"), nullable=True),
        sa.Column("tool_name", sa.String(length=80), nullable=False),
        sa.Column("arguments_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_summary", sa.String(length=240), nullable=False),
    )
    op.create_index(
        "ix_tool_executions_tenant_conversation",
        "tool_executions",
        ["tenant_id", "conversation_id", "started_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_tool_executions_tenant_conversation", table_name="tool_executions")
    op.drop_table("tool_executions")
