#!/usr/bin/env python3
"""
Simple Pricing Service V2 - No Prometheus Metrics
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
SERVICE_NAME = "pricing"
PORT = int(os.getenv("PORT", "8086"))

# Logging
logger = structlog.get_logger(__name__)

# =============================================================================
# MODELS
# =============================================================================

class PriceResolutionRequest(BaseModel):
    tenant_id: str
    items: List[Dict[str, Any]]
    context: Optional[Dict[str, Any]] = None

class PriceResolutionResponse(BaseModel):
    resolved: bool
    items: List[Dict[str, Any]]
    total_amount_minor: Optional[int] = None
    currency: Optional[str] = None

class CreatePricebookPayload(BaseModel):
    tenant_id: str
    name: str
    description: Optional[str] = None
    active: bool = True

class CreatePricebookResponse(BaseModel):
    pricebook_id: str
    name: str
    description: Optional[str] = None
    active: bool
    created_at: datetime

# =============================================================================
# MAIN APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Pricing Service V2 (Simple Version)")
    yield
    # Shutdown
    logger.info("Shutting down Pricing Service V2")

app = FastAPI(
    title="Pricing Service V2",
    description="Pricing and pricebook management service",
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

@app.get("/pricing/v2/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "pricing",
        "version": "2.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/pricing/v2/readiness")
async def readiness_check():
    """Readiness check endpoint"""
    return {
        "status": "ready",
        "service": "pricing",
        "database": "mock"
    }

@app.post("/pricing/v2/resolve", response_model=PriceResolutionResponse)
async def resolve_prices(request: PriceResolutionRequest):
    """Resolve prices for items"""
    try:
        # Mock price resolution
        resolved_items = []
        total_amount = 0
        
        for item in request.items:
            # Mock price calculation
            base_price = item.get("base_price_minor", 1000)  # Default 10.00
            quantity = item.get("quantity", 1)
            item_total = base_price * quantity
            
            resolved_item = {
                **item,
                "final_price_minor": item_total,
                "currency": "USD"
            }
            resolved_items.append(resolved_item)
            total_amount += item_total
        
        logger.info(f"Resolved prices for {len(resolved_items)} items")
        
        return PriceResolutionResponse(
            resolved=True,
            items=resolved_items,
            total_amount_minor=total_amount,
            currency="USD"
        )
        
    except Exception as e:
        logger.error(f"Failed to resolve prices: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/pricing/v2/pricebooks", response_model=CreatePricebookResponse)
async def create_pricebook(payload: CreatePricebookPayload):
    """Create a new pricebook"""
    try:
        # Mock pricebook creation
        pricebook_id = f"pricebook_{int(time.time())}"
        now = datetime.utcnow()
        
        logger.info(f"Created pricebook {pricebook_id} for tenant {payload.tenant_id}")
        
        return CreatePricebookResponse(
            pricebook_id=pricebook_id,
            name=payload.name,
            description=payload.description,
            active=payload.active,
            created_at=now
        )
        
    except Exception as e:
        logger.error(f"Failed to create pricebook: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/pricing/v2/integration/status")
async def integration_status():
    """Integration status endpoint"""
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "version": "2.0.0",
        "integrations": {
            "catalog": {"connected": True, "events_handled": ["PRODUCT_CREATED", "PRODUCT_UPDATED"]},
            "orders": {"connected": True, "events_published": ["PRICE_RESOLVED"]},
            "billing": {"connected": True, "events_published": ["PRICE_CHANGED"]},
            "usage": {"connected": True, "events_published": ["OVERAGE_CHECK"]}
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
