from contextlib import asynccontextmanager
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from data_intelligence_service.core.config import SETTINGS
from data_intelligence_service.core.logger import logger
from data_intelligence_service.core.neo4j_client import init_constraints, close_driver
from data_intelligence_service.vector.pg_vector import init_pgvector, similarity_search
from data_intelligence_service.vector.embeddings import embed_text

# Graph queries
from data_intelligence_service.graph.queries.approved_universe import (
    get_approved_product_ids, get_approved_product_ids_for_org_unit,
)
from data_intelligence_service.graph.queries.user_governance import get_user_context, get_user_hierarchy
from data_intelligence_service.graph.queries.store_products import (
    get_products_for_store, get_stores_for_product, get_tenant_topology,
)

# Intelligence router
from data_intelligence_service.intelligence.agents.query_router import route_and_execute


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Data Intelligence Service starting up...")
    
    # Graph init
    init_constraints()
    
    # Vector init
    init_pgvector()

    # Intelligence init
    if not SETTINGS.AZURE_OPENAI_API_KEY:
        logger.warning("AZURE_OPENAI_API_KEY not set — LLM queries will fail")

    yield

    close_driver()
    logger.info("Data Intelligence Service shut down")


app = FastAPI(
    title="ZeroQue Data Intelligence Service",
    version="0.1.0",
    description="Unified Graph, Vector, and Intelligence Service",
    lifespan=lifespan,
)


# ── Health ──────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok", 
        "service": "data_intelligence_service",
        "llm_configured": bool(SETTINGS.AZURE_OPENAI_API_KEY)
    }


# ── Graph API ───────────────────────────────────────────────────────
@app.get("/graph/approved-products/{user_id}")
async def api_approved_products(user_id: str, tenant_id: str = Query(...), is_admin: bool = Query(False)):
    try:
        result = get_approved_product_ids(tenant_id, user_id, is_admin=is_admin)
        return {"user_id": user_id, "approved_product_ids": result}
    except Exception as exc:
        raise HTTPException(500, f"Graph query failed: {exc}")

@app.get("/graph/approved-products/org-unit/{org_unit_id}")
async def api_approved_products_for_org_unit(org_unit_id: str, tenant_id: str = Query(...)):
    try:
        result = get_approved_product_ids_for_org_unit(tenant_id, org_unit_id)
        return {"org_unit_id": org_unit_id, "approved_product_ids": result}
    except Exception as exc:
        raise HTTPException(500, f"Graph query failed: {exc}")

@app.get("/graph/user-context/{user_id}")
async def api_user_context(user_id: str, tenant_id: str = Query(...)):
    try:
        ctx = get_user_context(user_id, tenant_id)
        return ctx
    except Exception as exc:
        raise HTTPException(500, f"Graph query failed: {exc}")

@app.get("/graph/user-hierarchy/{user_id}")
async def api_user_hierarchy(user_id: str):
    try:
        chain = get_user_hierarchy(user_id)
        return {"user_id": user_id, "hierarchy": chain}
    except Exception as exc:
        raise HTTPException(500, f"Graph query failed: {exc}")

@app.get("/graph/store/{store_id}/products")
async def api_store_products(store_id: str):
    return {"store_id": store_id, "product_ids": get_products_for_store(store_id)}

@app.get("/graph/product/{product_id}/stores")
async def api_product_stores(product_id: str):
    return {"product_id": product_id, "store_ids": get_stores_for_product(product_id)}

@app.get("/graph/tenant/{tenant_id}/topology")
async def api_tenant_topology(tenant_id: str):
    topo = get_tenant_topology(tenant_id)
    if not topo:
        raise HTTPException(404, "Tenant not found in graph")
    return topo


# ── Vector API ──────────────────────────────────────────────────────
class SearchRequest(BaseModel):
    query: str
    tenant_id: str
    user_id: Optional[str] = None
    top_k: int = 20
    skip_governance: bool = False

@app.post("/vector/search")
async def api_search(req: SearchRequest):
    query_embedding = embed_text(req.query)
    approved_ids = None
    
    if req.user_id and not req.skip_governance:
        # Instead of HTTP call, direct function call:
        try:
            approved_ids = get_approved_product_ids(req.tenant_id, req.user_id, is_admin=False)
            if approved_ids == "__all__":
                approved_ids = ["__all__"]
        except Exception as exc:
            logger.error(f"Failed to fetch approved IDs from graph: {exc}")
            approved_ids = []

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


# ── Intelligence API ────────────────────────────────────────────────
class QueryRequest(BaseModel):
    question: str
    tenant_id: str
    user_id: Optional[str] = None

class QueryResponse(BaseModel):
    answer: str
    data: list
    query_plan: dict

@app.post("/intelligence/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    if not SETTINGS.AZURE_OPENAI_API_KEY:
        raise HTTPException(503, "Intelligence service not configured — AZURE_OPENAI_API_KEY required")

    try:
        result = await route_and_execute(
            question=req.question,
            tenant_id=req.tenant_id,
            user_id=req.user_id,
        )
        return QueryResponse(**result)
    except Exception as exc:
        logger.error(f"Query failed: {exc}", exc_info=True)
        raise HTTPException(500, f"Query execution failed: {exc}")
