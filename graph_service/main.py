"""
Graph Service — main entry point.

Runs as a standalone FastAPI app on port 8005.
On startup it:
  1. Connects to Neo4j and creates constraints
  2. Registers all event handlers
  3. Starts the outbox polling loop in the background

Exposes REST endpoints for governance queries that other
services can call (e.g. "Approved Universe for user X").
"""
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query

from graph_service.core.config import SETTINGS
from graph_service.core.neo4j_client import init_constraints, close_driver
from graph_service.core.outbox_consumer import register_handler, start_polling
from graph_service.core.logger import logger

from graph_service.handlers import (
    tenant_handler,
    site_handler,
    store_handler,
    store_product_handler,
    user_handler,
    org_unit_handler,
    product_handler,
    category_handler,
    vendor_handler,
    role_handler,
    cost_centre_handler,
    approved_range_handler,
    policy_handler,
)

from graph_service.queries.approved_universe import (
    get_approved_product_ids,
    get_approved_product_ids_for_org_unit,
)
from graph_service.queries.user_governance import get_user_context, get_user_hierarchy
from graph_service.queries.store_products import (
    get_products_for_store,
    get_stores_for_product,
    get_tenant_topology,
)


def _register_handlers():
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Graph Service starting up...")
    init_constraints()
    _register_handlers()

    poll_task = asyncio.create_task(start_polling())
    logger.info("Outbox polling task started")

    yield

    poll_task.cancel()
    close_driver()
    logger.info("Graph Service shut down")


app = FastAPI(
    title="ZeroQue Graph Service",
    version="0.1.0",
    description="Governance topology graph — Neo4j projection layer",
    lifespan=lifespan,
)


# ── Health ──────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "service": "graph_service"}


# ── Approved Universe ───────────────────────────────────────────────
@app.get("/graph/approved-products/{user_id}")
async def api_approved_products(
    user_id: str,
    tenant_id: str = Query(...),
    is_admin: bool = Query(False),
):
    try:
        result = get_approved_product_ids(tenant_id, user_id, is_admin=is_admin)
        return {"user_id": user_id, "approved_product_ids": result}
    except Exception as exc:
        raise HTTPException(500, f"Graph query failed: {exc}")


@app.get("/graph/approved-products/org-unit/{org_unit_id}")
async def api_approved_products_for_org_unit(
    org_unit_id: str,
    tenant_id: str = Query(...),
):
    try:
        result = get_approved_product_ids_for_org_unit(tenant_id, org_unit_id)
        return {"org_unit_id": org_unit_id, "approved_product_ids": result}
    except Exception as exc:
        raise HTTPException(500, f"Graph query failed: {exc}")


# ── User Governance Context ─────────────────────────────────────────
@app.get("/graph/user-context/{user_id}")
async def api_user_context(
    user_id: str,
    tenant_id: str = Query(...),
):
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


# ── Store / Product topology ────────────────────────────────────────
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
