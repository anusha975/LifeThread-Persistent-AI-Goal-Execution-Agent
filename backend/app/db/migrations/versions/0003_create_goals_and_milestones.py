"""create goals and milestones

Revision ID: 0003_create_goals_and_milestones
Revises: 0002_create_users_table
Create Date: 2026-09-24 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_create_goals_and_milestones"
down_revision: str | None = "0002_create_users_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. goals table
    op.create_table(
        "goals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), server_default="ACTIVE", nullable=False),
        sa.Column("priority", sa.String(length=50), server_default="MEDIUM", nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("success_criteria", sa.JSON(), server_default="[]", nullable=False),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_goals_id"), "goals", ["id"], unique=False)
    op.create_index(op.f("ix_goals_user_id"), "goals", ["user_id"], unique=False)
    op.create_index(op.f("ix_goals_status"), "goals", ["status"], unique=False)
    op.create_index(op.f("ix_goals_priority"), "goals", ["priority"], unique=False)
    op.create_index(op.f("ix_goals_deadline"), "goals", ["deadline"], unique=False)
    op.create_index(op.f("ix_goals_created_at"), "goals", ["created_at"], unique=False)
    op.create_index(op.f("ix_goals_updated_at"), "goals", ["updated_at"], unique=False)

    # 2. goal_constraints table
    op.create_table(
        "goal_constraints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
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
    )
    op.create_index(op.f("ix_goal_constraints_id"), "goal_constraints", ["id"], unique=False)
    op.create_index(
        op.f("ix_goal_constraints_goal_id"), "goal_constraints", ["goal_id"], unique=False
    )
    op.create_index(
        op.f("ix_goal_constraints_created_at"), "goal_constraints", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_goal_constraints_updated_at"), "goal_constraints", ["updated_at"], unique=False
    )

    # 3. goal_milestones table
    op.create_table(
        "goal_milestones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), server_default="PENDING", nullable=False),
        sa.Column("order_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index(op.f("ix_goal_milestones_id"), "goal_milestones", ["id"], unique=False)
    op.create_index(
        op.f("ix_goal_milestones_goal_id"), "goal_milestones", ["goal_id"], unique=False
    )
    op.create_index(
        op.f("ix_goal_milestones_created_at"), "goal_milestones", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_goal_milestones_updated_at"), "goal_milestones", ["updated_at"], unique=False
    )


def downgrade() -> None:
    op.drop_table("goal_milestones")
    op.drop_table("goal_constraints")
    op.drop_table("goals")
