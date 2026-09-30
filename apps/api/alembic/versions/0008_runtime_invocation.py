"""Runtime invocation id and duration on a turn trace.

A hosted turn stores the runtime invocation id and how long the call took.
Local traces leave both empty. The columns do not store the request payload.

Revision ID: 0008_runtime_invocation
Revises: 0007_knowledge
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_runtime_invocation"
down_revision: str | None = "0007_knowledge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_traces",
        sa.Column("runtime_invocation_id", sa.String(length=200), nullable=True),
    )
    op.add_column("agent_traces", sa.Column("duration_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_traces", "duration_ms")
    op.drop_column("agent_traces", "runtime_invocation_id")
