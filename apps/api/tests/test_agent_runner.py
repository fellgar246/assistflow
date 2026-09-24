"""Mock runner budgets, prompt versions, and the disabled-assistant path."""

import subprocess
import sys
from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from assistflow_contracts.agent import (
    HistoryMessage,
    PromptRef,
    ScriptedPlan,
    ScriptedStep,
    StepKind,
    StopReason,
    TurnContext,
)
from assistflow_contracts.conversation import MessageRole
from assistflow_conversations.repository import AgentTraceRepository
from assistflow_test_fixtures.agent_scripts import (
    ASK_FOR_ORDER_NUMBER,
    ORDER_NUMBER_RECEIVED,
    select_script,
)
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from assistflow_api.config import repo_root
from assistflow_runtime import (
    BUDGET_MESSAGE,
    HISTORY_MESSAGE_CAP,
    MockAgentRunner,
    PromptNotFoundError,
    PromptRegistry,
    TurnLimits,
    bound_history,
)

HARBOR = UUID("11111111-1111-4111-8111-111111111111")
FIELDLINE = UUID("22222222-2222-4222-8222-222222222222")
HARBOR_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001")


def _limits(**overrides: int) -> TurnLimits:
    values = {
        "max_agent_steps": 8,
        "max_tool_calls_per_turn": 5,
        "max_model_calls_per_turn": 4,
    }
    values.update(overrides)
    return TurnLimits(**values)


def _runner(
    select_plan: Callable[[str], ScriptedPlan] | None = None, **limits: int
) -> MockAgentRunner:
    return MockAgentRunner(
        prompts=PromptRegistry(repo_root() / "agent" / "prompts"),
        limits=_limits(**limits),
        select_plan=select_script if select_plan is None else select_plan,
    )


def _context(message: str, *, prompt_version: str = "1", history_count: int = 0) -> TurnContext:
    history = [
        HistoryMessage(role=MessageRole.CUSTOMER, content=f"earlier {index}")
        for index in range(history_count)
    ]
    return TurnContext(
        tenant_id=HARBOR,
        customer_id=HARBOR_CUSTOMER,
        conversation_id=uuid4(),
        correlation_id="corr-agent-1",
        customer_message=message,
        history=history,
        prompt=PromptRef(id="local-support", version=prompt_version),
    )


def _plan(steps: list[ScriptedStep], message: str = "Planned reply.") -> ScriptedPlan:
    return ScriptedPlan(assistant_message=message, steps=steps)


def test_scripted_plan_returns_text_proposals_and_a_trace() -> None:
    plan = _plan(
        [
            ScriptedStep(kind=StepKind.MODEL, summary="order status request"),
            ScriptedStep(
                kind=StepKind.TOOL_PROPOSAL,
                summary="proposed get_order",
                tool_name="get_order",
                arguments={"order_number": "ORD-10482", "access_token": "secret-token"},
            ),
        ]
    )
    result = _runner(lambda _message: plan, max_model_calls_per_turn=4).run(_context("status"))

    assert result.assistant_message == "Planned reply."
    assert result.stop_reason is StopReason.COMPLETED
    assert result.trace_id == result.trace.id
    assert result.trace.prompt_id == "local-support"
    assert result.trace.prompt_version == "1"
    assert [step.kind for step in result.trace.steps] == [
        StepKind.MODEL,
        StepKind.TOOL_PROPOSAL,
    ]
    assert result.proposed_tool_calls[0].name == "get_order"
    assert result.proposed_tool_calls[0].arguments["order_number"] == "ORD-10482"
    assert result.usage.input_tokens == 0
    assert result.usage.output_tokens == 0
    summary = result.trace.steps[1].input_summary
    assert "ORD-10482" in summary
    assert "secret-token" not in summary
    assert "chain of thought" not in result.assistant_message.lower()
    joined = " ".join(step.input_summary for step in result.trace.steps)
    assert "chain of thought" not in joined.lower()


def test_step_budget_stops_at_eight_with_a_safe_message() -> None:
    steps = [ScriptedStep(kind=StepKind.MODEL, summary=f"step {index}") for index in range(9)]
    result = _runner(
        lambda _message: _plan(steps),
        max_model_calls_per_turn=20,
        max_tool_calls_per_turn=20,
    ).run(_context("too broad"))

    assert result.stop_reason is StopReason.STOPPED_BUDGET
    assert result.trace.stop_reason is StopReason.STOPPED_BUDGET
    assert len(result.trace.steps) == 8
    assert result.trace.steps[-1].kind is StepKind.BUDGET
    lowered = result.assistant_message.lower()
    assert result.assistant_message == BUDGET_MESSAGE
    assert "narrow" in lowered
    assert "person" in lowered
    assert "delivered" not in lowered
    assert "in transit" not in lowered
    assert "ord-" not in lowered


def test_tool_and_model_caps_stop_the_turn() -> None:
    tools = [
        ScriptedStep(
            kind=StepKind.TOOL_PROPOSAL,
            summary="proposed get_order",
            tool_name="get_order",
            arguments={"order_number": f"ORD-{index}"},
        )
        for index in range(6)
    ]
    tool_result = _runner(lambda _message: _plan(tools), max_model_calls_per_turn=20).run(
        _context("tools")
    )
    assert tool_result.stop_reason is StopReason.STOPPED_BUDGET
    assert len(tool_result.proposed_tool_calls) == 5
    assert tool_result.trace.steps[-1].kind is StepKind.BUDGET

    models = [ScriptedStep(kind=StepKind.MODEL, summary=f"model {index}") for index in range(5)]
    model_result = _runner(lambda _message: _plan(models), max_tool_calls_per_turn=20).run(
        _context("models")
    )
    assert model_result.stop_reason is StopReason.STOPPED_BUDGET
    assert sum(step.kind is StepKind.MODEL for step in model_result.trace.steps) == 4


def test_prompt_registry_returns_a_version_and_rejects_unknown_ids() -> None:
    registry = PromptRegistry(repo_root() / "agent" / "prompts")
    first = registry.get("local-support", "1")
    second = registry.get("local-support", "2")

    assert "tool" in first.text.lower()
    assert "not retrieved" in first.text.lower()
    assert "version 2" in second.text.lower()
    assert first.text != second.text
    with pytest.raises(PromptNotFoundError):
        registry.get("missing-prompt", "1")

    result = _runner().run(_context("hello", prompt_version="2"))
    assert result.trace.prompt_id == "local-support"
    assert result.trace.prompt_version == "2"
    assert first.text not in " ".join(step.input_summary for step in result.trace.steps)


def test_order_script_asks_for_a_number_and_does_not_state_a_date() -> None:
    missing = _runner().run(_context("Where is my order?"))
    assert missing.assistant_message == ASK_FOR_ORDER_NUMBER
    assert missing.proposed_tool_calls == []

    numbered = _runner().run(_context("Where is ORD-10482?"))
    assert numbered.assistant_message == ORDER_NUMBER_RECEIVED
    assert numbered.proposed_tool_calls[0].name == "get_order"
    assert "delivered" not in numbered.assistant_message.lower()
    assert "in transit" not in numbered.assistant_message.lower()


def test_history_window_keeps_the_newest_messages() -> None:
    messages = [
        HistoryMessage(role=MessageRole.CUSTOMER, content=f"message {index}") for index in range(25)
    ]
    bounded = bound_history(messages)
    assert len(bounded) == HISTORY_MESSAGE_CAP
    assert bounded[0].content == "message 5"
    assert bounded[-1].content == "message 24"

    huge = [
        HistoryMessage(role=MessageRole.CUSTOMER, content="x" * 20000),
        HistoryMessage(role=MessageRole.CUSTOMER, content="y" * 20000),
        HistoryMessage(role=MessageRole.ASSISTANT, content="kept"),
    ]
    trimmed = bound_history(huge)
    assert [item.content for item in trimmed] == ["kept"]


def test_enabled_assistant_stores_a_reply_and_a_trace(
    support_client: TestClient, support_engine: Engine
) -> None:
    headers = {
        "X-Tenant-Id": str(HARBOR),
        "X-Customer-Id": str(HARBOR_CUSTOMER),
        "X-Correlation-Id": "corr-agent-route",
    }
    created = support_client.post(
        "/conversations",
        headers=headers,
        json={"idempotency_key": "agent-conv"},
    )
    conversation_id = UUID(created.json()["id"])
    posted = support_client.post(
        f"/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": "Where is ORD-10482?", "idempotency_key": "agent-msg"},
    )
    assert posted.status_code == 201

    transcript = support_client.get(f"/conversations/{conversation_id}/messages", headers=headers)
    contents = [item["content"] for item in transcript.json()["items"]]
    assert contents == ["Where is ORD-10482?", ORDER_NUMBER_RECEIVED]

    with Session(support_engine) as session:
        traces = AgentTraceRepository(session).list_for_conversation(HARBOR, conversation_id)
        hidden = AgentTraceRepository(session).get(FIELDLINE, traces[0].id)
        session.rollback()

    assert len(traces) == 1
    assert traces[0].prompt_id == "local-support"
    assert traces[0].prompt_version == "1"
    assert traces[0].stop_reason == "completed"
    assert traces[0].input_tokens == 0
    assert hidden is None
    summaries = " ".join(step.input_summary for step in traces[0].steps)
    assert "chain of thought" not in summaries.lower()
    assert "secret" not in summaries.lower()
    assert any(step.kind == "tool_proposal" for step in traces[0].steps)


def test_default_api_import_does_not_load_cloud_sdks() -> None:
    script = """
import sys
import assistflow_api.main
banned = [
    name
    for name in sys.modules
    if name.split(".", 1)[0] in {"boto3", "botocore"}
    or "agentcore" in name.lower()
    or "bedrock" in name.lower()
]
if banned:
    raise SystemExit(",".join(banned))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
