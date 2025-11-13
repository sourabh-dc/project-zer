import uuid
from typing import Optional
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException, Query, Depends, Request, APIRouter
from sqlalchemy import text
from sqlalchemy.orm import Session

from Models import PaymentTransaction, PaymentIntent, Customer, PaymentRefund, PaymentAdjustment, TradeAccount, \
    CurrencyRate, PaymentWebhook
from Schemas import PaymentIntentRequest, PaymentIntentResponse, CustomerRequest, RefundRequest, \
    PaymentAdjustmentRequest, TradeAccountResponse, TradeAccountRequest, MultiCurrencyConversionRequest, \
    MultiCurrencyConversionResponse
from core.db_config import get_db

app = APIRouter()
# =============================================================================
# PAYMENT INTENT ENDPOINTS
# =============================================================================

@app.post("/payments/v2/intent")
async def create_payment_intent(
        request: PaymentIntentRequest,
        db: Session = Depends(get_db)
):
    """Create a payment intent"""
    try:
        payment_intent_id = f"pi_{uuid.uuid4().hex[:16]}"

        transaction = PaymentTransaction(
            tenant_id=uuid.UUID(request.tenant_id),
            provider=request.provider,
            payment_intent_id=payment_intent_id,
            amount_minor=request.amount_minor,
            currency=request.currency,
            status="pending",
            order_id=uuid.UUID(request.order_id) if request.order_id else None,
            site_id=uuid.UUID(request.site_id) if request.site_id else None,
            store_id=uuid.UUID(request.store_id) if request.store_id else None,
            user_id=uuid.UUID(request.user_id) if request.user_id else None,
            transaction_metadata=request.metadata,
            raw_response={"status": "pending"}
        )

        db.add(transaction)
        db.commit()
        db.refresh(transaction)

        return {
            "ok": True,
            "payment_intent_id": payment_intent_id,
            "client_secret": f"{payment_intent_id}_secret_{uuid.uuid4().hex[:16]}",
            "status": "pending",
            "transaction_id": str(transaction.id)
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/payment-intents/{payment_intent_id}")
async def get_payment_intent(
        payment_intent_id: str,
        db: Session = Depends(get_db)
):
    """Get payment intent details"""
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
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/payment-intents")
async def create_payment_intent_v2(
        request: PaymentIntentRequest,
        db: Session = Depends(get_db)
):
    """Create a payment intent - Phase 5"""
    try:
        payment_intent = PaymentIntent(
            tenant_id=uuid.UUID(request.tenant_id),
            order_id=uuid.UUID(request.order_id) if request.order_id else None,
            amount_minor=request.amount_minor,
            currency=request.currency,
            provider=request.provider,
            payment_method="card",
            payment_metadata=request.metadata,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24)
        )

        db.add(payment_intent)
        db.commit()
        db.refresh(payment_intent)

        return PaymentIntentResponse(
            payment_intent_id=str(payment_intent.payment_intent_id),
            client_secret=f"{payment_intent.payment_intent_id}_secret_{uuid.uuid4().hex[:16]}",
            amount_minor=payment_intent.amount_minor,
            currency=payment_intent.currency,
            status=payment_intent.status,
            provider=payment_intent.provider,
            expires_at=payment_intent.expires_at
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CUSTOMER ENDPOINTS
# =============================================================================

@app.post("/payments/v2/customers")
async def create_customer(
        request: CustomerRequest,
        db: Session = Depends(get_db)
):
    """Create or update a customer"""
    try:
        external_customer_id = f"cus_{uuid.uuid4().hex[:16]}"

        customer = Customer(
            tenant_id=uuid.UUID(request.tenant_id),
            provider=request.provider,
            external_customer_id=external_customer_id,
            email=request.email,
            name=request.name,
            phone=request.phone,
            transaction_metadata=request.metadata
        )

        db.add(customer)
        db.commit()
        db.refresh(customer)

        return {
            "ok": True,
            "customer_id": external_customer_id,
            "email": request.email,
            "name": request.name
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# REFUND ENDPOINTS
# =============================================================================

@app.post("/payments/v2/refund")
async def refund_payment(
        request: RefundRequest,
        db: Session = Depends(get_db)
):
    """Refund a payment"""
    try:
        transaction = db.query(PaymentTransaction).filter(
            PaymentTransaction.payment_intent_id == request.payment_intent_id,
            PaymentTransaction.tenant_id == uuid.UUID(request.tenant_id)
        ).first()

        if not transaction:
            raise HTTPException(status_code=404, detail="Payment transaction not found")

        refund_amount = request.amount_minor or transaction.amount_minor
        refund_id = f"ref_{uuid.uuid4().hex[:16]}"

        refund = PaymentRefund(
            tenant_id=uuid.UUID(request.tenant_id),
            payment_transaction_id=transaction.id,
            refund_id=refund_id,
            amount_minor=refund_amount,
            currency=transaction.currency,
            reason=request.reason,
            status="succeeded"
        )

        db.add(refund)
        transaction.status = "refunded"
        db.commit()

        return {
            "ok": True,
            "refund_id": refund_id,
            "amount_minor": refund_amount,
            "status": "succeeded"
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ADJUSTMENT ENDPOINTS
# =============================================================================

@app.post("/payments/v2/adjustment")
async def create_adjustment(
        request: PaymentAdjustmentRequest,
        db: Session = Depends(get_db)
):
    """Create a payment adjustment"""
    try:
        transaction = db.query(PaymentTransaction).filter(
            PaymentTransaction.payment_intent_id == request.payment_intent_id,
            PaymentTransaction.tenant_id == uuid.UUID(request.tenant_id)
        ).first()

        if not transaction:
            raise HTTPException(status_code=404, detail="Payment transaction not found")

        adjustment = PaymentAdjustment(
            tenant_id=uuid.UUID(request.tenant_id),
            payment_transaction_id=transaction.id,
            adjustment_type=request.adjustment_type,
            adjustment_amount_minor=request.amount_minor,
            adjustment_reason=request.reason,
            currency=request.currency,
            is_applied=True,
            applied_at=datetime.now(timezone.utc)
        )

        db.add(adjustment)
        db.commit()
        db.refresh(adjustment)

        return {
            "ok": True,
            "adjustment_id": str(adjustment.id),
            "type": request.adjustment_type,
            "amount_minor": request.amount_minor,
            "status": "applied"
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# TRADE ACCOUNT ENDPOINTS
# =============================================================================

@app.post("/trade-accounts", response_model=TradeAccountResponse)
async def create_trade_account(
        request: TradeAccountRequest,
        db: Session = Depends(get_db)
):
    """Create a new trade account"""
    try:
        account_number = f"TA-{uuid.uuid4().hex[:8].upper()}"

        trade_account = TradeAccount(
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
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/trade-accounts")
async def list_trade_accounts(
        tenant_id: str = Query(...),
        limit: int = Query(100, le=1000),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db)
):
    """List trade accounts"""
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
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CURRENCY CONVERSION ENDPOINTS
# =============================================================================

@app.post("/currency/convert", response_model=MultiCurrencyConversionResponse)
async def convert_currency(
        request: MultiCurrencyConversionRequest,
        db: Session = Depends(get_db)
):
    """Convert currency using stored exchange rates"""
    try:
        rate_record = db.query(CurrencyRate).filter(
            CurrencyRate.base_currency == request.from_currency.upper(),
            CurrencyRate.target_currency == request.to_currency.upper(),
            CurrencyRate.is_active == True,
            CurrencyRate.valid_from <= datetime.now(timezone.utc)
        ).order_by(CurrencyRate.created_at.desc()).first()

        if not rate_record:
            exchange_rate = 1.0
        else:
            exchange_rate = float(rate_record.rate)

        converted_amount = int(request.amount_minor * exchange_rate)

        return MultiCurrencyConversionResponse(
            from_currency=request.from_currency.upper(),
            to_currency=request.to_currency.upper(),
            original_amount_minor=request.amount_minor,
            converted_amount_minor=converted_amount,
            exchange_rate=exchange_rate,
            converted_at=datetime.now(timezone.utc)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# TRANSACTION QUERY ENDPOINTS
# =============================================================================

@app.get("/payments/v2/transactions")
async def list_transactions(
        tenant_id: str = Query(...),
        provider: Optional[str] = Query(None),
        status: Optional[str] = Query(None),
        limit: int = Query(100, le=1000),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db)
):
    """List payment transactions with filters"""
    try:
        query = db.query(PaymentTransaction).filter(
            PaymentTransaction.tenant_id == uuid.UUID(tenant_id)
        )

        if provider:
            query = query.filter(PaymentTransaction.provider == provider)

        if status:
            query = query.filter(PaymentTransaction.status == status)

        transactions = query.order_by(PaymentTransaction.created_at.desc()).offset(offset).limit(limit).all()

        return {
            "ok": True,
            "transactions": [
                {
                    "id": str(t.id),
                    "provider": t.provider,
                    "payment_intent_id": t.payment_intent_id,
                    "charge_id": t.charge_id,
                    "amount_minor": t.amount_minor,
                    "currency": t.currency,
                    "status": t.status,
                    "order_id": str(t.order_id) if t.order_id else None,
                    "site_id": str(t.site_id) if t.site_id else None,
                    "store_id": str(t.store_id) if t.store_id else None,
                    "user_id": str(t.user_id) if t.user_id else None,
                    "created_at": t.created_at.isoformat(),
                    "updated_at": t.updated_at.isoformat() if t.updated_at else None
                }
                for t in transactions
            ],
            "total": len(transactions),
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/payments/v2/reports")
async def get_payment_reports(
        tenant_id: str = Query(...),
        period_start: str = Query(...),
        period_end: str = Query(...),
        currency: Optional[str] = Query("GBP"),
        db: Session = Depends(get_db)
):
    """Get payment reports and analytics"""
    try:
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

        daily_query = text("""
                           SELECT DATE (created_at) as date, COUNT (*) as count, SUM (amount_minor) as total_amount_minor
                           FROM payment_transactions_new
                           WHERE tenant_id = :tenant_id
                             AND currency = :currency
                             AND created_at >= :period_start
                             AND created_at <= :period_end
                             AND status = 'succeeded'
                           GROUP BY DATE (created_at)
                           ORDER BY date
                           """)

        daily_result = db.execute(daily_query, {
            "tenant_id": tenant_id,
            "currency": currency,
            "period_start": period_start,
            "period_end": period_end
        }).fetchall()

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
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# WEBHOOK ENDPOINTS
# =============================================================================

@app.post("/payments/v2/webhook/{provider}")
async def process_webhook(
        provider: str,
        request: Request,
        db: Session = Depends(get_db)
):
    """Process webhook from payment providers"""
    try:
        payload = await request.json()

        webhook = PaymentWebhook(
            tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
            provider=provider,
            event_type=payload.get("type", "unknown"),
            event_data=payload,
            processed=True,
            processed_at=datetime.now(timezone.utc)
        )

        db.add(webhook)
        db.commit()

        return {"ok": True, "status": "processed"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# LEGACY ENDPOINTS
# =============================================================================

@app.post("/stripe/customers")
async def stripe_customers_legacy():
    """Legacy endpoint - deprecated"""
    return {
        "deprecated": True,
        "migrate_to": "/payments/v2/customers",
        "message": "This endpoint is deprecated. Please use /payments/v2/customers"
    }


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

