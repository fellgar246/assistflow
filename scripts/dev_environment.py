"""Operate the dev environment: state, plan, deploy, smoke, cost, and destroy.

Destroy deletes the dev stack only. Production is out of scope.
Revalidate current prices before apply. This file does not embed a provider price.
"""

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

MISSING_CREDENTIALS = (
    "AWS credentials are not configured. "
    "Set AWS_PROFILE, or run this from the deploy workflow. "
    "This command did not succeed."
)
_SECRET_MARKERS = ("AKIA", "ASIA", "aws_secret_access_key", "SessionToken")
_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class _HttpResult:
    status: int
    body: str


def main(argv: list[str] | None = None) -> int:
    """Run one dev-environment command. Return the process exit code."""
    parser = argparse.ArgumentParser(description="Operate the dev environment.")
    parser.add_argument(
        "command",
        choices=["bootstrap", "plan", "deploy", "smoke", "cost-check", "destroy"],
    )
    args = parser.parse_args(argv)
    commands = {
        "bootstrap": bootstrap,
        "plan": plan,
        "deploy": deploy,
        "smoke": smoke,
        "cost-check": cost_check,
        "destroy": destroy,
    }
    return commands[args.command](os.environ)


def bootstrap(environ: Mapping[str, str]) -> int:
    """Create the state bucket and lock table, then write backend.hcl."""
    if not credentials_configured(environ):
        print(MISSING_CREDENTIALS)
        return 2
    if shutil.which("aws") is None:
        print("The AWS CLI is not installed. Bootstrap did not succeed.")
        return 2
    region = _region(environ)
    account = _account_id(region, environ)
    if account is None:
        print("AWS credentials were rejected. Bootstrap did not succeed.")
        return 2
    bucket = f"assistflow-dev-tfstate-{account}"
    table = "assistflow-dev-tf-lock"
    if not _ensure_bucket(bucket, region, environ):
        return 1
    if not _ensure_lock_table(table, region, environ):
        return 1
    backend = _root() / "infra" / "environments" / "dev" / "backend.hcl"
    backend.write_text(
        "\n".join(
            [
                f'bucket         = "{bucket}"',
                f'region         = "{region}"',
                f'dynamodb_table = "{table}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"Remote state bucket {bucket} and lock table {table} are ready.")
    print("backend.hcl was written for the dev environment and is not committed.")
    return 0


def plan(environ: Mapping[str, str]) -> int:
    """Plan the dev stack. Do not apply it."""
    ready = _ready(environ)
    if ready is None:
        return 2
    print("Planning the dev environment.")
    return _terraform(ready[0], ready[1], "plan", environ)


def deploy(environ: Mapping[str, str]) -> int:
    """Apply the dev stack."""
    ready = _ready(environ)
    if ready is None:
        return 2
    print("Applying the dev environment.")
    return _terraform(ready[0], ready[1], "apply", environ)


def destroy(environ: Mapping[str, str]) -> int:
    """Destroy the dev stack. Production is out of scope."""
    print("Destroy deletes the dev environment only. Production is out of scope.")
    if environ.get("ASSISTFLOW_DESTROY_DEV", "").strip().lower() not in _TRUE:
        print("Set ASSISTFLOW_DESTROY_DEV=true to delete the dev stack. Destroy did not succeed.")
        return 2
    ready = _ready(environ)
    if ready is None:
        return 2
    code = _terraform(ready[0], ready[1], "destroy", environ)
    if code == 0:
        print("Run make aws-plan to confirm this stack has no remaining resources.")
    return code


def smoke(environ: Mapping[str, str]) -> int:
    """Call health and the seeded order read. Fail when credentials are absent."""
    if not credentials_configured(environ):
        print(MISSING_CREDENTIALS)
        return 2
    base = environ.get("DEV_API_BASE_URL", "").strip().rstrip("/")
    if base == "":
        print("Set DEV_API_BASE_URL to the deployed dev API. Smoke did not succeed.")
        return 2
    health = _get(f"{base}/health")
    if health is None or health.status != 200 or "healthy" not in health.body:
        status = "no response" if health is None else str(health.status)
        print(f"Dev API health did not return success (HTTP {status}).")
        return 1
    print("Dev API health returned success.")
    order = _get(f"{base}/orders/ORD-10482")
    if order is None or order.status != 200 or "ORD-10482" not in order.body:
        status = "no response" if order is None else str(order.status)
        print(f"Dev API read did not return the seeded order (HTTP {status}).")
        return 1
    print("Dev API read returned the seeded order.")
    return 0


def cost_check(environ: Mapping[str, str]) -> int:
    """Confirm the live monthly budget is $5 with alerts at $1, $3, and $5."""
    if not credentials_configured(environ):
        print(MISSING_CREDENTIALS)
        return 2
    if not budget_configuration_ok(_root()):
        print(
            "The budget configuration does not include a $5 limit "
            "and thresholds at $1, $3, and $5. Cost check did not succeed."
        )
        return 1
    if shutil.which("aws") is None:
        print("The AWS CLI is not installed. Cost check did not succeed.")
        return 2
    region = _region(environ)
    account = _account_id(region, environ)
    if account is None:
        print("AWS credentials were rejected. Cost check did not succeed.")
        return 2
    budget = _aws_json(
        [
            "budgets",
            "describe-budget",
            "--account-id",
            account,
            "--budget-name",
            "assistflow-monthly",
        ],
        region,
        environ,
    )
    notifications = _aws_json(
        [
            "budgets",
            "describe-notifications-for-budget",
            "--account-id",
            account,
            "--budget-name",
            "assistflow-monthly",
        ],
        region,
        environ,
    )
    if budget is None or notifications is None or not _budget_matches(budget, notifications):
        print(
            "The monthly budget assistflow-monthly is missing or does not match. "
            "Cost check did not succeed."
        )
        return 1
    print("Monthly budget assistflow-monthly is $5 with alert thresholds at $1, $3, and $5.")
    configuration = _aws_json(
        [
            "lambda",
            "get-function-configuration",
            "--function-name",
            API_FUNCTION_NAME,
        ],
        region,
        environ,
    )
    if configuration is None or not kill_switches_off(configuration):
        print(
            "The deployed API task is missing or does not keep the kill switches off. "
            "Cost check did not succeed."
        )
        return 1
    print("The deployed API task keeps hosted features and the assistant off.")
    return 0


API_FUNCTION_NAME = "assistflow-dev-api"
KILL_SWITCH_ENV = {
    "LOCAL_ONLY_MODE": "true",
    "AWS_ENABLED": "false",
    "AGENTCORE_ENABLED": "false",
    "BEDROCK_ENABLED": "false",
    "MANAGED_RAG_ENABLED": "false",
    "LONG_TERM_MEMORY_ENABLED": "false",
    "GUARDRAILS_ENABLED": "false",
    "AI_ENABLED": "false",
}


def kill_switches_off(configuration: Mapping[str, object]) -> bool:
    """True when the deployed task keeps discretionary AI and AWS features off."""
    environment = configuration.get("Environment")
    if not isinstance(environment, dict):
        return False
    variables = environment.get("Variables")
    if not isinstance(variables, dict):
        return False
    for key, expected in KILL_SWITCH_ENV.items():
        value = variables.get(key)
        if not isinstance(value, str) or value.strip().lower() != expected:
            return False
    return True


def budget_configuration_ok(root: Path) -> bool:
    """True when the budget module records $5 and absolute thresholds at $1, $3, and $5."""
    module = (root / "infra" / "modules" / "budget" / "main.tf").read_text(encoding="utf-8")
    variables = (root / "infra" / "modules" / "budget" / "variables.tf").read_text(encoding="utf-8")
    return (
        "monthly_alert_thresholds_usd = [1, 3, 5]" in module
        and 'threshold_type            = "ABSOLUTE_VALUE"' in module
        and 'default     = "5"' in variables
    )


def package_api_probe(root: Path, destination: Path) -> str:
    """Zip the dev API probe and return its base64 SHA-256."""
    source = root / "infra" / "modules" / "api" / "health.py"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w") as archive:
        archive.write(source, arcname="health.py")
    digest = hashlib.sha256(destination.read_bytes()).digest()
    return base64.b64encode(digest).decode("ascii")


def credentials_configured(environ: Mapping[str, str]) -> bool:
    """True when the environment or the AWS CLI can identify a caller."""
    if _explicit_credentials(environ):
        return True
    if shutil.which("aws") is None:
        return False
    region = _region(environ)
    account = _account_id(region, environ)
    return account is not None


def _explicit_credentials(environ: Mapping[str, str]) -> bool:
    key = environ.get("AWS_ACCESS_KEY_ID", "").strip()
    secret = environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
    if key != "" and secret != "":
        return True
    if environ.get("AWS_PROFILE", "").strip() != "":
        return True
    if environ.get("AWS_WEB_IDENTITY_TOKEN_FILE", "").strip() != "":
        return True
    if environ.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "").strip() != "":
        return True
    return environ.get("AWS_CONTAINER_CREDENTIALS_FULL_URI", "").strip() != ""


def _ready(environ: Mapping[str, str]) -> tuple[Path, Path] | None:
    if not credentials_configured(environ):
        print(MISSING_CREDENTIALS)
        return None
    root = _root()
    backend = root / "infra" / "environments" / "dev" / "backend.hcl"
    if not backend.is_file():
        print("Remote state is not configured. Run make aws-bootstrap once, then retry.")
        print("This command did not succeed.")
        return None
    if shutil.which("terraform") is None:
        print("Terraform is not installed. This command did not succeed.")
        return None
    return root, backend


def _terraform(root: Path, backend: Path, action: str, environ: Mapping[str, str]) -> int:
    dev = root / "infra" / "environments" / "dev"
    child = dict(environ)
    child["TF_IN_AUTOMATION"] = "true"
    child.pop("TF_LOG", None)
    init = subprocess.run(
        [
            "terraform",
            f"-chdir={dev}",
            "init",
            "-input=false",
            f"-backend-config={backend}",
        ],
        check=False,
        cwd=root,
        env=child,
    )
    if init.returncode != 0:
        return init.returncode
    archive = root / "dist" / "dev-api-probe.zip"
    digest = package_api_probe(root, archive)
    command = [
        "terraform",
        f"-chdir={dev}",
        action,
        "-input=false",
        "-lock-timeout=120s",
        "-var",
        f"api_package_path={archive}",
        "-var",
        f"api_package_hash={digest}",
    ]
    if action in {"apply", "destroy"}:
        command.append("-auto-approve")
    completed = subprocess.run(command, check=False, cwd=root, env=child)
    return completed.returncode


def _ensure_bucket(bucket: str, region: str, environ: Mapping[str, str]) -> bool:
    head = _run_aws(["s3api", "head-bucket", "--bucket", bucket], region, environ)
    if head.returncode != 0:
        create = ["s3api", "create-bucket", "--bucket", bucket]
        if region != "us-east-1":
            create.extend(["--create-bucket-configuration", f"LocationConstraint={region}"])
        created = _run_aws(create, region, environ)
        if created.returncode != 0:
            print(_safe_error(created.stderr))
            return False
    steps = [
        [
            "s3api",
            "put-bucket-versioning",
            "--bucket",
            bucket,
            "--versioning-configuration",
            "Status=Enabled",
        ],
        [
            "s3api",
            "put-bucket-encryption",
            "--bucket",
            bucket,
            "--server-side-encryption-configuration",
            '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}',
        ],
        [
            "s3api",
            "put-public-access-block",
            "--bucket",
            bucket,
            "--public-access-block-configuration",
            "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true",
        ],
        [
            "s3api",
            "put-bucket-tagging",
            "--bucket",
            bucket,
            "--tagging",
            (
                '{"TagSet":['
                '{"Key":"Project","Value":"assistflow"},'
                '{"Key":"Environment","Value":"dev"},'
                '{"Key":"ManagedBy","Value":"terraform"},'
                '{"Key":"CostCenter","Value":"learning"},'
                '{"Key":"AutoCleanup","Value":"true"}'
                "]}"
            ),
        ],
    ]
    for step in steps:
        completed = _run_aws(step, region, environ)
        if completed.returncode != 0:
            print(_safe_error(completed.stderr))
            return False
    return True


def _ensure_lock_table(table: str, region: str, environ: Mapping[str, str]) -> bool:
    described = _run_aws(["dynamodb", "describe-table", "--table-name", table], region, environ)
    if described.returncode == 0:
        return True
    created = _run_aws(
        [
            "dynamodb",
            "create-table",
            "--table-name",
            table,
            "--attribute-definitions",
            "AttributeName=LockID,AttributeType=S",
            "--key-schema",
            "AttributeName=LockID,KeyType=HASH",
            "--billing-mode",
            "PAY_PER_REQUEST",
            "--tags",
            "Key=Project,Value=assistflow",
            "Key=Environment,Value=dev",
            "Key=ManagedBy,Value=terraform",
            "Key=CostCenter,Value=learning",
            "Key=AutoCleanup,Value=true",
        ],
        region,
        environ,
    )
    if created.returncode != 0:
        print(_safe_error(created.stderr))
        return False
    return True


def _budget_matches(budget: dict[str, object], notifications: dict[str, object]) -> bool:
    body = budget.get("Budget")
    if not isinstance(body, dict):
        return False
    limit = body.get("BudgetLimit")
    if not isinstance(limit, dict):
        return False
    amount = limit.get("Amount")
    if isinstance(amount, str):
        try:
            dollars = float(amount)
        except ValueError:
            return False
    elif isinstance(amount, int | float):
        dollars = float(amount)
    else:
        return False
    if dollars != 5:
        return False
    return _thresholds(notifications) >= {1, 3, 5}


def _thresholds(payload: dict[str, object]) -> set[int]:
    found: set[int] = set()
    items = payload.get("Notifications")
    if not isinstance(items, list):
        return found
    for item in items:
        if not isinstance(item, dict):
            continue
        note = item.get("Notification", item)
        if not isinstance(note, dict):
            continue
        if note.get("ThresholdType") != "ABSOLUTE_VALUE":
            continue
        threshold = note.get("Threshold")
        if isinstance(threshold, int | float) and float(threshold).is_integer():
            found.add(int(threshold))
    return found


def _account_id(region: str, environ: Mapping[str, str]) -> str | None:
    completed = _run_aws(
        ["sts", "get-caller-identity", "--query", "Account", "--output", "text"],
        region,
        environ,
    )
    account = completed.stdout.strip()
    if completed.returncode != 0 or not account.isdigit():
        return None
    return account


def _aws_json(args: list[str], region: str, environ: Mapping[str, str]) -> dict[str, object] | None:
    completed = _run_aws([*args, "--output", "json"], region, environ)
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _run_aws(
    args: list[str],
    region: str,
    environ: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    child = dict(environ)
    child["AWS_REGION"] = region
    child["AWS_DEFAULT_REGION"] = region
    child["AWS_EC2_METADATA_DISABLED"] = "true"
    command = ["aws", *args, "--region", region]
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=child,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(command, 1, "", "")


def _get(url: str) -> _HttpResult | None:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
            status = getattr(response, "status", 200)
            return _HttpResult(status=int(status), body=raw.decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return _HttpResult(status=exc.code, body=raw.decode("utf-8", errors="replace"))
    except urllib.error.URLError:
        return None


def _region(environ: Mapping[str, str]) -> str:
    region = environ.get("AWS_REGION", "").strip() or environ.get("AWS_DEFAULT_REGION", "").strip()
    return region or "us-east-1"


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _safe_error(text: str) -> str:
    if any(marker in text for marker in _SECRET_MARKERS):
        return "AWS request failed. Details were omitted."
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else "AWS request failed."


if __name__ == "__main__":
    raise SystemExit(main())
