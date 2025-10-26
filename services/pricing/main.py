# services/pricing/main.py - ZeroQue Pricing Service V2
# Production-ready pricing service with Celery, RabbitMQ, and saga patterns

import os
from datetime import datetime, timezone
from typing import Dict
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import redis
from sqlalchemy.orm import Session

from core.config import get_settings
from .utils.pricing_logger import logger
from .repositories.db_config import  get_db_with_rls
from .schemas import PricebookRequest, PriceRuleRequest, PriceCalculationRequest
from .utils.user_auth import get_user_context
from .services.pricing_services import create_pricebook, get_pricebooks, create_price_rule, \
    calculate_price_service

# Configuration
SERVICE_NAME = "pricing"
SERVICE_VERSION = "4.1.0"

DATABASE_URL = get_settings().DATABASE_URL
REDIS_URL = get_settings().REDIS_URL
RABBITMQ_URL = get_settings().RABBITMQ_URL
ENVIRONMENT = get_settings().ENVIRONMENT
JWT_SECRET_KEY = get_settings().JWT_SECRET_KEY
JWT_ALGORITHM = get_settings().JWT_ALGORITHM

import pybreaker
# Redis setup
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Circuit breaker for external service calls
service_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# External service URLs
CATALOG_BASE = os.getenv("CATALOG_BASE", "http://localhost:8008")
ORDERS_BASE = os.getenv("ORDERS_BASE", "http://localhost:8003")

# Circuit breaker for external services
circuit_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan"""
    # Startup
    logger.info("Starting pricing service", version=SERVICE_VERSION)
    yield
    # Shutdown
    logger.info("Shutting down pricing service")

app = FastAPI(
    title="ZeroQue Pricing Service",
    description="Production-ready pricing service with Celery and RabbitMQ",
    version=SERVICE_VERSION,
    lifespan=lifespan
)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

# =============================================================================
# API ENDPOINTS
# =============================================================================
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    logger.info("Checking Health of Pricing....")
    return {
        "status": "healthy",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/pricebooks")
async def create_pricebook_route(
    req: PricebookRequest,
    db: Session= Depends(get_db_with_rls),
    uctx: Dict = Depends(get_user_context)
):
    """Create a new pricebook"""
    return await create_pricebook(req, db, uctx)

@app.get("/pricebooks")
async def list_pricebooks(
    tenant_id: str = Query(...),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_with_rls)
):
    """List pricebooks for a tenant"""
    return await get_pricebooks(tenant_id, limit, offset, db)

@app.post("/pricebooks/{pricebook_id}/rules")
async def create_price_rule_route(
    pricebook_id: str,
    req: PriceRuleRequest,
    db: Session = Depends(get_db_with_rls),
    uctx: Dict = Depends(get_user_context)
):
    """Create a price rule"""
    return await create_price_rule(pricebook_id, req, db, uctx)

@app.post("/calculate")
async def calculate_price_endpoint(
    req: PriceCalculationRequest,
    db: Session = Depends(get_db_with_rls)
):
    """Calculate price for a product"""
    return await calculate_price_service(req, db)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8226")))
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )