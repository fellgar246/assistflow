"""Read published help documents for the signed-in tenant."""

from typing import Annotated, Any
from uuid import UUID

from assistflow_contracts.support import Problem
from assistflow_customers.errors import SupportError
from assistflow_knowledge.models import KnowledgeDocumentRow
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from assistflow_api.actor import Actor
from assistflow_api.deps import get_session, require_customer

router = APIRouter()

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": Problem},
    403: {"model": Problem},
    404: {"model": Problem},
}

CustomerCaller = Annotated[Actor, Depends(require_customer)]
Db = Annotated[Session, Depends(get_session)]


class DocumentView(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    title: str
    source_uri: str
    version: int
    body: str


class DocumentPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[DocumentView]


def _view(row: KnowledgeDocumentRow) -> DocumentView:
    return DocumentView(
        id=row.id,
        title=row.title,
        source_uri=row.source_uri,
        version=row.version,
        body=row.body,
    )


def _published(session: Session, tenant_id: UUID, document_id: UUID) -> KnowledgeDocumentRow:
    row = session.get(KnowledgeDocumentRow, document_id)
    if row is None or row.tenant_id != tenant_id or row.status != "published":
        raise SupportError("document_not_found", "That document was not found.", 404)
    return row


@router.get("/documents", response_model=DocumentPage, responses=_ERRORS)
def list_documents(actor: CustomerCaller, session: Db) -> DocumentPage:
    """List published documents for the token tenant."""
    rows = session.scalars(
        select(KnowledgeDocumentRow)
        .where(
            KnowledgeDocumentRow.tenant_id == actor.tenant_id,
            KnowledgeDocumentRow.status == "published",
        )
        .order_by(KnowledgeDocumentRow.title, KnowledgeDocumentRow.id)
    ).all()
    return DocumentPage(items=[_view(row) for row in rows])


@router.get("/documents/{document_id}", response_model=DocumentView, responses=_ERRORS)
def read_document(document_id: UUID, actor: CustomerCaller, session: Db) -> DocumentView:
    """Return one published document. Another tenant is not found."""
    return _view(_published(session, actor.tenant_id, document_id))
