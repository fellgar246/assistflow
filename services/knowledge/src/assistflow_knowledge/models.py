"""Knowledge document and chunk tables.

Embeddings are stored as JSON so the same rows work in tests and in PostgreSQL.
Scoring happens in process.
"""

from datetime import datetime
from uuid import UUID

from assistflow_customers.db import Base, UtcDateTime
from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON


class KnowledgeDocumentRow(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_uri",
            "version",
            name="uq_knowledge_documents_tenant_source_version",
        ),
        Index(
            "ix_knowledge_documents_tenant_status",
            "tenant_id",
            "status",
            "source_uri",
            "version",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(200))
    source_uri: Mapped[str] = mapped_column(String(400))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    checksum: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class KnowledgeChunkRow(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (Index("ix_knowledge_chunks_document_ordinal", "document_id", "ordinal"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    document_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("knowledge_documents.id"))
    version: Mapped[int] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(JSON)
