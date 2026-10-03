"""Hosted runtime runner, session isolation, quota, timeout, and operator commands."""

import json
import os
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from assistflow_contracts.agent import (
    AgentResult,
    AgentTrace,
    PromptRef,
    StopReason,
    TurnContext,
    Usage,
)
from assistflow_contracts.conversation import MessageRole
from assistflow_conversations.commands import ActorContext, append_message, open_conversation
from assistflow_conversations.repository import AgentTraceRepository
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from assistflow_api.agents import InProcessAgentRunner, build_agent_runner, build_model_adapter
from assistflow_api.config import Settings, load_settings, repo_root
from assistflow_api.main import create_app
from assistflow_api.runtime_entry import run_payload
from assistflow_api.turns import build_turn_gateway, complete_agent_turn
from assistflow_runtime.facts import domain_facts, order_facts_from_fixture
from assistflow_runtime.handler import package_result
from assistflow_runtime.hosted_runner import (
    QUOTA_MESSAGE,
    TIMEOUT_MESSAGE,
    AgentCoreRuntimeRunner,
    RuntimeReply,
    RuntimeTimeoutError,
    RuntimeTransportError,
    encode_turn,
)
from assistflow_runtime.packaging import package_sources
from assistflow_runtime.quota import SessionQuota
from assistflow_runtime.session_ref import runtime_session_id

HARBOR = UUID("11111111-1111-4111-8111-111111111111")
FIELDLINE = UUID("22222222-2222-4222-8222-222222222222")
HARBOR_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001")
FIELDLINE_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0002")


def _fixture() -> dict[str, Any]:
    raw = json.loads((repo_root() / "knowledge" / "fixtures" / "support_domain.json").read_text())
    if not isinstance(raw, dict):
        raise AssertionError("fixture")
    return raw


def _turn(
    tenant_id: UUID,
    customer_id: UUID,
    message: str,
    conversation_id: UUID | None = None,
) -> TurnContext:
    return TurnContext(
        tenant_id=tenant_id,
        customer_id=customer_id,
        conversation_id=conversation_id or uuid4(),
        correlation_id="corr-runtime",
        customer_message=message,
        history=[],
        prompt=PromptRef(id="local-support", version="1"),
    )


def _gateway(session: Session, turn: TurnContext, settings: Settings) -> Any:
    del turn
    return build_turn_gateway(
        session,
        max_tool_calls=settings.max_tool_calls_per_turn,
        max_chunks=settings.max_chunks_per_retrieval,
        score_floor=settings.retrieval_score_floor,
    )


def _packed(message: str = "Packed reply.") -> dict[str, Any]:
    trace_id = uuid4()
    result = AgentResult(
        assistant_message=message,
        proposed_tool_calls=[],
        trace_id=trace_id,
        stop_reason=StopReason.COMPLETED,
        usage=Usage(),
        trace=AgentTrace(
            id=trace_id,
            prompt_id="local-support",
            prompt_version="1",
            stop_reason=StopReason.COMPLETED,
            steps=[],
        ),
    )
    return package_result(result)


class RecordingTransport:
    def __init__(self, body: dict[str, Any] | None = None) -> None:
        self.calls = 0
        self.session_ids: list[str] = []
        self.payloads: list[bytes] = []
        self._body = body if body is not None else _packed()

    def invoke(self, session_id: str, payload: bytes, timeout_seconds: float) -> RuntimeReply:
        self.calls += 1
        self.session_ids.append(session_id)
        self.payloads.append(payload)
        return RuntimeReply(invocation_id=f"inv-{self.calls}", body=self._body, duration_ms=15)


class SandboxTransport:
    """Run the hosted entry against the local database for one turn."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._settings = load_settings({})
        self.session_ids: list[str] = []
        self.payloads: list[bytes] = []

    def invoke(self, session_id: str, payload: bytes, timeout_seconds: float) -> RuntimeReply:
        self.session_ids.append(session_id)
        self.payloads.append(payload)
        document = json.loads(payload)
        with Session(self._engine) as session:
            body = run_payload(session, self._settings, document)
            session.rollback()
        return RuntimeReply(invocation_id=f"inv-{session_id[:8]}", body=body, duration_ms=7)


def test_in_process_order_facts_match_the_fixture(support_engine: Engine) -> None:
    settings = load_settings({})
    runner = build_agent_runner(settings)
    assert isinstance(runner, InProcessAgentRunner)
    turn = _turn(HARBOR, HARBOR_CUSTOMER, "Where is ORD-10482?")
    with Session(support_engine) as session:
        result = runner.bind(_gateway(session, turn, settings)).run(turn)
        session.rollback()

    assert domain_facts(result) == order_facts_from_fixture(_fixture(), "ORD-10482")


def test_hosted_handler_returns_the_same_order_facts(support_engine: Engine) -> None:
    settings = load_settings({})
    turn = _turn(HARBOR, HARBOR_CUSTOMER, "Where is ORD-10482?")
    with Session(support_engine) as session:
        local = (
            InProcessAgentRunner(settings, _adapter(settings))
            .bind(_gateway(session, turn, settings))
            .run(turn)
        )
        session.rollback()
    hosted = AgentCoreRuntimeRunner(
        SandboxTransport(support_engine),
        SessionQuota(settings.max_sessions_per_day),
        timeout_seconds=5,
    ).run(turn)

    assert domain_facts(hosted) == domain_facts(local)
    assert hosted.trace.runtime_invocation_id is not None
    assert hosted.trace.duration_ms == 7
    assert "ava.chen@example.com" not in encode_turn(turn).decode()


def test_two_conversations_stay_in_separate_sessions(support_engine: Engine) -> None:
    settings = load_settings({})
    sandbox = SandboxTransport(support_engine)
    runner = AgentCoreRuntimeRunner(
        sandbox,
        SessionQuota(settings.max_sessions_per_day),
        timeout_seconds=5,
    )
    harbor = _turn(HARBOR, HARBOR_CUSTOMER, "Where is ORD-10482?")
    fieldline = _turn(FIELDLINE, FIELDLINE_CUSTOMER, "Where is ORD-20817?")
    harbor_result = runner.run(harbor)
    fieldline_result = runner.run(fieldline)

    harbor_session = runtime_session_id(harbor.conversation_id)
    fieldline_session = runtime_session_id(fieldline.conversation_id)
    assert harbor_session != fieldline_session
    assert sandbox.session_ids == [
        str(harbor.conversation_id),
        str(fieldline.conversation_id),
    ]
    assert all("@" not in session_id for session_id in sandbox.session_ids)
    joined = b" ".join(sandbox.payloads).decode()
    assert "ava.chen@example.com" not in joined
    assert "ben.ortiz@example.com" not in joined
    assert domain_facts(harbor_result).origin_hub == "DFW"
    assert domain_facts(fieldline_result).origin_hub == "EWR"
    assert "EWR" not in harbor_result.assistant_message
    assert "DFW" not in fieldline_result.assistant_message


def test_timeout_fails_the_turn_and_the_same_session_can_continue() -> None:
    transport = _BlockingTransport()
    runner = AgentCoreRuntimeRunner(transport, SessionQuota(25), timeout_seconds=0.3)
    turn = _turn(HARBOR, HARBOR_CUSTOMER, "Where is ORD-10482?")
    try:
        failed = runner.run(turn)
        assert failed.stop_reason is StopReason.FAILED
        assert failed.assistant_message == TIMEOUT_MESSAGE
        assert transport.calls == 1
        continued = runner.run(turn)
    finally:
        transport.release.set()

    assert continued.stop_reason is StopReason.COMPLETED
    assert transport.calls == 2


def test_quota_refuses_a_new_session_before_the_remote_call() -> None:
    transport = RecordingTransport()
    runner = AgentCoreRuntimeRunner(transport, SessionQuota(1), timeout_seconds=5)
    first = runner.run(_turn(HARBOR, HARBOR_CUSTOMER, "Where is ORD-10482?"))
    second = runner.run(_turn(FIELDLINE, FIELDLINE_CUSTOMER, "Where is ORD-20817?"))

    assert first.stop_reason is StopReason.COMPLETED
    assert second.stop_reason is StopReason.FAILED
    assert second.assistant_message == QUOTA_MESSAGE
    assert transport.calls == 1


def test_transport_error_retries_once_and_keeps_the_session_slot() -> None:
    transport = _FlakyTransport(failures=2)
    runner = AgentCoreRuntimeRunner(transport, SessionQuota(1), timeout_seconds=5)
    failed = runner.run(_turn(HARBOR, HARBOR_CUSTOMER, "Where is ORD-10482?"))
    refused = runner.run(_turn(FIELDLINE, FIELDLINE_CUSTOMER, "Where is ORD-20817?"))

    assert transport.calls == 2
    assert failed.stop_reason is StopReason.FAILED
    assert refused.assistant_message == QUOTA_MESSAGE
    assert transport.calls == 2


def test_one_transport_error_then_succeeds() -> None:
    transport = _FlakyTransport(failures=1)
    runner = AgentCoreRuntimeRunner(transport, SessionQuota(25), timeout_seconds=5)
    result = runner.run(_turn(HARBOR, HARBOR_CUSTOMER, "Where is ORD-10482?"))

    assert transport.calls == 2
    assert result.stop_reason is StopReason.COMPLETED
    assert result.trace.runtime_invocation_id == "inv-2"


def test_successful_hosted_call_stores_invocation_id_and_duration(support_engine: Engine) -> None:
    transport = RecordingTransport()
    settings = load_settings(
        {
            "AGENTCORE_ENABLED": "true",
            "AGENTCORE_RUNTIME_ARN": (
                "arn:aws:bedrock-agentcore:us-east-1:000000000000:runtime/assistflow_support"
            ),
        }
    )
    runner = build_agent_runner(settings, quota=SessionQuota(25), transport=transport)
    assert runner is not None
    with Session(support_engine) as session:
        actor = ActorContext("customer", HARBOR_CUSTOMER, "corr-runtime-trace")
        opened = open_conversation(session, HARBOR, HARBOR_CUSTOMER, "runtime-conv", actor)
        written = append_message(
            session,
            HARBOR,
            HARBOR_CUSTOMER,
            opened.conversation.id,
            MessageRole.CUSTOMER,
            "Where is ORD-10482?",
            "runtime-msg",
            actor,
        )
        result = complete_agent_turn(
            session,
            HARBOR,
            HARBOR_CUSTOMER,
            opened.conversation.id,
            written.message.id,
            written.message.content,
            "runtime-msg",
            actor,
            runner,
        )
        session.commit()
        stored = AgentTraceRepository(session).get(HARBOR, result.trace_id)

    assert stored is not None
    assert stored.runtime_invocation_id == "inv-1"
    assert stored.duration_ms == 15
    assert result.trace.runtime_invocation_id == "inv-1"
    assert result.trace.duration_ms == 15


def test_disabled_chat_does_not_construct_the_runtime_client(
    support_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[object] = []

    def forbid(*args: object, **kwargs: object) -> object:
        calls.append(args)
        raise AssertionError("runtime client constructed")

    monkeypatch.setattr("assistflow_api.agents.build_data_plane_client", forbid)
    app = create_app(load_settings({}), engine=support_engine)
    from tokens import customer_headers

    with TestClient(app) as client:
        headers = customer_headers(client, HARBOR, HARBOR_CUSTOMER, "corr-runtime-off")
        created = client.post("/conversations", headers=headers, json={"idempotency_key": "rt-off"})
        conversation_id = created.json()["id"]
        posted = client.post(
            f"/conversations/{conversation_id}/messages",
            headers=headers,
            json={"content": "Where is ORD-10482?", "idempotency_key": "rt-off-msg"},
        )
        assert posted.status_code == 201
        transcript = client.get(f"/conversations/{conversation_id}/messages", headers=headers)

    assert calls == []
    assert "DFW" in transcript.json()["items"][1]["content"]
    assert "2099-06-15" in transcript.json()["items"][1]["content"]


def test_enabled_runner_without_an_arn_does_not_construct_a_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbid(*args: object, **kwargs: object) -> object:
        raise AssertionError("runtime client constructed")

    monkeypatch.setattr("assistflow_api.agents.build_data_plane_client", forbid)
    runner = build_agent_runner(load_settings({"AGENTCORE_ENABLED": "true"}))
    assert isinstance(runner, AgentCoreRuntimeRunner)
    result = runner.run(_turn(HARBOR, HARBOR_CUSTOMER, "Where is ORD-10482?"))
    assert result.stop_reason is StopReason.FAILED


def test_data_plane_builder_does_not_name_the_control_plane() -> None:
    root = repo_root()
    watched = [
        root / "agent/runtime/src/assistflow_runtime/hosted_runner.py",
        root / "apps/api/src/assistflow_api/agents.py",
        root / "apps/api/src/assistflow_api/routes/conversations.py",
        root / "apps/api/src/assistflow_api/turns.py",
        root / "apps/api/src/assistflow_api/main.py",
    ]
    combined = "\n".join(path.read_text() for path in watched)
    assert "bedrock-agentcore-control" not in combined
    assert '"bedrock-agentcore"' in combined


def test_deploy_command_stops_before_terraform_without_the_flag() -> None:
    script = repo_root() / "scripts" / "deploy_agentcore.py"
    source = script.read_text()
    assert "$" not in source
    env = os.environ.copy()
    env["AGENTCORE_ENABLED"] = "false"
    env.pop("AGENTCORE_CONTAINER_IMAGE_URI", None)
    completed = subprocess.run(
        [sys.executable, str(script), "--apply"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 2
    assert "was not run" in completed.stdout
    assert "terraform" not in completed.stdout.lower()
    assert "Revalidate current AgentCore runtime pricing" in completed.stdout


def test_smoke_command_skips_without_credentials() -> None:
    script = repo_root() / "scripts" / "smoke_agentcore.py"
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "AGENTCORE_RUNTIME_ARN",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_PROFILE",
            "AWS_SESSION_TOKEN",
        }
    }
    completed = subprocess.run(
        [sys.executable, str(script)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    assert "skipped" in completed.stdout


def test_package_contains_the_handler_and_omits_planning_files(tmp_path: Path) -> None:
    archive = package_sources(repo_root(), tmp_path / "agent.zip")
    names = zipfile.ZipFile(archive).namelist()
    assert any(name.endswith("assistflow_runtime/handler.py") for name in names)
    assert any(name.endswith("runtime_entry.py") for name in names)


def test_dev_runtime_flag_defaults_off() -> None:
    variables = (repo_root() / "infra/environments/dev/variables.tf").read_text()
    module = (repo_root() / "infra/modules/agentcore/main.tf").read_text()
    workflow = (repo_root() / ".github/workflows/pull-request.yml").read_text()
    assert 'variable "enable_agentcore"' in variables
    assert "default     = false" in variables
    assert "count = var.enabled ? 1 : 0" in module
    assert "deploy-agentcore" not in workflow
    assert "smoke-agentcore" not in workflow


def _adapter(settings: Settings) -> Any:
    return build_model_adapter(settings)


class _BlockingTransport:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.calls = 0
        self._lock = threading.Lock()

    def invoke(self, session_id: str, payload: bytes, timeout_seconds: float) -> RuntimeReply:
        with self._lock:
            self.calls += 1
            call = self.calls
        if call == 1:
            self.release.wait(timeout=3)
            raise RuntimeTimeoutError("stuck")
        return RuntimeReply(
            invocation_id="inv-continued",
            body=_packed("Continued."),
            duration_ms=4,
        )


class _FlakyTransport:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def invoke(self, session_id: str, payload: bytes, timeout_seconds: float) -> RuntimeReply:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeTransportError("connection reset")
        return RuntimeReply(invocation_id=f"inv-{self.calls}", body=_packed(), duration_ms=9)
