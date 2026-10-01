"""Write tools. Tier 2 mutation runs only when the application passes a grant."""

from collections.abc import Callable
from datetime import date
from typing import NoReturn
from uuid import UUID

from assistflow_conversations.repository import ConversationRepository
from assistflow_orders.repository import OrderRecord
from assistflow_refunds.commands import create_refund_request
from assistflow_refunds.eligibility import check_refund
from assistflow_refunds.repository import RefundRepository
from assistflow_returns.commands import create_return_request
from assistflow_returns.eligibility import check_return
from assistflow_returns.repository import ReturnRepository
from assistflow_shipping.commands import update_shipping_address
from assistflow_shipping.eligibility import check_address_change
from assistflow_shipping.repository import ShipmentRepository
from assistflow_tickets.commands import add_ticket_note, create_ticket, request_human_escalation
from pydantic import BaseModel
from sqlalchemy.orm import Session

from assistflow_tools.hashing import arguments_hash
from assistflow_tools.idempotency import audit_denied_write, run_idempotent_write
from assistflow_tools.models import (
    AddTicketNoteArgs,
    CheckEligibilityArgs,
    CreateRefundRequestArgs,
    CreateReturnRequestArgs,
    CreateTicketArgs,
    RequestHumanEscalationArgs,
    ToolContext,
    ToolError,
    ToolRefusal,
    ToolStatus,
    UpdateShippingAddressArgs,
)

Handler = Callable[[ToolContext, object], dict[str, object]]


def public_write_handlers(session: Session, *, today: date | None = None) -> dict[str, Handler]:
    """Register reads and the write paths the agent loop is allowed to reach."""
    clock = date.today() if today is None else today
    return {
        "check_address_change_eligibility": _address_eligibility(session, clock),
        "check_return_eligibility": _return_eligibility(session, clock),
        "check_refund_eligibility": _refund_eligibility(session),
        "create_ticket": _create_ticket(session),
        "add_ticket_note": _add_note(session),
        "request_human_escalation": _escalate(session),
        "update_shipping_address": _address_gate(session, clock),
        "create_return_request": _return_gate(session, clock),
        "create_refund_request": _refund_gate(session),
    }


def approved_write_handlers(session: Session, *, today: date | None = None) -> dict[str, Handler]:
    """Mutation paths. Callers must already hold an application approval grant."""
    clock = date.today() if today is None else today
    return {
        "update_shipping_address": _address_approved(session, clock),
        "create_return_request": _return_approved(session, clock),
        "create_refund_request": _refund_approved(session),
    }


def _address_eligibility(session: Session, today: date) -> Handler:
    def handle(context: ToolContext, arguments: object) -> dict[str, object]:
        parsed = _as(CheckEligibilityArgs, arguments)
        order = _order(session, context, parsed.order_id)
        shipment = ShipmentRepository(session).get_by_order(context.tenant_id, order.id)
        decision = check_address_change(
            order.status,
            None if shipment is None else shipment.status,
            None if shipment is None else shipment.estimated_delivery_on,
            today,
        )
        return {"eligible": decision.eligible, "reason_code": decision.reason_code}

    return handle


def _return_eligibility(session: Session, today: date) -> Handler:
    def handle(context: ToolContext, arguments: object) -> dict[str, object]:
        parsed = _as(CheckEligibilityArgs, arguments)
        order = _order(session, context, parsed.order_id)
        shipment = ShipmentRepository(session).get_by_order(context.tenant_id, order.id)
        decision = check_return(
            order_status=order.status,
            shipment_status=None if shipment is None else shipment.status,
            estimated_delivery_on=None if shipment is None else shipment.estimated_delivery_on,
            shipped_on=None
            if shipment is None or shipment.shipped_at is None
            else shipment.shipped_at.date(),
            has_open_return=ReturnRepository(session).has_open_return(context.tenant_id, order.id),
            today=today,
        )
        return {
            "eligible": decision.eligible,
            "reason_code": decision.reason_code,
            "allowed_reason_codes": list(decision.allowed_reason_codes),
        }

    return handle


def _refund_eligibility(session: Session) -> Handler:
    def handle(context: ToolContext, arguments: object) -> dict[str, object]:
        parsed = _as(CheckEligibilityArgs, arguments)
        order = _order(session, context, parsed.order_id)
        decision = check_refund(
            order_status=order.status,
            total_cents=order.total_cents,
            reserved_cents=RefundRepository(session).reserved_cents(context.tenant_id, order.id),
            currency=order.currency,
        )
        return {
            "eligible": decision.eligible,
            "reason_code": decision.reason_code,
            "maximum_amount_cents": decision.maximum_amount_cents,
        }

    return handle


def _create_ticket(session: Session) -> Handler:
    def handle(context: ToolContext, arguments: object) -> dict[str, object]:
        parsed = _as(CreateTicketArgs, arguments)
        digest = _digest("create_ticket", parsed)

        def effect() -> dict[str, object]:
            written = create_ticket(
                session,
                context.tenant_id,
                context.customer_id,
                parsed.priority,
                parsed.category,
                parsed.summary,
                parsed.idempotency_key,
                conversation_id=_linked_conversation(session, context),
                correlation_id=context.correlation_id,
                actor_type=context.actor_type,
                actor_id=context.customer_id,
            )
            return {"id": str(written.ticket.id), "status": written.ticket.status.value}

        return run_idempotent_write(
            session,
            context,
            "create_ticket",
            parsed.idempotency_key,
            digest,
            effect,
        )

    return handle


def _add_note(session: Session) -> Handler:
    def handle(context: ToolContext, arguments: object) -> dict[str, object]:
        parsed = _as(AddTicketNoteArgs, arguments)
        digest = _digest("add_ticket_note", parsed)

        def effect() -> dict[str, object]:
            written = add_ticket_note(
                session,
                context.tenant_id,
                parsed.ticket_id,
                parsed.body,
                parsed.idempotency_key,
                customer_id=context.customer_id,
                actor_type=context.actor_type,
                correlation_id=context.correlation_id,
                actor_id=context.customer_id,
            )
            return {"id": str(written.id)}

        return run_idempotent_write(
            session,
            context,
            "add_ticket_note",
            parsed.idempotency_key,
            digest,
            effect,
        )

    return handle


def _escalate(session: Session) -> Handler:
    def handle(context: ToolContext, arguments: object) -> dict[str, object]:
        parsed = _as(RequestHumanEscalationArgs, arguments)
        digest = _digest("request_human_escalation", parsed)

        def effect() -> dict[str, object]:
            written = request_human_escalation(
                session,
                context.tenant_id,
                context.customer_id,
                context.conversation_id,
                parsed.reason,
                parsed.idempotency_key,
                actor_type=context.actor_type,
                correlation_id=context.correlation_id,
                actor_id=context.customer_id,
            )
            return {
                "conversation_id": str(written.conversation_id),
                "ticket_id": str(written.ticket_id),
                "status": written.status,
            }

        return run_idempotent_write(
            session,
            context,
            "request_human_escalation",
            parsed.idempotency_key,
            digest,
            effect,
        )

    return handle


def _address_gate(session: Session, today: date) -> Handler:
    def handle(context: ToolContext, arguments: object) -> dict[str, object]:
        parsed = _as(UpdateShippingAddressArgs, arguments)
        order = _order_or_deny(session, context, parsed.order_id, "update_shipping_address")
        shipment = ShipmentRepository(session).get_by_order(context.tenant_id, order.id)
        decision = check_address_change(
            order.status,
            None if shipment is None else shipment.status,
            None if shipment is None else shipment.estimated_delivery_on,
            today,
        )
        if not decision.eligible:
            _refuse_ineligible(
                session,
                context,
                "update_shipping_address",
                decision.reason_code,
                "address change",
            )
        raise ToolRefusal(
            "pending_approval",
            "This change is waiting for approval.",
            ToolStatus.PENDING_APPROVAL,
        )

    return handle


def _return_gate(session: Session, today: date) -> Handler:
    def handle(context: ToolContext, arguments: object) -> dict[str, object]:
        parsed = _as(CreateReturnRequestArgs, arguments)
        order = _order_or_deny(session, context, parsed.order_id, "create_return_request")
        shipment = ShipmentRepository(session).get_by_order(context.tenant_id, order.id)
        decision = check_return(
            order_status=order.status,
            shipment_status=None if shipment is None else shipment.status,
            estimated_delivery_on=None if shipment is None else shipment.estimated_delivery_on,
            shipped_on=None
            if shipment is None or shipment.shipped_at is None
            else shipment.shipped_at.date(),
            has_open_return=ReturnRepository(session).has_open_return(context.tenant_id, order.id),
            today=today,
        )
        if not decision.eligible:
            _refuse_ineligible(
                session,
                context,
                "create_return_request",
                decision.reason_code,
                "return",
            )
        raise ToolRefusal(
            "pending_approval",
            "This change is waiting for approval.",
            ToolStatus.PENDING_APPROVAL,
        )

    return handle


def _refund_gate(session: Session) -> Handler:
    def handle(context: ToolContext, arguments: object) -> dict[str, object]:
        parsed = _as(CreateRefundRequestArgs, arguments)
        order = _order_or_deny(session, context, parsed.order_id, "create_refund_request")
        decision = check_refund(
            order_status=order.status,
            total_cents=order.total_cents,
            reserved_cents=RefundRepository(session).reserved_cents(context.tenant_id, order.id),
            currency=order.currency,
        )
        if not decision.eligible:
            _refuse_ineligible(
                session,
                context,
                "create_refund_request",
                decision.reason_code,
                "refund",
            )
        if parsed.amount_cents > decision.maximum_amount_cents:
            audit_denied_write(session, context, "create_refund_request", "amount_exceeds_maximum")
            raise ToolRefusal(
                "amount_exceeds_maximum",
                "The refund amount exceeds the eligible maximum (amount_exceeds_maximum).",
                ToolStatus.BLOCKED,
                {"eligible": False, "reason_code": "amount_exceeds_maximum"},
            )
        raise ToolRefusal(
            "pending_approval",
            "This change is waiting for approval.",
            ToolStatus.PENDING_APPROVAL,
        )

    return handle


def _address_approved(session: Session, today: date) -> Handler:
    def handle(context: ToolContext, arguments: object) -> dict[str, object]:
        parsed = _as(UpdateShippingAddressArgs, arguments)
        digest = _digest("update_shipping_address", parsed)

        def effect() -> dict[str, object]:
            order = _order(session, context, parsed.order_id)
            written = update_shipping_address(
                session,
                context.tenant_id,
                order.order_number,
                parsed.new_address,
                parsed.idempotency_key,
                customer_id=context.customer_id,
                actor_type=context.actor_type,
                correlation_id=context.correlation_id,
                actor_id=context.customer_id,
                today=today,
            )
            return {
                "order_number": written.order_number,
                "status": "updated",
                "previous_address": written.previous_address.model_dump(mode="json"),
                "new_address": written.new_address.model_dump(mode="json"),
            }

        return run_idempotent_write(
            session,
            context,
            "update_shipping_address",
            parsed.idempotency_key,
            digest,
            effect,
        )

    return handle


def _return_approved(session: Session, today: date) -> Handler:
    def handle(context: ToolContext, arguments: object) -> dict[str, object]:
        parsed = _as(CreateReturnRequestArgs, arguments)
        digest = _digest("create_return_request", parsed)

        def effect() -> dict[str, object]:
            order = _order(session, context, parsed.order_id)
            written = create_return_request(
                session,
                context.tenant_id,
                order.order_number,
                parsed.reason_code,
                parsed.idempotency_key,
                today,
                correlation_id=context.correlation_id,
                actor_type=context.actor_type,
                actor_id=context.customer_id,
            )
            return {
                "id": str(written.id),
                "status": written.status.value,
                "reason_code": written.reason_code,
            }

        return run_idempotent_write(
            session,
            context,
            "create_return_request",
            parsed.idempotency_key,
            digest,
            effect,
        )

    return handle


def _refund_approved(session: Session) -> Handler:
    def handle(context: ToolContext, arguments: object) -> dict[str, object]:
        parsed = _as(CreateRefundRequestArgs, arguments)
        digest = _digest("create_refund_request", parsed)

        def effect() -> dict[str, object]:
            order = _order(session, context, parsed.order_id)
            written = create_refund_request(
                session,
                context.tenant_id,
                order.order_number,
                parsed.amount_cents,
                parsed.idempotency_key,
                reason_code=parsed.reason_code,
                correlation_id=context.correlation_id,
                actor_type=context.actor_type,
                actor_id=context.customer_id,
            )
            if written.status.value == "paid":
                raise ToolError("internal_error", "A refund request cannot be marked paid.")
            return {
                "id": str(written.id),
                "status": written.status.value,
                "amount_cents": written.amount_cents,
                "currency": written.currency,
                "reason_code": parsed.reason_code,
            }

        return run_idempotent_write(
            session,
            context,
            "create_refund_request",
            parsed.idempotency_key,
            digest,
            effect,
        )

    return handle


def _refuse_ineligible(
    session: Session,
    context: ToolContext,
    tool_name: str,
    reason_code: str,
    label: str,
) -> NoReturn:
    audit_denied_write(session, context, tool_name, reason_code)
    raise ToolRefusal(
        reason_code,
        f"This order is not eligible for a {label} ({reason_code}).",
        ToolStatus.BLOCKED,
        {"eligible": False, "reason_code": reason_code},
    )


def _order_or_deny(
    session: Session, context: ToolContext, order_id: str, tool_name: str
) -> OrderRecord:
    try:
        return _order(session, context, order_id)
    except ToolError as exc:
        audit_denied_write(session, context, tool_name, exc.code)
        raise


def _linked_conversation(session: Session, context: ToolContext) -> UUID | None:
    found = ConversationRepository(session).get(context.tenant_id, context.conversation_id)
    if found is None:
        return None
    if context.actor_type == "customer" and found.customer_id != context.customer_id:
        return None
    return found.id


def _order(session: Session, context: ToolContext, order_id: str) -> OrderRecord:
    from assistflow_tools.handlers import _visible_order

    return _visible_order(session, context, order_id)


def _digest(tool_name: str, parsed: BaseModel) -> str:
    dumped = parsed.model_dump(mode="json")
    if not isinstance(dumped, dict):
        raise ToolError("internal_error", "The arguments could not be hashed.")
    return arguments_hash(tool_name, dumped)


def _as[ModelT: BaseModel](model: type[ModelT], arguments: object) -> ModelT:
    if isinstance(arguments, model):
        return arguments
    return model.model_validate(arguments)
