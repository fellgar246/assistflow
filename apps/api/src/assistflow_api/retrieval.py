"""Select a retrieval provider. AWS clients are built only for the selected provider."""

from __future__ import annotations

from typing import TYPE_CHECKING

from assistflow_knowledge.retriever import KnowledgeRetriever
from assistflow_knowledge.selection import build_retriever
from sqlalchemy.orm import Session

from assistflow_api.config import Settings, validate_retrieval_settings

if TYPE_CHECKING:
    from assistflow_knowledge.managed import ManagedRetrievalClient
    from assistflow_knowledge.object_store import ObjectStore


def build_knowledge_retriever(
    settings: Settings,
    session: Session,
    *,
    object_store: ObjectStore | None = None,
    managed_client: ManagedRetrievalClient | None = None,
) -> KnowledgeRetriever:
    """Build the configured retriever. Local mode never constructs an AWS client."""
    validate_retrieval_settings(settings)
    store = object_store
    client = managed_client
    if settings.rag_provider.value == "s3" and store is None:
        from assistflow_tools.aws_retrieval import s3_store

        store = s3_store(settings.aws_region)
    if settings.rag_provider.value == "managed" and client is None:
        from assistflow_tools.aws_retrieval import managed_retrieve_client

        client = managed_retrieve_client(settings.aws_region)
    return build_retriever(
        settings.rag_provider.value,
        session,
        bucket=settings.knowledge_bucket,
        key_prefix=settings.knowledge_key_prefix,
        managed_enabled=settings.managed_rag_enabled,
        knowledge_base_id=settings.managed_knowledge_base_id,
        knowledge_bases=settings.managed_knowledge_bases,
        metadata_key=settings.managed_rag_metadata_key,
        chunk_cap=settings.max_chunks_per_retrieval,
        score_floor=settings.retrieval_score_floor,
        local_only=settings.local_only_mode,
        object_store=store,
        managed_client=client,
    )
