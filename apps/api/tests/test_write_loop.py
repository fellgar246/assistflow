"""The agent loop cannot open the approval gate for a sensitive write."""

from datetime import date
from typing import Any
from uuid import UUID, uuid4

from assistflow_contracts.agent import (
    AdapterUsage,
    ModelMessage,
    ModelText,
    ModelToolUse,
    PromptRef,
    ToolSchema,
    ToolUseRequest,
    TurnContext,
)
from assistflow_orders.repository import OrderRepository
from assistflow_refunds.models import RefundRequestRow
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from assistflow_api.config import repo_root
from assistflow_runtime.limits import TurnLimits
from assistflow_runtime.loop import AgentLoop
from assistflow_runtime.prompts import PromptRegistry
from assistflow_tools import LocalToolGateway, build_registry, service_handlers
from assistflow_tools.writes import approved_write_handlers

HARBOR = UUID("11111111-1111-4111-8111-111111111111")
HARBOR_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001")
ORDER = "ORD-10482"
TODAY = date(2026, 9, 23)


class _Scripted:
    def __init__(self, responses: list[ModelText | ModelToolUse]) -> None:
        self._responses = list(responses)

    def complete(
        self,
        messages: list[ModelMessage],
        tools: list[ToolSchema],
        max_output_tokens: int,
    ) -> ModelText | ModelToolUse:
        del messages, tools, max_output_tokens
        return self._responses.pop(0)


def _compose(_views: list[dict[str, Any]]) -> str:
    return ""


def test_the_agent_loop_does_not_mutate_a_sensitive_write(support_engine: Engine) -> None:
    with Session(support_engine) as session:
        registry = build_registry(
            service_handlers(session, today=TODAY),
            approved=approved_write_handlers(session, today=TODAY),
        )
        gateway = LocalToolGateway(registry, writes_enabled=True)
        before = OrderRepository(session).require(HARBOR, ORDER).shipping_address.line1
        usage = AdapterUsage(input_tokens=1, output_tokens=1)
        model = _Scripted(
            [
                ModelToolUse(
                    requests=[
                        ToolUseRequest(
                            id="refund-1",
                            name="create_refund_request",
                            arguments={
                                "order_id": ORDER,
                                "amount_cents": 1000,
                                "reason_code": "damaged",
                                "idempotency_key": "loop-refund",
                            },
                        ),
                        ToolUseRequest(
                            id="address-1",
                            name="update_shipping_address",
                            arguments={
                                "order_id": ORDER,
                                "new_address": {
                                    "recipient": "Ava Chen",
                                    "line1": "42 Congress Avenue",
                                    "city": "Austin",
                                    "region": "TX",
                                    "postal_code": "78701",
                                    "country": "US",
                                },
                                "idempotency_key": "loop-address",
                            },
                        ),
                    ],
                    usage=usage,
                    provider="mock",
                    model_id="mock",
                    latency_ms=1,
                ),
                ModelText(
                    text="I cannot change that yet.",
                    usage=usage,
                    provider="mock",
                    model_id="mock",
                    latency_ms=1,
                ),
            ]
        )
        result = AgentLoop(
            model,
            gateway,
            PromptRegistry(repo_root() / "agent" / "prompts"),
            TurnLimits(8, 5, 4),
            _compose,
        ).run(
            TurnContext(
                tenant_id=HARBOR,
                customer_id=HARBOR_CUSTOMER,
                conversation_id=uuid4(),
                correlation_id="corr-loop",
                customer_message="Please refund ORD-10482 and change the address.",
                history=[],
                prompt=PromptRef(id="local-support", version="1"),
            )
        )
        refunds = session.scalar(select(func.count()).select_from(RefundRequestRow))
        address = OrderRepository(session).require(HARBOR, ORDER).shipping_address.line1

    denied = [
        item
        for item in result.executed_tools
        if item.name
        in {
            "create_refund_request",
            "update_shipping_address",
        }
    ]
    assert {item.name for item in denied} == {
        "create_refund_request",
        "update_shipping_address",
    }
    assert all(item.status == "blocked" for item in denied)
    assert all(item.error_code == "tool_denied" for item in denied)
    assert refunds == 0
    assert address == before
