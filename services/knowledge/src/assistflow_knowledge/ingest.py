"""Ingest published files into tenant-scoped document versions."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from assistflow_customers.errors import require_tenant_id
from sqlalchemy import select
from sqlalchemy.orm import Session

from assistflow_knowledge.catalog import PUBLISHED_DOCUMENTS, PublishedDocument
from assistflow_knowledge.chunking import chunk_text
from assistflow_knowledge.embeddings import EmbeddingProvider
from assistflow_knowledge.models import KnowledgeChunkRow, KnowledgeDocumentRow


@dataclass(frozen=True)
class IngestResult:
    """What one file did for one tenant."""

    source_uri: str
    version: int
    created: bool


def content_checksum(body: str) -> str:
    """SHA-256 of the file bytes. Unchanged content is a no-op on re-ingest."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def ingest_documents(
    session: Session,
    root: Path,
    tenant_ids: list[UUID],
    embedder: EmbeddingProvider,
    *,
    documents: tuple[PublishedDocument, ...] = PUBLISHED_DOCUMENTS,
) -> list[IngestResult]:
    """Chunk each published file and store a row per tenant.

    The same file text is copied into separate rows so tenant scope is real.
    """
    results: list[IngestResult] = []
    for tenant_id in tenant_ids:
        require_tenant_id(tenant_id)
        for document in documents:
            path = root / document.source_uri
            body = path.read_text(encoding="utf-8")
            results.append(_ingest_one(session, tenant_id, document, body, embedder))
    return results


def ingest_text(
    session: Session,
    tenant_id: UUID,
    source_uri: str,
    title: str,
    body: str,
    embedder: EmbeddingProvider,
    *,
    status: str = "published",
) -> IngestResult:
    """Store one document body. Used by tests that need a private article."""
    require_tenant_id(tenant_id)
    return _ingest_one(
        session,
        tenant_id,
        PublishedDocument(source_uri, title),
        body,
        embedder,
        status=status,
    )


def retire_document(session: Session, tenant_id: UUID, source_uri: str) -> None:
    """Mark every version of a source retired so retrieval skips its chunks."""
    require_tenant_id(tenant_id)
    rows = session.scalars(
        select(KnowledgeDocumentRow).where(
            KnowledgeDocumentRow.tenant_id == tenant_id,
            KnowledgeDocumentRow.source_uri == source_uri,
        )
    )
    for row in rows:
        row.status = "retired"


def _ingest_one(
    session: Session,
    tenant_id: UUID,
    document: PublishedDocument,
    body: str,
    embedder: EmbeddingProvider,
    *,
    status: str = "published",
) -> IngestResult:
    checksum = content_checksum(body)
    existing = list(
        session.scalars(
            select(KnowledgeDocumentRow)
            .where(
                KnowledgeDocumentRow.tenant_id == tenant_id,
                KnowledgeDocumentRow.source_uri == document.source_uri,
            )
            .order_by(KnowledgeDocumentRow.version)
        )
    )
    if any(row.checksum == checksum for row in existing):
        matched = next(row for row in existing if row.checksum == checksum)
        return IngestResult(document.source_uri, matched.version, created=False)
    version = 1 if not existing else existing[-1].version + 1
    row = KnowledgeDocumentRow(
        id=uuid4(),
        tenant_id=tenant_id,
        title=document.title,
        source_uri=document.source_uri,
        version=version,
        status=status,
        checksum=checksum,
        body=body,
        created_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    for ordinal, text in enumerate(chunk_text(body)):
        session.add(
            KnowledgeChunkRow(
                id=uuid4(),
                document_id=row.id,
                version=version,
                ordinal=ordinal,
                text=text,
                embedding=embedder.embed(text),
            )
        )
    return IngestResult(document.source_uri, version, created=True)
