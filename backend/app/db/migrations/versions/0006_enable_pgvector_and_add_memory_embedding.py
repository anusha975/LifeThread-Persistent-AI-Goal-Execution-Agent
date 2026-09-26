"""enable pgvector and add memory embedding

Revision ID: 0006_enable_pgvector_and_add_memory_embedding
Revises: 0005_create_plans_and_plan_items
Create Date: 2026-09-24 22:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "0006_enable_pgvector_and_add_memory_embedding"
down_revision: str | None = "0005_create_plans_and_plan_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    # 1. Enable pgvector extension in PostgreSQL
    if dialect_name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Add embedding column to memories table
    op.add_column("memories", sa.Column("embedding", Vector(1536), nullable=True))

    # 3. Create vector index for cosine similarity in PostgreSQL
    if dialect_name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_memories_embedding ON memories USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_memories_embedding")

    op.drop_column("memories", "embedding")
