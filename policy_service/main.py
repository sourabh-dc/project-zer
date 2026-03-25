"""
Policy Engine Service — FastAPI application entry point.

Fully standalone service. Connects to the same PostgreSQL database
but has zero code dependency on any other service.
Runs on a separate port (default 8004).
"""
import os
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from policy_service.Models import Base
from policy_service.core.db_config import engine
from policy_service.services.policy_master import router as policy_master_router
from policy_service.services.policy_evaluator import router as policy_evaluator_router
from policy_service.utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: create policy tables on startup."""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Policy Engine tables initialized")
    except Exception as e:
        logger.error(f"❌ Policy table initialization failed: {e}")

    yield

    logger.info("Policy Engine shutting down")


app = FastAPI(
    title="Policy Engine Service",
    version="1.0.0",
    description="Governance and decisioning layer — evaluates policies for every action",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    logger.error(f"Unhandled exception in {request.url.path}: {exc}\n{tb}")
    return JSONResponse(status_code=500, content={"detail": str(exc)})


allow_origins = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["*"],
)

# Include routers
app.include_router(policy_master_router)
app.include_router(policy_evaluator_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "policy-engine"}
