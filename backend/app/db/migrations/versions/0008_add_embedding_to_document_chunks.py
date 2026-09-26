"""add embedding to document chunks

Revision ID: 0008_add_embedding_to_document_chunks
Revises: 0007_create_documents_and_document_chunks
Create Date: 2026-09-24 23:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "0008_add_embedding_to_document_chunks"
down_revision: str | None = "0007_create_documents_and_document_chunks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    # 1. Add vector embedding column to document_chunks
    op.add_column("document_chunks", sa.Column("embedding", Vector(1536), nullable=True))

    # 2. In PostgreSQL, create HNSW cosine similarity index
    if dialect_name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding ON document_chunks USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding")

    op.drop_column("document_chunks", "embedding")
