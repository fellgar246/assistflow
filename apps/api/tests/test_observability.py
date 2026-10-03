"""One correlation id diagnoses a failed tool, and the metric names move."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
import structlog
from assistflow_contracts.agent import AdapterUsage, ModelText, ModelToolUse, ToolUseRequest
from assistflow_contracts.observe import METRIC_NAMES
from assistflow_conversations.models import AgentTraceRow
from assistflow_conversations.repository import AuditRepository, ToolExecutionRepository
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from assistflow_api.config import load_settings, repo_root
from assistflow_api.logging import bind_production_logs, configure_logging, reset_production_logs
from assistflow_api.metrics import InMemoryMetrics, build_metrics
from assistflow_tools.faults import clear_faults, fail_tool_once
from tokens import customer_headers

HARBOR = UUID("11111111-1111-4111-8111-111111111111")
HARBOR_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001")
ORDER = "ORD-10482"
CORRELATION = "corr-failed-tool"
TOKEN = "Bearer abcdefghijklmnop"
PAYLOAD = "RAW_MODEL_PAYLOAD"
HOPS = {"http", "conversation", "agent", "model", "retrieval", "gateway", "tool", "command"}


class ScriptedOrder:
    """One get_order call, then text, with known token counts."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self,
        messages: list[object],
        tools: list[object],
        max_output_tokens: int,
    ) -> ModelText | ModelToolUse:
        del messages, tools, max_output_tokens
        self.calls += 1
        if self.calls == 1:
            return ModelToolUse(
                requests=[
                    ToolUseRequest(
                        id="order-1",
                        name="get_order",
                        arguments={"order_id": ORDER},
                    )
                ],
                usage=AdapterUsage(input_tokens=11, output_tokens=3),
                provider="mock",
                model_id="mock",
                latency_ms=5,
            )
        return ModelText(
            text="Order looked up.",
            usage=AdapterUsage(input_tokens=6, output_tokens=5),
            provider="mock",
            model_id="mock",
            latency_ms=2,
        )


class FailingOrder:
    """Retrieve policy text, then fail get_order once the fixture flag is set."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self,
        messages: list[object],
        tools: list[object],
        max_output_tokens: int,
    ) -> ModelText | ModelToolUse:
        del messages, tools, max_output_tokens
        self.calls += 1
        if self.calls == 1:
            return ModelToolUse(
                requests=[
                    ToolUseRequest(
                        id="search-1",
                        name="search_support_policy",
                        arguments={"query": "order help"},
                    ),
                    ToolUseRequest(
                        id="order-1",
                        name="get_order",
                        arguments={"order_id": ORDER},
                    ),
                ],
                usage=AdapterUsage(input_tokens=4, output_tokens=2),
                provider="mock",
                model_id="mock",
                latency_ms=3,
            )
        return ModelText(
            text="I could not complete that lookup.",
            usage=AdapterUsage(input_tokens=1, output_tokens=1),
            provider="mock",
            model_id="mock",
            latency_ms=1,
        )


def test_health_returns_a_correlation_id(support_client: TestClient) -> None:
    echoed = support_client.get("/health", headers={"X-Correlation-Id": CORRELATION})
    generated = support_client.get("/health")
    denied = support_client.get("/orders")

    assert echoed.headers["X-Correlation-Id"] == CORRELATION
    assert generated.headers["X-Correlation-Id"] != ""
    assert generated.headers["X-Correlation-Id"] != CORRELATION
    assert denied.status_code == 401
    assert denied.headers["X-Correlation-Id"] != ""


def test_failed_get_order_is_one_correlation(
    support_client: TestClient,
    support_engine: Engine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _state(support_client).model_adapter = FailingOrder()
    _state(support_client).production_logs = True
    fail_tool_once("get_order")
    try:
        conversation_id = _open(support_client, "failed-conv")
        sent = support_client.post(
            f"/conversations/{conversation_id}/messages",
            headers=_headers(support_client),
            json={
                "content": f"Where is {ORDER}? {TOKEN} {PAYLOAD}",
                "idempotency_key": "failed-msg",
            },
        )
        transcript = support_client.get(
            f"/conversations/{conversation_id}/messages",
            headers=_headers(support_client),
        )
    finally:
        clear_faults()

    assert sent.status_code == 201
    assert sent.headers["X-Correlation-Id"] == CORRELATION
    body = transcript.text
    assert "Traceback" not in body
    assert TOKEN not in body

    hops = _state(support_client).trace_store.hops(CORRELATION)
    assert {item.hop for item in hops} >= HOPS
    failed = [item for item in hops if item.hop == "tool" and item.tool_name == "get_order"]
    assert failed
    assert failed[0].error_code == "tool_failed"
    assert failed[0].latency_ms >= 0
    http = [item for item in hops if item.hop == "http" and item.error_code == "tool_failed"]
    assert http
    assert all(item.correlation_id == CORRELATION for item in hops)

    with Session(support_engine) as session:
        traces = list(
            session.scalars(
                select(AgentTraceRow).where(AgentTraceRow.correlation_id == CORRELATION)
            )
        )
        executions = ToolExecutionRepository(session).list_for_conversation(
            HARBOR, UUID(conversation_id)
        )
        audits = AuditRepository(session).list_for_correlation(HARBOR, CORRELATION)
    assert traces
    assert traces[0].correlation_id == CORRELATION
    assert hasattr(traces[0], "runtime_invocation_id")
    order = next(item for item in executions if item.tool_name == "get_order")
    assert order.correlation_id == CORRELATION
    assert order.error_code == "tool_failed"
    assert order.latency_ms >= 0
    failed_audit = next(item for item in audits if item.action == "tool.failed")
    assert failed_audit.correlation_id == CORRELATION
    assert failed_audit.payload["tool_name"] == "get_order"
    assert failed_audit.payload["error_code"] == "tool_failed"
    assert "latency_ms" in failed_audit.payload

    output = capsys.readouterr().out + capsys.readouterr().err
    assert TOKEN not in output
    assert "abcdefghijklmnop" not in output
    assert PAYLOAD not in output
    assert "Traceback" not in output
    assert "trace_hop" in output


def test_aws_demo_mode_drops_model_documents() -> None:
    from assistflow_api.correlation import _production_mode

    loaded = load_settings(
        {
            "EXECUTION_MODE": "aws-demo",
            "AUTH_ISSUER": "https://example.invalid/issuer",
            "AUTH_AUDIENCE": "assistflow-api",
        }
    )

    class State:
        production_logs = False
        settings = loaded

    class App:
        state = State()

    assert _production_mode({"type": "http", "app": App()}) is True


def test_aws_demo_log_line_drops_tokens_and_model_payloads(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging()
    token = bind_production_logs(True)
    try:
        structlog.get_logger("assistflow.turn").info(
            "turn_persisted",
            authorization=TOKEN,
            model_payload={"messages": [{"content": PAYLOAD}]},
            assistant_message=TOKEN,
        )
    finally:
        reset_production_logs(token)

    output = capsys.readouterr().out
    assert "abcdefghijklmnop" not in output
    assert PAYLOAD not in output
    assert "model_payload" not in output


def test_scripted_turn_approval_and_abstention_move_metrics(
    support_client: TestClient,
) -> None:
    before = _metrics(support_client)
    _state(support_client).model_adapter = ScriptedOrder()
    conversation_id = _open(support_client, "metrics-conv")
    sent = support_client.post(
        f"/conversations/{conversation_id}/messages",
        headers=_headers(support_client, "corr-metrics-turn"),
        json={"content": f"Where is {ORDER}?", "idempotency_key": "metrics-msg"},
    )
    assert sent.status_code == 201
    after_turn = _metrics(support_client)
    assert after_turn["conversation_count"] == before["conversation_count"] + 1
    assert after_turn["agent_turn_count"] == before["agent_turn_count"] + 1
    assert after_turn["tool_call_count"] == before["tool_call_count"] + 1
    assert after_turn["model_input_tokens"] == before["model_input_tokens"] + 17
    assert after_turn["model_output_tokens"] == before["model_output_tokens"] + 8

    _state(support_client).model_adapter = None
    asked = support_client.post(
        f"/conversations/{conversation_id}/messages",
        headers=_headers(support_client, "corr-metrics-approval"),
        json={
            "content": (
                "Please change the delivery address for ORD-10482\n"
                "recipient: Ava Chen\n"
                "line1: 42 Congress Avenue\n"
                "city: Austin\n"
                "region: TX\n"
                "postal_code: 78701\n"
                "country: US"
            ),
            "idempotency_key": "metrics-address",
        },
    )
    assert asked.status_code == 201
    approval = _approval(support_client, conversation_id)
    confirmed = support_client.post(
        f"/conversations/{conversation_id}/approvals/{approval['id']}/confirm",
        headers=_headers(support_client, "corr-metrics-confirm"),
        json={},
    )
    assert confirmed.status_code == 200
    after_approval = _metrics(support_client)
    assert after_approval["approval_requested_count"] == before["approval_requested_count"] + 1
    assert after_approval["approval_accepted_count"] == before["approval_accepted_count"] + 1

    abstained = support_client.post(
        f"/conversations/{conversation_id}/messages",
        headers=_headers(support_client, "corr-metrics-abstain"),
        json={
            "content": "What is the capital of Mongolia?",
            "idempotency_key": "metrics-abstain",
        },
    )
    assert abstained.status_code == 201
    after_abstain = _metrics(support_client)
    assert (
        after_abstain["grounded_answer_failure_count"]
        == after_approval["grounded_answer_failure_count"] + 1
    )
    assert after_abstain["rag_retrieval_count"] >= after_approval["rag_retrieval_count"] + 1

    scraped = support_client.get("/metrics")
    assert scraped.status_code == 200
    assert set(METRIC_NAMES) <= set(scraped.json()["metrics"])


def test_escalation_rate_is_escalations_over_conversations() -> None:
    metrics = InMemoryMetrics()
    metrics.increment(
        "conversation_count",
        tenant_id="11111111-1111-4111-8111-111111111111",
    )
    metrics.record_escalation("11111111-1111-4111-8111-111111111111")

    assert metrics.snapshot()["human_escalation_rate"] == 1.0


def test_cloudwatch_client_is_built_only_when_both_flags_are_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sys.modules.pop("assistflow_api.cloudwatch_metrics", None)
    assert not hasattr(build_metrics(False, True, "us-east-1"), "_client")
    assert "assistflow_api.cloudwatch_metrics" not in sys.modules
    assert not hasattr(build_metrics(True, False, "us-east-1"), "_client")
    assert "assistflow_api.cloudwatch_metrics" not in sys.modules

    published: list[dict[str, object]] = []

    class Client:
        def put_metric_data(self, **kwargs: object) -> dict[str, object]:
            published.append(kwargs)
            return {}

    fake = types.ModuleType("boto3")
    fake.client = lambda *_args, **_kwargs: Client()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "boto3", fake)
    recorder = build_metrics(True, True, "us-east-1")
    recorder.increment(
        "tool_call_count",
        tool="get_order",
        status="failed",
        tenant_id="11111111-1111-4111-8111-111111111111",
    )

    assert recorder.snapshot()["tool_call_count"] == 1
    assert published
    metric = published[0]["MetricData"]
    assert isinstance(metric, list)
    assert metric[0]["MetricName"] == "tool_call_count"


def test_unknown_metric_labels_are_dropped() -> None:
    metrics = InMemoryMetrics()
    metrics.increment(
        "tool_failure_count",
        tool="get_order",
        status="failed",
        tenant_id="11111111-1111-4111-8111-111111111111",
        customer_id="secret-customer",
        error="free-form failure text",
    )

    assert metrics.snapshot()["tool_failure_count"] == 1
    assert "secret-customer" not in repr(metrics.snapshot())


def test_default_terraform_plan_creates_no_dashboard(tmp_path: Path) -> None:
    root = repo_root()
    variables = (root / "infra" / "environments" / "dev" / "variables.tf").read_text(
        encoding="utf-8"
    )
    block = variables.split('variable "enable_observability"', maxsplit=1)[1][:240]
    assert "default     = false" in block
    module = (root / "infra" / "modules" / "observability" / "main.tf").read_text(encoding="utf-8")
    for name in METRIC_NAMES:
        assert name in module
    assert "retention_in_days = var.log_retention_days" in module
    created = _plan_observability(tmp_path, root, enabled=False)
    assert "aws_cloudwatch_dashboard" not in created
    assert "aws_cloudwatch_log_group" not in created


def test_enabled_dashboard_plan_names_the_metrics(tmp_path: Path) -> None:
    planned = _plan_observability(tmp_path / "enabled", root=repo_root(), enabled=True, body=True)
    assert isinstance(planned, str)
    for name in METRIC_NAMES:
        assert name in planned


def _state(client: TestClient) -> Any:
    return cast(Any, client).app.state


def _open(client: TestClient, key: str) -> str:
    created = client.post(
        "/conversations",
        headers=_headers(client),
        json={"idempotency_key": key},
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]
    assert isinstance(conversation_id, str)
    return conversation_id


def _headers(client: TestClient, correlation: str = CORRELATION) -> dict[str, str]:
    return customer_headers(client, HARBOR, HARBOR_CUSTOMER, correlation)


def _metrics(client: TestClient) -> dict[str, float]:
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.json()["metrics"]
    assert isinstance(body, dict)
    return {str(key): float(value) for key, value in body.items()}


def _approval(client: TestClient, conversation_id: str) -> dict[str, object]:
    transcript = client.get(
        f"/conversations/{conversation_id}/messages",
        headers=_headers(client),
    )
    assert transcript.status_code == 200
    for item in transcript.json()["items"]:
        approvals = item.get("approvals")
        if isinstance(approvals, list) and approvals:
            approval = approvals[0]
            assert isinstance(approval, dict)
            return approval
    raise AssertionError("expected an approval card")


def _plan_observability(
    tmp_path: Path,
    root: Path,
    *,
    enabled: bool,
    body: bool = False,
) -> set[str] | str:
    cache = root / "infra" / "environments" / "dev" / ".terraform" / "providers"
    installed = cache / "registry.terraform.io" / "hashicorp" / "aws"
    if not installed.is_dir():
        dev = root / "infra" / "environments" / "dev"
        warmup = subprocess.run(
            ["terraform", f"-chdir={dev}", "init", "-backend=false", "-input=false"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert warmup.returncode == 0, warmup.stderr
    versions = sorted(path.name for path in installed.iterdir() if path.is_dir())
    assert versions, "The AWS provider cache is missing. Run terraform init in the dev stack."
    version = versions[-1]
    config = tmp_path / "plan"
    config.mkdir(parents=True)
    module = (root / "infra" / "modules" / "observability").as_posix()
    flag = "true" if enabled else "false"
    (config / "main.tf").write_text(
        "\n".join(
            [
                "terraform {",
                "  required_providers {",
                "    aws = {",
                '      source  = "hashicorp/aws"',
                f'      version = "{version}"',
                "    }",
                "  }",
                "}",
                'provider "aws" {',
                '  region                      = "us-east-1"',
                "  skip_credentials_validation = true",
                "  skip_metadata_api_check     = true",
                "  skip_requesting_account_id  = true",
                "}",
                'module "observability" {',
                f'  source  = "{module}"',
                f"  enabled = {flag}",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    cli = tmp_path / "terraform.rc"
    cli.write_text(
        "\n".join(
            [
                "provider_installation {",
                "  filesystem_mirror {",
                f'    path    = "{cache.as_posix()}"',
                '    include = ["registry.terraform.io/hashicorp/aws"]',
                "  }",
                "  direct {",
                '    exclude = ["registry.terraform.io/hashicorp/aws"]',
                "  }",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["TF_CLI_CONFIG_FILE"] = str(cli)
    env["AWS_EC2_METADATA_DISABLED"] = "true"
    init = subprocess.run(
        ["terraform", f"-chdir={config}", "init", "-backend=false", "-input=false"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert init.returncode == 0, init.stderr
    plan = config / "plan.tfplan"
    planned = subprocess.run(
        ["terraform", f"-chdir={config}", "plan", "-input=false", f"-out={plan}"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert planned.returncode == 0, planned.stderr
    show = subprocess.run(
        ["terraform", f"-chdir={config}", "show", "-json", str(plan)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert show.returncode == 0, show.stderr
    if body:
        return show.stdout
    document = json.loads(show.stdout)
    changes = document.get("resource_changes") or []
    return {
        item["type"]
        for item in changes
        if isinstance(item, dict) and item.get("change", {}).get("actions") != ["no-op"]
    }
