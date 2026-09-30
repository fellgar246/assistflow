"""Copy published product files into object storage for one tenant at a time."""

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from assistflow_customers.errors import require_tenant_id

from assistflow_knowledge.catalog import PUBLISHED_DOCUMENTS, PublishedDocument
from assistflow_knowledge.documents import (
    StoredDocument,
    dumps_document,
    loads_document,
    stable_document_id,
)
from assistflow_knowledge.ingest import content_checksum
from assistflow_knowledge.object_store import ObjectStore


@dataclass(frozen=True)
class SyncResult:
    """What one product file did for one tenant."""

    source_uri: str
    tenant_id: UUID
    version: int
    created: bool


def sync_documents(
    store: ObjectStore,
    bucket: str,
    key_prefix: str,
    root: Path,
    tenant_ids: list[UUID],
    *,
    documents: tuple[PublishedDocument, ...] = PUBLISHED_DOCUMENTS,
) -> list[SyncResult]:
    """Upload the published corpus. Unchanged checksums are left in place.

    Only files under `root` are read. The command does not fetch remote URLs.
    """
    if bucket.strip() == "":
        raise ValueError("Document sync requires a bucket.")
    if "{tenant_id}" not in key_prefix:
        raise ValueError("A {tenant_id} prefix is required.")
    results: list[SyncResult] = []
    for tenant_id in tenant_ids:
        require_tenant_id(tenant_id)
        for document in documents:
            body = _read_product_file(root, document.source_uri)
            results.append(_sync_one(store, bucket, key_prefix, tenant_id, document, body))
    return results


def tenant_prefix(key_prefix: str, tenant_id: UUID) -> str:
    """Prefix that contains the tenant id. The bucket root is never used."""
    rendered = key_prefix.format(tenant_id=str(tenant_id))
    if str(tenant_id) not in rendered or ".." in rendered.split("/"):
        raise ValueError("A {tenant_id} prefix is required.")
    if not rendered.endswith("/"):
        rendered = f"{rendered}/"
    return rendered


def object_key(key_prefix: str, tenant_id: UUID, source_uri: str) -> str:
    """Key for one tenant's copy of a product file."""
    _reject_source_uri(source_uri)
    return f"{tenant_prefix(key_prefix, tenant_id)}{source_uri}.json"


def _sync_one(
    store: ObjectStore,
    bucket: str,
    key_prefix: str,
    tenant_id: UUID,
    document: PublishedDocument,
    body: str,
) -> SyncResult:
    key = object_key(key_prefix, tenant_id, document.source_uri)
    checksum = content_checksum(body)
    raw = store.get_bytes(bucket, key)
    existing = loads_document(raw) if raw is not None else None
    if (
        existing is not None
        and existing.checksum == checksum
        and existing.tenant_id == tenant_id
        and existing.status == "published"
    ):
        return SyncResult(document.source_uri, tenant_id, existing.version, created=False)
    version = 1 if existing is None else existing.version + 1
    stored = StoredDocument(
        document_id=stable_document_id(tenant_id, document.source_uri),
        tenant_id=tenant_id,
        title=document.title,
        version=version,
        source_uri=document.source_uri,
        checksum=checksum,
        status="published",
        body=body,
    )
    store.put_bytes(bucket, key, dumps_document(stored))
    return SyncResult(document.source_uri, tenant_id, version, created=True)


def _read_product_file(root: Path, source_uri: str) -> str:
    _reject_source_uri(source_uri)
    base = root.resolve()
    path = (base / source_uri).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise ValueError("Sync only reads published product files.")
    return path.read_text(encoding="utf-8")


def _reject_source_uri(source_uri: str) -> None:
    if source_uri.strip() == "":
        raise ValueError("Sync only reads published product files.")
    lowered = source_uri.lower()
    if "://" in lowered or lowered.startswith(("http:", "https:")):
        raise ValueError("Sync only reads published product files.")
    parts = Path(source_uri).parts
    if not parts or source_uri.startswith(("/", "\\")) or ".." in parts:
        raise ValueError("Sync only reads published product files.")
