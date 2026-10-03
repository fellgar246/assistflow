"""Dev stack defaults, deploy workflow, and operator commands."""

import importlib.util
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from assistflow_api.config import repo_root

_AI_RESOURCES = {
    "aws_bedrockagentcore_agent_runtime",
    "aws_bedrockagentcore_gateway",
    "aws_bedrockagentcore_memory",
    "aws_bedrockagent_knowledge_base",
    "aws_cognito_user_pool",
    "aws_scheduler_schedule",
}
_REQUIRED_TAGS = {
    "Project": "assistflow",
    "Environment": "dev",
    "ManagedBy": "terraform",
    "CostCenter": "learning",
    "AutoCleanup": "true",
}


def test_default_flags_leave_optional_ai_off() -> None:
    variables = (repo_root() / "infra" / "environments" / "dev" / "variables.tf").read_text(
        encoding="utf-8"
    )
    for name in (
        "enable_agentcore",
        "enable_long_term_memory",
        "enable_managed_rag",
        "enable_schedules",
        "enable_cognito",
    ):
        block = variables.split(f'variable "{name}"', maxsplit=1)[1]
        block = block.split("variable ", maxsplit=1)[0]
        assert "default     = false" in block


def test_default_plan_creates_no_optional_ai_resources(tmp_path: Path) -> None:
    created = _plan(tmp_path, ai=False, dev_api=False)
    assert created.isdisjoint(_AI_RESOURCES)
    assert "aws_apigatewayv2_api" not in created
    assert "aws_dynamodb_table" not in created
    assert "aws_sqs_queue" not in created
    assert "aws_cloudwatch_log_group" not in created
    assert "aws_budgets_budget" not in created
    assert "aws_iam_openid_connect_provider" not in created


def test_selected_flags_plan_the_dev_api_queue_logs_and_metadata(tmp_path: Path) -> None:
    created = _plan(tmp_path, ai=False, dev_api=True)
    assert {"aws_apigatewayv2_api", "aws_lambda_function", "aws_sqs_queue"} <= created
    assert "aws_cloudwatch_log_group" in created
    assert "aws_dynamodb_table" in created
    assert created.isdisjoint(_AI_RESOURCES)
    tagged = _tagged_resources(tmp_path)
    assert tagged
    for tags in tagged:
        assert _REQUIRED_TAGS.items() <= tags.items()


def test_budget_configuration_is_five_dollars_with_three_thresholds() -> None:
    module = cast(Any, _operator())
    assert module.budget_configuration_ok(repo_root())
    text = (repo_root() / "infra" / "modules" / "budget" / "main.tf").read_text(encoding="utf-8")
    assert "Alerts are governance" in text


def test_bedrock_permissions_name_the_model_and_guardrail() -> None:
    policy = (repo_root() / "infra" / "modules" / "agentcore" / "main.tf").read_text(
        encoding="utf-8"
    )
    assert "foundation-model/*" not in policy
    assert "foundation-model/${var.bedrock_model_id}" in policy
    assert "guardrail/${var.bedrock_guardrail_id}" in policy
    assert '"bedrock:*"' not in policy


def test_deploy_role_is_not_administrator_access() -> None:
    policy = (
        repo_root() / "infra" / "modules" / "github_oidc" / "deploy_policy.json.tftpl"
    ).read_text(encoding="utf-8")
    trust = (repo_root() / "infra" / "modules" / "github_oidc" / "main.tf").read_text(
        encoding="utf-8"
    )
    marker = '"Sid": "DenyAdministratorAccess"'
    deny = policy.split(marker, maxsplit=1)[1].split('"Sid":', maxsplit=1)[0]
    assert "arn:aws:iam::aws:policy/AdministratorAccess" in deny
    allowed = policy.split('"Sid": "StateBucket"', maxsplit=1)[1]
    assert "AdministratorAccess" not in allowed
    assert '"Action": "*"' not in policy
    assert "lambda:CreateFunction" in policy
    assert "iam:CreateAccessKey" in policy
    assert "repo:${var.github_repository}:environment:${var.deploy_environment}" in trust
    assert "pull_request" not in trust


def test_dev_deploy_workflow_uses_oidc_on_the_trusted_path() -> None:
    workflow = (repo_root() / ".github" / "workflows" / "deploy-dev.yml").read_text(
        encoding="utf-8"
    )
    header = workflow.split("jobs:", maxsplit=1)[0]
    pull_request = (repo_root() / ".github" / "workflows" / "pull-request.yml").read_text(
        encoding="utf-8"
    )
    assert "id-token: write" in workflow
    assert "AWS_ACCESS_KEY_ID" not in workflow
    assert "pull_request" not in header
    assert "workflow_dispatch" in header
    assert "- main" in header
    assert "make aws-deploy" in workflow
    assert "make aws-smoke" in workflow
    assert "deploy-agentcore" not in workflow
    assert "make lint" in pull_request
    assert "make typecheck" in pull_request
    assert "make test" in pull_request
    assert "make eval" in pull_request
    assert "aws-deploy" not in pull_request
    assert "id-token: write" not in pull_request


def test_hosted_agent_deploy_stays_on_a_manual_workflow() -> None:
    workflow = (repo_root() / ".github" / "workflows" / "deploy-agentcore.yml").read_text(
        encoding="utf-8"
    )
    assert "workflow_dispatch" in workflow
    assert "pull_request" not in workflow
    assert "push:" not in workflow
    assert "id-token: write" in workflow
    assert "AWS_ACCESS_KEY_ID" not in workflow
    assert "make deploy-agentcore" in workflow
    assert "aws-deploy" not in workflow


def test_remote_state_is_documented_and_not_committed() -> None:
    root = repo_root()
    main = (root / "infra" / "environments" / "dev" / "main.tf").read_text(encoding="utf-8")
    example = (root / "infra" / "environments" / "dev" / "backend.hcl.example").read_text(
        encoding="utf-8"
    )
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert 'backend "s3"' in main
    assert "encrypt = true" in " ".join(main.split())
    assert "dynamodb_table" in example
    assert "backend.hcl" in gitignore
    assert not (root / "infra" / "environments" / "dev" / "backend.hcl").exists()


def test_operator_commands_fail_without_credentials(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    for command in ("plan", "smoke", "cost-check"):
        completed = _run(command, env)
        assert completed.returncode == 2, completed.stdout
        assert "did not succeed" in completed.stdout
        assert "AWS credentials are not configured" in completed.stdout
        assert "terraform" not in completed.stdout.lower()


def test_destroy_refuses_without_the_dev_flag(tmp_path: Path) -> None:
    completed = _run("destroy", _isolated_env(tmp_path))
    assert completed.returncode == 2
    assert "dev environment only" in completed.stdout
    assert "Production is out of scope" in completed.stdout
    assert "did not succeed" in completed.stdout
    assert "terraform" not in completed.stdout.lower()


def test_probe_answers_health_and_the_seeded_order() -> None:
    path = repo_root() / "infra" / "modules" / "api" / "health.py"
    health = cast(Any, _load(path, "dev_api_health"))
    status = health.handler({"rawPath": "/health"}, None)
    order = health.handler({"rawPath": "/orders/ORD-10482"}, None)
    assert status["statusCode"] == 200
    assert "healthy" in status["body"]
    assert order["statusCode"] == 200
    assert "ORD-10482" in order["body"]


def _operator() -> ModuleType:
    return _load(repo_root() / "scripts" / "dev_environment.py", "dev_environment")


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    loader = spec.loader
    assert loader is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _run(command: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    script = repo_root() / "scripts" / "dev_environment.py"
    return subprocess.run(
        [sys.executable, str(script), command],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _isolated_env(tmp_path: Path) -> dict[str, str]:
    blocked = {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
        "AWS_SHARED_CREDENTIALS_FILE",
        "AWS_CONFIG_FILE",
        "DEV_API_BASE_URL",
        "ASSISTFLOW_DESTROY_DEV",
    }
    env = {key: value for key, value in os.environ.items() if key not in blocked}
    credentials = tmp_path / "empty-credentials"
    config = tmp_path / "empty-config"
    credentials.write_text("", encoding="utf-8")
    config.write_text("", encoding="utf-8")
    env["AWS_SHARED_CREDENTIALS_FILE"] = str(credentials)
    env["AWS_CONFIG_FILE"] = str(config)
    env["AWS_EC2_METADATA_DISABLED"] = "true"
    return env


def _plan(tmp_path: Path, *, ai: bool, dev_api: bool) -> set[str]:
    document = json.loads(_plan_json(tmp_path, ai=ai, dev_api=dev_api))
    changes = document.get("resource_changes") or []
    return {
        item["type"]
        for item in changes
        if isinstance(item, dict) and item.get("change", {}).get("actions") != ["no-op"]
    }


def _tagged_resources(tmp_path: Path) -> list[dict[str, str]]:
    document = json.loads((tmp_path / "show.json").read_text(encoding="utf-8"))
    found: list[dict[str, str]] = []
    for item in document.get("resource_changes") or []:
        if not isinstance(item, dict):
            continue
        after = item.get("change", {}).get("after") or {}
        if not isinstance(after, dict):
            continue
        tags = after.get("tags_all") or after.get("tags")
        if isinstance(tags, dict) and tags:
            found.append({str(key): str(value) for key, value in tags.items()})
    return found


def _plan_json(tmp_path: Path, *, ai: bool, dev_api: bool) -> str:
    root = repo_root()
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
    package = tmp_path / "probe.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("health.py", "def handler(event, context):\n    return {}\n")
    flag = "true" if dev_api else "false"
    ai_flag = "true" if ai else "false"
    modules = root / "infra" / "modules"
    config = tmp_path / "plan"
    config.mkdir()
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
                "  default_tags {",
                "    tags = {",
                '      Project     = "assistflow"',
                '      Environment = "dev"',
                '      ManagedBy   = "terraform"',
                '      CostCenter  = "learning"',
                '      AutoCleanup = "true"',
                "    }",
                "  }",
                "}",
                'module "api" {',
                f'  source       = "{(modules / "api").as_posix()}"',
                f"  enabled      = {flag}",
                f'  package_path = "{package.as_posix()}"',
                '  package_hash = "abc"',
                "}",
                'module "metadata" {',
                f'  source  = "{(modules / "metadata").as_posix()}"',
                f"  enabled = {flag}",
                "}",
                'module "observability" {',
                f'  source  = "{(modules / "observability").as_posix()}"',
                f"  enabled = {flag}",
                "}",
                'module "async_workers" {',
                f'  source              = "{(modules / "async_workers").as_posix()}"',
                f"  enabled             = {flag}",
                f'  worker_package_path = "{package.as_posix()}"',
                '  worker_package_hash = "abc"',
                '  database_url        = "postgresql://example"',
                "}",
                'module "agentcore" {',
                f'  source  = "{(modules / "agentcore").as_posix()}"',
                f"  enabled = {ai_flag}",
                "}",
                'module "agentcore_gateway" {',
                f'  source  = "{(modules / "agentcore_gateway").as_posix()}"',
                f"  enabled = {ai_flag}",
                "}",
                'module "memory" {',
                f'  source  = "{(modules / "memory").as_posix()}"',
                f"  enabled = {ai_flag}",
                "}",
                'module "managed_rag" {',
                f'  source  = "{(modules / "managed_rag").as_posix()}"',
                f"  enabled = {ai_flag}",
                "}",
                'module "schedules" {',
                f'  source  = "{(modules / "schedules").as_posix()}"',
                f"  enabled = {ai_flag}",
                "}",
                'module "cognito" {',
                f'  source  = "{(modules / "cognito").as_posix()}"',
                f"  enabled = {ai_flag}",
                "}",
                'module "budget" {',
                f'  source  = "{(modules / "budget").as_posix()}"',
                "  enabled = false",
                "}",
                'module "github_oidc" {',
                f'  source  = "{(modules / "github_oidc").as_posix()}"',
                "  enabled = false",
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
        [
            "terraform",
            f"-chdir={config}",
            "plan",
            "-input=false",
            "-refresh=false",
            f"-out={plan}",
        ],
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
    (tmp_path / "show.json").write_text(show.stdout, encoding="utf-8")
    return show.stdout
