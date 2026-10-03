"""List or delete dev resources tagged for this project.

The default is a dry run. Pass --execute to delete. Any environment other than
dev is refused, and nothing is deleted. Only Project=assistflow and
AutoCleanup=true resources in dev are eligible.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

MISSING_CREDENTIALS = (
    "AWS credentials are not configured. "
    "Set AWS_PROFILE, or run this from the deploy workflow. "
    "This command did not succeed."
)


@dataclass(frozen=True)
class TaggedResource:
    """One ARN and the tags the cleanup filter reads."""

    arn: str
    tags: dict[str, str]


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    """Run cleanup. Dry-run is the default. A non-dev environment returns 2."""
    parser = argparse.ArgumentParser(description="Clean tagged dev resources.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="List matches and delete nothing.")
    group.add_argument("--execute", action="store_true", help="Delete matched dev resources.")
    parser.add_argument("--environment", default="", help="Environment name. Only dev is allowed.")
    args = parser.parse_args(list(argv) if argv is not None else None)
    env = os.environ if environ is None else environ
    named = args.environment.strip()
    if named == "":
        named = env.get("ASSISTFLOW_ENVIRONMENT", "dev").strip()
    environment = named or "dev"
    if environment != "dev":
        print("Cleanup refuses to run when the environment is not dev. Nothing was deleted.")
        return 2
    if not credentials_configured(env):
        print(MISSING_CREDENTIALS)
        return 2
    if shutil.which("aws") is None:
        print("The AWS CLI is not installed. Cleanup did not succeed.")
        return 2
    resources = list_tagged(env)
    if resources is None:
        return 1
    return run_cleanup(
        environment=environment,
        execute=bool(args.execute),
        resources=resources,
        delete=lambda arn: delete_resource(arn, env),
    )


def run_cleanup(
    *,
    environment: str,
    execute: bool,
    resources: Sequence[TaggedResource],
    delete: Callable[[str], None],
) -> int:
    """Print matches. Delete them only for dev when execute is true."""
    if environment != "dev":
        print("Cleanup refuses to run when the environment is not dev. Nothing was deleted.")
        return 2
    targets = [item for item in resources if selected(item)]
    for item in targets:
        print(f"{item.arn} Project=assistflow AutoCleanup=true")
    if not execute:
        print("Dry run. Nothing was deleted.")
        return 0
    for item in targets:
        delete(item.arn)
    print(f"Deleted {len(targets)} dev resources.")
    return 0


def selected(resource: TaggedResource) -> bool:
    """True for this project's auto-cleanup resources in dev."""
    tags = {key: value.strip() for key, value in resource.tags.items()}
    return (
        tags.get("Project") == "assistflow"
        and tags.get("AutoCleanup", "").lower() == "true"
        and tags.get("Environment") == "dev"
    )


def list_tagged(environ: Mapping[str, str]) -> list[TaggedResource] | None:
    """Ask the tagging API for this project's dev resources. Untagged rows are dropped."""
    region = _region(environ)
    completed = _run_aws(
        [
            "resourcegroupstaggingapi",
            "get-resources",
            "--tag-filters",
            "Key=Project,Values=assistflow",
            "Key=AutoCleanup,Values=true",
            "Key=Environment,Values=dev",
            "--output",
            "json",
        ],
        region,
        environ,
    )
    if completed is None or completed.returncode != 0:
        print("The tagging API did not return resources. Cleanup did not succeed.")
        return None
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        print("The tagging API did not return resources. Cleanup did not succeed.")
        return None
    if not isinstance(payload, dict):
        return None
    found: list[TaggedResource] = []
    rows = payload.get("ResourceTagMappingList")
    if not isinstance(rows, list):
        return found
    for row in rows:
        parsed = _resource(row)
        if parsed is not None and selected(parsed):
            found.append(parsed)
    return found


def delete_resource(arn: str, environ: Mapping[str, str]) -> None:
    """Delete one known resource type. Unknown ARNs are skipped."""
    region = _region(environ)
    if ":function:" in arn and ":lambda:" in arn:
        name = arn.rsplit(":function:", maxsplit=1)[-1]
        _run_aws(["lambda", "delete-function", "--function-name", name], region, environ)
        return
    if ":log-group:" in arn:
        name = arn.split(":log-group:", maxsplit=1)[-1]
        if name.endswith(":*"):
            name = name[:-2]
        _run_aws(["logs", "delete-log-group", "--log-group-name", name], region, environ)
        return
    print(f"Skipped {arn}. This cleanup command does not delete that resource type.")


def credentials_configured(environ: Mapping[str, str]) -> bool:
    """True when the environment names a caller. The AWS CLI is checked by the caller."""
    key = environ.get("AWS_ACCESS_KEY_ID", "").strip()
    secret = environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
    if key and secret:
        return True
    if environ.get("AWS_PROFILE", "").strip():
        return True
    if environ.get("AWS_WEB_IDENTITY_TOKEN_FILE", "").strip():
        return True
    if environ.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "").strip():
        return True
    return bool(environ.get("AWS_CONTAINER_CREDENTIALS_FULL_URI", "").strip())


def _resource(row: object) -> TaggedResource | None:
    if not isinstance(row, dict):
        return None
    arn = row.get("ResourceARN")
    if not isinstance(arn, str) or arn.strip() == "":
        return None
    tags: dict[str, str] = {}
    raw_tags = row.get("Tags")
    if isinstance(raw_tags, list):
        for item in raw_tags:
            if not isinstance(item, dict):
                continue
            key = item.get("Key")
            value = item.get("Value")
            if isinstance(key, str) and isinstance(value, str):
                tags[key] = value
    return TaggedResource(arn=arn, tags=tags)


def _region(environ: Mapping[str, str]) -> str:
    region = environ.get("AWS_REGION", "").strip() or environ.get("AWS_DEFAULT_REGION", "").strip()
    return region or "us-east-1"


def _run_aws(
    args: list[str],
    region: str,
    environ: Mapping[str, str],
) -> subprocess.CompletedProcess[str] | None:
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
        return None


if __name__ == "__main__":
    raise SystemExit(main())
