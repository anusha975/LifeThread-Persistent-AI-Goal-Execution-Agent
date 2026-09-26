"""create plans and plan items

Revision ID: 0005_create_plans_and_plan_items
Revises: 0004_create_tasks_and_dependencies
Create Date: 2026-09-24 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_create_plans_and_plan_items"
down_revision: str | None = "0004_create_tasks_and_dependencies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. plans table
    op.create_table(
        "plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="ACTIVE", nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("is_feasible", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("deadline_risk", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("risk_level", sa.String(length=20), server_default="LOW", nullable=False),
        sa.Column("schedule_utilization", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("total_duration_minutes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("goal_id", "version", name="uq_plan_goal_version"),
    )
    op.create_index(op.f("ix_plans_id"), "plans", ["id"], unique=False)
    op.create_index(op.f("ix_plans_goal_id"), "plans", ["goal_id"], unique=False)
    op.create_index(op.f("ix_plans_version"), "plans", ["version"], unique=False)
    op.create_index(op.f("ix_plans_status"), "plans", ["status"], unique=False)
    op.create_index(op.f("ix_plans_created_at"), "plans", ["created_at"], unique=False)
    op.create_index(op.f("ix_plans_updated_at"), "plans", ["updated_at"], unique=False)

    # 2. plan_items table
    op.create_table(
        "plan_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("priority", sa.String(length=50), server_default="MEDIUM", nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_plan_items_id"), "plan_items", ["id"], unique=False)
    op.create_index(op.f("ix_plan_items_plan_id"), "plan_items", ["plan_id"], unique=False)
    op.create_index(op.f("ix_plan_items_task_id"), "plan_items", ["task_id"], unique=False)
    op.create_index(
        op.f("ix_plan_items_scheduled_start"),
        "plan_items",
        ["scheduled_start"],
        unique=False,
    )
    op.create_index(
        op.f("ix_plan_items_created_at"),
        "plan_items",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_plan_items_updated_at"),
        "plan_items",
        ["updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("plan_items")
    op.drop_table("plans")
