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

_TOOL_PACKAGES = (
    ("agent/tools/src/assistflow_tools", "assistflow_tools"),
    ("packages/contracts/src/assistflow_contracts", "assistflow_contracts"),
    ("services/customers/src/assistflow_customers", "assistflow_customers"),
    ("services/orders/src/assistflow_orders", "assistflow_orders"),
    ("services/shipping/src/assistflow_shipping", "assistflow_shipping"),
    ("services/tickets/src/assistflow_tickets", "assistflow_tickets"),
    ("services/knowledge/src/assistflow_knowledge", "assistflow_knowledge"),
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


def package_tool_target(root: Path, destination: Path) -> Path:
    """Write a zip of the read-tool function sources.

    The archive contains the first-party packages the handler imports. The
    operator still supplies third-party dependencies and the database URL.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative, prefix in _TOOL_PACKAGES:
            base = root / relative
            if not base.exists():
                continue
            for path in sorted(item for item in base.rglob("*") if item.is_file()):
                if _skip(path):
                    continue
                archived = Path(prefix) / path.relative_to(base)
                archive.write(path, archived.as_posix())
    return destination


def _skip(path: Path) -> bool:
    return "__pycache__" in path.parts or path.suffix == ".pyc"
