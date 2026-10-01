"""Create a return request. There is no public HTTP route for this command."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from assistflow_contracts.support import RETURN_REASON_CODES, ReturnStatus
from assistflow_conversations.audit import audit_payload
from assistflow_conversations.repository import AuditEventRecord, AuditRepository
from assistflow_customers.errors import SupportError
from assistflow_customers.hashing import canonical_hash
from assistflow_customers.repository import IdempotencyRepository, replay_or_conflict
from assistflow_orders.repository import OrderRepository
from assistflow_shipping.repository import ShipmentRepository
from sqlalchemy.orm import Session

from assistflow_returns.eligibility import check_return
from assistflow_returns.repository import ReturnRecord, ReturnRepository

_COMMAND = "create_return_request"


@dataclass(frozen=True)
class ReturnWrite:
    id: UUID
    status: ReturnStatus
    reason_code: str
    replayed: bool


def create_return_request(
    session: Session,
    tenant_id: UUID,
    order_number: str,
    reason_code: str,
    idempotency_key: str,
    today: date | None = None,
    *,
    correlation_id: str = "return",
    actor_type: str = "application",
    actor_id: UUID | None = None,
) -> ReturnWrite:
    """Record a return when eligibility passes. Replays return the original row."""
    arguments_hash = canonical_hash({"order_number": order_number, "reason_code": reason_code})
    idempotency = IdempotencyRepository(session)
    stored = replay_or_conflict(
        idempotency.find(tenant_id, _COMMAND, idempotency_key),
        arguments_hash,
    )
    if stored is not None:
        return ReturnWrite(
            id=UUID(str(stored["id"])),
            status=ReturnStatus(str(stored["status"])),
            reason_code=str(stored["reason_code"]),
            replayed=True,
        )
    if reason_code not in RETURN_REASON_CODES:
        raise SupportError("invalid_reason_code", "The return reason code is not allowed.", 400)

    order = OrderRepository(session).require(tenant_id, order_number)
    shipment = ShipmentRepository(session).get_by_order(tenant_id, order.id)
    decision = check_return(
        order_status=order.status,
        shipment_status=None if shipment is None else shipment.status,
        estimated_delivery_on=None if shipment is None else shipment.estimated_delivery_on,
        shipped_on=None
        if shipment is None or shipment.shipped_at is None
        else shipment.shipped_at.date(),
        has_open_return=ReturnRepository(session).has_open_return(tenant_id, order.id),
        today=datetime.now(UTC).date() if today is None else today,
    )
    if not decision.eligible:
        raise SupportError(
            decision.reason_code,
            "This order is not eligible for a return.",
            409,
        )

    created_at = datetime.now(UTC)
    record = ReturnRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        order_id=order.id,
        status=ReturnStatus.REQUESTED,
        reason_code=reason_code,
        created_at=created_at,
    )
    ReturnRepository(session).insert(record)
    AuditRepository(session).append(
        AuditEventRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            actor_type=actor_type,
            actor_id=order.customer_id if actor_id is None else actor_id,
            action="return.requested",
            target_type="return_request",
            target_id=record.id,
            payload=audit_payload(
                {
                    "return_id": str(record.id),
                    "order_number": order.order_number,
                    "reason_code": reason_code,
                    "status": record.status.value,
                }
            ),
            created_at=created_at,
        )
    )
    idempotency.save(
        record_id=uuid4(),
        tenant_id=tenant_id,
        command_name=_COMMAND,
        idempotency_key=idempotency_key,
        arguments_hash=arguments_hash,
        result_json={
            "id": str(record.id),
            "status": record.status.value,
            "reason_code": record.reason_code,
        },
        created_at=created_at,
    )
    return ReturnWrite(
        id=record.id,
        status=record.status,
        reason_code=record.reason_code,
        replayed=False,
    )
