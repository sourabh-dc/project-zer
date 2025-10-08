#!/usr/bin/env python3
"""
Simple Orders Service V2 - No Prometheus Metrics
"""

import os
import time
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional, List
from datetime import datetime

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Configuration
SERVICE_NAME = "orders"
PORT = int(os.getenv("PORT", "8080"))

# Logging
logger = structlog.get_logger(__name__)

# =============================================================================
# MODELS
# =============================================================================

class CreateOrderPayload(BaseModel):
    tenant_id: str
    user_id: str
    items: List[Dict[str, Any]]
    site_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class CreateOrderResponse(BaseModel):
    order_id: str
    tenant_id: str
    user_id: str
    status: str
    total_amount_minor: int
    currency: str
    created_at: datetime

class OrderStatusPayload(BaseModel):
    order_id: str
    status: str
    metadata: Optional[Dict[str, Any]] = None

class OrderStatusResponse(BaseModel):
    order_id: str
    status: str
    updated_at: datetime

# =============================================================================
# MAIN APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Orders Service V2 (Simple Version)")
    yield
    # Shutdown
    logger.info("Shutting down Orders Service V2")

app = FastAPI(
    title="Orders Service V2",
    description="Order management service",
    version="2.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# ENDPOINTS
# =============================================================================

@app.get("/orders/v2/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "orders",
        "version": "2.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/orders/v2/readiness")
async def readiness_check():
    """Readiness check endpoint"""
    return {
        "status": "ready",
        "service": "orders",
        "database": "mock"
    }

@app.post("/orders/v2/orders", response_model=CreateOrderResponse)
async def create_order(payload: CreateOrderPayload):
    """Create a new order"""
    try:
        # Mock order creation
        order_id = f"order_{int(time.time())}"
        now = datetime.utcnow()
        
        # Calculate total amount
        total_amount = 0
        for item in payload.items:
            price = item.get("price_minor", 1000)
            quantity = item.get("quantity", 1)
            total_amount += price * quantity
        
        logger.info(f"Created order {order_id} for tenant {payload.tenant_id}")
        
        return CreateOrderResponse(
            order_id=order_id,
            tenant_id=payload.tenant_id,
            user_id=payload.user_id,
            status="pending",
            total_amount_minor=total_amount,
            currency="USD",
            created_at=now
        )
        
    except Exception as e:
        logger.error(f"Failed to create order: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/orders/v2/orders/{order_id}/status", response_model=OrderStatusResponse)
async def update_order_status(order_id: str, payload: OrderStatusPayload):
    """Update order status"""
    try:
        # Mock status update
        now = datetime.utcnow()
        
        logger.info(f"Updated order {order_id} status to {payload.status}")
        
        return OrderStatusResponse(
            order_id=order_id,
            status=payload.status,
            updated_at=now
        )
        
    except Exception as e:
        logger.error(f"Failed to update order status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/orders/v2/integration/status")
async def integration_status():
    """Integration status endpoint"""
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "version": "2.0.0",
        "integrations": {
            "pricing": {"connected": True, "events_handled": ["PRICE_RESOLVED"]},
            "ledger": {"connected": True, "events_published": ["ORDER_COMPLETED"]},
            "cv-gateway": {"connected": True, "events_published": ["ORDER_CREATED"]}
        },
        "status": {
            "database_available": False,
            "metrics_enabled": False
        }
    }

# =============================================================================
# STARTUP
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main_simple:app",
        host="0.0.0.0",
        port=PORT,
        reload=os.getenv("ENVIRONMENT") == "development"
    )
