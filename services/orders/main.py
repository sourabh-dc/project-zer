# services/orders/main.py - ZeroQue Orders Service V2
# Production-ready orders service with Celery, RabbitMQ, and saga patterns

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

from services.orders.services.order_services import create_order, get_orders, get_order, update_order, cancel_order
from .utils.orders_logger import logger
from core.config import get_settings
from .schemas import OrderRequest, OrderUpdateRequest
from .repositories.db_config import get_db
from .utils.user_auth import get_user_context

# =============================================================================
# CONFIGURATION
# =============================================================================

SERVICE_NAME = "orders"
SERVICE_VERSION = "4.1.0"

# Configuration
DATABASE_URL = get_settings().DATABASE_URL
REDIS_URL = get_settings().REDIS_URL
RABBITMQ_URL = get_settings().RABBITMQ_URL
ENVIRONMENT = get_settings().ENVIRONMENT

# Redis setup
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan"""
    # Startup
    logger.info("Starting orders service", version=SERVICE_VERSION)
    yield
    # Shutdown
    logger.info("Shutting down orders service")

app = FastAPI(
    title="ZeroQue Orders Service",
    description="Production-ready orders service with Celery and RabbitMQ",
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

@app.post("/orders")
async def create_order_route(
    req: OrderRequest,
    db: Session = Depends(get_db),
    uctx: Dict = Depends(get_user_context)
):
    return await create_order(req, db=db, uctx=uctx)

@app.get("/orders")
async def list_orders(
    tenant_id: str = Query(...),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """List orders for a tenant"""
    return await get_orders(tenant_id, limit, offset, db=db)

@app.get("/orders/{order_id}")
async def get_order_route(
    order_id: str,
    db: Session = Depends(get_db)
):
    """Get order by ID"""
    return await get_order(order_id, db=db)

@app.put("/orders/{order_id}")
async def update_order_route(order_id: str, req: OrderUpdateRequest, db: Session = Depends(get_db), uctx: Dict = Depends(get_user_context)
):
    """Update order"""
    return await update_order(order_id, req, db, uctx)

@app.delete("/orders/{order_id}")
async def cancel_order_route(
    order_id: str,
    db: Session = Depends(get_db),
    uctx: Dict = Depends(get_user_context)
):
    """Cancel order"""
    return await cancel_order(order_id, db=db, uctx=uctx)

# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8224")))
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )