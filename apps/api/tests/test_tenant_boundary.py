"""Cross-tenant reads and writes fail closed. Tokens come from the local issuer."""

import json
import os
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import structlog
from assistflow_contracts.gateway import verify_actor_context
from assistflow_contracts.support import ShippingAddress
from assistflow_customers.errors import SupportError
from assistflow_orders.repository import OrderRepository
from assistflow_shipping.commands import update_shipping_address
from assistflow_shipping.repository import ShipmentRepository
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from assistflow_api.config import load_settings, repo_root
from assistflow_api.main import create_app
from assistflow_api.turns import build_turn_gateway, gateway_actor_for
from assistflow_knowledge.embeddings import DeterministicEmbedding
from assistflow_knowledge.ingest import ingest_text
from assistflow_knowledge.models import KnowledgeDocumentRow
from assistflow_memory.allowlist import PREFERRED_LANGUAGE
from assistflow_memory.local_preferences import LocalPreferenceMemory
from assistflow_runtime.gateway import AgentCoreToolGateway
from tokens import customer_headers, remote_settings, staff_headers, token_for

HARBOR = UUID("11111111-1111-4111-8111-111111111111")
FIELDLINE = UUID("22222222-2222-4222-8222-222222222222")
HARBOR_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001")
FIELDLINE_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0002")
NORA = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbb0001")
OWEN = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbb0002")
FIELD_PHRASE = "Fieldline dock passphrase stays private."


def test_local_login_names_people_and_hides_tenant_ids(support_client: TestClient) -> None:
    catalog = support_client.get("/dev/issuer/users")
    assert catalog.status_code == 200
    keys = [item["key"] for item in catalog.json()["users"]]
    assert keys == ["ava-chen", "nora-hale", "ben-ortiz", "owen-blake"]
    assert "tenant_id" not in catalog.text
    assert "11111111" not in catalog.text

    session = support_client.post("/dev/issuer/session", json={"user": "ava-chen"})
    assert session.status_code == 200
    assert session.json()["role"] == "customer"
    assert "access_token" not in session.json()
    orders = support_client.get("/orders/ORD-10482")
    assert orders.status_code == 200
    assert orders.json()["order_number"] == "ORD-10482"


def test_missing_token_is_unauthorized_and_the_log_omits_it(support_client: TestClient) -> None:
    with structlog.testing.capture_logs() as logs:
        missing = support_client.get("/orders/ORD-10482")
    assert missing.status_code == 401
    assert missing.json()["code"] == "unauthorized"
    assert any(item.get("event") == "authorization_denied" for item in logs)

    token = token_for(support_client, "ava-chen")
    with structlog.testing.capture_logs() as denied_logs:
        forbidden = support_client.get(
            "/staff/inbox",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert forbidden.status_code == 403
    rendered = repr(denied_logs)
    assert token not in rendered
    assert "Bearer" not in rendered
    assert any(item.get("event") == "authorization_denied" for item in denied_logs)


def test_roles_cannot_switch_and_staff_stay_in_their_tenant(
    support_client: TestClient, support_engine: Engine
) -> None:
    customer = customer_headers(support_client, HARBOR, HARBOR_CUSTOMER)
    staff = staff_headers(support_client, HARBOR, NORA)
    other_staff = staff_headers(support_client, FIELDLINE, OWEN)
    opened = support_client.post(
        "/conversations",
        headers=customer,
        json={"idempotency_key": "boundary-escalate"},
    )
    conversation_id = opened.json()["id"]
    from assistflow_tickets.commands import request_human_escalation

    with Session(support_engine) as session:
        request_human_escalation(
            session,
            HARBOR,
            HARBOR_CUSTOMER,
            UUID(conversation_id),
            "Need a person",
            "boundary-escalate-key",
            actor_type="customer",
            correlation_id="boundary",
            actor_id=HARBOR_CUSTOMER,
        )
        session.commit()

    inbox = support_client.get("/staff/inbox", headers=customer)
    assert inbox.status_code == 403
    assert "Ava Chen" not in inbox.text

    orders = support_client.get("/orders", headers=staff)
    assert orders.status_code == 403

    harbor_inbox = support_client.get("/staff/inbox", headers=staff)
    field_inbox = support_client.get("/staff/inbox", headers=other_staff)
    assert [item["id"] for item in harbor_inbox.json()["items"]] == [conversation_id]
    assert field_inbox.json()["items"] == []
    assert "Ava Chen" not in field_inbox.text


def test_customer_cannot_read_or_write_another_tenant(
    support_client: TestClient, support_engine: Engine
) -> None:
    ava = customer_headers(support_client, HARBOR, HARBOR_CUSTOMER)
    ben = customer_headers(support_client, FIELDLINE, FIELDLINE_CUSTOMER)
    document_id = _private_document(support_engine)

    hidden_order = support_client.get("/orders/ORD-20817", headers=ava)
    hidden_shipment = support_client.get("/orders/ORD-20817/shipment", headers=ava)
    listed = support_client.get("/orders", headers=ava)
    assert hidden_order.status_code == 404
    assert hidden_shipment.status_code == 404
    assert "EWR" not in hidden_order.text
    assert "EWR" not in hidden_shipment.text
    assert "Ben Ortiz" not in hidden_order.text
    assert "90 Cedar" not in hidden_shipment.text
    assert [item["order_number"] for item in listed.json()["items"]] == ["ORD-10482"]

    created = support_client.post(
        "/tickets",
        headers=ava,
        json={
            "customer_id": str(FIELDLINE_CUSTOMER),
            "tenant_id": str(FIELDLINE),
            "priority": "normal",
            "category": "order",
            "summary": "Harbor only ticket",
            "idempotency_key": "boundary-ticket",
        },
    )
    assert created.status_code == 201
    ticket_id = created.json()["id"]
    assert support_client.get(f"/tickets/{ticket_id}", headers=ben).status_code == 404
    assert "Harbor only" not in support_client.get(f"/tickets/{ticket_id}", headers=ben).text
    assert support_client.get(f"/tickets/{ticket_id}", headers=ava).status_code == 200

    conversation = support_client.post(
        "/conversations",
        headers=ava,
        json={"idempotency_key": "boundary-conv", "tenant_id": str(FIELDLINE)},
    )
    assert conversation.status_code == 201
    conversation_id = conversation.json()["id"]
    assert support_client.get(f"/conversations/{conversation_id}", headers=ben).status_code == 404
    ben_list = support_client.get("/conversations", headers=ben)
    assert conversation_id not in [item["id"] for item in ben_list.json()["items"]]

    hidden_doc = support_client.get(f"/documents/{document_id}", headers=ava)
    doc_list = support_client.get("/documents", headers=ava)
    assert hidden_doc.status_code == 404
    assert FIELD_PHRASE not in hidden_doc.text
    assert FIELD_PHRASE not in doc_list.text
    before = _document_count(support_engine, FIELDLINE)
    refused = support_client.post(
        "/documents",
        headers=ava,
        json={"tenant_id": str(FIELDLINE), "title": "Leak", "body": "nope"},
    )
    assert refused.status_code == 405
    assert _document_count(support_engine, FIELDLINE) == before
    assert support_client.get(f"/documents/{document_id}", headers=ben).json()["body"] == (
        FIELD_PHRASE
    )

    _assert_order_and_shipment_writes_stay_home(support_engine)
    _assert_preference_delete_stays_home(support_engine)
    _assert_tool_actor_is_the_token_tenant(support_engine)


def test_hosted_gateway_signs_the_verified_actor() -> None:
    conversation_id = uuid4()
    actor = gateway_actor_for(
        tenant_id=HARBOR,
        customer_id=HARBOR_CUSTOMER,
        actor_type="customer",
        correlation_id="boundary-gateway",
        conversation_id=conversation_id,
    )
    captured: dict[str, object] = {}

    class Capture:
        def request(
            self,
            method: str,
            params: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            captured["method"] = method
            captured["headers"] = headers
            captured["params"] = params
            return {
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                '{"name":"get_order","status":"succeeded","summary":"ok",'
                                '"risk_level":"read","arguments_hash":"abc"}'
                            ),
                        }
                    ]
                }
            }

    gateway = AgentCoreToolGateway(Capture(), inbound_token="inbound", context_secret="secret")
    blocked = gateway.call_tool(
        "get_order",
        {"order_id": "ORD-1", "tenant_id": str(FIELDLINE)},
        actor,
    )
    assert blocked.error_code == "invalid_arguments"
    assert "headers" not in captured

    called = gateway.call_tool("get_order", {"order_id": "ORD-10482"}, actor)
    assert called.status == "succeeded"
    headers = captured["headers"]
    assert isinstance(headers, dict)
    signed = headers["x-actor-context"]
    assert isinstance(signed, str)
    verified = verify_actor_context(signed, "secret")
    assert verified is not None
    assert verified.tenant_id == HARBOR
    assert verified.customer_id == HARBOR_CUSTOMER
    assert str(FIELDLINE) not in signed


def test_remote_modes_reject_the_local_issuer(support_engine: Engine) -> None:
    for mode in ("aws-demo", "showcase"):
        with pytest.raises(ValueError, match="local token issuer"):
            create_app(
                load_settings({"EXECUTION_MODE": mode, "AUTH_ISSUER": "https://assistflow.local"}),
                engine=support_engine,
            )
        with pytest.raises(ValueError, match="local token issuer"):
            create_app(load_settings({"EXECUTION_MODE": mode}), engine=support_engine)

    local = create_app(load_settings({}), engine=support_engine)
    with TestClient(local) as local_client:
        token = token_for(local_client, "ava-chen")
    remote = create_app(load_settings(remote_settings()), engine=support_engine)
    with TestClient(remote) as remote_client:
        missing = remote_client.post("/dev/issuer/token", json={"user": "ava-chen"})
        assert missing.status_code == 404
        rejected = remote_client.get("/orders", headers={"Authorization": f"Bearer {token}"})
    assert rejected.status_code == 401
    assert token not in rejected.text


def test_default_terraform_plan_creates_no_user_pool(tmp_path: Path) -> None:
    root = repo_root()
    variables_path = root / "infra" / "environments" / "dev" / "variables.tf"
    variables = variables_path.read_text(encoding="utf-8")
    block = variables.split('variable "enable_cognito"', maxsplit=1)[1][:240]
    assert "default     = false" in block
    module = (root / "infra" / "modules" / "cognito" / "main.tf").read_text(encoding="utf-8")
    assert module.count("count = var.enabled ? 1 : 0") >= 4
    created = _plan_disabled_cognito(tmp_path, root)
    assert "aws_cognito_user_pool" not in created
    assert "aws_cognito_user_pool_client" not in created
    assert "aws_cognito_user_group" not in created


def _private_document(engine: Engine) -> UUID:
    with Session(engine) as session:
        ingest_text(
            session,
            FIELDLINE,
            "knowledge/private/fieldline-secret.md",
            "Fieldline private",
            FIELD_PHRASE,
            DeterministicEmbedding(),
        )
        session.commit()
        document_id = session.scalar(
            select(KnowledgeDocumentRow.id).where(
                KnowledgeDocumentRow.tenant_id == FIELDLINE,
                KnowledgeDocumentRow.source_uri == "knowledge/private/fieldline-secret.md",
            )
        )
    assert isinstance(document_id, UUID)
    return document_id


def _document_count(engine: Engine, tenant_id: UUID) -> int:
    with Session(engine) as session:
        counted = session.scalar(
            select(func.count())
            .select_from(KnowledgeDocumentRow)
            .where(KnowledgeDocumentRow.tenant_id == tenant_id)
        )
    return int(counted or 0)


def _assert_order_and_shipment_writes_stay_home(engine: Engine) -> None:
    address = ShippingAddress(
        recipient="Ava Chen",
        line1="18 Market Street",
        line2="Apt 4",
        city="Austin",
        region="TX",
        postal_code="78701",
        country="US",
    )
    with Session(engine) as session:
        try:
            update_shipping_address(
                session,
                HARBOR,
                "ORD-20817",
                address,
                "boundary-address",
                customer_id=HARBOR_CUSTOMER,
                actor_type="customer",
                correlation_id="boundary",
                actor_id=HARBOR_CUSTOMER,
            )
            raise AssertionError("cross-tenant address write was allowed")
        except SupportError as exc:
            assert exc.status_code == 404
        field_order = OrderRepository(session).require(FIELDLINE, "ORD-20817")
        shipment = ShipmentRepository(session).get_by_order(FIELDLINE, field_order.id)
        assert shipment is not None
        forged = replace(shipment, tenant_id=HARBOR, origin_hub="DFW")
        try:
            ShipmentRepository(session).update(forged)
            raise AssertionError("cross-tenant shipment write was allowed")
        except SupportError as exc:
            assert exc.status_code == 404
        session.rollback()
        unchanged = OrderRepository(session).require(FIELDLINE, "ORD-20817")
        assert unchanged.shipping_address.line1 == "90 Cedar Avenue"
        kept = ShipmentRepository(session).get_by_order(FIELDLINE, unchanged.id)
        assert kept is not None
        assert kept.origin_hub == "EWR"


def _assert_preference_delete_stays_home(engine: Engine) -> None:
    with Session(engine) as session:
        memory = LocalPreferenceMemory(session)
        now = datetime.now(UTC)
        memory.remember(HARBOR, HARBOR_CUSTOMER, PREFERRED_LANGUAGE, "en", now)
        memory.remember(FIELDLINE, FIELDLINE_CUSTOMER, PREFERRED_LANGUAGE, "es", now)
        session.commit()
    app = create_app(load_settings({"LONG_TERM_MEMORY_ENABLED": "true"}), engine=engine)
    with TestClient(app) as client:
        deleted = client.delete(
            "/preferences",
            headers=customer_headers(client, HARBOR, HARBOR_CUSTOMER),
        )
        other = client.get(
            "/preferences",
            headers=customer_headers(client, FIELDLINE, FIELDLINE_CUSTOMER),
        )
    assert deleted.status_code == 204
    assert other.json()["items"][0]["value"] == "es"


def _assert_tool_actor_is_the_token_tenant(engine: Engine) -> None:
    with Session(engine) as session:
        gateway = build_turn_gateway(
            session,
            max_tool_calls=5,
            max_chunks=4,
            score_floor=0.28,
        )
        actor = gateway_actor_for(
            tenant_id=HARBOR,
            customer_id=HARBOR_CUSTOMER,
            actor_type="customer",
            correlation_id="boundary-tool",
            conversation_id=uuid4(),
        )
        result = gateway.call_tool("get_order", {"order_id": "ORD-20817"}, actor)
    assert result.error_code == "not_found"
    assert "EWR" not in result.summary
    assert "Ben" not in result.summary
    assert "90 Cedar" not in result.summary


def _plan_disabled_cognito(tmp_path: Path, root: Path) -> set[str]:
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
    config.mkdir()
    module = (root / "infra" / "modules" / "cognito").as_posix()
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
                'module "cognito" {',
                f'  source  = "{module}"',
                "  enabled = false",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    cli = tmp_path / "terraform.rc"
    mirror = cache.as_posix()
    cli.write_text(
        "\n".join(
            [
                "provider_installation {",
                "  filesystem_mirror {",
                f'    path    = "{mirror}"',
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
    document = json.loads(show.stdout)
    changes = document.get("resource_changes") or []
    return {
        item["type"]
        for item in changes
        if isinstance(item, dict) and item.get("change", {}).get("actions") != ["no-op"]
    }
