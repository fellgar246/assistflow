"""Request dependencies for tenant scope and paging."""

from collections.abc import Iterator
from typing import Annotated, cast
from uuid import UUID, uuid4

from fastapi import Header, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from assistflow_api.actor import require_tenant_header


class PageQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    limit: int
    cursor: str | None


def require_tenant(x_tenant_id: Annotated[str | None, Header()] = None) -> UUID:
    """Read the tenant from the demo header. A missing value is an error."""
    return require_tenant_header(x_tenant_id)


def correlation_id(
    request: Request,
    x_correlation_id: Annotated[str | None, Header()] = None,
) -> str:
    """Use the caller id when present. Otherwise the API assigns one."""
    if x_correlation_id is not None and x_correlation_id.strip() != "":
        value = x_correlation_id.strip()
    else:
        value = str(uuid4())
    request.state.correlation_id = value
    return value


def get_session(request: Request) -> Iterator[Session]:
    engine = cast(Engine, request.app.state.engine)
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def page_query(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> PageQuery:
    if cursor is not None and cursor.strip() == "":
        cursor = None
    return PageQuery(limit=limit, cursor=cursor)
