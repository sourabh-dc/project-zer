"""
Graph Service — FastAPI application.

Exposes:
    POST /graph/ingest   — receives events from consumers, projects to Neo4j
    GET  /graph/topology — query the tenant's org topology
    GET  /health         — service health check
"""
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from graph_service.neo4j_client import init_constraints, close_driver, run_cypher
from graph_service.handlers import dispatch

logger = logging.getLogger("graph_service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Graph Service starting up...")
    init_constraints()
    yield
    close_driver()
    logger.info("Graph Service shut down")


app = FastAPI(
    title="ZeroQue Graph Service",
    version="2.0.0",
    description="Neo4j topology projection — receives events via consumer pipeline",
    lifespan=lifespan,
)


class IngestRequest(BaseModel):
    event_id: Optional[str] = None
    event_type: str
    tenant_id: str
    aggregate_type: Optional[str] = None
    aggregate_id: Optional[str] = None
    payload: Dict[str, Any] = {}


@app.post("/graph/ingest", status_code=200)
async def ingest_event(req: IngestRequest):
    """Receive an event from the consumer pipeline and project it into Neo4j."""
    event = {
        "event_id": req.event_id,
        "event_type": req.event_type,
        "tenant_id": req.tenant_id,
        "aggregate_type": req.aggregate_type,
        "aggregate_id": req.aggregate_id,
        "payload": req.payload,
    }
    handled = dispatch(event)
    return {
        "status": "processed" if handled else "skipped",
        "event_type": req.event_type,
    }


@app.get("/graph/topology/{tenant_id}")
async def get_topology(tenant_id: str):
    """Return the organizational topology for a tenant."""
    try:
        result = run_cypher(
            """
            MATCH (t:Tenant {tenant_id: $tid})
            OPTIONAL MATCH (t)-[:HAS_SITE]->(s:Site)
            OPTIONAL MATCH (t)-[:HAS_USER]->(u:User)
            OPTIONAL MATCH (t)-[:HAS_VENDOR]->(v:Vendor)
            OPTIONAL MATCH (t)-[:HAS_COST_CENTRE]->(cc:CostCentre)
            OPTIONAL MATCH (t)-[:HAS_ORG_UNIT]->(ou:OrgUnit)
            RETURN t.tenant_id AS tenant_id,
                   t.name AS tenant_name,
                   COUNT(DISTINCT s) AS site_count,
                   COUNT(DISTINCT u) AS user_count,
                   COUNT(DISTINCT v) AS vendor_count,
                   COUNT(DISTINCT cc) AS cost_centre_count,
                   COUNT(DISTINCT ou) AS org_unit_count
            """,
            {"tid": tenant_id},
        )
        if not result:
            raise HTTPException(404, "Tenant not found in graph")
        return result[0]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Graph query failed: {exc}")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "graph_service"}
