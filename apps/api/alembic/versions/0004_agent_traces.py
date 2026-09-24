"""Agent trace tables.

A trace stores the prompt id, the stop reason, and a safe step summary.
It does not store provider payloads or chain-of-thought text.

Revision ID: 0004_agent_traces
Revises: 0003_conversations
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_agent_traces"
down_revision: str | None = "0003_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_traces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("correlation_id", sa.String(length=200), nullable=False),
        sa.Column("prompt_id", sa.String(length=80), nullable=False),
        sa.Column("prompt_version", sa.String(length=40), nullable=False),
        sa.Column("stop_reason", sa.String(length=32), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_agent_traces_tenant_conversation",
        "agent_traces",
        ["tenant_id", "conversation_id", "created_at", "id"],
    )
    op.create_table(
        "agent_trace_steps",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("trace_id", sa.Uuid(), sa.ForeignKey("agent_traces.id"), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("input_summary", sa.String(length=240), nullable=False),
    )
    op.create_index(
        "ix_agent_trace_steps_trace_index",
        "agent_trace_steps",
        ["trace_id", "step_index"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_trace_steps_trace_index", table_name="agent_trace_steps")
    op.drop_table("agent_trace_steps")
    op.drop_index("ix_agent_traces_tenant_conversation", table_name="agent_traces")
    op.drop_table("agent_traces")
