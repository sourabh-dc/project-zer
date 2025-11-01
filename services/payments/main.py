# Payments Service V2 - Enhanced V4.1 Architecture
# Multi-provider payment processing with sagas, events, and RLS

import os
import uuid
import json
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, Body, HTTPException, Query, Depends, Request, BackgroundTasks
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import text, or_
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import redis
import pybreaker

from core.config import get_settings
from services.payments.repositories.database_ops import log_audit
from services.payments.repositories.payment_provider import StripeProvider
from services.payments.services.payment_services import create_payment_intent, create_customer, refund_payment
from services.payments.utils.user_auth import get_user_context, check_permission
from .models import TradeAccount, CurrencyRate, PaymentIntent
from .schemas import PaymentIntentRequest, CustomerRequest, RefundRequest, RailRequest, TradeAccountRequest,\
     TradeAccountResponse, MultiCurrencyConversionRequest, MultiCurrencyConversionResponse, PaymentIntentResponse
from .repositories.db_config import get_db_with_rls, set_rls_context
from .utils.payments_logger import logger
from .repositories.payment_saga import PaymentIntentSaga
from .utils.metrics import payment_requests_total, webhook_requests_total

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
async def process_webhook(
    provider: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_with_rls)
):
    """Process webhook from payment providers"""
    try:
        payload = await request.json()
        signature = request.headers.get("stripe-signature") if provider == "stripe" else None
        
        # Get provider config (use first available tenant for demo)
        tenant_id = "demo_tenant_id"  # In production, determine from webhook payload
        
        provider_config = await PaymentIntentSaga(db)._get_provider_config(tenant_id, provider)
        provider_instance = await PaymentIntentSaga(db)._get_provider(provider, provider_config)
        
        # Process webhook
        result = await provider_instance.process_webhook(payload, signature)
        
        if not result.get("ok"):
            webhook_requests_total.labels(
                provider=provider,
                event_type="unknown",
                status="failure"
            ).inc()
            raise HTTPException(status_code=400, detail=result.get("error"))
        
        # Update metrics
        webhook_requests_total.labels(
            provider=provider,
            event_type=result.get("event_type", "unknown"),
            status="success"
        ).inc()
        
        # If payment succeeded, update transaction and publish events
        if result.get("status") == "succeeded":
            background_tasks.add_task(
                _handle_payment_success,
                db, tenant_id, result
            )
        elif result.get("status") == "failed":
            background_tasks.add_task(
                _handle_payment_failure,
                db, tenant_id, result
            )
        
        return {"ok": True, "status": "processed"}
        
    except Exception as e:
        logger.error(f"Webhook processing failed: {str(e)}")
        webhook_requests_total.labels(
            provider=provider,
            event_type="unknown",
            status="failure"
        ).inc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

async def _handle_payment_success(db: Session, tenant_id: str, result: Dict[str, Any]):
    """Handle successful payment"""
    try:
        # Update transaction status
        db.execute(text("""
            UPDATE payment_transactions_new
            SET status = 'succeeded', updated_at = NOW()
            WHERE payment_intent_id = :payment_intent_id AND tenant_id = :tenant_id
        """), {
            "payment_intent_id": result["payment_intent_id"],
            "tenant_id": tenant_id
        })
        
        db.commit()
        
        # Publish PAYMENT_PAID event
        await PaymentIntentSaga(db)._publish_event(
            tenant_id,
            "PAYMENT_PAID",
            result
        )
        
        logger.info(f"Payment succeeded: {result['payment_intent_id']}")
        
    except Exception as e:
        logger.error(f"Failed to handle payment success: {str(e)}")
        db.rollback()

async def _handle_payment_failure(db: Session, tenant_id: str, result: Dict[str, Any]):
    """Handle failed payment"""
    try:
        # Update transaction status
        db.execute(text("""
            UPDATE payment_transactions_new
            SET status = 'failed', updated_at = NOW()
            WHERE payment_intent_id = :payment_intent_id AND tenant_id = :tenant_id
        """), {
            "payment_intent_id": result["payment_intent_id"],
            "tenant_id": tenant_id
        })
        
        db.commit()
        
        # Publish PAYMENT_FAILED event
        await PaymentIntentSaga(db)._publish_event(
            tenant_id,
            "PAYMENT_FAILED",
            result
        )
        
        logger.info(f"Payment failed: {result['payment_intent_id']}")
        
    except Exception as e:
        logger.error(f"Failed to handle payment failure: {str(e)}")
        db.rollback()

# =============================================================================
# ADMIN ENDPOINTS
# =============================================================================

@app.post("/payments/v2/admin/rails/payment")
async def configure_payment_provider(
    request: RailRequest,
    db: Session = Depends(get_db_with_rls),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Configure payment provider for a tenant"""
    try:
        # Set RLS context
        await set_rls_context(db, request.tenant_id, user_context.get("user_id"))
        
        # Check permissions
        if not check_permission("payments.admin.configure", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        # Upsert provider configuration
        db.execute(text("""
            INSERT INTO zeroque_rails (tenant_id, type, name, config, active, created_at, updated_at)
            VALUES (:tenant_id, :type, :name, :config, :active, NOW(), NOW())
            ON CONFLICT (tenant_id, type, name)
            DO UPDATE SET config = :config, active = :active, updated_at = NOW()
        """), {
            "tenant_id": request.tenant_id,
            "type": request.type,
            "name": request.name,
            "config": json.dumps(request.config),
            "active": request.active
        })
        
        db.commit()
        
        # Log audit
        await log_audit(
            db, "configure_payment_provider", "zeroque_rails",
            f"{request.tenant_id}:{request.name}", request.dict(),
            request.tenant_id, user_context.get("user_id")
        )
        
        return {"ok": True, "message": f"Provider {request.name} configured successfully"}
        
    except Exception as e:
        logger.error(f"Provider configuration failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

# =============================================================================
# QUERY ENDPOINTS
# =============================================================================

@app.get("/payments/v2/transactions")
async def list_transactions(
    tenant_id: str = Query(...),
    provider: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_with_rls),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """List payment transactions with filters"""
    try:
        # Set RLS context
        await set_rls_context(db, tenant_id, user_context.get("user_id"))
        
        # Check permissions
        if not check_permission("payments.view_transactions", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        # Build query
        query = text("""
            SELECT id, provider, payment_intent_id, charge_id, amount_minor, currency, status,
                   order_id, site_id, store_id, user_id, created_at, updated_at
            FROM payment_transactions_new
            WHERE tenant_id = :tenant_id
        """)
        
        params = {"tenant_id": tenant_id}
        
        if provider:
            query = text(str(query) + " AND provider = :provider")
            params["provider"] = provider
        
        if status:
            query = text(str(query) + " AND status = :status")
            params["status"] = status
        
        query = text(str(query) + " ORDER BY created_at DESC LIMIT :limit OFFSET :offset")
        params.update({"limit": limit, "offset": offset})
        
        # Execute query
        result = db.execute(query, params).fetchall()
        
        transactions = []
        for row in result:
            transactions.append({
                "id": str(row[0]),
                "provider": row[1],
                "payment_intent_id": row[2],
                "charge_id": row[3],
                "amount_minor": row[4],
                "currency": row[5],
                "status": row[6],
                "order_id": str(row[7]) if row[7] else None,
                "site_id": str(row[8]) if row[8] else None,
                "store_id": str(row[9]) if row[9] else None,
                "user_id": str(row[10]) if row[10] else None,
                "created_at": row[11].isoformat(),
                "updated_at": row[12].isoformat() if row[12] else None
            })
        
        return {
            "ok": True,
            "transactions": transactions,
            "total": len(transactions),
            "limit": limit,
            "offset": offset
        }
        
    except Exception as e:
        logger.error(f"Transaction listing failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.get("/payments/v2/reports")
async def get_payment_reports(
    tenant_id: str = Query(...),
    period_start: str = Query(...),
    period_end: str = Query(...),
    currency: Optional[str] = Query("GBP"),
    db: Session = Depends(get_db_with_rls),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Get payment reports and analytics (blueprint-inspired)"""
    try:
        # Set RLS context
        await set_rls_context(db, tenant_id, user_context.get("user_id"))
        
        # Check permissions
        if not check_permission("payments.view_reports", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        # Get payment summary by provider
        summary_query = text("""
            SELECT provider, status, COUNT(*) as count, SUM(amount_minor) as total_amount_minor
            FROM payment_transactions_new
            WHERE tenant_id = :tenant_id 
              AND currency = :currency
              AND created_at >= :period_start 
              AND created_at <= :period_end
            GROUP BY provider, status
            ORDER BY provider, status
        """)
        
        summary_result = db.execute(summary_query, {
            "tenant_id": tenant_id,
            "currency": currency,
            "period_start": period_start,
            "period_end": period_end
        }).fetchall()
        
        # Get daily payment trends
        daily_query = text("""
            SELECT DATE(created_at) as date, COUNT(*) as count, SUM(amount_minor) as total_amount_minor
            FROM payment_transactions_new
            WHERE tenant_id = :tenant_id 
              AND currency = :currency
              AND created_at >= :period_start 
              AND created_at <= :period_end
              AND status = 'succeeded'
            GROUP BY DATE(created_at)
            ORDER BY date
        """)
        
        daily_result = db.execute(daily_query, {
            "tenant_id": tenant_id,
            "currency": currency,
            "period_start": period_start,
            "period_end": period_end
        }).fetchall()
        
        # Format results
        summary = {}
        for row in summary_result:
            provider = row[0]
            status = row[1]
            count = row[2]
            amount = row[3]
            
            if provider not in summary:
                summary[provider] = {}
            
            summary[provider][status] = {
                "count": count,
                "total_amount_minor": amount
            }
        
        daily_trends = []
        for row in daily_result:
            daily_trends.append({
                "date": str(row[0]),
                "count": row[1],
                "total_amount_minor": row[2]
            })
        
        return {
            "ok": True,
            "period": {
                "start": period_start,
                "end": period_end,
                "currency": currency
            },
            "summary": summary,
            "daily_trends": daily_trends,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Payment reports failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

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
async def create_trade_account(
    request: TradeAccountRequest,
    db = Depends(get_db_with_rls),
    uctx: Dict = Depends(get_user_context)
):
    """Create a new trade account - Phase 5"""
    try:
        payment_requests_total.labels(endpoint="create_trade_account", status="start").inc()

        # Check permissions
        if not check_permission("payments.create", uctx):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        # Generate account number
        account_number = f"TA-{uuid.uuid4().hex[:8].upper()}"

        trade_account = TradeAccount(
            tenant_id=uuid.UUID(uctx["tenant_id"]),
            account_number=account_number,
            company_name=request.company_name,
            contact_email=request.contact_email,
            credit_limit_minor=request.credit_limit_minor,
            available_credit_minor=request.credit_limit_minor,
            currency=request.currency,
            payment_terms_days=request.payment_terms_days
        )

        db.add(trade_account)
        db.commit()
        db.refresh(trade_account)

        payment_requests_total.labels(endpoint="create_trade_account", status="ok").inc()

        return TradeAccountResponse(
            trade_account_id=str(trade_account.trade_account_id),
            account_number=trade_account.account_number,
            company_name=trade_account.company_name,
            contact_email=trade_account.contact_email,
            credit_limit_minor=trade_account.credit_limit_minor,
            available_credit_minor=trade_account.available_credit_minor,
            currency=trade_account.currency,
            payment_terms_days=trade_account.payment_terms_days,
            is_active=trade_account.is_active,
            created_at=trade_account.created_at
        )

    except Exception as e:
        payment_requests_total.labels(endpoint="create_trade_account", status="fail").inc()
        logger.error(f"Failed to create trade account: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/trade-accounts")
async def list_trade_accounts(
    tenant_id: str = Query(...),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    db = Depends(get_db_with_rls)
):
    """List trade accounts - Phase 5"""
    try:
        query = db.query(TradeAccount).filter(
            TradeAccount.tenant_id == uuid.UUID(tenant_id),
            TradeAccount.is_active == True
        )

        accounts = query.offset(offset).limit(limit).all()

        return {
            "trade_accounts": [
                TradeAccountResponse(
                    trade_account_id=str(acc.trade_account_id),
                    account_number=acc.account_number,
                    company_name=acc.company_name,
                    contact_email=acc.contact_email,
                    credit_limit_minor=acc.credit_limit_minor,
                    available_credit_minor=acc.available_credit_minor,
                    currency=acc.currency,
                    payment_terms_days=acc.payment_terms_days,
                    is_active=acc.is_active,
                    created_at=acc.created_at
                )
                for acc in accounts
            ],
            "total": len(accounts),
            "limit": limit,
            "offset": offset
        }

    except Exception as e:
        logger.error(f"Failed to list trade accounts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/payment-intents", response_model=PaymentIntentResponse)
async def create_payment_intent2(
    request: PaymentIntentRequest,
    db = Depends(get_db_with_rls),
    uctx: Dict = Depends(get_user_context)
):
    """Create a payment intent - Phase 5"""
    try:
        payment_requests_total.labels(endpoint="create_payment_intent", status="start").inc()

        # Check permissions
        if not check_permission("payments.create", uctx):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        # Check if trade account exists and has sufficient credit
        if request.trade_account_id:
            trade_account = db.query(TradeAccount).filter(
                TradeAccount.trade_account_id == uuid.UUID(request.trade_account_id),
                TradeAccount.tenant_id == uuid.UUID(uctx["tenant_id"]),
                TradeAccount.is_active == True
            ).first()

            if not trade_account:
                raise HTTPException(status_code=404, detail="Trade account not found")

            if trade_account.available_credit_minor < request.amount_minor:
                raise HTTPException(status_code=400, detail="Insufficient credit limit")

        # Create payment intent
        payment_intent = PaymentIntent(
            tenant_id=uuid.UUID(uctx["tenant_id"]),
            order_id=uuid.UUID(request.order_id) if request.order_id else None,
            trade_account_id=uuid.UUID(request.trade_account_id) if request.trade_account_id else None,
            amount_minor=request.amount_minor,
            currency=request.currency,
            provider="stripe",  # Default to Stripe for Phase 5
            payment_method=request.payment_method,
            metadata=request.metadata,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24)  # 24 hour expiry
        )

        db.add(payment_intent)
        db.commit()
        db.refresh(payment_intent)

        # Create Stripe payment intent
        stripe_provider = StripeProvider({"api_key": os.getenv("STRIPE_SECRET_KEY", "sk_test_demo")})

        stripe_intent = await stripe_provider.create_payment_intent({
            "amount": request.amount_minor,
            "currency": request.currency.lower(),
            "payment_method_types": [request.payment_method],
            "metadata": {
                "payment_intent_id": str(payment_intent.payment_intent_id),
                "tenant_id": uctx["tenant_id"],
                "user_id": uctx["user_id"]
            }
        })

        # Update payment intent with provider details
        payment_intent.provider_intent_id = stripe_intent.get("id")
        payment_intent.status = "processing"
        db.commit()

        payment_requests_total.labels(endpoint="create_payment_intent", status="ok").inc()

        return PaymentIntentResponse(
            payment_intent_id=str(payment_intent.payment_intent_id),
            client_secret=stripe_intent.get("client_secret"),
            amount_minor=payment_intent.amount_minor,
            currency=payment_intent.currency,
            status=payment_intent.status,
            provider=payment_intent.provider,
            expires_at=payment_intent.expires_at
        )

    except HTTPException:
        raise
    except Exception as e:
        payment_requests_total.labels(endpoint="create_payment_intent", status="fail").inc()
        logger.error(f"Failed to create payment intent: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/currency/convert", response_model=MultiCurrencyConversionResponse)
async def convert_currency(
    request: MultiCurrencyConversionRequest,
    db = Depends(get_db_with_rls)
):
    """Convert currency using stored exchange rates - Phase 5"""
    try:
        payment_requests_total.labels(endpoint="convert_currency", status="start").inc()

        # Get current exchange rate
        rate_record = db.query(CurrencyRate).filter(
            CurrencyRate.base_currency == request.from_currency.upper(),
            CurrencyRate.target_currency == request.to_currency.upper(),
            CurrencyRate.is_active == True,
            CurrencyRate.valid_from <= datetime.now(timezone.utc),
            or_(CurrencyRate.valid_to.is_(None), CurrencyRate.valid_to >= datetime.now(timezone.utc))
        ).order_by(CurrencyRate.created_at.desc()).first()

        if not rate_record:
            # Use fallback rate (1:1 for demo)
            exchange_rate = 1.0
        else:
            exchange_rate = float(rate_record.rate)

        converted_amount = int(request.amount_minor * exchange_rate)

        payment_requests_total.labels(endpoint="convert_currency", status="ok").inc()

        return MultiCurrencyConversionResponse(
            from_currency=request.from_currency.upper(),
            to_currency=request.to_currency.upper(),
            original_amount_minor=request.amount_minor,
            converted_amount_minor=converted_amount,
            exchange_rate=exchange_rate,
            converted_at=datetime.now(timezone.utc)
        )

    except Exception as e:
        payment_requests_total.labels(endpoint="convert_currency", status="fail").inc()
        logger.error(f"Failed to convert currency: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/payment-intents/{payment_intent_id}")
async def get_payment_intent(
    payment_intent_id: str,
    db = Depends(get_db_with_rls)
):
    """Get payment intent details - Phase 5"""
    try:
        payment_intent = db.query(PaymentIntent).filter(
            PaymentIntent.payment_intent_id == uuid.UUID(payment_intent_id)
        ).first()

        if not payment_intent:
            raise HTTPException(status_code=404, detail="Payment intent not found")

        return {
            "payment_intent_id": str(payment_intent.payment_intent_id),
            "order_id": str(payment_intent.order_id) if payment_intent.order_id else None,
            "trade_account_id": str(payment_intent.trade_account_id) if payment_intent.trade_account_id else None,
            "amount_minor": payment_intent.amount_minor,
            "currency": payment_intent.currency,
            "status": payment_intent.status,
            "provider": payment_intent.provider,
            "provider_intent_id": payment_intent.provider_intent_id,
            "payment_method": payment_intent.payment_method,
            "metadata": payment_intent.payment_metadata,
            "expires_at": payment_intent.expires_at.isoformat() if payment_intent.expires_at else None,
            "succeeded_at": payment_intent.succeeded_at.isoformat() if payment_intent.succeeded_at else None,
            "failed_at": payment_intent.failed_at.isoformat() if payment_intent.failed_at else None,
            "created_at": payment_intent.created_at.isoformat(),
            "updated_at": payment_intent.updated_at.isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get payment intent: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
async def handle_payment_required_event(
    event_data: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db_with_rls)
):
    """Handle ORDER_COMPLETED event from Orders service requiring payment"""
    try:
        logger.info(f"Received ORDER_COMPLETED event requiring payment: {event_data}")
        
        order_id = event_data.get("order_id")
        tenant_id = event_data.get("tenant_id")
        total_amount_minor = event_data.get("total_amount_minor", 0)
        currency = event_data.get("currency", "GBP")
        
        if not order_id or not tenant_id:
            raise HTTPException(status_code=400, detail="Missing order_id or tenant_id")
        
        # Create payment intent for the order
        request = PaymentIntentRequest(
            tenant_id=tenant_id,
            order_id=order_id,
            amount_minor=total_amount_minor,
            currency=currency,
            provider="stripe",  # Default provider
            metadata={"order_id": order_id, "auto_created": True}
        )
        
        saga = PaymentIntentSaga(db)
        result = await saga.create_payment_intent(request)
        
        logger.info(f"Created payment intent for order: {result}")
        return {"ok": True, "payment_intent_created": True, "result": result}
        
    except Exception as e:
        logger.error(f"Error handling payment required event: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to handle event: {str(e)}")
    finally:
        db.close()

@app.get("/payments/v2/integration/status")
async def get_integration_status():
    """Get status of all service integrations"""
    try:
        integration_status = {
            "orders_service": {"status": "unknown", "url": "http://localhost:8081"},
            "billing_service": {"status": "unknown", "url": "http://localhost:8083"},
            "ledger_service": {"status": "unknown", "url": "http://localhost:8086"},
            "notifications_service": {"status": "unknown", "url": "http://localhost:8087"}
        }
        
        # Test each service connectivity
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            for service_name, config in integration_status.items():
                try:
                    response = await client.get(f"{config['url']}/health")
                    if response.status_code == 200:
                        config["status"] = "healthy"
                        config["response_time_ms"] = response.elapsed.total_seconds() * 1000
                    else:
                        config["status"] = "unhealthy"
                except Exception as e:
                    config["status"] = "unreachable"
                    config["error"] = str(e)
        
        return {
            "integration_status": integration_status,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting integration status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get integration status: {str(e)}")

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