"""Load the support-domain fixture into the database.

Running the command again updates the same rows and does not duplicate them.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import structlog
from assistflow_contracts.support import (
    CustomerStatus,
    OrderStatus,
    ShipmentStatus,
    ShippingAddress,
    TicketCategory,
    TicketPriority,
    TicketStatus,
)
from assistflow_customers.repository import CustomerRecord, CustomerRepository
from assistflow_orders.repository import OrderRecord, OrderRepository
from assistflow_shipping.eligibility import check_address_change
from assistflow_shipping.repository import ShipmentRecord, ShipmentRepository
from assistflow_tickets.repository import TicketRecord, TicketRepository
from pydantic import BaseModel, ConfigDict
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from assistflow_api.config import load_settings, repo_root
from assistflow_api.schema import load_models

logger = structlog.get_logger(__name__)


class FixtureCustomer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    email: str
    display_name: str
    status: CustomerStatus
    created_at: datetime


class FixtureShipment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    carrier_name: str
    status: ShipmentStatus
    origin_hub: str
    estimated_delivery_on: date | None
    shipped_at: datetime | None


class FixtureOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    customer_id: UUID
    order_number: str
    status: OrderStatus
    currency: str
    total_cents: int
    shipping_address: ShippingAddress
    created_at: datetime
    shipment: FixtureShipment


class FixtureTicket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    customer_id: UUID
    priority: TicketPriority
    category: TicketCategory
    status: TicketStatus
    summary: str
    created_at: datetime


class FixtureTenant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    label: str
    customers: list[FixtureCustomer]
    orders: list[FixtureOrder]
    tickets: list[FixtureTicket] = []


class FixtureFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policies: list[str]
    tenants: list[FixtureTenant]


def fixture_path() -> Path:
    return repo_root() / "knowledge" / "fixtures" / "support_domain.json"


def seed_support_domain(engine: Engine, path: Path | None = None) -> None:
    """Insert or update the published support fixture."""
    load_models()
    source = path if path is not None else fixture_path()
    document = FixtureFile.model_validate(json.loads(source.read_text(encoding="utf-8")))
    root = repo_root()
    for relative in document.policies:
        if not (root / relative).is_file():
            raise FileNotFoundError(f"Published policy file is missing: {relative}")

    today = datetime.now(UTC).date()
    with Session(engine) as session:
        customers = 0
        orders = 0
        for tenant in document.tenants:
            for customer in tenant.customers:
                _upsert_customer(session, tenant.id, customer)
                customers += 1
            for order in tenant.orders:
                _upsert_order(session, tenant.id, order, today)
                orders += 1
            for ticket in tenant.tickets:
                _upsert_ticket(session, tenant.id, ticket)
        session.commit()
    logger.info("support_domain_seeded", customers=customers, orders=orders)


def _upsert_customer(session: Session, tenant_id: UUID, item: FixtureCustomer) -> None:
    repository = CustomerRepository(session)
    existing = repository.get_by_email(tenant_id, item.email)
    record = CustomerRecord(
        id=item.id if existing is None else existing.id,
        tenant_id=tenant_id,
        email=item.email,
        display_name=item.display_name,
        status=item.status,
        created_at=item.created_at if existing is None else existing.created_at,
    )
    if existing is None:
        repository.insert(record)
    else:
        repository.update(record)


def _upsert_order(session: Session, tenant_id: UUID, item: FixtureOrder, today: date) -> None:
    repository = OrderRepository(session)
    existing = repository.get(tenant_id, item.order_number)
    record = OrderRecord(
        id=item.id if existing is None else existing.id,
        tenant_id=tenant_id,
        customer_id=item.customer_id,
        order_number=item.order_number,
        status=item.status,
        currency=item.currency,
        total_cents=item.total_cents,
        shipping_address=item.shipping_address,
        created_at=item.created_at if existing is None else existing.created_at,
    )
    if existing is None:
        repository.insert(record)
    else:
        repository.update(record)
    session.flush()
    stored = repository.require(tenant_id, item.order_number)
    _upsert_shipment(session, tenant_id, stored.id, item, today)


def _upsert_shipment(
    session: Session, tenant_id: UUID, order_id: UUID, item: FixtureOrder, today: date
) -> None:
    repository = ShipmentRepository(session)
    existing = repository.get_by_order(tenant_id, order_id)
    shipment = item.shipment
    eligible = check_address_change(
        item.status,
        shipment.status,
        shipment.estimated_delivery_on,
        today,
    ).eligible
    record = ShipmentRecord(
        id=shipment.id if existing is None else existing.id,
        tenant_id=tenant_id,
        order_id=order_id,
        carrier_name=shipment.carrier_name,
        status=shipment.status,
        origin_hub=shipment.origin_hub,
        estimated_delivery_on=shipment.estimated_delivery_on,
        address_change_eligible=eligible,
        shipped_at=shipment.shipped_at,
    )
    if existing is None:
        repository.insert(record)
    else:
        repository.update(record)


def _upsert_ticket(session: Session, tenant_id: UUID, item: FixtureTicket) -> None:
    repository = TicketRepository(session)
    existing = repository.get(tenant_id, item.id)
    record = TicketRecord(
        id=item.id,
        tenant_id=tenant_id,
        customer_id=item.customer_id,
        conversation_id=None if existing is None else existing.conversation_id,
        priority=item.priority,
        category=item.category,
        status=item.status,
        summary=item.summary,
        assigned_to=None if existing is None else existing.assigned_to,
        created_at=item.created_at if existing is None else existing.created_at,
    )
    if existing is None:
        repository.insert(record)
    else:
        repository.update(record)


def main() -> None:
    from assistflow_api.db import create_db_engine

    engine = create_db_engine(load_settings().database_url)
    try:
        seed_support_domain(engine)
    finally:
        engine.dispose()
    print("Seeded support domain fixtures.")


if __name__ == "__main__":
    main()
