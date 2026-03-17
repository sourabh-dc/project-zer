"""
Vector Service — main entry point.

Runs as a standalone FastAPI app on port 8006.
On startup it:
  1. Initializes pgvector tables
  2. Registers product embedding handlers
  3. Starts the outbox polling loop

Exposes a governance-filtered semantic search endpoint.
"""
import asyncio
from contextlib import asynccontextmanager
from typing import List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from vector_service.core.config import SETTINGS
from vector_service.core.pg_vector import init_pgvector, similarity_search
from vector_service.core.embeddings import embed_text
from vector_service.core.outbox_consumer import register_handler, start_polling
from vector_service.core.logger import logger

from vector_service.handlers.product_embedding_handler import handle as product_handler


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Vector Service starting up...")
    init_pgvector()
    register_handler("product", product_handler)
    poll_task = asyncio.create_task(start_polling())
    logger.info("Vector outbox polling task started")
    yield
    poll_task.cancel()
    logger.info("Vector Service shut down")


app = FastAPI(
    title="ZeroQue Vector Service",
    version="0.1.0",
    description="Governance-filtered semantic search — pgvector projection layer",
    lifespan=lifespan,
)


# ── Health ──────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "service": "vector_service"}


# ── Semantic Search ─────────────────────────────────────────────────
class SearchRequest(BaseModel):
    query: str
    tenant_id: str
    user_id: Optional[str] = None
    top_k: int = 20
    skip_governance: bool = False


@app.post("/vector/search")
async def api_search(req: SearchRequest):
    """Governance-filtered product search.

    Flow:
      1. Embed the query text
      2. If user_id is provided, fetch their Approved Universe
         from the graph service (unless skip_governance=True)
      3. Run cosine similarity search restricted to approved products
    """
    query_embedding = embed_text(req.query)

    approved_ids = None
    if req.user_id and not req.skip_governance:
        approved_ids = await _fetch_approved_ids(req.tenant_id, req.user_id)

    results = similarity_search(
        tenant_id=req.tenant_id,
        query_embedding=query_embedding,
        approved_product_ids=approved_ids,
        top_k=req.top_k,
    )

    return {
        "query": req.query,
        "results": results,
        "total": len(results),
        "governance_applied": approved_ids is not None,
    }


async def _fetch_approved_ids(tenant_id: str, user_id: str) -> Optional[List[str]]:
    """Call the graph service to get the user's approved product IDs."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{SETTINGS.GRAPH_SERVICE_URL}/graph/approved-products/{user_id}",
                params={"tenant_id": tenant_id},
            )
            if resp.status_code == 200:
                data = resp.json()
                ids = data.get("approved_product_ids", [])
                if ids == "__all__":
                    return ["__all__"]
                return ids
            else:
                logger.warning(f"Graph service returned {resp.status_code}")
                return []
    except Exception as exc:
        logger.error(f"Failed to fetch approved IDs from graph service: {exc}")
        return []
