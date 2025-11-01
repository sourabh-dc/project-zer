import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from sqlalchemy import text, or_
from sqlalchemy.orm import Session

from services.payments.models import AuditLog, CustomerNew, PaymentTransactionNew, PaymentRefund, TradeAccount, \
    PaymentIntent, CurrencyRate
from services.payments.repositories.payment_saga import PaymentIntentSaga
from services.payments.utils.payments_logger import logger


async def log_audit(db: Session, action: str, resource_type: str, resource_id: str = None,
                   details: Dict[str, Any] = None, tenant_id: str = None, user_id: str = None):
    """Log audit event"""
    audit_log = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details
    )
    db.add(audit_log)
    db.commit()

async def create_customer_db(request, external_cust_id,  db: Session):
    customer = CustomerNew(
        tenant_id=request.tenant_id,
        provider=request.provider,
        external_customer_id=external_cust_id,
        email=request.email,
        name=request.name,
        phone=request.metadata.get("phone") if request.metadata else None
    )
    db.add(customer)
    db.commit()
    return customer

async def get_transaction(db: Session, request) :
    transaction = db.query(PaymentTransactionNew).filter(
        PaymentTransactionNew.payment_intent_id == request.payment_intent_id,
        PaymentTransactionNew.tenant_id == request.tenant_id
    ).first()

    return transaction

async def store_refund(db, transaction, refund_id, refund_amount, request):
    # Store refund record
    refund = PaymentRefund(
        tenant_id=request.tenant_id,
        payment_transaction_id=transaction.id,
        refund_id=refund_id,
        amount_minor=refund_amount,
        currency=transaction.currency,
        reason=request.reason,
        status="succeeded"
    )
    db.add(refund)
    db.commit()
    return refund

async def update_transaction_status(db, transaction, status):
    transaction.status = status
    db.commit()

async def handle_payment_success(db: Session, tenant_id: str, result: Dict[str, Any]):
    """Handle successful payment"""
    try:
        # Update transaction status
        db.execute(text("""
                        UPDATE payment_transactions_new
                        SET status     = 'succeeded',
                            updated_at = NOW()
                        WHERE payment_intent_id = :payment_intent_id
                          AND tenant_id = :tenant_id
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


async def handle_payment_failure(db: Session, tenant_id: str, result: Dict[str, Any]):
    """Handle failed payment"""
    try:
        # Update transaction status
        db.execute(text("""
                        UPDATE payment_transactions_new
                        SET status     = 'failed',
                            updated_at = NOW()
                        WHERE payment_intent_id = :payment_intent_id
                          AND tenant_id = :tenant_id
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

async def upsert_provider_config(db, request):
    # Upsert provider configuration
    db.execute(text("""
                    INSERT INTO zeroque_rails (tenant_id, type, name, config, active, created_at, updated_at)
                    VALUES (:tenant_id, :type, :name, :config, :active, NOW(), NOW()) ON CONFLICT (tenant_id, type, name)
                DO
                    UPDATE SET config = :config, active = :active, updated_at = NOW()
                    """), {
                   "tenant_id": request.tenant_id,
                   "type": request.type,
                   "name": request.name,
                   "config": json.dumps(request.config),
                   "active": request.active
               })

    db.commit()

async def get_transactions(db, tenant_id: str, provider, status, limit, offset):
    # Build query
    query = text("""
                 SELECT id, provider, payment_intent_id, charge_id, amount_minor, currency, status, order_id,
                        site_id, store_id, user_id, created_at, updated_at
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

    return transactions

async def get_payment_summary(db: Session, tenant_id: str, currency: str, period_start: str, period_end: str):
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
    return summary_result

async def get_daily_payment(db, tenant_id: str, currency: str, period_start: str, period_end: str):
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

    return daily_result

async def create_trade_account_db(db, request, uctx, account_number: str):
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

    return trade_account

async def get_trade_accounts_db(db, tenant_id: str, offset: int, limit: int):
    query = db.query(TradeAccount).filter(
        TradeAccount.tenant_id == uuid.UUID(tenant_id),
        TradeAccount.is_active == True
    )
    accounts = query.offset(offset).limit(limit).all()
    return accounts

async def get_trade_account(db, tenant_id: str, request):
    trade_account = db.query(TradeAccount).filter(
        TradeAccount.trade_account_id == uuid.UUID(request.trade_account_id),
        TradeAccount.tenant_id == tenant_id,
        TradeAccount.is_active == True
    ).first()
    return trade_account

async def create_payment_intent_db(db, request, uctx):
    payment_intent = PaymentIntent(
        tenant_id=uuid.UUID(uctx["tenant_id"]),
        order_id=uuid.UUID(request.order_id) if request.order_id else None,
        trade_account_id=uuid.UUID(request.trade_account_id) if request.trade_account_id else None,
        amount_minor=request.amount_minor,
        currency=request.currency,
        provider="stripe",  # Default to Stripe for Phase 5
        payment_method=request.payment_method,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24)  # 24 hour expiry
    )

    db.add(payment_intent)
    db.commit()
    db.refresh(payment_intent)
    return payment_intent

async def update_payment_intent_status_db(db, payment_intent, status):
    payment_intent.status = status
    db.commit()
    db.refresh(payment_intent)
    return payment_intent

async def get_current_exchange_rate(db, request):
    rate = db.query(CurrencyRate).filter(
        CurrencyRate.base_currency == request.from_currency.upper(),
        CurrencyRate.target_currency == request.to_currency.upper(),
        CurrencyRate.is_active == True,
        CurrencyRate.valid_from <= datetime.now(timezone.utc),
        or_(CurrencyRate.valid_to.is_(None), CurrencyRate.valid_to >= datetime.now(timezone.utc))
    ).order_by(CurrencyRate.created_at.desc()).first()

    return rate

async def get_payment_intent_db(db, payment_intent_id: str):
    payment_intent = db.query(PaymentIntent).filter(
            PaymentIntent.payment_intent_id == uuid.UUID(payment_intent_id)
        ).first()
    return payment_intent