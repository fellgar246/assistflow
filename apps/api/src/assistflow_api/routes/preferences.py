"""Read and delete stored preferences for the current customer."""

from datetime import UTC, datetime
from typing import Annotated, Any

from assistflow_contracts.memory import MemoryPreferenceList
from assistflow_contracts.support import Problem
from assistflow_customers.errors import SupportError
from assistflow_memory.ports import PreferenceMemory
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from assistflow_api.actor import Actor, require_actor
from assistflow_api.config import Settings
from assistflow_api.deps import correlation_id, get_session
from assistflow_api.turns import memory_ports_for

router = APIRouter()

_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": Problem},
}

DevActor = Annotated[Actor, Depends(require_actor)]
Db = Annotated[Session, Depends(get_session)]
Correlation = Annotated[str, Depends(correlation_id)]


def _stamp(response: Response, correlation: str) -> None:
    response.headers["X-Correlation-Id"] = correlation


def _preferences(request: Request, session: Session) -> PreferenceMemory:
    settings = request.app.state.settings
    if not isinstance(settings, Settings):
        raise SupportError("not_found", "Preferences are not available.", 404)
    port = memory_ports_for(settings, session, None).preferences
    if port is None:
        raise SupportError("not_found", "Preferences are not available.", 404)
    return port


@router.get("/preferences", response_model=MemoryPreferenceList, responses=_ERRORS)
def list_preferences(
    request: Request,
    response: Response,
    actor: DevActor,
    session: Db,
    correlation: Correlation,
) -> MemoryPreferenceList:
    """Return this customer's stored preferences. Another tenant is denied."""
    port = _preferences(request, session)
    _stamp(response, correlation)
    items = port.load(actor.tenant_id, actor.customer_id, datetime.now(UTC))
    return MemoryPreferenceList(items=items)


@router.delete("/preferences", status_code=204, responses=_ERRORS)
def delete_preferences(
    request: Request,
    response: Response,
    actor: DevActor,
    session: Db,
    correlation: Correlation,
) -> Response:
    """Delete this customer's preferences. Another tenant's rows stay in place."""
    port = _preferences(request, session)
    port.delete(actor.tenant_id, actor.customer_id)
    _stamp(response, correlation)
    return Response(status_code=204)
