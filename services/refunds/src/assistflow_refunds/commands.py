"""Create a refund request. There is no public HTTP route for this command."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from assistflow_contracts.support import RefundStatus
from assistflow_customers.errors import SupportError
from assistflow_customers.hashing import canonical_hash
from assistflow_customers.repository import IdempotencyRepository, replay_or_conflict
from assistflow_orders.repository import OrderRepository
from assistflow_returns.repository import ReturnRepository
from sqlalchemy.orm import Session

from assistflow_refunds.eligibility import check_refund
from assistflow_refunds.repository import RefundRecord, RefundRepository

_COMMAND = "create_refund_request"


@dataclass(frozen=True)
class RefundWrite:
    id: UUID
    status: RefundStatus
    amount_cents: int
    currency: str
    replayed: bool


def create_refund_request(
    session: Session,
    tenant_id: UUID,
    order_number: str,
    amount_cents: int,
    idempotency_key: str,
    return_request_id: UUID | None = None,
) -> RefundWrite:
    """Record a refund request inside the eligible maximum. This does not capture a payment."""
    arguments_hash = canonical_hash(
        {
            "order_number": order_number,
            "amount_cents": amount_cents,
            "return_request_id": None if return_request_id is None else str(return_request_id),
        }
    )
    idempotency = IdempotencyRepository(session)
    stored = replay_or_conflict(
        idempotency.find(tenant_id, _COMMAND, idempotency_key),
        arguments_hash,
    )
    if stored is not None:
        return RefundWrite(
            id=UUID(str(stored["id"])),
            status=RefundStatus(str(stored["status"])),
            amount_cents=int(str(stored["amount_cents"])),
            currency=str(stored["currency"]),
            replayed=True,
        )
    if amount_cents <= 0:
        raise SupportError("invalid_amount", "The refund amount must be greater than zero.", 400)

    order = OrderRepository(session).require(tenant_id, order_number)
    if return_request_id is not None:
        linked = ReturnRepository(session).require(tenant_id, return_request_id)
        if linked.order_id != order.id:
            raise SupportError("return_not_found", "Return request was not found.", 404)

    decision = check_refund(
        order_status=order.status,
        total_cents=order.total_cents,
        reserved_cents=RefundRepository(session).reserved_cents(tenant_id, order.id),
        currency=order.currency,
    )
    if not decision.eligible:
        raise SupportError(decision.reason_code, "This order is not eligible for a refund.", 409)
    if amount_cents > decision.maximum_amount_cents:
        raise SupportError(
            "amount_exceeds_maximum",
            "The refund amount exceeds the eligible maximum.",
            409,
        )

    created_at = datetime.now(UTC)
    record = RefundRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        order_id=order.id,
        return_request_id=return_request_id,
        status=RefundStatus.REQUESTED,
        amount_cents=amount_cents,
        currency=order.currency,
        created_at=created_at,
    )
    RefundRepository(session).insert(record)
    idempotency.save(
        record_id=uuid4(),
        tenant_id=tenant_id,
        command_name=_COMMAND,
        idempotency_key=idempotency_key,
        arguments_hash=arguments_hash,
        result_json={
            "id": str(record.id),
            "status": record.status.value,
            "amount_cents": record.amount_cents,
            "currency": record.currency,
        },
        created_at=created_at,
    )
    return RefundWrite(
        id=record.id,
        status=record.status,
        amount_cents=record.amount_cents,
        currency=record.currency,
        replayed=False,
    )
