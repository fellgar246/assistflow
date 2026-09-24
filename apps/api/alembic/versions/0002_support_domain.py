"""Support domain tables.

Customers, orders, shipments, return requests, refund requests, and tickets
are scoped by tenant_id. Refund rows are requests, not payment captures.

Revision ID: 0002_support_domain
Revises: 0001_baseline
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_support_domain"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "email", name="uq_customers_tenant_email"),
    )
    op.create_index("ix_customers_tenant_created", "customers", ["tenant_id", "created_at", "id"])

    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("order_number", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("total_cents", sa.Integer(), nullable=False),
        sa.Column("shipping_address", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "order_number", name="uq_orders_tenant_number"),
    )
    op.create_index("ix_orders_tenant_created", "orders", ["tenant_id", "created_at", "id"])

    op.create_table(
        "shipments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("carrier_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("origin_hub", sa.String(length=64), nullable=False),
        sa.Column("estimated_delivery_on", sa.Date(), nullable=True),
        sa.Column("address_change_eligible", sa.Boolean(), nullable=False),
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "order_id", name="uq_shipments_tenant_order"),
    )

    op.create_table(
        "return_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_return_requests_tenant_order", "return_requests", ["tenant_id", "order_id"]
    )

    op.create_table(
        "refund_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("return_request_id", sa.Uuid(), sa.ForeignKey("return_requests.id"), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_refund_requests_tenant_order", "refund_requests", ["tenant_id", "order_id"]
    )

    op.create_table(
        "tickets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("assigned_to", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tickets_tenant_created", "tickets", ["tenant_id", "created_at", "id"])

    op.create_table(
        "command_idempotency",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("command_name", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("arguments_hash", sa.String(length=64), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "command_name",
            "idempotency_key",
            name="uq_command_idempotency_key",
        ),
    )


def downgrade() -> None:
    op.drop_table("command_idempotency")
    op.drop_index("ix_tickets_tenant_created", table_name="tickets")
    op.drop_table("tickets")
    op.drop_index("ix_refund_requests_tenant_order", table_name="refund_requests")
    op.drop_table("refund_requests")
    op.drop_index("ix_return_requests_tenant_order", table_name="return_requests")
    op.drop_table("return_requests")
    op.drop_table("shipments")
    op.drop_index("ix_orders_tenant_created", table_name="orders")
    op.drop_table("orders")
    op.drop_index("ix_customers_tenant_created", table_name="customers")
    op.drop_table("customers")
