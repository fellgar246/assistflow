"""Outbox and side-effect tables.

The business transaction writes the outbox. A later publisher and the
consumers use these rows. Notices, summaries, and evaluation markers are
idempotent on the event id.

Revision ID: 0013_side_effects
Revises: 0012_staff_console
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_side_effects"
down_revision: str | None = "0012_staff_console"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_outbox",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("correlation_id", sa.String(length=200), nullable=False),
        sa.Column("event_name", sa.String(length=64), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_event_outbox_status_created",
        "event_outbox",
        ["status", "created_at", "id"],
    )
    op.create_table(
        "side_effect_receipts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("consumer_name", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "consumer_name",
            "event_id",
            name="uq_side_effect_receipts_consumer_event",
        ),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_name", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("ticket_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_notifications_event_id"),
    )
    op.create_index(
        "ix_notifications_tenant_created",
        "notifications",
        ["tenant_id", "created_at", "id"],
    )
    op.create_table(
        "notification_emails",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_notification_emails_event_id"),
    )
    op.create_table(
        "conversation_summaries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_conversation_summaries_event_id"),
    )
    op.create_index(
        "ix_conversation_summaries_tenant_conversation",
        "conversation_summaries",
        ["tenant_id", "conversation_id"],
    )
    op.create_table(
        "evaluation_intake",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_evaluation_intake_event_id"),
    )
    op.create_index(
        "ix_evaluation_intake_tenant_created",
        "evaluation_intake",
        ["tenant_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_evaluation_intake_tenant_created", table_name="evaluation_intake")
    op.drop_table("evaluation_intake")
    op.drop_index(
        "ix_conversation_summaries_tenant_conversation",
        table_name="conversation_summaries",
    )
    op.drop_table("conversation_summaries")
    op.drop_table("notification_emails")
    op.drop_index("ix_notifications_tenant_created", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("side_effect_receipts")
    op.drop_index("ix_event_outbox_status_created", table_name="event_outbox")
    op.drop_table("event_outbox")
