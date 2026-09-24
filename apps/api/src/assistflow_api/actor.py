"""Local development actor.

Tenant and customer come from request headers. This module does not read a
tenant id from a request body or from model output. A later identity check
can replace `require_actor` without changing route code.
"""

from typing import Annotated
from uuid import UUID

from assistflow_customers.errors import SupportError
from fastapi import Header
from pydantic import BaseModel, ConfigDict


class LocalActorOption(BaseModel):
    """A seeded customer the local UI can act as. Labels are for display."""

    model_config = ConfigDict(frozen=True)

    label: str
    organization: str
    tenant_id: UUID
    customer_id: UUID


class LocalActorList(BaseModel):
    model_config = ConfigDict(frozen=True)

    actors: list[LocalActorOption]


LOCAL_ACTORS: tuple[LocalActorOption, ...] = (
    LocalActorOption(
        label="Ava Chen",
        organization="Harbor Goods",
        tenant_id=UUID("11111111-1111-4111-8111-111111111111"),
        customer_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001"),
    ),
    LocalActorOption(
        label="Ben Ortiz",
        organization="Fieldline Supply",
        tenant_id=UUID("22222222-2222-4222-8222-222222222222"),
        customer_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0002"),
    ),
)


class Actor(BaseModel):
    """Server-side caller. Routes use this object instead of body-supplied identity."""

    model_config = ConfigDict(frozen=True)

    tenant_id: UUID
    customer_id: UUID
    actor_type: str
    actor_id: UUID


def require_tenant_header(x_tenant_id: Annotated[str | None, Header()] = None) -> UUID:
    """Read the demo tenant header. A missing value is an error."""
    return _parse_uuid(
        x_tenant_id,
        "tenant_required",
        "A tenant scope is required.",
        "invalid_tenant",
        "The tenant id is invalid.",
    )


def require_actor(
    x_tenant_id: Annotated[str | None, Header()] = None,
    x_customer_id: Annotated[str | None, Header()] = None,
) -> Actor:
    """Resolve the local demo customer. Both ids are headers, never model fields."""
    tenant_id = require_tenant_header(x_tenant_id)
    customer_id = _parse_uuid(
        x_customer_id,
        "customer_required",
        "A customer scope is required.",
        "invalid_customer",
        "The customer id is invalid.",
    )
    return Actor(
        tenant_id=tenant_id,
        customer_id=customer_id,
        actor_type="customer",
        actor_id=customer_id,
    )


def _parse_uuid(
    raw: str | None,
    missing_code: str,
    missing_message: str,
    invalid_code: str,
    invalid_message: str,
) -> UUID:
    if raw is None or raw.strip() == "":
        raise SupportError(missing_code, missing_message, 400)
    try:
        return UUID(raw.strip())
    except ValueError as exc:
        raise SupportError(invalid_code, invalid_message, 400) from exc
