"""Empty baseline.

Later domain tables are added in their own revisions.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-23
"""

from collections.abc import Sequence

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
