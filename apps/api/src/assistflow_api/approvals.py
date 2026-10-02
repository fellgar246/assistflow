"""Run a stored proposal after the customer confirms it.

The arguments come from the approval row. The request body cannot replace them.
"""

from datetime import date
from uuid import UUID

from assistflow_contracts.approval import ApprovalView
from assistflow_conversations.approvals import (
    ApprovalFailure,
    begin_confirm,
    consume_approval,
)
from assistflow_conversations.commands import ActorContext
from assistflow_conversations.repository import ApprovalRecord
from assistflow_customers.errors import SupportError
from assistflow_tools import build_registry, service_handlers
from assistflow_tools.approval import issue_application_approval
from assistflow_tools.models import ToolContext, ToolStatus
from assistflow_tools.writes import approved_write_handlers
from sqlalchemy.orm import Session


def confirm_stored_approval(
    session: Session,
    tenant_id: UUID,
    customer_id: UUID,
    conversation_id: UUID,
    approval_id: UUID,
    actor: ActorContext,
    *,
    today: date | None = None,
) -> ApprovalView | ApprovalFailure:
    """Execute the saved command and consume the approval in this session."""
    ready = begin_confirm(
        session,
        tenant_id,
        customer_id,
        conversation_id,
        approval_id,
        actor,
    )
    if isinstance(ready, ApprovalFailure):
        return ready
    if ready.status.value == "consumed":
        return _view(ready)
    registry = build_registry(
        service_handlers(session, today=today),
        approved=approved_write_handlers(session, today=today),
    )
    outcome = registry.apply_approved(
        ready.action_type,
        dict(ready.arguments),
        ToolContext(
            tenant_id=tenant_id,
            customer_id=customer_id,
            actor_type=actor.actor_type,
            correlation_id=actor.correlation_id,
            conversation_id=conversation_id,
        ),
        issue_application_approval(),
    )
    if outcome.status is not ToolStatus.SUCCEEDED:
        code = outcome.error_code or "approval_failed"
        raise SupportError(code, outcome.summary, 409)
    consumed = consume_approval(
        session,
        tenant_id,
        conversation_id,
        ready,
        actor,
    )
    return _view(consumed)


def present_approval(record: ApprovalRecord) -> ApprovalView:
    """Render the stored diff. Arguments are not part of this payload."""
    return _view(record)


def _view(record: ApprovalRecord) -> ApprovalView:
    return ApprovalView.model_validate(
        {
            "id": record.id,
            "action_type": record.action_type,
            "status": record.status.value,
            "proposed_change": record.proposed_change,
            "requested_at": record.requested_at,
            "expires_at": record.expires_at,
            "approved_at": record.approved_at,
            "approved_by": record.approved_by,
        }
    )
