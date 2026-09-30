"""Tenant-scoped retrieval over the latest published document version."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from assistflow_customers.errors import require_tenant_id
from sqlalchemy import select
from sqlalchemy.orm import Session

from assistflow_knowledge.embeddings import EmbeddingProvider, cosine
from assistflow_knowledge.models import KnowledgeChunkRow, KnowledgeDocumentRow

DEFAULT_CHUNK_CAP = 4
DEFAULT_SCORE_FLOOR = 0.28


@dataclass(frozen=True)
class RetrievedChunk:
    document_id: UUID
    version: int
    title: str
    text: str
    score: float


class KnowledgeRetriever(Protocol):
    """Retrieval port. Callers do not choose a storage provider."""

    @property
    def chunk_cap(self) -> int:
        """Maximum chunks one call may return."""

    @property
    def score_floor(self) -> float:
        """Minimum score kept for a scored provider."""

    def retrieve(self, tenant_id: UUID, query: str, limit: int) -> list[RetrievedChunk]:
        """Return scored chunks for one tenant. `limit` cannot exceed the cap."""


class LocalKnowledgeRetriever:
    """Score published chunks for one tenant. Other tenants and retired rows are absent."""

    def __init__(
        self,
        session: Session,
        embedder: EmbeddingProvider,
        *,
        chunk_cap: int = DEFAULT_CHUNK_CAP,
        score_floor: float = DEFAULT_SCORE_FLOOR,
    ) -> None:
        self._session = session
        self._embedder = embedder
        self._chunk_cap = chunk_cap
        self._score_floor = score_floor

    @property
    def chunk_cap(self) -> int:
        return self._chunk_cap

    @property
    def score_floor(self) -> float:
        return self._score_floor

    def retrieve(self, tenant_id: UUID, query: str, limit: int) -> list[RetrievedChunk]:
        """Return scored chunks. `limit` cannot exceed the configured cap."""
        tenant_id = require_tenant_id(tenant_id)
        if limit > self._chunk_cap:
            raise ValueError("Retrieval limit exceeds the configured cap.")
        if limit < 1 or not query.strip():
            return []
        query_vector = self._embedder.embed(query)
        latest = _latest_published(self._session, tenant_id)
        if not latest:
            return []
        rows = self._session.execute(
            select(KnowledgeChunkRow, KnowledgeDocumentRow)
            .join(KnowledgeDocumentRow, KnowledgeChunkRow.document_id == KnowledgeDocumentRow.id)
            .where(KnowledgeDocumentRow.id.in_(latest))
        )
        scored: list[RetrievedChunk] = []
        for chunk, document in rows:
            embedding = chunk.embedding if isinstance(chunk.embedding, list) else []
            score = cosine(query_vector, [float(value) for value in embedding])
            if score < self._score_floor:
                continue
            scored.append(
                RetrievedChunk(
                    document_id=document.id,
                    version=document.version,
                    title=document.title,
                    text=chunk.text,
                    score=score,
                )
            )
        return rank_chunks(scored, limit)


def rank_chunks(chunks: list[RetrievedChunk], limit: int) -> list[RetrievedChunk]:
    """Highest score first. Title and text break ties."""
    ranked = sorted(chunks, key=lambda item: (-item.score, item.title, item.text))
    return ranked[:limit]


def _latest_published(session: Session, tenant_id: UUID) -> list[UUID]:
    rows = session.scalars(
        select(KnowledgeDocumentRow).where(
            KnowledgeDocumentRow.tenant_id == tenant_id,
            KnowledgeDocumentRow.status == "published",
        )
    )
    best: dict[str, KnowledgeDocumentRow] = {}
    for row in rows:
        current = best.get(row.source_uri)
        if current is None or row.version > current.version:
            best[row.source_uri] = row
    return [row.id for row in best.values()]
