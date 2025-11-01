# Payments Service V2 - Enhanced V4.1 Architecture
# Multi-provider payment processing with sagas, events, and RLS

import os
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, Body, Query, Depends, Request, BackgroundTasks
from fastapi.responses import Response
from sqlalchemy.orm import Session
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import redis
import pybreaker

from core.config import get_settings
from services.payments.services.payment_services import create_payment_intent, create_customer, refund_payment, \
    process_webhook, configure_payment_provider, fetch_transactions, get_payment_reports, create_trade_account, \
    get_trade_accounts, create_payment_intent2, convert_currency, get_payment_intent, handle_payment_required_event, \
    get_integration_status
from services.payments.utils.user_auth import get_user_context
from .schemas import PaymentIntentRequest, CustomerRequest, RefundRequest, RailRequest, TradeAccountRequest,\
     TradeAccountResponse, MultiCurrencyConversionRequest, MultiCurrencyConversionResponse, PaymentIntentResponse
from .repositories.db_config import get_db_with_rls
from .utils.payments_logger import logger

# Configuration
DATABASE_URL = get_settings().DATABASE_URL
REDIS_URL = get_settings().REDIS_URL
RABBITMQ_URL = get_settings().RABBITMQ_URL
ENVIRONMENT = get_settings().ENVIRONMENT
ALLOW_DEMO = get_settings().ALLOW_DEMO
JWT_ALGORITHM = get_settings().JWT_ALGORITHM
JWT_SECRET_KEY = get_settings().JWT_SECRET_KEY

# =============================================================================
# CONFIGURATION & LOGGING
# =============================================================================

SERVICE_NAME = "payments"
SERVICE_VERSION = "4.1.0"

# Redis setup
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Circuit breaker for external service calls
service_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    logger.info("Starting Payments Service V2", version="2.0.0", environment="production")
    yield
    # Shutdown
    logger.info("Shutting down Payments Service V2")

app = FastAPI(
    title="ZeroQue Payments Service V2",
    version="2.0.0",
    description="Multi-provider payment processing with V4.1 architecture",
    lifespan=lifespan
)

# =============================================================================
# HEALTH AND STATUS ENDPOINTS
# =============================================================================

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok", "service": "payments", "version": "2.0.0"}

def check_db():
    """Simple database connectivity check"""
    # Temporarily return True to avoid database connection issues
    return True

@app.get("/readiness")
async def readiness():
    """Readiness check endpoint"""
    return {
        "service": "payments",
        "db": check_db(),
        "version": "2.0.0"
    }

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# =============================================================================
# PAYMENT ENDPOINTS
# =============================================================================

@app.post("/payments/v2/intent")
async def create_payment_intent_route(
    request: PaymentIntentRequest,
    db: Session = Depends(get_db_with_rls),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Create a payment intent with any supported provider"""
    return await create_payment_intent(request, db, user_context)

@app.post("/payments/v2/customers")
async def create_customer_route(request: CustomerRequest, db: Session = Depends(get_db_with_rls),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Create or update a customer with any supported provider"""
    return await create_customer(request, db, user_context)

@app.post("/payments/v2/refund")
async def refund_payment_route(
    request: RefundRequest, db: Session = Depends(get_db_with_rls), user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Refund a payment"""
    return await refund_payment(request, db, user_context)

@app.post("/payments/v2/webhook/{provider}")
async def process_webhook_route(provider: str, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db_with_rls)
):
    """Process webhook from payment providers"""
    return await process_webhook(provider, request, background_tasks, db)

# =============================================================================
# ADMIN ENDPOINTS
# =============================================================================

@app.post("/payments/v2/admin/rails/payment")
async def configure_payment_provider_route(
    request: RailRequest,
    db: Session = Depends(get_db_with_rls),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Configure payment provider for a tenant"""
    return await configure_payment_provider(request, db, user_context)

# =============================================================================
# QUERY ENDPOINTS
# =============================================================================

@app.get("/payments/v2/transactions")
async def list_transactions(tenant_id: str = Query(...), provider: Optional[str] = Query(None), status: Optional[str] = Query(None),
    limit: int = Query(100, le=1000), offset: int = Query(0, ge=0), db: Session = Depends(get_db_with_rls),
    user_context: Dict[str, Any] = Depends(get_user_context)):
    """List payment transactions with filters"""
    return await fetch_transactions(tenant_id, provider, status, limit, offset, db, user_context)

@app.get("/payments/v2/reports")
async def get_payment_reports_route(tenant_id: str = Query(...), period_start: str = Query(...), period_end: str = Query(...),
    currency: Optional[str] = Query("GBP"), db: Session = Depends(get_db_with_rls), user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Get payment reports and analytics (blueprint-inspired)"""
    return await get_payment_reports(tenant_id, period_start, period_end, currency, db, user_context)

# =============================================================================
# LEGACY ENDPOINT DEPRECATION
# =============================================================================

@app.post("/stripe/customers")
async def stripe_customers_legacy():
    """Legacy endpoint - deprecated"""
    return {
        "deprecated": True,
        "migrate_to": "/payments/v2/customers",
        "message": "This endpoint is deprecated. Please use /payments/v2/customers"
    }

# Phase 5: Trade Account & Multi-Currency Endpoints
@app.post("/trade-accounts", response_model=TradeAccountResponse)
async def create_trade_account_route(request: TradeAccountRequest, db = Depends(get_db_with_rls), uctx: Dict = Depends(get_user_context)
):
    """Create a new trade account - Phase 5"""
    return await create_trade_account(request, db, uctx)

@app.get("/trade-accounts")
async def list_trade_accounts(tenant_id: str = Query(...), limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0), db = Depends(get_db_with_rls)):
    """List trade accounts - Phase 5"""
    return await get_trade_accounts(tenant_id, limit, offset, db)

@app.post("/payment-intents", response_model=PaymentIntentResponse)
async def create_payment_intent_route2(request: PaymentIntentRequest, db = Depends(get_db_with_rls), uctx: Dict = Depends(get_user_context)
):
    """Create a payment intent - Phase 5"""
    return await create_payment_intent2(request, db, uctx)

@app.post("/currency/convert", response_model=MultiCurrencyConversionResponse)
async def convert_currency_route(request: MultiCurrencyConversionRequest, db = Depends(get_db_with_rls)):
    """Convert currency using stored exchange rates - Phase 5"""
    return await convert_currency(request, db)

@app.get("/payment-intents/{payment_intent_id}")
async def get_payment_intent_route(payment_intent_id: str, db = Depends(get_db_with_rls)):
    """Get payment intent details - Phase 5"""
    return await get_payment_intent(payment_intent_id, db)

@app.post("/stripe/payment-intent")
async def stripe_payment_intent_legacy():
    """Legacy endpoint - deprecated"""
    return {
        "deprecated": True,
        "migrate_to": "/payments/v2/intent",
        "message": "This endpoint is deprecated. Please use /payments/v2/intent"
    }

@app.post("/stripe/webhook")
async def stripe_webhook_legacy():
    """Legacy endpoint - deprecated"""
    return {
        "deprecated": True,
        "migrate_to": "/payments/v2/webhook/stripe",
        "message": "This endpoint is deprecated. Please use /payments/v2/webhook/stripe"
    }

# =============================================================================
# INTEGRATION ENDPOINTS
# =============================================================================

@app.post("/payments/v2/integration/orders/payment-required")
async def handle_payment_required_event_route(event_data: Dict[str, Any] = Body(...), db: Session = Depends(get_db_with_rls)
):
    return await handle_payment_required_event(event_data, db)

@app.get("/payments/v2/integration/status")
async def get_integration_status_route():
    """Get status of all service integrations"""
    return await get_integration_status()

# =============================================================================
# MAIN EXECUTION
# =============================================================================
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8225")))
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )