"""Change a shipping address. This command does not call a carrier."""

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from assistflow_contracts.support import ShippingAddress
from assistflow_conversations.audit import audit_payload
from assistflow_conversations.repository import AuditEventRecord, AuditRepository
from assistflow_customers.errors import SupportError
from assistflow_customers.hashing import canonical_hash
from assistflow_customers.repository import IdempotencyRepository, replay_or_conflict
from assistflow_orders.repository import OrderRepository
from sqlalchemy.orm import Session

from assistflow_shipping.eligibility import check_address_change
from assistflow_shipping.repository import ShipmentRepository

_COMMAND = "update_shipping_address"


@dataclass(frozen=True)
class AddressWrite:
    order_number: str
    previous_address: ShippingAddress
    new_address: ShippingAddress
    replayed: bool


def update_shipping_address(
    session: Session,
    tenant_id: UUID,
    order_number: str,
    new_address: ShippingAddress,
    idempotency_key: str,
    *,
    customer_id: UUID,
    actor_type: str,
    correlation_id: str,
    actor_id: UUID,
    today: date | None = None,
) -> AddressWrite:
    """Store a new address when the shipment is still eligible. Replays do not write again."""
    arguments_hash = canonical_hash(
        {"order_number": order_number, "new_address": new_address.model_dump(mode="json")}
    )
    idempotency = IdempotencyRepository(session)
    stored = replay_or_conflict(
        idempotency.find(tenant_id, _COMMAND, idempotency_key),
        arguments_hash,
    )
    if stored is not None:
        return AddressWrite(
            order_number=str(stored["order_number"]),
            previous_address=ShippingAddress.model_validate(stored["previous_address"]),
            new_address=ShippingAddress.model_validate(stored["new_address"]),
            replayed=True,
        )

    order = OrderRepository(session).require(tenant_id, order_number)
    if actor_type == "customer" and order.customer_id != customer_id:
        raise SupportError("denied", "That order is not available.", 403)
    shipment = ShipmentRepository(session).get_by_order(tenant_id, order.id)
    decision = check_address_change(
        order.status,
        None if shipment is None else shipment.status,
        None if shipment is None else shipment.estimated_delivery_on,
        datetime.now(UTC).date() if today is None else today,
    )
    if not decision.eligible:
        raise SupportError(
            decision.reason_code,
            "This order is not eligible for an address change.",
            409,
        )

    created_at = datetime.now(UTC)
    previous = order.shipping_address
    OrderRepository(session).update(replace(order, shipping_address=new_address))
    AuditRepository(session).append(
        AuditEventRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="shipping.address_updated",
            target_type="order",
            target_id=order.id,
            payload=audit_payload(
                {
                    "order_number": order.order_number,
                    "previous_address": previous.model_dump(mode="json"),
                    "new_address": new_address.model_dump(mode="json"),
                }
            ),
            created_at=created_at,
        )
    )
    result: dict[str, object] = {
        "order_number": order.order_number,
        "previous_address": previous.model_dump(mode="json"),
        "new_address": new_address.model_dump(mode="json"),
    }
    idempotency.save(
        record_id=uuid4(),
        tenant_id=tenant_id,
        command_name=_COMMAND,
        idempotency_key=idempotency_key,
        arguments_hash=arguments_hash,
        result_json=result,
        created_at=created_at,
    )
    return AddressWrite(
        order_number=order.order_number,
        previous_address=previous,
        new_address=new_address,
        replayed=False,
    )
