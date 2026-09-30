"""Package the agent sources for an operator deploy. This module does not call AWS."""

import zipfile
from pathlib import Path

_ROOTS = (
    "agent/runtime/src",
    "agent/tools/src",
    "packages/contracts/src",
    "packages/test-fixtures/src",
    "apps/api/src/assistflow_api",
    "infra/agentcore",
)


def package_sources(root: Path, destination: Path) -> Path:
    """Write a zip of the agent sources."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in _ROOTS:
            base = root / relative
            if not base.exists():
                continue
            files = (
                [base]
                if base.is_file()
                else sorted(path for path in base.rglob("*") if path.is_file())
            )
            for path in files:
                if _skip(path):
                    continue
                archive.write(path, path.relative_to(root).as_posix())
    return destination


def _skip(path: Path) -> bool:
    return "__pycache__" in path.parts or path.suffix == ".pyc"
