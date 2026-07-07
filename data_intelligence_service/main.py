import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Query, Response
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

# Intelligence agent (LangGraph) + memory + derived knowledge
from data_intelligence_service.intelligence.agents.agent import run_agent
from data_intelligence_service.intelligence.agents import memory as _mem
from data_intelligence_service.intelligence.observability import metrics as _metrics
from data_intelligence_service.intelligence.derived import handlers as derived_handlers
from data_intelligence_service.intelligence.derived.store import ensure_table_exists
from data_intelligence_service.intelligence.cost import tracker as _cost


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

    # Derived knowledge handlers — recompute precomputed facts when data changes.
    # These run AFTER the graph/vector handlers so the graph is already updated
    # when facts that depend on graph data (approved_product_count) are computed.
    register_handler("purchase_request", derived_handlers.handle_purchase_request)
    register_handler("approved_range",   derived_handlers.handle_approved_range)
    register_handler("budget",           derived_handlers.handle_budget)
    register_handler("policy",           derived_handlers.handle_policy)
    register_handler("org_unit",         derived_handlers.handle_org_unit)
    register_handler("vendor",           derived_handlers.handle_vendor)
    register_handler("product",          derived_handlers.handle_product)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Data Intelligence Service starting up...")
    
    # Graph init
    init_constraints()
    _register_handlers()

    # Vector init
    init_pgvector()

    # Derived knowledge table — create if not exists (idempotent)
    ensure_table_exists()

    # Cost monitoring table — create if not exists
    _cost.ensure_usage_table()

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
class ObjectContext(BaseModel):
    """Context for the object the user is currently viewing.

    Pass this when the user is on a Product, Supplier, Purchase Request,
    Order, or Contract page. The agent will auto-inherit this context so
    questions like 'what is this?' or 'can I order this?' resolve correctly.
    """
    object_type: str                  # product | supplier | request | order | contract
    object_id: str
    object_data: Optional[Dict[str, Any]] = None   # pre-fetched data (optional)


class QueryRequest(BaseModel):
    question: str
    tenant_id: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None   # pass same value across turns for memory
    current_object: Optional[ObjectContext] = None  # object context auto-inheritance (spec §13.2)

class QueryResponse(BaseModel):
    answer: str
    data: list
    query_plan: dict
    routing_meta: Dict[str, Any] = {}
    permission_meta: Dict[str, Any] = {}  # user context summary — roles, scope, admin flag
    trace: Dict[str, Any] = {}            # per-query explainability (engine, latency, tokens, steps)
    session_id: Optional[str] = None      # echo for client tracking

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
            current_object=req.current_object.model_dump() if req.current_object else None,
        )
        if result.get("blocked"):
            raise HTTPException(400, result.get("error", "Request not permitted"))
        return QueryResponse(
            answer=result["answer"],
            data=result["data"],
            query_plan=result.get("query_plan") or {},
            routing_meta=result.get("routing_meta") or {},
            permission_meta=result.get("permission_meta") or {},
            trace=result.get("trace") or {},
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
    return {"active_sessions": _mem.active_sessions()}


# ── Cost / Usage Monitoring ──────────────────────────────────────────────────

@app.get("/intelligence/cost/tenants")
async def cost_by_tenant(days: int = Query(default=30, ge=1, le=365)):
    """Total cost and token usage per tenant for the last N days."""
    return {"days": days, "tenants": _cost.get_cost_by_tenant(days)}


@app.get("/intelligence/cost/users")
async def cost_by_user(tenant_id: str = Query(...), days: int = Query(default=30, ge=1, le=365)):
    """Per-user cost breakdown for a tenant."""
    return {"tenant_id": tenant_id, "days": days, "users": _cost.get_cost_by_user(tenant_id, days)}


@app.get("/intelligence/cost/models")
async def cost_by_model(days: int = Query(default=30, ge=1, le=365)):
    """Cost breakdown by model/deployment tier."""
    return {"days": days, "models": _cost.get_cost_by_model(days)}


@app.get("/intelligence/cost/abuse")
async def abuse_detection(hours: int = Query(default=1, ge=1, le=24)):
    """Tenants exceeding the abuse cost threshold in a rolling window.

    Tenants spending more than ABUSE_COST_THRESHOLD_USD (default $5) per hour.
    Use for throttling decisions and manual review.
    """
    candidates = _cost.get_abuse_candidates(hours)
    return {
        "hours": hours,
        "threshold_usd": float(os.getenv("ABUSE_COST_THRESHOLD_USD", "5.0")),
        "flagged_tenants": candidates,
        "count": len(candidates),
    }


# ── Observability ────────────────────────────────────────────────────────────
@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus metrics endpoint.

    Scraped by Prometheus every 15s. Visualise in Grafana.
    Returns 501 if prometheus_client is not installed.
    """
    if not _metrics.is_available():
        raise HTTPException(501, "prometheus_client not installed. Run: pip install prometheus-client")

    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    registry = _metrics.get_registry()
    data = generate_latest(registry)
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
