import asyncio
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from data_intelligence_service.core.config import SETTINGS
from data_intelligence_service.core.logger import logger
from data_intelligence_service.intelligence.middleware.auth import ApiKeyMiddleware
from data_intelligence_service.core.neo4j_client import init_constraints, close_driver
from data_intelligence_service.vector.pg_vector import init_pgvector, similarity_search
from data_intelligence_service.vector.embeddings import embed_text
from data_intelligence_service.core.outbox_consumer import start_polling, register_handler

# Graph handlers
from data_intelligence_service.graph.handlers import (
    tenant_handler, site_handler, store_handler, store_product_handler,
    user_handler, org_unit_handler, product_handler, category_handler,
    vendor_handler, role_handler, cost_centre_handler, approved_range_handler,
    policy_handler, mandate_handler,
)

# Graph queries
from data_intelligence_service.graph.queries.approved_universe import (
    get_approved_product_ids, get_approved_product_ids_for_org_unit,
)
from data_intelligence_service.graph.queries.user_governance import get_user_context, get_user_hierarchy
from data_intelligence_service.graph.queries.store_products import (
    get_products_for_store, get_stores_for_product, get_tenant_topology,
)

# Vector handler
from data_intelligence_service.vector.handlers.product_embedding_handler import handle as vector_product_handler

# Intelligence agent (LangGraph) + memory
from data_intelligence_service.intelligence.agents.agent import run_agent
from data_intelligence_service.intelligence.agents import memory as _mem


def _register_handlers():
    # Graph handlers
    register_handler("tenant", tenant_handler.handle)
    register_handler("site", site_handler.handle)
    register_handler("store", store_handler.handle)
    register_handler("store_product", store_product_handler.handle)
    register_handler("user", user_handler.handle)
    register_handler("org_unit", org_unit_handler.handle)
    register_handler("product", product_handler.handle)
    register_handler("category", category_handler.handle)
    register_handler("vendor", vendor_handler.handle)
    register_handler("role", role_handler.handle)
    register_handler("role_permission", role_handler.handle)
    register_handler("cost_centre", cost_centre_handler.handle)
    register_handler("approved_range", approved_range_handler.handle)
    register_handler("policy", policy_handler.handle)
    register_handler("policy_rule", policy_handler.handle)
    register_handler("policy_assignment", policy_handler.handle)
    register_handler("mandate", mandate_handler.handle)
    
    # Vector handlers
    register_handler("product", vector_product_handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Data Intelligence Service starting up...")
    
    # Graph init
    init_constraints()
    _register_handlers()
    
    # Vector init
    init_pgvector()

    # Intelligence init
    if not SETTINGS.AZURE_OPENAI_API_KEY:
        logger.warning("AZURE_OPENAI_API_KEY not set — LLM queries will fail")
        
    poll_task = asyncio.create_task(start_polling())
    logger.info("Outbox polling task started")

    yield

    poll_task.cancel()
    close_driver()
    logger.info("Data Intelligence Service shut down")


app = FastAPI(
    title="ZeroQue Data Intelligence Service",
    version="0.2.0",
    description="Unified Graph, Vector, and Intelligence Service",
    lifespan=lifespan,
)

app.add_middleware(ApiKeyMiddleware)


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
    session_id: Optional[str] = None   # pass same value across turns for memory

class QueryResponse(BaseModel):
    answer: str
    data: list
    query_plan: dict
    routing_meta: Dict[str, Any] = {}
    session_id: Optional[str] = None   # echo for client tracking

@app.post("/intelligence/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    if not SETTINGS.AZURE_OPENAI_API_KEY:
        raise HTTPException(503, "Intelligence service not configured — AZURE_OPENAI_API_KEY required")

    try:
        result = await run_agent(
            question=req.question,
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            session_id=req.session_id,
        )
        if result.get("blocked"):
            raise HTTPException(400, result.get("error", "Request not permitted"))
        return QueryResponse(
            answer=result["answer"],
            data=result["data"],
            query_plan=result.get("query_plan") or {},
            routing_meta=result.get("routing_meta") or {},
            session_id=result.get("session_id"),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Query failed: {exc}", exc_info=True)
        raise HTTPException(500, f"Query execution failed: {exc}")


@app.delete("/intelligence/session/{session_id}")
async def clear_session(session_id: str, tenant_id: str = Query(...)):
    """Clear conversation memory for a session (user presses 'New conversation')."""
    _mem.clear_session(tenant_id, session_id)
    return {"cleared": True, "session_id": session_id}


@app.get("/intelligence/sessions/stats")
async def session_stats():
    """Diagnostic: number of active sessions in memory."""
    return {"active_sessions": _mem.active_sessions()}
