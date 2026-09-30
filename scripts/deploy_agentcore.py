"""Package the hosted agent and apply it only when the operator asks.

Revalidate current AgentCore runtime pricing before apply. This command is not
part of pull-request checks.
"""

import argparse
import base64
import hashlib
import os
import subprocess
import sys
from pathlib import Path

from assistflow_runtime.packaging import package_sources, package_tool_target

_TRUE = {"1", "true", "yes", "on"}


def main(argv: list[str] | None = None) -> int:
    """Return 0 after an explicit apply. Return 2 when the gates are closed."""
    parser = argparse.ArgumentParser(description="Package and deploy the hosted agent runtime.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the dev stack with the hosted runtime enabled.",
    )
    args = parser.parse_args(argv)
    print("Revalidate current AgentCore runtime pricing before apply.")
    enabled = os.environ.get("AGENTCORE_ENABLED", "").strip().lower() in _TRUE
    if not enabled or not args.apply:
        print("Hosted runtime deploy was not run.")
        return 2
    image = os.environ.get("AGENTCORE_CONTAINER_IMAGE_URI", "").strip()
    if image == "":
        print("Set AGENTCORE_CONTAINER_IMAGE_URI before apply.")
        return 2
    root = Path(__file__).resolve().parents[1]
    archive = package_sources(root, root / "dist" / "agentcore-runtime.zip")
    tool_archive = package_tool_target(root, root / "dist" / "read-tools.zip")
    print(f"Packaged {archive}")
    print(f"Packaged {tool_archive}")
    command = [
        "terraform",
        "-chdir=infra/environments/dev",
        "apply",
        "-input=false",
        "-var",
        "enable_agentcore=true",
        "-var",
        f"agentcore_container_image_uri={image}",
        "-var",
        f"agentcore_tool_package_path={tool_archive}",
        "-var",
        f"agentcore_tool_package_hash={_sha256_base64(tool_archive)}",
    ]
    command.extend(_secret_var("agentcore_gateway_inbound_token", "GATEWAY_INBOUND_TOKEN"))
    command.extend(_secret_var("agentcore_actor_context_secret", "AGENTCORE_ACTOR_CONTEXT_SECRET"))
    command.extend(_secret_var("agentcore_tool_database_url", "DATABASE_URL"))
    subprocess.run(command, cwd=root, check=True)
    return 0


def _sha256_base64(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).digest()
    return base64.b64encode(digest).decode("ascii")


def _secret_var(name: str, env_name: str) -> list[str]:
    value = os.environ.get(env_name, "").strip()
    if value == "":
        return []
    return ["-var", f"{name}={value}"]


if __name__ == "__main__":
    sys.exit(main())
