"""Choose a retriever from plain settings. Callers supply any cloud client."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.orm import Session

from assistflow_knowledge.embeddings import DeterministicEmbedding, EmbeddingProvider
from assistflow_knowledge.retriever import (
    DEFAULT_CHUNK_CAP,
    DEFAULT_SCORE_FLOOR,
    KnowledgeRetriever,
    LocalKnowledgeRetriever,
)

if TYPE_CHECKING:
    from assistflow_knowledge.managed import ManagedRetrievalClient
    from assistflow_knowledge.object_store import ObjectStore

_TRUE = {"1", "true", "yes", "on"}


def build_retriever(
    provider: str,
    session: Session,
    *,
    bucket: str = "",
    key_prefix: str = "tenants/{tenant_id}/",
    managed_enabled: bool = False,
    knowledge_base_id: str = "",
    knowledge_bases: Mapping[str, str] | None = None,
    metadata_key: str = "",
    chunk_cap: int = DEFAULT_CHUNK_CAP,
    score_floor: float = DEFAULT_SCORE_FLOOR,
    local_only: bool = False,
    object_store: ObjectStore | None = None,
    managed_client: ManagedRetrievalClient | None = None,
    embedder: EmbeddingProvider | None = None,
) -> KnowledgeRetriever:
    """Return the selected retriever. Local-only mode always returns the local index."""
    vectors = embedder if embedder is not None else DeterministicEmbedding()
    selected = "local" if local_only else provider.strip().lower()
    if selected in {"", "local"}:
        return LocalKnowledgeRetriever(
            session,
            vectors,
            chunk_cap=chunk_cap,
            score_floor=score_floor,
        )
    if selected == "s3":
        if object_store is None:
            raise ValueError("S3 retrieval requires an object store.")
        from assistflow_knowledge.s3 import S3KnowledgeRetriever

        return S3KnowledgeRetriever(
            object_store,
            bucket,
            key_prefix,
            vectors,
            chunk_cap=chunk_cap,
            score_floor=score_floor,
        )
    if selected == "managed":
        if not managed_enabled:
            raise RuntimeError("Managed retrieval is disabled.")
        if managed_client is None:
            raise ValueError("Managed retrieval requires a retrieve client.")
        from assistflow_knowledge.managed import ManagedKnowledgeRetriever

        bases = {UUID(tenant_id): base for tenant_id, base in (knowledge_bases or {}).items()}
        return ManagedKnowledgeRetriever(
            managed_client,
            knowledge_base_id=knowledge_base_id,
            knowledge_bases=bases,
            metadata_key=metadata_key,
            chunk_cap=chunk_cap,
            score_floor=score_floor,
        )
    raise ValueError("Invalid RAG_PROVIDER. Expected local, s3, or managed.")


def build_retriever_from_environ(
    session: Session,
    environ: Mapping[str, str] | None = None,
    *,
    object_store: ObjectStore | None = None,
    managed_client: ManagedRetrievalClient | None = None,
) -> KnowledgeRetriever:
    """Read retrieval settings from the process environment. Missing values stay local."""
    values = os.environ if environ is None else environ
    local_only = values.get("LOCAL_ONLY_MODE", "").strip().lower() in _TRUE
    provider = "local" if local_only else values.get("RAG_PROVIDER", "local")
    return build_retriever(
        provider,
        session,
        bucket=values.get("KNOWLEDGE_BUCKET", "").strip(),
        key_prefix=values.get("KNOWLEDGE_KEY_PREFIX", "").strip() or "tenants/{tenant_id}/",
        managed_enabled=values.get("MANAGED_RAG_ENABLED", "").strip().lower() in _TRUE,
        knowledge_base_id=values.get("MANAGED_KNOWLEDGE_BASE_ID", "").strip(),
        knowledge_bases=_bases(values.get("MANAGED_KNOWLEDGE_BASES")),
        metadata_key=values.get("MANAGED_RAG_METADATA_KEY", "").strip(),
        chunk_cap=_int(values.get("MAX_CHUNKS_PER_RETRIEVAL"), DEFAULT_CHUNK_CAP),
        score_floor=_float(values.get("RETRIEVAL_SCORE_FLOOR"), DEFAULT_SCORE_FLOOR),
        local_only=local_only,
        object_store=object_store,
        managed_client=managed_client,
    )


def _bases(raw: str | None) -> dict[str, str]:
    if raw is None or raw.strip() == "":
        return {}
    parsed: dict[str, str] = {}
    for part in raw.split(","):
        piece = part.strip()
        if piece == "" or "=" not in piece:
            continue
        tenant_id, base = piece.split("=", 1)
        if tenant_id.strip() and base.strip():
            parsed[tenant_id.strip()] = base.strip()
    return parsed


def _int(raw: str | None, default: int) -> int:
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _float(raw: str | None, default: float) -> float:
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default
