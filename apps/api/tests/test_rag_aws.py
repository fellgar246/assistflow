"""AWS retrieval providers stay behind the same port and stay off unless configured."""

import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from assistflow_contracts.agent import (
    AdapterUsage,
    AgentResult,
    ModelMessage,
    ModelResponse,
    ModelText,
    ModelToolUse,
    PromptRef,
    ToolSchema,
    ToolUseRequest,
    TurnContext,
)
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from assistflow_api.config import RagProvider, load_settings, repo_root
from assistflow_api.main import create_app
from assistflow_api.retrieval import build_knowledge_retriever
from assistflow_api.sync_knowledge import require_s3_sync
from assistflow_knowledge.catalog import PublishedDocument
from assistflow_knowledge.chunking import chunk_text
from assistflow_knowledge.documents import dumps_document, loads_document
from assistflow_knowledge.embeddings import DeterministicEmbedding, cosine
from assistflow_knowledge.managed import ManagedHit, ManagedKnowledgeRetriever
from assistflow_knowledge.object_store import MemoryObjectStore
from assistflow_knowledge.retriever import RetrievedChunk
from assistflow_knowledge.s3 import S3KnowledgeRetriever
from assistflow_knowledge.sync import sync_documents
from assistflow_runtime.limits import TurnLimits
from assistflow_runtime.loop import AgentLoop
from assistflow_runtime.prompts import PromptRegistry
from assistflow_tools import LocalToolGateway, build_registry, service_handlers

HARBOR = UUID("11111111-1111-4111-8111-111111111111")
FIELDLINE = UUID("22222222-2222-4222-8222-222222222222")
HARBOR_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001")
BUCKET = "assistflow-knowledge"
PREFIX = "tenants/{tenant_id}/"
SHIPPING = "knowledge/policies/shipping-policy.md"


def test_s3_provider_runs_citation_and_abstention_fixtures() -> None:
    store = _synced_store()
    retriever = _s3(store)
    _assert_fixtures(retriever)


def test_managed_provider_runs_citation_and_abstention_fixtures() -> None:
    store = _synced_store()
    retriever = _managed(store)
    _assert_fixtures(retriever)


def test_shipping_question_cites_the_same_document_for_each_provider(
    support_engine: Engine,
) -> None:
    cases = _cases()["documents"]
    assert isinstance(cases, list)
    shipping = next(case for case in cases if case["id"] == "shipping-policy")
    query = str(shipping["query"])
    store = _synced_store()
    with Session(support_engine) as session:
        local = build_knowledge_retriever(load_settings({}), session)
        found = {
            "local": local.retrieve(HARBOR, query, 4),
            "s3": _s3(store).retrieve(HARBOR, query, 4),
            "managed": _managed(store).retrieve(HARBOR, query, 4),
        }
    titles = {name: chunks[0].title for name, chunks in found.items()}
    versions = {name: chunks[0].version for name, chunks in found.items()}
    assert titles == {
        "local": "Shipping policy",
        "s3": "Shipping policy",
        "managed": "Shipping policy",
    }
    assert versions == {"local": 1, "s3": 1, "managed": 1}
    body = (repo_root() / SHIPPING).read_text(encoding="utf-8")
    assert all(chunks[0].text in body for chunks in found.values())


def test_agent_loop_cites_a_stub_retriever_without_branching_on_provider(
    support_engine: Engine,
) -> None:
    stub = _StubRetriever()
    with Session(support_engine) as session:
        result = _run_loop(session, stub, "What is the shipping cutoff?")
    assert result.citations
    assert result.citations[0].title == "Shipping policy"
    assert result.citations[0].version == "1"
    assert stub.calls == 1
    loop_source = repo_root() / "agent" / "runtime" / "src" / "assistflow_runtime" / "loop.py"
    source = loop_source.read_text(encoding="utf-8")
    for token in (
        "boto3",
        "RAG_PROVIDER",
        "rag_provider",
        "S3KnowledgeRetriever",
        "ManagedKnowledgeRetriever",
    ):
        assert token not in source


def test_retrieval_cap_still_bounds_a_turn(support_engine: Engine) -> None:
    stub = _StubRetriever()
    with Session(support_engine) as session:
        gateway = LocalToolGateway(
            build_registry(service_handlers(session, retriever=stub)),
            max_executions=5,
        )
        loop = AgentLoop(
            _DoubleSearch(),
            gateway,
            PromptRegistry(repo_root() / "agent" / "prompts"),
            TurnLimits(8, 5, 4, max_retrievals_per_turn=1),
            lambda _views: "unused",
        )
        loop.run(_turn("Look up shipping twice"))
    assert stub.calls == 1


def test_s3_retrieval_stays_inside_the_tenant_prefix() -> None:
    store = MemoryObjectStore()
    _put_note(store, HARBOR, "knowledge/private/harbor-note.md", "Harbor lane cutoff is private.")
    _put_note(
        store,
        FIELDLINE,
        "knowledge/private/fieldline-note.md",
        "Fieldline dock cutoff is private.",
    )
    _put_note(
        store,
        HARBOR,
        "knowledge/private/retired-note.md",
        "Retired lantern phrase should never be retrieved.",
        status="retired",
    )
    retriever = _s3(store)
    fieldline = retriever.retrieve(FIELDLINE, "Fieldline dock cutoff", 4)
    assert fieldline
    assert all("Harbor lane" not in chunk.text for chunk in fieldline)
    assert retriever.retrieve(HARBOR, "Retired lantern phrase", 4) == []
    harbor = retriever.retrieve(HARBOR, "Harbor lane cutoff", 4)
    assert harbor
    assert all("Fieldline dock" not in chunk.text for chunk in harbor)


def test_managed_retrieval_drops_uncitable_hits_and_applies_the_score_floor() -> None:
    cited = _hit("Shipping policy", score=0.9)
    weak = _hit("Shipping policy", score=0.01)
    blank = ManagedHit(text="no source", score=0.99, document_id=None, title=None, version=None)
    retriever = ManagedKnowledgeRetriever(
        _ScriptedClient([cited, weak, blank]),
        knowledge_base_id="kb-1",
        metadata_key="tenant_id",
    )
    found = retriever.retrieve(HARBOR, "shipping cutoff", 4)
    assert len(found) == 1
    assert found[0].title == "Shipping policy"
    assert found[0].version == 1


def test_unscored_provider_abstains_without_a_citation() -> None:
    retriever = ManagedKnowledgeRetriever(
        _ScriptedClient(
            [ManagedHit(text="orphan", score=None, document_id=None, title=None, version=None)]
        ),
        knowledge_base_id="kb-1",
        metadata_key="tenant_id",
    )
    assert retriever.retrieve(HARBOR, "shipping cutoff", 4) == []


def test_unscored_provider_keeps_a_citable_hit() -> None:
    retriever = ManagedKnowledgeRetriever(
        _ScriptedClient([_hit("Shipping policy", score=None)]),
        knowledge_base_id="kb-1",
        metadata_key="tenant_id",
    )
    found = retriever.retrieve(HARBOR, "shipping cutoff", 4)
    assert len(found) == 1
    assert found[0].title == "Shipping policy"
    assert found[0].version == 1


def test_managed_base_per_tenant_does_not_read_the_other_base() -> None:
    client = _ScriptedClient([_hit("Shipping policy", score=0.9, tenant_id=str(HARBOR))])
    retriever = ManagedKnowledgeRetriever(
        client,
        knowledge_bases={HARBOR: "kb-harbor", FIELDLINE: "kb-fieldline"},
    )
    assert retriever.retrieve(FIELDLINE, "shipping cutoff", 4) == []
    assert client.calls[-1]["knowledge_base_id"] == "kb-fieldline"
    harbor = retriever.retrieve(HARBOR, "shipping cutoff", 4)
    assert harbor
    assert client.calls[-1]["knowledge_base_id"] == "kb-harbor"


def test_managed_retriever_requires_a_tenant_filter() -> None:
    client = _ScriptedClient([])
    try:
        ManagedKnowledgeRetriever(client)
    except ValueError as exc:
        assert "tenant" in str(exc).lower()
    else:
        raise AssertionError("a missing tenant filter must fail")
    try:
        ManagedKnowledgeRetriever(client, knowledge_base_id="kb-1")
    except ValueError as exc:
        assert "metadata" in str(exc).lower()
    else:
        raise AssertionError("a shared base without a metadata filter must fail")


def test_s3_settings_require_a_bucket_and_a_tenant_prefix() -> None:
    try:
        load_settings({"RAG_PROVIDER": "s3"})
    except ValueError as exc:
        assert "KNOWLEDGE_BUCKET" in str(exc)
    else:
        raise AssertionError("s3 without a bucket must fail")
    try:
        load_settings(
            {
                "RAG_PROVIDER": "s3",
                "KNOWLEDGE_BUCKET": BUCKET,
                "KNOWLEDGE_KEY_PREFIX": "docs/",
            }
        )
    except ValueError as exc:
        assert "tenant_id" in str(exc)
    else:
        raise AssertionError("s3 without a tenant prefix must fail")


def test_managed_settings_require_a_filter_when_the_flag_is_on() -> None:
    try:
        load_settings(
            {
                "RAG_PROVIDER": "managed",
                "MANAGED_RAG_ENABLED": "true",
                "MANAGED_KNOWLEDGE_BASE_ID": "kb-1",
            }
        )
    except ValueError as exc:
        assert "metadata filter" in str(exc)
    else:
        raise AssertionError("managed retrieval without a tenant filter must fail")
    settings = load_settings(
        {
            "RAG_PROVIDER": "managed",
            "MANAGED_RAG_ENABLED": "true",
            "MANAGED_KNOWLEDGE_BASES": f"{HARBOR}=kb-harbor",
        }
    )
    assert settings.rag_provider is RagProvider.MANAGED
    assert settings.managed_knowledge_bases[str(HARBOR)] == "kb-harbor"


def test_api_start_does_not_construct_the_managed_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import assistflow_knowledge.managed as managed

    calls: list[str] = []

    def spy(_self: object, *_args: object, **_kwargs: object) -> None:
        calls.append("managed")

    monkeypatch.setattr(managed.ManagedKnowledgeRetriever, "__init__", spy)
    app = create_app(load_settings({"MANAGED_RAG_ENABLED": "false"}))
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    assert calls == []
    assert "boto3" not in sys.modules


def test_sync_rejects_remote_urls_and_skips_an_unchanged_checksum(tmp_path: Path) -> None:
    root = tmp_path
    relative = "knowledge/policies/shipping-policy.md"
    path = root / relative
    path.parent.mkdir(parents=True)
    path.write_text("The DFW hub cutoff is 2099-06-15.\n", encoding="utf-8")
    store = MemoryObjectStore()
    document = PublishedDocument(relative, "Shipping policy")
    first = sync_documents(store, BUCKET, PREFIX, root, [HARBOR], documents=(document,))
    second = sync_documents(store, BUCKET, PREFIX, root, [HARBOR], documents=(document,))
    assert first[0].created is True
    assert second[0].created is False
    assert second[0].version == 1
    path.write_text("The DFW hub cutoff is 2099-06-15.\nA later note.\n", encoding="utf-8")
    third = sync_documents(store, BUCKET, PREFIX, root, [HARBOR], documents=(document,))
    assert third[0].created is True
    assert third[0].version == 2
    for source in ("https://example.com/policy.md", "../secrets.txt"):
        try:
            sync_documents(
                store,
                BUCKET,
                PREFIX,
                root,
                [HARBOR],
                documents=(PublishedDocument(source, "Remote"),),
            )
        except ValueError as exc:
            assert "published product files" in str(exc)
        else:
            raise AssertionError(source)
    try:
        require_s3_sync(load_settings({}))
    except ValueError as exc:
        assert "RAG_PROVIDER=s3" in str(exc)
    else:
        raise AssertionError("local sync must be refused")


def test_default_plan_creates_no_managed_retrieval(tmp_path: Path) -> None:
    root = repo_root()
    infra = root / "infra"
    bucket = (infra / "modules" / "knowledge_bucket" / "main.tf").read_text(encoding="utf-8")
    managed = (infra / "modules" / "managed_rag" / "main.tf").read_text(encoding="utf-8")
    dev = (infra / "environments" / "dev" / "main.tf").read_text(encoding="utf-8")
    variables = (infra / "environments" / "dev" / "variables.tf").read_text(encoding="utf-8")
    for flag in (
        "block_public_acls",
        "block_public_policy",
        "ignore_public_acls",
        "restrict_public_buckets",
    ):
        assert f"{flag} " in bucket
        assert "true" in bucket.split(flag, maxsplit=1)[1].split("\n", maxsplit=1)[0]
    assert "count = var.enabled ? 1 : 0" in bucket
    assert "count = var.enabled ? 1 : 0" in managed
    assert "var.enable_managed_rag" in dev
    managed_block = variables.split('variable "enable_managed_rag"', maxsplit=1)[1][:200]
    bucket_block = variables.split('variable "enable_knowledge_bucket"', maxsplit=1)[1][:240]
    assert "default     = false" in managed_block
    assert "default     = false" in bucket_block
    created = _plan_disabled_modules(tmp_path, root)
    assert "aws_bedrockagent_knowledge_base" not in created
    assert "aws_bedrockagent_data_source" not in created
    assert "aws_s3_bucket" not in created


def _plan_disabled_modules(tmp_path: Path, root: Path) -> set[object]:
    """Plan the retrieval modules with their default switch off. No AWS account is used."""
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
    bucket_module = (root / "infra" / "modules" / "knowledge_bucket").as_posix()
    managed_module = (root / "infra" / "modules" / "managed_rag").as_posix()
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
                "",
                'provider "aws" {',
                '  region                      = "us-east-1"',
                "  skip_credentials_validation = true",
                "  skip_metadata_api_check     = true",
                "  skip_requesting_account_id  = true",
                "}",
                "",
                'module "knowledge_bucket" {',
                f'  source  = "{bucket_module}"',
                "  enabled = false",
                "}",
                "",
                'module "managed_rag" {',
                f'  source  = "{managed_module}"',
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
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE"):
        env.pop(key, None)
    env.update(
        {
            "TF_CLI_CONFIG_FILE": str(cli),
            "TF_IN_AUTOMATION": "1",
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_REGION": "us-east-1",
        }
    )
    init = subprocess.run(
        ["terraform", f"-chdir={config}", "init", "-backend=false", "-input=false"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert init.returncode == 0, init.stderr
    plan = tmp_path / "default.tfplan"
    completed = subprocess.run(
        [
            "terraform",
            f"-chdir={config}",
            "plan",
            "-input=false",
            "-lock=false",
            "-refresh=false",
            f"-out={plan}",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
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
        change.get("type")
        for change in changes
        if "create" in change.get("change", {}).get("actions", [])
    }


class _StubRetriever:
    """Fixed chunks. The loop does not know which provider produced them."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def chunk_cap(self) -> int:
        return 4

    @property
    def score_floor(self) -> float:
        return 0.28

    def retrieve(self, tenant_id: UUID, query: str, limit: int) -> list[RetrievedChunk]:
        del tenant_id, query, limit
        self.calls += 1
        return [
            RetrievedChunk(
                document_id=uuid4(),
                version=1,
                title="Shipping policy",
                text="The demo shipment leaves the DFW hub.",
                score=0.9,
            )
        ]


class _SearchAdapter:
    def complete(
        self,
        messages: list[ModelMessage],
        tools: list[ToolSchema],
        max_output_tokens: int,
    ) -> ModelResponse:
        del tools, max_output_tokens
        if any(message.tool_name == "search_support_policy" for message in messages):
            return ModelText(text="done", usage=AdapterUsage(), provider="mock", model_id="mock")
        return ModelToolUse(
            requests=[
                ToolUseRequest(
                    id="search-1",
                    name="search_support_policy",
                    arguments={"query": "DFW hub cutoff 2099-06-15"},
                )
            ],
            usage=AdapterUsage(),
            provider="mock",
            model_id="mock",
        )


class _DoubleSearch:
    def complete(
        self,
        messages: list[ModelMessage],
        tools: list[ToolSchema],
        max_output_tokens: int,
    ) -> ModelResponse:
        del messages, tools, max_output_tokens
        return ModelToolUse(
            requests=[
                ToolUseRequest(
                    id="search-1",
                    name="search_support_policy",
                    arguments={"query": "shipping cutoff"},
                ),
                ToolUseRequest(
                    id="search-2",
                    name="search_support_policy",
                    arguments={"query": "shipping cutoff again"},
                ),
            ],
            usage=AdapterUsage(),
            provider="mock",
            model_id="mock",
        )


class _ScriptedClient:
    def __init__(self, hits: list[ManagedHit]) -> None:
        self._hits = hits
        self.calls: list[dict[str, str]] = []

    def retrieve(
        self,
        *,
        knowledge_base_id: str,
        query: str,
        tenant_id: str,
        metadata_key: str,
        limit: int,
    ) -> list[ManagedHit]:
        del query, limit
        self.calls.append(
            {
                "knowledge_base_id": knowledge_base_id,
                "tenant_id": tenant_id,
                "metadata_key": metadata_key,
            }
        )
        return [hit for hit in self._hits if hit.tenant_id in {None, "", tenant_id}]


class _CorpusClient:
    """Scores synced product files. It records the tenant filter and does not call AWS."""

    def __init__(self, store: MemoryObjectStore) -> None:
        self._store = store
        self._embedder = DeterministicEmbedding()

    def retrieve(
        self,
        *,
        knowledge_base_id: str,
        query: str,
        tenant_id: str,
        metadata_key: str,
        limit: int,
    ) -> list[ManagedHit]:
        del knowledge_base_id, limit
        if metadata_key.strip() == "":
            raise ValueError("A tenant metadata filter is required.")
        prefix = f"tenants/{tenant_id}/"
        query_vector = self._embedder.embed(query)
        hits: list[ManagedHit] = []
        for key in self._store.list_keys(BUCKET, prefix):
            raw = self._store.get_bytes(BUCKET, key)
            document = loads_document(raw) if raw is not None else None
            if document is None or str(document.tenant_id) != tenant_id:
                continue
            if document.status != "published":
                continue
            for text in chunk_text(document.body):
                hits.append(
                    ManagedHit(
                        text=text,
                        score=cosine(query_vector, self._embedder.embed(text)),
                        document_id=str(document.document_id),
                        title=document.title,
                        version=str(document.version),
                        tenant_id=str(document.tenant_id),
                    )
                )
        return hits


def _synced_store() -> MemoryObjectStore:
    store = MemoryObjectStore()
    sync_documents(store, BUCKET, PREFIX, repo_root(), [HARBOR, FIELDLINE])
    return store


def _s3(store: MemoryObjectStore, *, floor: float = 0.28) -> S3KnowledgeRetriever:
    return S3KnowledgeRetriever(
        store,
        BUCKET,
        PREFIX,
        DeterministicEmbedding(),
        score_floor=floor,
    )


def _managed(store: MemoryObjectStore) -> ManagedKnowledgeRetriever:
    return ManagedKnowledgeRetriever(
        _CorpusClient(store),
        knowledge_base_id="kb-shared",
        metadata_key="tenant_id",
    )


def _assert_fixtures(retriever: S3KnowledgeRetriever | ManagedKnowledgeRetriever) -> None:
    cases = _cases()
    documents = cases["documents"]
    abstentions = cases["abstentions"]
    assert isinstance(documents, list)
    assert isinstance(abstentions, list)
    assert len(documents) >= 6
    assert len(abstentions) >= 5
    for case in documents:
        assert isinstance(case, dict)
        found = retriever.retrieve(HARBOR, str(case["query"]), 4)
        assert found, case["id"]
        assert found[0].title == case["title"]
        assert found[0].version == 1
        body = (repo_root() / _source_for(str(case["title"]))).read_text(encoding="utf-8")
        assert found[0].text in body
    for query in abstentions:
        assert retriever.retrieve(HARBOR, str(query), 4) == []


def _source_for(title: str) -> str:
    names = {
        "Return policy": "knowledge/policies/return-policy.md",
        "Refund policy": "knowledge/policies/refund-policy.md",
        "Shipping policy": SHIPPING,
        "Account security": "knowledge/policies/account-security.md",
        "Product FAQ": "knowledge/product-docs/product-faq.md",
        "Support playbook": "knowledge/product-docs/support-playbook.md",
    }
    return names[title]


def _cases() -> dict[str, object]:
    loaded = json.loads(
        (repo_root() / "agent" / "evaluations" / "retrieval-cases.json").read_text(encoding="utf-8")
    )
    assert isinstance(loaded, dict)
    return loaded


def _put_note(
    store: MemoryObjectStore,
    tenant_id: UUID,
    source_uri: str,
    body: str,
    *,
    status: str = "published",
) -> None:
    from assistflow_knowledge.documents import StoredDocument, stable_document_id
    from assistflow_knowledge.ingest import content_checksum
    from assistflow_knowledge.sync import object_key

    document = StoredDocument(
        document_id=stable_document_id(tenant_id, source_uri),
        tenant_id=tenant_id,
        title="Shipping policy",
        version=1,
        source_uri=source_uri,
        checksum=content_checksum(body),
        status=status,
        body=body,
    )
    store.put_bytes(BUCKET, object_key(PREFIX, tenant_id, source_uri), dumps_document(document))


def _hit(title: str, *, score: float | None, tenant_id: str | None = None) -> ManagedHit:
    return ManagedHit(
        text="The demo shipment leaves the DFW hub.",
        score=score,
        document_id=str(uuid4()),
        title=title,
        version="1",
        tenant_id=tenant_id,
    )


def _run_loop(session: Session, retriever: _StubRetriever, message: str) -> AgentResult:
    gateway = LocalToolGateway(build_registry(service_handlers(session, retriever=retriever)))
    loop = AgentLoop(
        _SearchAdapter(),
        gateway,
        PromptRegistry(repo_root() / "agent" / "prompts"),
        TurnLimits(8, 5, 4),
        lambda _views: "unused",
    )
    return loop.run(_turn(message))


def _turn(message: str) -> TurnContext:
    return TurnContext(
        tenant_id=HARBOR,
        customer_id=HARBOR_CUSTOMER,
        conversation_id=uuid4(),
        correlation_id="corr-rag-aws",
        customer_message=message,
        history=[],
        prompt=PromptRef(id="local-support", version="1"),
    )
