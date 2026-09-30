"""Local knowledge documents, embeddings, and retrieval."""

from assistflow_knowledge.catalog import PUBLISHED_DOCUMENTS, PublishedDocument
from assistflow_knowledge.embeddings import DeterministicEmbedding, EmbeddingProvider
from assistflow_knowledge.ingest import ingest_documents
from assistflow_knowledge.retriever import KnowledgeRetriever, RetrievedChunk

__all__ = [
    "PUBLISHED_DOCUMENTS",
    "DeterministicEmbedding",
    "EmbeddingProvider",
    "KnowledgeRetriever",
    "PublishedDocument",
    "RetrievedChunk",
    "ingest_documents",
]
