"""initial baseline

Revision ID: 0001_initial_baseline
Revises: None
Create Date: 2026-09-24 12:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001_initial_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Baseline migration establishing schema version tracking.
    # Concrete domain tables (Goal, Task, Memory) are added in subsequent modules.
    pass


def downgrade() -> None:
    pass
