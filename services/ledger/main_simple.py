#!/usr/bin/env python3
"""
Simple Ledger Service V4.1 - No Prometheus Metrics
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
SERVICE_NAME = "ledger"
PORT = int(os.getenv("PORT", "8092"))

# Logging
logger = structlog.get_logger(__name__)

# =============================================================================
# MODELS
# =============================================================================

class CreateEntryPayload(BaseModel):
    tenant_id: str
    account_id: str
    debit_amount_minor: int
    credit_amount_minor: int
    currency: str = "USD"
    description: str
    reference_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class CreateEntryResponse(BaseModel):
    entry_id: str
    tenant_id: str
    account_id: str
    debit_amount_minor: int
    credit_amount_minor: int
    currency: str
    created_at: datetime

class GetBalancePayload(BaseModel):
    tenant_id: str
    account_id: str
    currency: str = "USD"

class GetBalanceResponse(BaseModel):
    account_id: str
    balance_minor: int
    currency: str
    last_updated: datetime

class AdjustmentPayload(BaseModel):
    tenant_id: str
    account_id: str
    adjustment_amount_minor: int
    currency: str = "USD"
    reason: str
    reference_id: Optional[str] = None

class AdjustmentResponse(BaseModel):
    adjustment_id: str
    account_id: str
    adjustment_amount_minor: int
    new_balance_minor: int
    created_at: datetime

# =============================================================================
# MAIN APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Ledger Service V4.1 (Simple Version)")
    yield
    # Shutdown
    logger.info("Shutting down Ledger Service V4.1")

app = FastAPI(
    title="Ledger Service V4.1",
    description="Double-entry accounting ledger service",
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

@app.get("/ledger/v4/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "ledger",
        "version": "4.1.0",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/ledger/v4/readiness")
async def readiness_check():
    """Readiness check endpoint"""
    return {
        "status": "ready",
        "service": "ledger",
        "database": "mock"
    }

@app.post("/ledger/v4/entries", response_model=CreateEntryResponse)
async def create_entry(payload: CreateEntryPayload):
    """Create a ledger entry"""
    try:
        # Mock ledger entry creation
        entry_id = f"entry_{int(time.time())}"
        now = datetime.utcnow()
        
        logger.info(f"Created ledger entry {entry_id} for tenant {payload.tenant_id}")
        
        return CreateEntryResponse(
            entry_id=entry_id,
            tenant_id=payload.tenant_id,
            account_id=payload.account_id,
            debit_amount_minor=payload.debit_amount_minor,
            credit_amount_minor=payload.credit_amount_minor,
            currency=payload.currency,
            created_at=now
        )
        
    except Exception as e:
        logger.error(f"Failed to create ledger entry: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ledger/v4/balance", response_model=GetBalanceResponse)
async def get_balance(payload: GetBalancePayload):
    """Get account balance"""
    try:
        # Mock balance retrieval
        balance_minor = 100000  # $1000.00
        now = datetime.utcnow()
        
        logger.info(f"Retrieved balance for account {payload.account_id} in tenant {payload.tenant_id}")
        
        return GetBalanceResponse(
            account_id=payload.account_id,
            balance_minor=balance_minor,
            currency=payload.currency,
            last_updated=now
        )
        
    except Exception as e:
        logger.error(f"Failed to get balance: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ledger/v4/adjustments", response_model=AdjustmentResponse)
async def create_adjustment(payload: AdjustmentPayload):
    """Create account adjustment"""
    try:
        # Mock adjustment creation
        adjustment_id = f"adj_{int(time.time())}"
        new_balance = 100000 + payload.adjustment_amount_minor
        now = datetime.utcnow()
        
        logger.info(f"Created adjustment {adjustment_id} for account {payload.account_id}")
        
        return AdjustmentResponse(
            adjustment_id=adjustment_id,
            account_id=payload.account_id,
            adjustment_amount_minor=payload.adjustment_amount_minor,
            new_balance_minor=new_balance,
            created_at=now
        )
        
    except Exception as e:
        logger.error(f"Failed to create adjustment: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/ledger/v4/integration/status")
async def integration_status():
    """Integration status endpoint"""
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "version": "4.1.0",
        "integrations": {
            "orders": {"connected": True, "events_handled": ["ORDER_COMPLETED"]},
            "approvals": {"connected": True, "events_handled": ["APPROVAL_RESOLVED"]},
            "billing": {"connected": True, "events_handled": ["INVOICE_POSTED"]}
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
