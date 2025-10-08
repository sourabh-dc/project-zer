#!/usr/bin/env python3
"""
Simple Payments Service V4.1 - No Prometheus Metrics
"""

import os
import time
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional
from datetime import datetime

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Configuration
SERVICE_NAME = "payments"
PORT = int(os.getenv("PORT", "8093"))

# Logging
logger = structlog.get_logger(__name__)

# =============================================================================
# MODELS
# =============================================================================

class CreatePaymentIntentPayload(BaseModel):
    tenant_id: str
    amount_minor: int
    currency: str = "USD"
    order_id: Optional[str] = None
    customer_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class CreatePaymentIntentResponse(BaseModel):
    payment_intent_id: str
    client_secret: str
    status: str
    amount_minor: int
    currency: str

class ProcessRefundPayload(BaseModel):
    tenant_id: str
    payment_intent_id: str
    amount_minor: int
    currency: str = "USD"
    reason: Optional[str] = None

class ProcessRefundResponse(BaseModel):
    refund_id: str
    payment_intent_id: str
    amount_minor: int
    currency: str
    status: str

class CreateCustomerPayload(BaseModel):
    tenant_id: str
    email: str
    name: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class CreateCustomerResponse(BaseModel):
    customer_id: str
    email: str
    name: Optional[str] = None
    created_at: datetime

# =============================================================================
# MAIN APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Payments Service V4.1 (Simple Version)")
    yield
    # Shutdown
    logger.info("Shutting down Payments Service V4.1")

app = FastAPI(
    title="Payments Service V4.1",
    description="Payment processing service",
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

@app.get("/payments/v4/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "payments",
        "version": "4.1.0",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/payments/v4/readiness")
async def readiness_check():
    """Readiness check endpoint"""
    return {
        "status": "ready",
        "service": "payments",
        "database": "mock"
    }

@app.post("/payments/v4/intent", response_model=CreatePaymentIntentResponse)
async def create_payment_intent(payload: CreatePaymentIntentPayload):
    """Create payment intent"""
    try:
        # Mock payment intent creation
        payment_intent_id = f"pi_{int(time.time())}"
        client_secret = f"cs_{payment_intent_id}_secret"
        
        logger.info(f"Created payment intent {payment_intent_id} for tenant {payload.tenant_id}")
        
        return CreatePaymentIntentResponse(
            payment_intent_id=payment_intent_id,
            client_secret=client_secret,
            status="requires_payment_method",
            amount_minor=payload.amount_minor,
            currency=payload.currency
        )
        
    except Exception as e:
        logger.error(f"Failed to create payment intent: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/payments/v4/refund", response_model=ProcessRefundResponse)
async def process_refund(payload: ProcessRefundPayload):
    """Process refund"""
    try:
        # Mock refund processing
        refund_id = f"rf_{int(time.time())}"
        
        logger.info(f"Processed refund {refund_id} for payment {payload.payment_intent_id}")
        
        return ProcessRefundResponse(
            refund_id=refund_id,
            payment_intent_id=payload.payment_intent_id,
            amount_minor=payload.amount_minor,
            currency=payload.currency,
            status="succeeded"
        )
        
    except Exception as e:
        logger.error(f"Failed to process refund: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/payments/v4/customers", response_model=CreateCustomerResponse)
async def create_customer(payload: CreateCustomerPayload):
    """Create customer"""
    try:
        # Mock customer creation
        customer_id = f"cus_{int(time.time())}"
        now = datetime.utcnow()
        
        logger.info(f"Created customer {customer_id} for tenant {payload.tenant_id}")
        
        return CreateCustomerResponse(
            customer_id=customer_id,
            email=payload.email,
            name=payload.name,
            created_at=now
        )
        
    except Exception as e:
        logger.error(f"Failed to create customer: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/payments/v4/integration/status")
async def integration_status():
    """Integration status endpoint"""
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "version": "4.1.0",
        "integrations": {
            "orders": {"connected": True, "events_handled": ["ORDER_COMPLETED"]},
            "billing": {"connected": True, "events_handled": ["INVOICE_POSTED"]},
            "ledger": {"connected": True, "events_published": ["PAYMENT_CREATED", "PAYMENT_PAID"]}
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
