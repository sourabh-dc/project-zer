"""
Vector Service — pgvector storage layer.

Uses PostgreSQL with the pgvector extension for storing and
querying product/document embeddings. All queries respect
governance filters (approved product IDs from the graph).
"""
import json
import uuid
from typing import List, Dict, Any, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from data_intelligence_service.core.config import SETTINGS
from data_intelligence_service.core.logger import logger

_engine = None
_Session = None


def _get_session():
    global _engine, _Session
    if _engine is None:
        _engine = create_engine(SETTINGS.POSTGRES_URL, pool_pre_ping=True)
        _Session = sessionmaker(bind=_engine)
    return _Session()


def init_pgvector():
    """Create the pgvector extension and embeddings table if they don't exist."""
    session = _get_session()
    try:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        session.execute(text(f"""
            CREATE TABLE IF NOT EXISTS product_embeddings (
                id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id     UUID NOT NULL,
                product_id    UUID NOT NULL,
                chunk_index   INTEGER NOT NULL DEFAULT 0,
                chunk_text    TEXT NOT NULL,
                embedding     vector({SETTINGS.EMBEDDING_DIMENSIONS}),
                metadata      JSONB DEFAULT '{{}}'::jsonb,
                created_at    TIMESTAMPTZ DEFAULT NOW(),
                updated_at    TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (product_id, chunk_index)
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_product_embeddings_tenant
            ON product_embeddings (tenant_id)
        """))
        session.execute(text(f"""
            CREATE INDEX IF NOT EXISTS idx_product_embeddings_vector
            ON product_embeddings
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        """))
        session.commit()
        logger.info("pgvector extension + product_embeddings table initialized")
    except Exception as exc:
        session.rollback()
        logger.error(f"pgvector init error: {exc}")
    finally:
        session.close()


def upsert_product_embedding(
    tenant_id: str,
    product_id: str,
    chunk_text: str,
    embedding: List[float],
    chunk_index: int = 0,
    metadata: Optional[Dict] = None,
):
    """Insert or update a product embedding chunk."""
    session = _get_session()
    try:
        vec_str = "[" + ",".join(str(f) for f in embedding) + "]"
        session.execute(
            text("""
                INSERT INTO product_embeddings (id, tenant_id, product_id, chunk_index, chunk_text, embedding, metadata, updated_at)
                VALUES (:id, :tid, :pid, :ci, :ct, CAST(:emb AS vector), CAST(:meta AS jsonb), NOW())
                ON CONFLICT (product_id, chunk_index)
                DO UPDATE SET chunk_text = EXCLUDED.chunk_text,
                              embedding  = EXCLUDED.embedding,
                              metadata   = EXCLUDED.metadata,
                              updated_at = NOW()
            """),
            {
                "id": uuid.uuid4(),
                "tid": tenant_id,
                "pid": product_id,
                "ci": chunk_index,
                "ct": chunk_text,
                "emb": vec_str,
                "meta": json.dumps(metadata or {}),
            },
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.error(f"Upsert embedding error for product {product_id}: {exc}")
    finally:
        session.close()


def delete_product_embeddings(product_id: str):
    """Remove all embedding chunks for a deleted product."""
    session = _get_session()
    try:
        session.execute(
            text("DELETE FROM product_embeddings WHERE product_id = :pid"),
            {"pid": product_id},
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.error(f"Delete embeddings error for product {product_id}: {exc}")
    finally:
        session.close()


def similarity_search(
    tenant_id: str,
    query_embedding: List[float],
    approved_product_ids: Optional[List[str]] = None,
    top_k: int = 20,
) -> List[Dict[str, Any]]:
    """Governance-filtered vector similarity search.

    If approved_product_ids is provided, results are restricted to
    only those products (Approved Universe enforcement).
    If it equals ['__all__'], no product filter is applied (admin bypass).
    """
    session = _get_session()
    try:
        vec_str = "[" + ",".join(str(f) for f in query_embedding) + "]"

        filter_clause = ""
        params: Dict[str, Any] = {
            "tid": tenant_id,
            "emb": vec_str,
            "k": top_k,
        }

        if approved_product_ids is not None and approved_product_ids != ["__all__"]:
            if not approved_product_ids:
                return []
            filter_clause = "AND pe.product_id = ANY(:pids)"
            params["pids"] = approved_product_ids

        result = session.execute(
            text(f"""
                SELECT pe.product_id,
                       pe.chunk_index,
                       pe.chunk_text,
                       pe.metadata,
                       1 - (pe.embedding <=> CAST(:emb AS vector)) AS similarity
                FROM   product_embeddings pe
                WHERE  pe.tenant_id = :tid
                  {filter_clause}
                ORDER  BY pe.embedding <=> CAST(:emb AS vector)
                LIMIT  :k
            """),
            params,
        )

        hits = []
        for row in result:
            hits.append({
                "product_id": str(row.product_id),
                "chunk_index": row.chunk_index,
                "chunk_text": row.chunk_text,
                "metadata": row.metadata if isinstance(row.metadata, dict) else json.loads(row.metadata or "{}"),
                "similarity": float(row.similarity),
            })
        return hits
    except Exception as exc:
        logger.error(f"Similarity search error: {exc}")
        return []
    finally:
        session.close()
