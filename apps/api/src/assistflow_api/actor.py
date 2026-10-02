"""Verified caller.

Tenant, role, and customer or agent id come from a checked token.
Routes do not read those values from a request body.
"""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Role(StrEnum):
    CUSTOMER = "customer"
    SUPPORT_AGENT = "support_agent"


class SeedUser(BaseModel):
    """A deterministic local person. The login page offers the name, not a tenant id."""

    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    organization: str
    role: Role
    tenant_id: UUID
    customer_id: UUID | None = None
    agent_id: UUID | None = None


SEED_USERS: tuple[SeedUser, ...] = (
    SeedUser(
        key="ava-chen",
        label="Ava Chen",
        organization="Harbor Goods",
        role=Role.CUSTOMER,
        tenant_id=UUID("11111111-1111-4111-8111-111111111111"),
        customer_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001"),
    ),
    SeedUser(
        key="nora-hale",
        label="Nora Hale",
        organization="Harbor Goods",
        role=Role.SUPPORT_AGENT,
        tenant_id=UUID("11111111-1111-4111-8111-111111111111"),
        agent_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbb0001"),
    ),
    SeedUser(
        key="ben-ortiz",
        label="Ben Ortiz",
        organization="Fieldline Supply",
        role=Role.CUSTOMER,
        tenant_id=UUID("22222222-2222-4222-8222-222222222222"),
        customer_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0002"),
    ),
    SeedUser(
        key="owen-blake",
        label="Owen Blake",
        organization="Fieldline Supply",
        role=Role.SUPPORT_AGENT,
        tenant_id=UUID("22222222-2222-4222-8222-222222222222"),
        agent_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbb0002"),
    ),
)


class LocalActorOption(BaseModel):
    """A seeded customer the local UI can name. Labels are for display."""

    model_config = ConfigDict(frozen=True)

    label: str
    organization: str
    tenant_id: UUID
    customer_id: UUID


class LocalActorList(BaseModel):
    model_config = ConfigDict(frozen=True)

    actors: list[LocalActorOption]


def _customer_option(user: SeedUser) -> LocalActorOption:
    if user.customer_id is None:
        raise ValueError("A customer seed is missing a customer id.")
    return LocalActorOption(
        label=user.label,
        organization=user.organization,
        tenant_id=user.tenant_id,
        customer_id=user.customer_id,
    )


LOCAL_ACTORS: tuple[LocalActorOption, ...] = tuple(
    _customer_option(user) for user in SEED_USERS if user.role is Role.CUSTOMER
)


class LocalStaffOption(BaseModel):
    """A seeded support agent. This list is not a production directory."""

    model_config = ConfigDict(frozen=True)

    label: str
    organization: str
    tenant_id: UUID
    agent_id: UUID


class LocalStaffList(BaseModel):
    model_config = ConfigDict(frozen=True)

    actors: list[LocalStaffOption]


def _staff_option(user: SeedUser) -> LocalStaffOption:
    if user.agent_id is None:
        raise ValueError("A staff seed is missing an agent id.")
    return LocalStaffOption(
        label=user.label,
        organization=user.organization,
        tenant_id=user.tenant_id,
        agent_id=user.agent_id,
    )


LOCAL_STAFF: tuple[LocalStaffOption, ...] = tuple(
    _staff_option(user) for user in SEED_USERS if user.role is Role.SUPPORT_AGENT
)


class StaffActor(BaseModel):
    """Verified support agent. Tenant and agent id come from the token."""

    model_config = ConfigDict(frozen=True)

    tenant_id: UUID
    agent_id: UUID
    display_name: str
    actor_type: str


class Actor(BaseModel):
    """Verified customer. Routes use this object instead of body-supplied identity."""

    model_config = ConfigDict(frozen=True)

    tenant_id: UUID
    customer_id: UUID
    role: Role = Role.CUSTOMER
    actor_type: str
    actor_id: UUID


def seed_user(key: str) -> SeedUser | None:
    """Return one local person by login key."""
    return next((user for user in SEED_USERS if user.key == key), None)


def display_name_for(
    *,
    role: Role,
    tenant_id: UUID,
    customer_id: UUID | None,
    agent_id: UUID | None,
) -> str:
    """Name a seeded person. Anyone else is labeled without inventing a tenant."""
    for user in SEED_USERS:
        if user.role is not role or user.tenant_id != tenant_id:
            continue
        if role is Role.CUSTOMER and user.customer_id == customer_id:
            return user.label
        if role is Role.SUPPORT_AGENT and user.agent_id == agent_id:
            return user.label
    return "Signed in"
