"""Knowledge documents, chunks, and citation storage.

Revision ID: 0007_knowledge
Revises: 0006_model_provider
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_knowledge"
down_revision: str | None = "0006_model_provider"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("source_uri", sa.String(length=400), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "source_uri",
            "version",
            name="uq_knowledge_documents_tenant_source_version",
        ),
    )
    op.create_index(
        "ix_knowledge_documents_tenant_status",
        "knowledge_documents",
        ["tenant_id", "status", "source_uri", "version"],
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("knowledge_documents.id"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_knowledge_chunks_document_ordinal",
        "knowledge_chunks",
        ["document_id", "ordinal"],
    )
    op.add_column(
        "messages",
        sa.Column("citations", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "agent_traces",
        sa.Column("grounded_answer_failures", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("agent_traces", "grounded_answer_failures")
    op.drop_column("messages", "citations")
    op.drop_index("ix_knowledge_chunks_document_ordinal", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index("ix_knowledge_documents_tenant_status", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
