"""Package the hosted agent and apply it only when the operator asks.

Revalidate current AgentCore runtime pricing before apply. This command is not
part of pull-request checks.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from assistflow_runtime.packaging import package_sources

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
    print(f"Packaged {archive}")
    subprocess.run(
        [
            "terraform",
            "-chdir=infra/environments/dev",
            "apply",
            "-input=false",
            "-var",
            "enable_agentcore=true",
            "-var",
            f"agentcore_container_image_uri={image}",
        ],
        cwd=root,
        check=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
