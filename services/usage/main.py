# services/usage/main.py - ZeroQue Usage Service V4.1
# Production-ready usage service with Celery, RabbitMQ, and comprehensive metrics
from typing import Dict
from fastapi import FastAPI, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import redis
import pybreaker

from core.config import get_settings
from services.usage.schemas import UsageEventRequest
from services.usage.services.usage_service import record_usage, fetch_usage_events
from utils.user_auth import get_user_context
from repositories.db_config import get_db_with_rls
from utils.usage_logger import logger

# =============================================================================
# CONFIGURATION & LOGGING
# =============================================================================
SERVICE_NAME = "usage"
SERVICE_VERSION = "4.1.0"
REDIS_URL = get_settings().REDIS_URL

# Redis setup
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Circuit breaker for external service calls
service_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# =============================================================================
# FASTAPI APP
# =============================================================================

app = FastAPI(title="ZeroQue Usage Service", version=SERVICE_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Endpoints
@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME}

@app.post("/usage/v4/record")
async def record_usage_route(request: UsageEventRequest, db: Session = Depends(get_db_with_rls)):
    """Record a usage event"""
    return await record_usage(request, db)

@app.get("/usage/v4/events")
async def get_usage_events(tenant_id: str = Query(...), limit: int = Query(100), uctx: Dict = Depends(get_user_context), db: Session = Depends(get_db_with_rls)):
    """Get usage events for a tenant"""
    return await fetch_usage_events(tenant_id, limit, uctx, db)

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting {SERVICE_NAME} service")
    port = 8200
    uvicorn.run(app, host="0.0.0.0", port=port)
