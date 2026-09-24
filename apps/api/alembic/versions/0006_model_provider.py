"""Model provider columns on a turn trace.

A trace records the provider name and model id. It still omits raw provider payloads.

Revision ID: 0006_model_provider
Revises: 0005_tool_executions
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_model_provider"
down_revision: str | None = "0005_tool_executions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_traces",
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="mock"),
    )
    op.add_column(
        "agent_traces",
        sa.Column("model_id", sa.String(length=200), nullable=False, server_default="mock"),
    )


def downgrade() -> None:
    op.drop_column("agent_traces", "model_id")
    op.drop_column("agent_traces", "provider")
