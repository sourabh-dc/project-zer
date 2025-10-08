#!/usr/bin/env python3
"""
Simple CV Gateway Service V4.1 - No Prometheus Metrics
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
SERVICE_NAME = "cv_gateway"
PORT = int(os.getenv("PORT", "8091"))

# Logging
logger = structlog.get_logger(__name__)

# =============================================================================
# MODELS
# =============================================================================

class ProcessOrderPayload(BaseModel):
    tenant_id: str
    user_id: str
    items: List[Dict[str, Any]]
    site_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class ProcessOrderResponse(BaseModel):
    success: bool
    order_id: Optional[str] = None
    total_amount_minor: int
    currency: str
    message: str

class CheckBudgetPayload(BaseModel):
    tenant_id: str
    user_id: str
    amount_minor: int
    currency: str = "USD"

class CheckBudgetResponse(BaseModel):
    allowed: bool
    remaining_budget_minor: int
    approval_required: bool
    message: str

class CreateInvoicePayload(BaseModel):
    tenant_id: str
    order_id: str
    amount_minor: int
    currency: str = "USD"
    items: List[Dict[str, Any]]

class CreateInvoiceResponse(BaseModel):
    success: bool
    invoice_id: Optional[str] = None
    message: str

# =============================================================================
# MAIN APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting CV Gateway Service V4.1 (Simple Version)")
    yield
    # Shutdown
    logger.info("Shutting down CV Gateway Service V4.1")

app = FastAPI(
    title="CV Gateway Service V4.1",
    description="Computer Vision gateway service for order processing",
    version="4.1.0",
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

@app.get("/cv/v4/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "cv_gateway",
        "version": "4.1.0",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/cv/v4/readiness")
async def readiness_check():
    """Readiness check endpoint"""
    return {
        "status": "ready",
        "service": "cv_gateway",
        "database": "mock"
    }

@app.post("/cv/v4/orders/process", response_model=ProcessOrderResponse)
async def process_order(payload: ProcessOrderPayload):
    """Process order through CV gateway"""
    try:
        # Mock order processing
        order_id = f"cv_order_{int(time.time())}"
        total_amount = sum(item.get("price_minor", 1000) * item.get("quantity", 1) for item in payload.items)
        
        logger.info(f"Processed order {order_id} for tenant {payload.tenant_id}")
        
        return ProcessOrderResponse(
            success=True,
            order_id=order_id,
            total_amount_minor=total_amount,
            currency="USD",
            message="Order processed successfully"
        )
        
    except Exception as e:
        logger.error(f"Failed to process order: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/cv/v4/budget/check", response_model=CheckBudgetResponse)
async def check_budget(payload: CheckBudgetPayload):
    """Check budget limits for user"""
    try:
        # Mock budget check
        remaining_budget = 50000  # $500.00
        approval_required = payload.amount_minor > 10000  # $100.00
        
        logger.info(f"Checked budget for user {payload.user_id} in tenant {payload.tenant_id}")
        
        return CheckBudgetResponse(
            allowed=payload.amount_minor <= remaining_budget,
            remaining_budget_minor=remaining_budget,
            approval_required=approval_required,
            message="Budget check completed"
        )
        
    except Exception as e:
        logger.error(f"Failed to check budget: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/cv/v4/billing/create-invoice", response_model=CreateInvoiceResponse)
async def create_invoice(payload: CreateInvoicePayload):
    """Create invoice for order"""
    try:
        # Mock invoice creation
        invoice_id = f"invoice_{int(time.time())}"
        
        logger.info(f"Created invoice {invoice_id} for order {payload.order_id}")
        
        return CreateInvoiceResponse(
            success=True,
            invoice_id=invoice_id,
            message="Invoice created successfully"
        )
        
    except Exception as e:
        logger.error(f"Failed to create invoice: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/cv/v4/integration/status")
async def integration_status():
    """Integration status endpoint"""
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "version": "4.1.0",
        "integrations": {
            "orders": {"connected": True, "events_published": ["ORDER_CREATED"]},
            "approvals": {"connected": True, "events_handled": ["BUDGET_CHECK"]},
            "billing": {"connected": True, "events_handled": ["CREATE_INVOICE"]}
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
