"""Application-owned retrieval over documents stored in object storage."""

from uuid import UUID

from assistflow_customers.errors import require_tenant_id

from assistflow_knowledge.chunking import chunk_text
from assistflow_knowledge.documents import loads_document
from assistflow_knowledge.embeddings import EmbeddingProvider, cosine
from assistflow_knowledge.object_store import ObjectStore
from assistflow_knowledge.retriever import (
    DEFAULT_CHUNK_CAP,
    DEFAULT_SCORE_FLOOR,
    RetrievedChunk,
    rank_chunks,
)
from assistflow_knowledge.sync import tenant_prefix


class S3KnowledgeRetriever:
    """Score synced product files for one tenant. The bucket root is never listed."""

    def __init__(
        self,
        store: ObjectStore,
        bucket: str,
        key_prefix: str,
        embedder: EmbeddingProvider,
        *,
        chunk_cap: int = DEFAULT_CHUNK_CAP,
        score_floor: float = DEFAULT_SCORE_FLOOR,
    ) -> None:
        if bucket.strip() == "":
            raise ValueError("S3 retrieval requires a bucket.")
        if "{tenant_id}" not in key_prefix:
            raise ValueError("S3 retrieval requires a {tenant_id} prefix.")
        self._store = store
        self._bucket = bucket
        self._key_prefix = key_prefix
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
        """Return scored chunks from that tenant's prefix only."""
        tenant_id = require_tenant_id(tenant_id)
        if limit > self._chunk_cap:
            raise ValueError("Retrieval limit exceeds the configured cap.")
        if limit < 1 or not query.strip():
            return []
        prefix = tenant_prefix(self._key_prefix, tenant_id)
        query_vector = self._embedder.embed(query)
        scored: list[RetrievedChunk] = []
        for key in self._store.list_keys(self._bucket, prefix):
            if not key.startswith(prefix):
                continue
            raw = self._store.get_bytes(self._bucket, key)
            if raw is None:
                continue
            document = loads_document(raw)
            if document is None or document.status != "published":
                continue
            if document.tenant_id != tenant_id:
                continue
            for text in chunk_text(document.body):
                score = cosine(query_vector, self._embedder.embed(text))
                if score < self._score_floor:
                    continue
                scored.append(
                    RetrievedChunk(
                        document_id=document.document_id,
                        version=document.version,
                        title=document.title,
                        text=text,
                        score=score,
                    )
                )
        return rank_chunks(scored, limit)
