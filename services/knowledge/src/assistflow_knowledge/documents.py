"""JSON documents stored for application-owned retrieval."""

import json
from dataclasses import dataclass
from uuid import UUID, uuid5

_DOCUMENT_NAMESPACE = UUID("6f0c2e1a-7b4d-4e1a-9c3f-1a2b3c4d5e6f")


@dataclass(frozen=True)
class StoredDocument:
    """One published source file for one tenant."""

    document_id: UUID
    tenant_id: UUID
    title: str
    version: int
    source_uri: str
    checksum: str
    status: str
    body: str


def stable_document_id(tenant_id: UUID, source_uri: str) -> UUID:
    """Same tenant and source keep one id across versions."""
    return uuid5(_DOCUMENT_NAMESPACE, f"{tenant_id}:{source_uri}")


def dumps_document(document: StoredDocument) -> bytes:
    """Encode one stored document. The body is the product file, not a remote URL."""
    payload = {
        "document_id": str(document.document_id),
        "tenant_id": str(document.tenant_id),
        "title": document.title,
        "version": document.version,
        "source_uri": document.source_uri,
        "checksum": document.checksum,
        "status": document.status,
        "body": document.body,
    }
    return json.dumps(payload).encode("utf-8")


def loads_document(raw: bytes) -> StoredDocument | None:
    """Return a document when every citation field is present. Otherwise drop it."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    document_id = _uuid(payload.get("document_id"))
    tenant_id = _uuid(payload.get("tenant_id"))
    title = payload.get("title")
    version = payload.get("version")
    source_uri = payload.get("source_uri")
    checksum = payload.get("checksum")
    status = payload.get("status")
    body = payload.get("body")
    if (
        document_id is None
        or tenant_id is None
        or not isinstance(title, str)
        or not title.strip()
        or isinstance(version, bool)
        or not isinstance(version, int)
        or version < 1
        or not isinstance(source_uri, str)
        or not source_uri.strip()
        or not isinstance(checksum, str)
        or not isinstance(status, str)
        or not isinstance(body, str)
    ):
        return None
    return StoredDocument(
        document_id=document_id,
        tenant_id=tenant_id,
        title=title,
        version=version,
        source_uri=source_uri,
        checksum=checksum,
        status=status,
        body=body,
    )


def _uuid(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None
