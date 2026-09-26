"""create tasks and dependencies

Revision ID: 0004_create_tasks_and_dependencies
Revises: 0003_create_goals_and_milestones
Create Date: 2026-09-24 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_create_tasks_and_dependencies"
down_revision: str | None = "0003_create_goals_and_milestones"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. goal_decompositions table
    op.create_table(
        "goal_decompositions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("task_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "critical_path_duration_minutes", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("metadata", sa.JSON(), server_default="{}", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("goal_id", "version", name="uq_goal_decomposition_version"),
    )
    op.create_index(op.f("ix_goal_decompositions_id"), "goal_decompositions", ["id"], unique=False)
    op.create_index(
        op.f("ix_goal_decompositions_goal_id"),
        "goal_decompositions",
        ["goal_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_goal_decompositions_created_at"),
        "goal_decompositions",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_goal_decompositions_updated_at"),
        "goal_decompositions",
        ["updated_at"],
        unique=False,
    )

    # 2. tasks table
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("milestone_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), server_default="PENDING", nullable=False),
        sa.Column("priority", sa.String(length=50), server_default="MEDIUM", nullable=False),
        sa.Column("estimated_minutes", sa.Integer(), server_default="60", nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["milestone_id"], ["goal_milestones.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tasks_id"), "tasks", ["id"], unique=False)
    op.create_index(op.f("ix_tasks_goal_id"), "tasks", ["goal_id"], unique=False)
    op.create_index(op.f("ix_tasks_milestone_id"), "tasks", ["milestone_id"], unique=False)
    op.create_index(op.f("ix_tasks_version"), "tasks", ["version"], unique=False)
    op.create_index(op.f("ix_tasks_status"), "tasks", ["status"], unique=False)
    op.create_index(op.f("ix_tasks_created_at"), "tasks", ["created_at"], unique=False)
    op.create_index(op.f("ix_tasks_updated_at"), "tasks", ["updated_at"], unique=False)

    # 3. task_dependencies table
    op.create_table(
        "task_dependencies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("depends_on_task_id", sa.Uuid(), nullable=False),
        sa.Column("dependency_type", sa.String(length=50), server_default="BLOCKS", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["depends_on_task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "depends_on_task_id", name="uq_task_dependency"),
        sa.CheckConstraint("task_id != depends_on_task_id", name="ck_task_not_self_dependent"),
    )
    op.create_index(op.f("ix_task_dependencies_id"), "task_dependencies", ["id"], unique=False)
    op.create_index(
        op.f("ix_task_dependencies_task_id"),
        "task_dependencies",
        ["task_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_dependencies_depends_on_task_id"),
        "task_dependencies",
        ["depends_on_task_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_dependencies_created_at"),
        "task_dependencies",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_dependencies_updated_at"),
        "task_dependencies",
        ["updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("task_dependencies")
    op.drop_table("tasks")
    op.drop_table("goal_decompositions")
