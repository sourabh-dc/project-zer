"""
Intelligence Service — main entry point.

Runs as a standalone FastAPI app on port 8007.
Provides a natural language query interface for admins
that routes to Graph (Neo4j), SQL (Postgres), or Vector (pgvector)
based on query classification.
"""
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from intelligence_service.core.config import SETTINGS
from intelligence_service.core.logger import logger
from intelligence_service.agents.query_router import route_and_execute


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Intelligence Service starting up...")
    if not SETTINGS.AZURE_OPENAI_API_KEY:
        logger.warning("AZURE_OPENAI_API_KEY not set — LLM queries will fail")
    yield
    logger.info("Intelligence Service shut down")


app = FastAPI(
    title="ZeroQue Intelligence Service",
    version="0.1.0",
    description="GraphRAG query intelligence — natural language to Cypher/SQL/Vector",
    lifespan=lifespan,
)


class QueryRequest(BaseModel):
    question: str
    tenant_id: str
    user_id: Optional[str] = None


class QueryResponse(BaseModel):
    answer: str
    data: list
    query_plan: dict


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "intelligence_service",
        "llm_configured": bool(SETTINGS.AZURE_OPENAI_API_KEY),
    }


@app.post("/intelligence/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    """Ask a natural language question about your tenant's data.

    Examples:
      - "How many users are in the Mumbai org unit?"
      - "Which vendors supply the most products?"
      - "What is the total budget spent across all cost centres?"
      - "Find products similar to cleaning supplies"
      - "Which users have the admin role?"
      - "What approved ranges are assigned to the Delhi office?"
      - "Show me the org hierarchy for tenant X"
    """
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
