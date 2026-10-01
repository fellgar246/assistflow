"""Contract tests for idempotent writes and approval-gated sensitive tools."""

from datetime import date
from uuid import UUID, uuid4

from assistflow_contracts.gateway import TIER1_TOOL_NAMES, TIER2_TOOL_NAMES, GatewayActor
from assistflow_contracts.support import OrderStatus, ShippingAddress
from assistflow_conversations.commands import ActorContext, open_conversation
from assistflow_conversations.models import AuditEventRow
from assistflow_conversations.repository import ConversationRepository
from assistflow_customers.errors import SupportError
from assistflow_orders.repository import OrderRepository
from assistflow_refunds.models import RefundRequestRow
from assistflow_returns.models import ReturnRequestRow
from assistflow_shipping.commands import update_shipping_address
from assistflow_tickets.models import TicketNoteRow, TicketRow
from assistflow_tickets.repository import TicketRepository
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from assistflow_tools import ToolContext, build_registry, service_handlers
from assistflow_tools.approval import ApplicationApproval, issue_application_approval
from assistflow_tools.local_gateway import LocalToolGateway
from assistflow_tools.models import ToolStatus
from assistflow_tools.writes import approved_write_handlers

HARBOR = UUID("11111111-1111-4111-8111-111111111111")
FIELDLINE = UUID("22222222-2222-4222-8222-222222222222")
HARBOR_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001")
FIELDLINE_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0002")
HARBOR_TICKET = UUID("dddddddd-dddd-4ddd-8ddd-dddddddd0001")
ORDER = "ORD-10482"
DELIVERED = "ORD-20817"
TODAY = date(2026, 9, 23)
NEW_ADDRESS = {
    "recipient": "Ava Chen",
    "line1": "42 Congress Avenue",
    "line2": None,
    "city": "Austin",
    "region": "TX",
    "postal_code": "78701",
    "country": "US",
}
OTHER_ADDRESS = {
    **NEW_ADDRESS,
    "line1": "100 Second Street",
}


def _context(
    tenant_id: UUID = HARBOR,
    customer_id: UUID = HARBOR_CUSTOMER,
    conversation_id: UUID | None = None,
) -> ToolContext:
    return ToolContext(
        tenant_id=tenant_id,
        customer_id=customer_id,
        actor_type="customer",
        correlation_id="corr-write",
        conversation_id=conversation_id or uuid4(),
    )


def _registry(session: Session):
    return build_registry(
        service_handlers(session, today=TODAY),
        approved=approved_write_handlers(session, today=TODAY),
    )


def _escalation_events(session: Session) -> int:
    return _actions(session, "conversation.escalated")


def _actions(session: Session, action: str) -> int:
    rows = session.scalars(select(AuditEventRow).where(AuditEventRow.action == action)).all()
    return len(rows)


def _count(session: Session, model: type) -> int:
    total = session.scalar(select(func.count()).select_from(model))
    return int(total or 0)


def _line1(session: Session, tenant_id: UUID, order_number: str) -> str:
    order = OrderRepository(session).require(tenant_id, order_number)
    return order.shipping_address.line1


def test_create_ticket_replays_and_conflicts(support_session: Session) -> None:
    registry = _registry(support_session)
    context = _context()
    arguments = {
        "category": "shipping",
        "priority": "normal",
        "summary": "Package is late",
        "idempotency_key": "ticket-key",
    }
    before = _count(support_session, TicketRow)
    first = registry.execute("create_ticket", arguments, context)
    second = registry.execute("create_ticket", dict(arguments), context)
    conflict = registry.execute(
        "create_ticket",
        {**arguments, "summary": "Different summary"},
        context,
    )
    stored = TicketRepository(support_session).get(HARBOR, UUID(str(first.body["id"])))

    assert first.status is ToolStatus.SUCCEEDED
    assert first.body is not None
    assert second.body == first.body
    assert _count(support_session, TicketRow) == before + 1
    assert stored is not None
    assert stored.summary == "Package is late"
    assert conflict.status is ToolStatus.FAILED
    assert conflict.error_code == "idempotency_conflict"
    assert _count(support_session, TicketRow) == before + 1
    assert _actions(support_session, "write.conflict") == 1
    assert _actions(support_session, "ticket.created") == 1


def test_the_same_key_cannot_be_reused_for_another_tool(support_session: Session) -> None:
    registry = _registry(support_session)
    context = _context()
    registry.execute(
        "create_ticket",
        {
            "category": "other",
            "priority": "low",
            "summary": "One ticket",
            "idempotency_key": "shared-key",
        },
        context,
    )
    note = registry.execute(
        "add_ticket_note",
        {
            "ticket_id": str(HARBOR_TICKET),
            "body": "Should not be saved",
            "idempotency_key": "shared-key",
        },
        context,
    )

    assert note.status is ToolStatus.FAILED
    assert note.error_code == "idempotency_conflict"
    assert _count(support_session, TicketNoteRow) == 0


def test_ticket_note_replays_and_rejects_a_long_body(support_session: Session) -> None:
    registry = _registry(support_session)
    context = _context()
    arguments = {
        "ticket_id": str(HARBOR_TICKET),
        "body": "Left a note for the team",
        "idempotency_key": "note-key",
    }
    first = registry.execute("add_ticket_note", arguments, context)
    second = registry.execute("add_ticket_note", dict(arguments), context)
    conflict = registry.execute(
        "add_ticket_note",
        {**arguments, "body": "A different note"},
        context,
    )
    too_long = registry.execute(
        "add_ticket_note",
        {**arguments, "body": "x" * 2001, "idempotency_key": "note-long"},
        context,
    )

    assert first.status is ToolStatus.SUCCEEDED
    assert first.body is not None
    assert second.body == first.body
    assert _count(support_session, TicketNoteRow) == 1
    assert conflict.error_code == "idempotency_conflict"
    assert _count(support_session, TicketNoteRow) == 1
    assert too_long.error_code == "validation_error"
    assert _count(support_session, TicketNoteRow) == 1


def test_escalation_runs_once_and_denies_another_tenant(support_session: Session) -> None:
    opened = open_conversation(
        support_session,
        HARBOR,
        HARBOR_CUSTOMER,
        "conv-escalate",
        ActorContext(
            actor_type="customer",
            actor_id=HARBOR_CUSTOMER,
            correlation_id="corr-open",
        ),
    )
    conversation_id = opened.conversation.id
    registry = _registry(support_session)
    context = _context(conversation_id=conversation_id)
    arguments = {"reason": "I need a person", "idempotency_key": "esc-key"}
    first = registry.execute("request_human_escalation", arguments, context)
    second = registry.execute("request_human_escalation", dict(arguments), context)
    denied = registry.execute(
        "request_human_escalation",
        {"reason": "Take over this chat", "idempotency_key": "esc-other"},
        _context(FIELDLINE, FIELDLINE_CUSTOMER, conversation_id),
    )
    stored = ConversationRepository(support_session).require(HARBOR, conversation_id)

    assert first.status is ToolStatus.SUCCEEDED
    assert first.body is not None
    assert first.body["status"] == "escalated"
    assert second.body == first.body
    assert stored.status.value == "escalated"
    assert TicketRepository(support_session).list_ids_for_conversation(HARBOR, conversation_id) == [
        UUID(str(first.body["ticket_id"]))
    ]
    assert _escalation_events(support_session) == 1
    assert denied.status is ToolStatus.BLOCKED
    assert denied.error_code == "denied"
    assert _escalation_events(support_session) == 1


def test_eligibility_reads_do_not_mutate(support_session: Session) -> None:
    registry = _registry(support_session)
    context = _context()
    before = _line1(support_session, HARBOR, ORDER)
    returns_before = _count(support_session, ReturnRequestRow)
    refunds_before = _count(support_session, RefundRequestRow)
    address = registry.execute(
        "check_address_change_eligibility",
        {"order_id": ORDER},
        context,
    )
    returned = registry.execute(
        "check_return_eligibility",
        {"order_id": DELIVERED},
        _context(FIELDLINE, FIELDLINE_CUSTOMER),
    )
    refund = registry.execute("check_refund_eligibility", {"order_id": ORDER}, context)

    assert address.status is ToolStatus.SUCCEEDED
    assert address.body == {"eligible": True, "reason_code": "eligible"}
    assert returned.body is not None
    assert returned.body["eligible"] is True
    assert "changed_mind" in returned.body["allowed_reason_codes"]
    assert refund.body is not None
    assert refund.body["eligible"] is True
    assert refund.body["maximum_amount_cents"] == 4599
    assert "payment" not in refund.body
    assert _line1(support_session, HARBOR, ORDER) == before
    assert _count(support_session, ReturnRequestRow) == returns_before
    assert _count(support_session, RefundRequestRow) == refunds_before


def test_tier2_without_approval_does_not_mutate(support_session: Session) -> None:
    registry = _registry(support_session)
    context = _context()
    before = _line1(support_session, HARBOR, ORDER)
    address = registry.execute(
        "update_shipping_address",
        {"order_id": ORDER, "new_address": NEW_ADDRESS, "idempotency_key": "addr-wait"},
        context,
    )
    returned = registry.execute(
        "create_return_request",
        {"order_id": DELIVERED, "reason_code": "changed_mind", "idempotency_key": "ret-wait"},
        _context(FIELDLINE, FIELDLINE_CUSTOMER),
    )
    refund = registry.execute(
        "create_refund_request",
        {
            "order_id": ORDER,
            "amount_cents": 1000,
            "reason_code": "damaged",
            "idempotency_key": "ref-wait",
        },
        context,
    )

    assert address.status is ToolStatus.PENDING_APPROVAL
    assert returned.status is ToolStatus.PENDING_APPROVAL
    assert refund.status is ToolStatus.PENDING_APPROVAL
    assert _line1(support_session, HARBOR, ORDER) == before
    assert _count(support_session, ReturnRequestRow) == 0
    assert _count(support_session, RefundRequestRow) == 0


def test_ineligible_tier2_is_denied_without_a_row_change(support_session: Session) -> None:
    registry = _registry(support_session)
    context = _context()
    delivered_line = _line1(support_session, FIELDLINE, DELIVERED)
    address = registry.execute(
        "update_shipping_address",
        {
            "order_id": DELIVERED,
            "new_address": NEW_ADDRESS,
            "idempotency_key": "addr-no",
        },
        _context(FIELDLINE, FIELDLINE_CUSTOMER),
    )
    returned = registry.execute(
        "create_return_request",
        {"order_id": ORDER, "reason_code": "damaged", "idempotency_key": "ret-no"},
        context,
    )
    order = OrderRepository(support_session).require(HARBOR, ORDER)
    OrderRepository(support_session).update(
        order.__class__(
            id=order.id,
            tenant_id=order.tenant_id,
            customer_id=order.customer_id,
            order_number=order.order_number,
            status=OrderStatus.CANCELLED,
            currency=order.currency,
            total_cents=order.total_cents,
            shipping_address=order.shipping_address,
            created_at=order.created_at,
        )
    )
    refund = registry.execute(
        "create_refund_request",
        {
            "order_id": ORDER,
            "amount_cents": 100,
            "reason_code": "other",
            "idempotency_key": "ref-no",
        },
        context,
    )

    assert address.status is ToolStatus.BLOCKED
    assert address.body is not None
    assert address.body["reason_code"] == "already_delivered"
    assert "already_delivered" in address.summary
    assert returned.body is not None
    assert returned.body["reason_code"] == "not_delivered"
    assert refund.body is not None
    assert refund.body["reason_code"] == "order_cancelled"
    assert _line1(support_session, FIELDLINE, DELIVERED) == delivered_line
    assert _count(support_session, ReturnRequestRow) == 0
    assert _count(support_session, RefundRequestRow) == 0


def test_approved_address_change_runs_once(support_session: Session) -> None:
    registry = _registry(support_session)
    context = _context()
    grant = issue_application_approval()
    arguments = {
        "order_id": ORDER,
        "new_address": NEW_ADDRESS,
        "idempotency_key": "addr-yes",
    }
    first = registry.apply_approved("update_shipping_address", arguments, context, grant)
    second = registry.apply_approved("update_shipping_address", dict(arguments), context, grant)
    conflict = registry.apply_approved(
        "update_shipping_address",
        {**arguments, "new_address": OTHER_ADDRESS},
        context,
        grant,
    )

    assert isinstance(grant, ApplicationApproval)
    assert first.status is ToolStatus.SUCCEEDED
    assert first.body is not None
    assert second.body == first.body
    assert _line1(support_session, HARBOR, ORDER) == "42 Congress Avenue"
    assert conflict.error_code == "idempotency_conflict"
    assert _line1(support_session, HARBOR, ORDER) == "42 Congress Avenue"


def test_domain_address_command_is_idempotent(support_session: Session) -> None:
    context = _context()
    address = ShippingAddress.model_validate(NEW_ADDRESS)
    other = ShippingAddress.model_validate(OTHER_ADDRESS)
    first = update_shipping_address(
        support_session,
        HARBOR,
        ORDER,
        address,
        "domain-addr",
        customer_id=context.customer_id,
        actor_type=context.actor_type,
        correlation_id=context.correlation_id,
        actor_id=context.customer_id,
        today=TODAY,
    )
    second = update_shipping_address(
        support_session,
        HARBOR,
        ORDER,
        address,
        "domain-addr",
        customer_id=context.customer_id,
        actor_type=context.actor_type,
        correlation_id=context.correlation_id,
        actor_id=context.customer_id,
        today=TODAY,
    )
    try:
        update_shipping_address(
            support_session,
            HARBOR,
            ORDER,
            other,
            "domain-addr",
            customer_id=context.customer_id,
            actor_type=context.actor_type,
            correlation_id=context.correlation_id,
            actor_id=context.customer_id,
            today=TODAY,
        )
    except SupportError as exc:
        conflict = exc
    else:
        raise AssertionError("expected a conflict")

    assert first.replayed is False
    assert second.replayed is True
    assert second.order_number == first.order_number
    assert conflict.code == "idempotency_conflict"
    assert _line1(support_session, HARBOR, ORDER) == "42 Congress Avenue"


def test_approved_refund_replays_and_never_marks_paid(support_session: Session) -> None:
    registry = _registry(support_session)
    context = _context()
    grant = issue_application_approval()
    arguments = {
        "order_id": ORDER,
        "amount_cents": 1000,
        "reason_code": "damaged",
        "idempotency_key": "refund-yes",
    }
    first = registry.apply_approved("create_refund_request", arguments, context, grant)
    second = registry.apply_approved("create_refund_request", dict(arguments), context, grant)

    assert first.status is ToolStatus.SUCCEEDED
    assert first.body is not None
    assert first.body["status"] == "requested"
    assert first.body["status"] != "paid"
    assert "payment" not in first.body
    assert second.body == first.body
    assert _count(support_session, RefundRequestRow) == 1


def test_gateway_exposes_tier1_only_when_writes_are_enabled(support_session: Session) -> None:
    registry = _registry(support_session)
    actor = GatewayActor(
        tenant_id=HARBOR,
        customer_id=HARBOR_CUSTOMER,
        actor_type="customer",
        correlation_id="corr-gw",
        conversation_id=uuid4(),
    )
    closed = LocalToolGateway(registry)
    opened = LocalToolGateway(registry, writes_enabled=True)
    closed_names = {tool.name for tool in closed.list_tools()}
    opened_names = {tool.name for tool in opened.list_tools()}
    refunds_before = _count(support_session, RefundRequestRow)
    created = opened.call_tool(
        "create_ticket",
        {
            "category": "order",
            "priority": "high",
            "summary": "Gateway ticket",
            "idempotency_key": "gw-ticket",
        },
        actor,
    )
    waiting = opened.call_tool(
        "create_refund_request",
        {
            "order_id": ORDER,
            "amount_cents": 500,
            "reason_code": "other",
            "idempotency_key": "gw-refund",
        },
        actor,
    )
    blocked = closed.call_tool(
        "create_ticket",
        {
            "category": "order",
            "priority": "high",
            "summary": "Hidden ticket",
            "idempotency_key": "gw-hidden",
        },
        actor,
    )
    tier2 = next(tool for tool in opened.list_tools() if tool.name == "create_refund_request")
    write_tool = registry.lookup("create_ticket")
    read_tool = registry.lookup("get_order")

    assert closed_names.isdisjoint(TIER1_TOOL_NAMES | TIER2_TOOL_NAMES)
    assert opened_names >= TIER1_TOOL_NAMES
    assert opened_names >= TIER2_TOOL_NAMES
    assert "approval" in tier2.description.lower()
    assert created.status == "succeeded"
    assert waiting.status == "pending_approval"
    assert blocked.status == "blocked"
    assert _count(support_session, RefundRequestRow) == refunds_before
    assert write_tool is not None and write_tool.timeout_retries == 0
    assert write_tool.timeout_seconds == 3
    assert read_tool is not None and read_tool.timeout_retries == 1


def test_the_model_cannot_pass_an_approval_token(support_session: Session) -> None:
    registry = _registry(support_session)
    context = _context()
    before = _line1(support_session, HARBOR, ORDER)
    refused = registry.execute(
        "update_shipping_address",
        {
            "order_id": ORDER,
            "new_address": NEW_ADDRESS,
            "idempotency_key": "addr-token",
            "approval": "app-secret",
        },
        context,
    )
    try:
        ApplicationApproval()
    except TypeError:
        blocked_constructor = True
    else:
        blocked_constructor = False

    assert refused.error_code == "validation_error"
    assert blocked_constructor is True
    assert _line1(support_session, HARBOR, ORDER) == before
