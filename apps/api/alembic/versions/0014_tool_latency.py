"""Tool execution latency.

A failed or completed tool call stores how long the gateway took.
The customer response still carries only the safe summary.

Revision ID: 0014_tool_latency
Revises: 0013_side_effects
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_tool_latency"
down_revision: str | None = "0013_side_effects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tool_executions",
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("tool_executions", "latency_ms")
