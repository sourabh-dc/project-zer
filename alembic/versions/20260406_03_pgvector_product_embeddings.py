"""Move pgvector extension + product_embeddings DDL from runtime into Alembic.

Previously vector_service created these objects at startup via init_pgvector().
This revision makes the schema declarative and idempotent.

Embedding dimensions default to 1536 (text-embedding-3-small / ada-002).
If you change EMBEDDING_DIMENSIONS you must create a new migration to rebuild
the table and index — vector column widths are immutable in pgvector.

Revision ID: 20260406_03
Revises: 20260406_02
Create Date: 2026-04-06
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "20260406_03"
down_revision: Union[str, None] = "20260406_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIMENSIONS = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS product_embeddings (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID        NOT NULL,
            product_id  UUID        NOT NULL,
            chunk_index INTEGER     NOT NULL DEFAULT 0,
            chunk_text  TEXT        NOT NULL,
            embedding   vector({EMBEDDING_DIMENSIONS}),
            metadata    JSONB       DEFAULT '{{}}'::jsonb,
            created_at  TIMESTAMPTZ DEFAULT NOW(),
            updated_at  TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (product_id, chunk_index)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_product_embeddings_tenant
        ON product_embeddings (tenant_id)
    """)

    # ivfflat index — requires the extension to be loaded first.
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_product_embeddings_vector
        ON product_embeddings
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_product_embeddings_vector")
    op.execute("DROP INDEX IF EXISTS idx_product_embeddings_tenant")
    op.execute("DROP TABLE IF EXISTS product_embeddings")
    # Do NOT drop the vector extension — other tables may use it.
