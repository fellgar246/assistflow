"""Conversation, message, and audit tables.

Messages are ordered by created_at then id. Audit rows share the request
correlation id and are written in the same transaction as the mutation.

Revision ID: 0003_conversations
Revises: 0002_support_domain
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_conversations"
down_revision: str | None = "0002_support_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("agent_session_id", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_conversations_tenant_customer_created",
        "conversations",
        ["tenant_id", "customer_id", "created_at", "id"],
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_messages_conversation_created",
        "messages",
        ["conversation_id", "created_at", "id"],
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("correlation_id", sa.String(length=200), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_audit_events_tenant_correlation",
        "audit_events",
        ["tenant_id", "correlation_id", "created_at", "id"],
    )

    with op.batch_alter_table("tickets") as batch:
        batch.create_foreign_key(
            "fk_tickets_conversation_id",
            "conversations",
            ["conversation_id"],
            ["id"],
        )
    op.create_index(
        "ix_tickets_tenant_conversation",
        "tickets",
        ["tenant_id", "conversation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_tickets_tenant_conversation", table_name="tickets")
    with op.batch_alter_table("tickets") as batch:
        batch.drop_constraint("fk_tickets_conversation_id", type_="foreignkey")
    op.drop_index("ix_audit_events_tenant_correlation", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_tenant_customer_created", table_name="conversations")
    op.drop_table("conversations")
