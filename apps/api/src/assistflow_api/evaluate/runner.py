"""Run the golden scenarios against the mock assistant. No network client is built."""

import time
from datetime import date
from typing import Any
from uuid import UUID

from assistflow_contracts.agent import AgentResult, PromptRef, TurnContext
from assistflow_conversations.approvals import ApprovalFailure, store_proposal
from assistflow_conversations.commands import ActorContext, open_conversation
from assistflow_orders.repository import OrderRepository
from assistflow_refunds.models import RefundRequestRow
from assistflow_returns.models import ReturnRequestRow
from assistflow_runtime.limits import TurnLimits
from assistflow_runtime.loop import AgentLoop, ModelAdapterPort
from assistflow_runtime.mock_adapter import MockModelAdapter
from assistflow_runtime.prompts import PromptRegistry
from assistflow_test_fixtures.agent_scripts import follow_up_calls, reply_from_tools, select_script
from assistflow_tools import LocalToolGateway, build_registry, service_handlers
from assistflow_tools.faults import clear_faults, fail_tool_once
from assistflow_tools.writes import approved_write_handlers
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from assistflow_api.approvals import confirm_stored_approval
from assistflow_api.config import repo_root
from assistflow_api.evaluate.cost import TokenPrice, estimate_cost
from assistflow_api.evaluate.hosted import (
    HostedEvaluationClient,
    build_hosted_client,
    submit_scenarios,
)
from assistflow_api.evaluate.judge import QualitativeJudge, build_judge
from assistflow_api.evaluate.load import require_minimums
from assistflow_api.evaluate.report import build_report, qualitative_scores
from assistflow_api.evaluate.schema import Scenario
from assistflow_api.evaluate.score import TurnObservations, score_turn
from assistflow_api.schema import load_models
from assistflow_api.seed import seed_support_domain

# Fixed clock so return windows and address cutoffs do not follow the wall clock.
EVALUATION_CLOCK = date(2026, 10, 1)

HARBOR = UUID("11111111-1111-4111-8111-111111111111")
FIELDLINE = UUID("22222222-2222-4222-8222-222222222222")


def run_suite(
    scenarios: list[Scenario],
    *,
    prompt_id: str,
    prompt_version: str,
    prices: dict[str, TokenPrice],
    check_minimums: bool = True,
    hosted_enabled: bool = False,
    hosted_client: HostedEvaluationClient | None = None,
    judge_enabled: bool = False,
    judge: QualitativeJudge | None = None,
    adapter: ModelAdapterPort | None = None,
    engine: Engine | None = None,
) -> dict[str, Any]:
    """Score every scenario with the mock adapter and return a report."""
    if check_minimums:
        require_minimums(scenarios)
    if hosted_enabled and hosted_client is None:
        hosted_client = build_hosted_client()
    judged: dict[str, str] | None = None
    if judge_enabled:
        active = judge if judge is not None else build_judge()
        judged = active.scores()
    prompts = PromptRegistry(repo_root() / "agent" / "prompts")
    loaded = prompts.get(prompt_id, prompt_version)
    model = adapter if adapter is not None else MockModelAdapter(select_script, follow_up_calls)
    database = engine if engine is not None else _memory_engine()
    provider = "mock"
    rows: list[dict[str, Any]] = []
    try:
        for scenario in scenarios:
            row, provider = _one(
                database,
                scenario,
                model,
                prompts,
                loaded.id,
                loaded.version,
                prices,
            )
            rows.append(row)
    finally:
        clear_faults()
        if engine is None:
            database.dispose()
    if hosted_client is not None:
        submit_scenarios(hosted_client, [item.id for item in scenarios])
    return build_report(
        prompt_id=loaded.id,
        prompt_version=loaded.version,
        provider=provider,
        rows=rows,
        qualitative=qualitative_scores(judge_enabled, judged),
    )


def _one(
    engine: Engine,
    scenario: Scenario,
    adapter: ModelAdapterPort,
    prompts: PromptRegistry,
    prompt_id: str,
    prompt_version: str,
    prices: dict[str, TokenPrice],
) -> tuple[dict[str, Any], str]:
    clear_faults()
    fail_name = scenario.fixture_overrides.fail_tool
    if fail_name is not None:
        fail_tool_once(fail_name)
    started = time.perf_counter()
    with Session(engine) as session:
        before = _signature(session)
        conversation_id = open_conversation(
            session,
            scenario.tenant_id,
            scenario.customer_id,
            scenario.id,
            _actor(scenario, scenario.id),
        ).conversation.id
        registry = build_registry(
            service_handlers(session, today=EVALUATION_CLOCK),
            approved=approved_write_handlers(session, today=EVALUATION_CLOCK),
        )
        gateway = LocalToolGateway(registry, writes_enabled=True)
        result = AgentLoop(
            adapter,
            gateway,
            prompts,
            TurnLimits(8, 5, 4),
            reply_from_tools,
        ).run(
            TurnContext(
                tenant_id=scenario.tenant_id,
                customer_id=scenario.customer_id,
                conversation_id=conversation_id,
                correlation_id=scenario.id,
                customer_message=scenario.utterance,
                history=[],
                prompt=PromptRef(id=prompt_id, version=prompt_version),
            )
        )
        mutated_before = _signature(session) != before
        confirm_applied, refund_paid = _maybe_confirm(
            session,
            scenario,
            result,
            conversation_id,
            before,
        )
        observed = TurnObservations(
            mutated_before_confirm=mutated_before,
            confirm_applied=confirm_applied,
            refund_marked_paid=refund_paid,
        )
        scores = score_turn(scenario, result, observed)
        session.rollback()
    latency_ms = max(0, int((time.perf_counter() - started) * 1000))
    cost = estimate_cost(
        result.trace.model_id,
        result.usage.input_tokens,
        result.usage.output_tokens,
        prices,
    )
    row = {
        "id": scenario.id,
        "category": scenario.category.value,
        "prompt_version": prompt_version,
        "scores": scores,
        "latency_ms": latency_ms,
        "input_tokens": result.usage.input_tokens,
        "output_tokens": result.usage.output_tokens,
        "cost": cost,
    }
    return row, result.trace.provider


def _maybe_confirm(
    session: Session,
    scenario: Scenario,
    result: AgentResult,
    conversation_id: UUID,
    before: tuple[Any, ...],
) -> tuple[bool, bool]:
    if not scenario.expect.confirm:
        return False, _refund_paid(session)
    actor = _actor(scenario, scenario.id)
    applied = False
    for item in result.executed_tools:
        if item.status != "pending_approval" or not isinstance(item.body, dict):
            continue
        change = item.body.get("proposed_change")
        arguments = item.body.get("arguments")
        if not isinstance(change, dict) or not isinstance(arguments, dict):
            return False, _refund_paid(session)
        stored = store_proposal(
            session,
            tenant_id=scenario.tenant_id,
            conversation_id=conversation_id,
            actor=actor,
            tool_name=item.name,
            arguments=arguments,
            proposed_change=change,
            summary=item.summary,
        )
        confirmed = confirm_stored_approval(
            session,
            scenario.tenant_id,
            scenario.customer_id,
            conversation_id,
            stored.approval.id,
            actor,
            today=EVALUATION_CLOCK,
        )
        if isinstance(confirmed, ApprovalFailure):
            return False, _refund_paid(session)
        applied = True
    changed = _signature(session) != before
    return applied and changed, _refund_paid(session)


def _actor(scenario: Scenario, correlation_id: str) -> ActorContext:
    return ActorContext(
        actor_type="customer",
        actor_id=scenario.customer_id,
        correlation_id=correlation_id,
    )


def _signature(session: Session) -> tuple[Any, ...]:
    harbor = _line(session, HARBOR, "ORD-10482")
    fieldline = _line(session, FIELDLINE, "ORD-20817")
    refunds = session.scalar(select(func.count()).select_from(RefundRequestRow))
    returns = session.scalar(select(func.count()).select_from(ReturnRequestRow))
    return harbor, fieldline, refunds, returns


def _line(session: Session, tenant_id: UUID, order_number: str) -> str:
    order = OrderRepository(session).get(tenant_id, order_number)
    if order is None:
        return ""
    return order.shipping_address.line1


def _refund_paid(session: Session) -> bool:
    statuses = session.scalars(select(RefundRequestRow.status)).all()
    return any(status == "paid" for status in statuses)


def _memory_engine() -> Engine:
    from sqlalchemy import create_engine, event
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    load_models()
    from assistflow_customers.db import Base

    Base.metadata.create_all(engine)
    seed_support_domain(engine)
    return engine
