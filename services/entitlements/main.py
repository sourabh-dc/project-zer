# services/entitlements/main.py - ZeroQue Entitlements Service v4.1 (Production-Ready)
import os
from typing import Optional,  Dict
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from prometheus_client import  generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response
import pybreaker
import redis

from core.config import get_settings
from services.entitlements.services.entitlement_services import check_entitlement, create_usage
from .utils.entitlements_logger import logger
from .schemas import CheckEntitlementRequest, RecordUsageRequest
from .repositories.db_config import get_db_with_rls
from .utils.user_auth import get_user_context, check_permission

# Config
REDIS_URL = get_settings().REDIS_URL
SERVICE_NAME = "entitlements"
SERVICE_VERSION = "4.1.0"
USAGE_CLEANUP_DAYS = 365
RATE_LIMIT_REQUESTS_PER_MINUTE = 60

# Redis
redis_client = None

# Circuit Breaker
circuit_breaker = pybreaker.CircuitBreaker(fail_max=3, reset_timeout=30)

# App Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Entitlements Service v4.1")
    global redis_client
    try:
        redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        redis_client.ping()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")
    # Base.metadata.create_all(bind=engine)
    yield
    logger.info("Shutting down Entitlements Service v4.1")

app = FastAPI(
    title="ZeroQue Entitlements Service",
    version=SERVICE_VERSION,
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "https://yourdomain.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Health
@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME, "version": SERVICE_VERSION}

# Endpoints
@app.get("/entitlements/v2/check")
async def check_entitlement_route(req: CheckEntitlementRequest = Body(...), user_context: Dict = Depends(get_user_context), db: Session = Depends(get_db_with_rls)):
    """Check if tenant has access to feature and within limits"""
    return await check_entitlement(req, user_context, db)

@app.post("/entitlements/v2/usage/record")
async def record_usage(payload: RecordUsageRequest = Body(...), user_context: Dict = Depends(get_user_context), db: Session = Depends(get_db_with_rls)):
    return await create_usage(payload, user_context, db)

@app.get("/entitlements/v2/usage/{tenant_id}")
async def get_usage_summary(tenant_id: str, user_context: Dict = Depends(get_user_context), db: Session = Depends(get_db_with_rls)):
    if not check_permission("entitlements.view_usage", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    # ... (rest as per previous code, with RLS)

@app.post("/entitlements/v2/cache/clear")
async def clear_cache(tenant_id: Optional[str] = Query(None), user_context: Dict = Depends(get_user_context)):
    if not check_permission("entitlements.admin", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    # ... (rest as per previous code)

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8003")))
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION} on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)