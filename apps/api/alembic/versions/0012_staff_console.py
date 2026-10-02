"""Staff assignment, message authors, and tool error codes.

A person and the assistant share one conversation. Human replies keep a
distinct author. Tool rows may store an error code, not a raw payload.

Revision ID: 0012_staff_console
Revises: 0011_memory
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_staff_console"
down_revision: str | None = "0011_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("assigned_to", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_conversations_tenant_status_updated",
        "conversations",
        ["tenant_id", "status", "updated_at", "id"],
    )
    op.add_column("messages", sa.Column("author_type", sa.String(length=32), nullable=True))
    op.add_column("messages", sa.Column("author_name", sa.String(length=80), nullable=True))
    op.execute(
        """
        UPDATE messages
        SET author_type = CASE role
            WHEN 'customer' THEN 'customer'
            WHEN 'system' THEN 'system'
            WHEN 'tool' THEN 'system'
            ELSE 'model'
        END
        WHERE author_type IS NULL
        """
    )
    with op.batch_alter_table("messages") as batch:
        batch.alter_column("author_type", existing_type=sa.String(length=32), nullable=False)
    op.add_column("ticket_notes", sa.Column("author_type", sa.String(length=32), nullable=True))
    op.execute("UPDATE ticket_notes SET author_type = 'customer' WHERE author_type IS NULL")
    with op.batch_alter_table("ticket_notes") as batch:
        batch.alter_column("author_type", existing_type=sa.String(length=32), nullable=False)
    op.add_column("tool_executions", sa.Column("error_code", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("tool_executions", "error_code")
    with op.batch_alter_table("ticket_notes") as batch:
        batch.drop_column("author_type")
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("author_name")
        batch.drop_column("author_type")
    op.drop_index("ix_conversations_tenant_status_updated", table_name="conversations")
    op.drop_column("conversations", "assigned_to")
