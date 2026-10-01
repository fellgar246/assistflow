"""Run a tool write once for a tenant and client key."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from assistflow_conversations.audit import audit_payload
from assistflow_conversations.repository import AuditEventRecord, AuditRepository
from assistflow_customers.errors import SupportError
from assistflow_customers.repository import ToolIdempotencyRepository
from sqlalchemy.orm import Session

from assistflow_tools.models import ToolContext, ToolError

Effect = Callable[[], dict[str, object]]


def run_idempotent_write(
    session: Session,
    context: ToolContext,
    tool_name: str,
    idempotency_key: str,
    arguments_hash: str,
    effect: Effect,
) -> dict[str, object]:
    """Return the stored summary on replay. A different payload conflicts and does not write."""
    repository = ToolIdempotencyRepository(session)
    hit = repository.find(context.tenant_id, idempotency_key)
    if hit is not None:
        if hit.arguments_hash != arguments_hash or hit.tool_name != tool_name:
            _audit_denial(session, context, tool_name, "idempotency_conflict", "write.conflict")
            raise ToolError(
                "idempotency_conflict",
                "This idempotency key was already used with different arguments.",
            )
        return dict(hit.result_summary)
    try:
        with session.begin_nested():
            body = effect()
            repository.save(
                record_id=uuid4(),
                tenant_id=context.tenant_id,
                tool_name=tool_name,
                idempotency_key=idempotency_key,
                arguments_hash=arguments_hash,
                result_summary=body,
                created_at=datetime.now(UTC),
            )
    except SupportError as exc:
        _audit_denial(session, context, tool_name, exc.code, "write.denied")
        raise ToolError(exc.code, exc.message) from exc
    except ToolError as exc:
        _audit_denial(session, context, tool_name, exc.code, "write.denied")
        raise
    return body


def audit_denied_write(
    session: Session,
    context: ToolContext,
    tool_name: str,
    code: str,
) -> None:
    """Record a write that was refused before any business row changed."""
    _audit_denial(session, context, tool_name, code, "write.denied")


def _audit_denial(
    session: Session,
    context: ToolContext,
    tool_name: str,
    code: str,
    action: str,
) -> None:
    AuditRepository(session).append(
        AuditEventRecord(
            id=uuid4(),
            tenant_id=context.tenant_id,
            correlation_id=context.correlation_id,
            actor_type=context.actor_type,
            actor_id=context.customer_id,
            action=action,
            target_type="tool",
            target_id=context.customer_id,
            payload=audit_payload({"tool_name": tool_name, "code": code}),
            created_at=datetime.now(UTC),
        )
    )
