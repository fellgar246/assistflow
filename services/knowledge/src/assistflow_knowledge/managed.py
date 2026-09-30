"""Managed knowledge-base adapter. The client is built only when the flag is on."""

from collections.abc import Mapping
from typing import Any, Protocol
from uuid import UUID

from assistflow_customers.errors import require_tenant_id

from assistflow_knowledge.retriever import (
    DEFAULT_CHUNK_CAP,
    DEFAULT_SCORE_FLOOR,
    RetrievedChunk,
    rank_chunks,
)


class ManagedHit:
    """One provider hit before citation checks."""

    def __init__(
        self,
        *,
        text: str,
        score: float | None,
        document_id: str | None,
        title: str | None,
        version: str | None,
        tenant_id: str | None = None,
    ) -> None:
        self.text = text
        self.score = score
        self.document_id = document_id
        self.title = title
        self.version = version
        self.tenant_id = tenant_id


class ManagedRetrievalClient(Protocol):
    """Subset of a managed retrieve call. The tenant filter is mandatory."""

    def retrieve(
        self,
        *,
        knowledge_base_id: str,
        query: str,
        tenant_id: str,
        metadata_key: str,
        limit: int,
    ) -> list[ManagedHit]:
        """Return hits for one tenant. An empty metadata key is only valid for a tenant base."""


class ManagedKnowledgeRetriever:
    """Map managed hits into the shared chunk type. Hits that cannot be cited are dropped."""

    def __init__(
        self,
        client: ManagedRetrievalClient,
        *,
        knowledge_base_id: str = "",
        knowledge_bases: Mapping[UUID, str] | None = None,
        metadata_key: str = "",
        chunk_cap: int = DEFAULT_CHUNK_CAP,
        score_floor: float = DEFAULT_SCORE_FLOOR,
    ) -> None:
        bases = dict(knowledge_bases or {})
        if not metadata_key.strip() and not bases:
            raise ValueError(
                "Managed retrieval requires a metadata filter or a knowledge base per tenant."
            )
        if knowledge_base_id.strip() and not metadata_key.strip():
            raise ValueError("A shared knowledge base requires a tenant metadata filter.")
        if not knowledge_base_id.strip() and not bases:
            raise ValueError(
                "Managed retrieval requires a metadata filter or a knowledge base per tenant."
            )
        self._client = client
        self._knowledge_base_id = knowledge_base_id.strip()
        self._bases = bases
        self._metadata_key = metadata_key.strip()
        self._chunk_cap = chunk_cap
        self._score_floor = score_floor

    @property
    def chunk_cap(self) -> int:
        return self._chunk_cap

    @property
    def score_floor(self) -> float:
        return self._score_floor

    def retrieve(self, tenant_id: UUID, query: str, limit: int) -> list[RetrievedChunk]:
        """Query one tenant. A missing base for that tenant returns no chunks."""
        tenant_id = require_tenant_id(tenant_id)
        if limit > self._chunk_cap:
            raise ValueError("Retrieval limit exceeds the configured cap.")
        if limit < 1 or not query.strip():
            return []
        knowledge_base_id = self._bases.get(tenant_id, self._knowledge_base_id)
        if knowledge_base_id == "":
            return []
        if not self._metadata_key and tenant_id not in self._bases:
            raise ValueError(
                "Managed retrieval requires a metadata filter or a knowledge base per tenant."
            )
        hits = self._client.retrieve(
            knowledge_base_id=knowledge_base_id,
            query=query,
            tenant_id=str(tenant_id),
            metadata_key=self._metadata_key,
            limit=limit,
        )
        return _map_hits(hits, tenant_id, score_floor=self._score_floor, limit=limit)


def _map_hits(
    hits: list[ManagedHit],
    tenant_id: UUID,
    *,
    score_floor: float,
    limit: int,
) -> list[RetrievedChunk]:
    cited: list[tuple[RetrievedChunk, float | None]] = []
    saw_score = False
    for hit in hits:
        if hit.tenant_id not in {None, "", str(tenant_id)}:
            continue
        chunk = _citable_chunk(hit)
        if chunk is None:
            continue
        if hit.score is not None:
            saw_score = True
        cited.append((chunk, hit.score))
    if not cited:
        return []
    if not saw_score:
        return [chunk for chunk, _score in cited][:limit]
    kept = [chunk for chunk, score in cited if score is not None and score >= score_floor]
    return rank_chunks(kept, limit)


def _citable_chunk(hit: ManagedHit) -> RetrievedChunk | None:
    document_id = _uuid(hit.document_id)
    version = _version(hit.version)
    title = hit.title.strip() if isinstance(hit.title, str) else ""
    text = hit.text.strip()
    if document_id is None or version is None or title == "" or text == "":
        return None
    score = 1.0 if hit.score is None else hit.score
    return RetrievedChunk(
        document_id=document_id,
        version=version,
        title=title,
        text=text,
        score=score,
    )


def hits_from_retrieve_response(payload: dict[str, Any]) -> list[ManagedHit]:
    raw_hits = payload.get("retrievalResults")
    if not isinstance(raw_hits, list):
        return []
    hits: list[ManagedHit] = []
    for item in raw_hits:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        text = content.get("text") if isinstance(content, dict) else ""
        raw_metadata = item.get("metadata")
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        score = item.get("score")
        parsed_score: float | None
        if isinstance(score, bool) or not isinstance(score, int | float):
            parsed_score = None
        else:
            parsed_score = float(score)
        hits.append(
            ManagedHit(
                text=text if isinstance(text, str) else "",
                score=parsed_score,
                document_id=_meta_str(metadata, "document_id"),
                title=_meta_str(metadata, "title"),
                version=_meta_str(metadata, "version"),
                tenant_id=_meta_str(metadata, "tenant_id"),
            )
        )
    return hits


def _meta_str(metadata: Mapping[Any, Any], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, int | float) and key == "version":
        return str(int(value))
    if isinstance(value, dict):
        nested = value.get("stringValue")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
        number = value.get("numberValue")
        if isinstance(number, int | float):
            return str(int(number))
    return None


def _uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _version(value: str | None) -> int | None:
    if value is None or value.strip() == "":
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    if parsed < 1:
        return None
    return parsed
