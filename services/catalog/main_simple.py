#!/usr/bin/env python3
"""
Simple Catalog Service V2 - No Prometheus Metrics
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
SERVICE_NAME = "catalog"
PORT = int(os.getenv("PORT", "8082"))

# Logging
logger = structlog.get_logger(__name__)

# =============================================================================
# MODELS
# =============================================================================

class CreateProductPayload(BaseModel):
    tenant_id: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    price_minor: Optional[int] = None
    currency: str = "USD"
    metadata: Optional[Dict[str, Any]] = None

class CreateProductResponse(BaseModel):
    product_id: str
    tenant_id: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    price_minor: Optional[int] = None
    currency: str
    created_at: datetime

class CreateVendorPayload(BaseModel):
    tenant_id: str
    name: str
    contact_email: str
    metadata: Optional[Dict[str, Any]] = None

class CreateVendorResponse(BaseModel):
    vendor_id: str
    tenant_id: str
    name: str
    contact_email: str
    created_at: datetime

# =============================================================================
# MAIN APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Catalog Service V2 (Simple Version)")
    yield
    # Shutdown
    logger.info("Shutting down Catalog Service V2")

app = FastAPI(
    title="Catalog Service V2",
    description="Product and vendor catalog service",
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

@app.get("/catalog/v2/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "catalog",
        "version": "2.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/catalog/v2/readiness")
async def readiness_check():
    """Readiness check endpoint"""
    return {
        "status": "ready",
        "service": "catalog",
        "database": "mock"
    }

@app.post("/catalog/v2/products", response_model=CreateProductResponse)
async def create_product(payload: CreateProductPayload):
    """Create a new product"""
    try:
        # Mock product creation
        product_id = f"product_{int(time.time())}"
        now = datetime.utcnow()
        
        logger.info(f"Created product {product_id} for tenant {payload.tenant_id}")
        
        return CreateProductResponse(
            product_id=product_id,
            tenant_id=payload.tenant_id,
            name=payload.name,
            description=payload.description,
            category=payload.category,
            price_minor=payload.price_minor,
            currency=payload.currency,
            created_at=now
        )
        
    except Exception as e:
        logger.error(f"Failed to create product: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/catalog/v2/vendors", response_model=CreateVendorResponse)
async def create_vendor(payload: CreateVendorPayload):
    """Create a new vendor"""
    try:
        # Mock vendor creation
        vendor_id = f"vendor_{int(time.time())}"
        now = datetime.utcnow()
        
        logger.info(f"Created vendor {vendor_id} for tenant {payload.tenant_id}")
        
        return CreateVendorResponse(
            vendor_id=vendor_id,
            tenant_id=payload.tenant_id,
            name=payload.name,
            contact_email=payload.contact_email,
            created_at=now
        )
        
    except Exception as e:
        logger.error(f"Failed to create vendor: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/catalog/v2/integration/status")
async def integration_status():
    """Integration status endpoint"""
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "version": "2.0.0",
        "integrations": {
            "cv-connector": {"connected": True, "events_published": ["PRODUCT_CREATED"]},
            "pricing": {"connected": True, "events_published": ["PRODUCT_CREATED", "PRODUCT_UPDATED"]}
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
