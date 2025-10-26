# services/pricing/main.py - ZeroQue Pricing Service V2
# Production-ready pricing service with Celery, RabbitMQ, and saga patterns

import os
import uuid
import time
from datetime import datetime, timezone
from typing import Dict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import Response
from sqlalchemy import  text

from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import redis

from core.config import get_settings
from .utils.pricing_logger import logger
from .utils.metrics import pricing_operations_total, pricing_operation_duration
from .repositories.db_config import engine, SessionLocal, get_db_with_rls
from .models import Base, PriceRuleV2
from .schemas import PricebookRequest, PriceRuleRequest, PriceCalculationRequest, PriceCalculationResponse
from .utils.user_auth import get_user_context
from .repositories.pricing_saga import PricebookSaga
from .repositories.database_ops import audit
from .services.pricing_services import calculate_price

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
    
    # Create tables
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialized")
    
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
async def create_pricebook(
    req: PricebookRequest,
    db: SessionLocal = Depends(get_db_with_rls),
    uctx: Dict = Depends(get_user_context)
):
    """Create a new pricebook"""
    start = time.time()
    try:
        pricing_operations_total.labels(operation="create_pricebook", status="start").inc()
        
        pricebook_id = uuid.uuid4()
        tenant_id = uctx["tenant_id"]
        
        saga = PricebookSaga(db)
        result = await saga.exec(pricebook_id, tenant_id, req, uctx)
        
        pricing_operations_total.labels(operation="create_pricebook", status="ok").inc()
        pricing_operation_duration.labels(operation="create_pricebook").observe(time.time() - start)
        
        return result
        
    except ValueError as e:
        pricing_operations_total.labels(operation="create_pricebook", status="fail").inc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        pricing_operations_total.labels(operation="create_pricebook", status="fail").inc()
        logger.error("Pricebook creation failed", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/pricebooks")
async def list_pricebooks(
    tenant_id: str = Query(...),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    db: SessionLocal = Depends(get_db_with_rls)
):
    """List pricebooks for a tenant"""
    try:
        pricebooks = db.execute(
            text("SELECT * FROM pricebooks_v2 WHERE tenant_id = :tenant_id ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
            {"tenant_id": tenant_id, "limit": limit, "offset": offset}
        ).fetchall()
        
        return [dict(pricebook._mapping) for pricebook in pricebooks]
        
    except Exception as e:
        logger.error("Failed to list pricebooks", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/pricebooks/{pricebook_id}/rules")
async def create_price_rule(
    pricebook_id: str,
    req: PriceRuleRequest,
    db: SessionLocal = Depends(get_db_with_rls),
    uctx: Dict = Depends(get_user_context)
):
    """Create a price rule"""
    try:
        rule_id = uuid.uuid4()
        rule = PriceRuleV2(
            rule_id=rule_id,
            pricebook_id=pricebook_id,
            product_id=req.product_id,
            variant_id=req.variant_id,
            rule_type=req.rule_type,
            rule_value=req.rule_value,
            min_quantity=req.min_quantity,
            max_quantity=req.max_quantity,
            valid_from=req.valid_from,
            valid_until=req.valid_until
        )
        db.add(rule)
        db.commit()
        
        # Audit log
        audit(db, uctx["tenant_id"], uctx["user_id"], "CREATE", "price_rule", str(rule_id), req.dict())
        
        return {"rule_id": str(rule_id), "created": True}
        
    except Exception as e:
        logger.error("Failed to create price rule", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/calculate")
async def calculate_price_endpoint(
    req: PriceCalculationRequest,
    db: SessionLocal = Depends(get_db_with_rls)
):
    """Calculate price for a product"""
    try:
        # Check cache first
        cached = db.execute(text("""
            SELECT * FROM calculated_prices_v2 
            WHERE product_id = :product_id 
            AND (variant_id = :variant_id OR variant_id IS NULL)
            AND pricebook_id = :pricebook_id 
            AND quantity = :quantity
            AND expires_at > NOW()
            ORDER BY calculated_at DESC LIMIT 1
        """), {
            "product_id": req.product_id,
            "variant_id": req.variant_id,
            "pricebook_id": req.pricebook_id,
            "quantity": req.quantity
        }).fetchone()
        
        if cached:
            return PriceCalculationResponse(
                product_id=req.product_id,
                variant_id=req.variant_id,
                pricebook_id=req.pricebook_id,
                quantity=req.quantity,
                base_price_minor=req.base_price_minor,
                calculated_price_minor=cached.calculated_price_minor,
                currency="GBP",
                applied_rules=[]
            )
        
        # Calculate price
        calculated_price, applied_rules = calculate_price(
            db, req.product_id, req.variant_id, req.pricebook_id, req.quantity, req.base_price_minor
        )
        
        return PriceCalculationResponse(
            product_id=req.product_id,
            variant_id=req.variant_id,
            pricebook_id=req.pricebook_id,
            quantity=req.quantity,
            base_price_minor=req.base_price_minor,
            calculated_price_minor=calculated_price,
            currency="GBP",
            applied_rules=applied_rules
        )
        
    except Exception as e:
        logger.error("Price calculation failed", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


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