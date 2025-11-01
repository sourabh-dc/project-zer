import os
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from services.payments.repositories.database_ops import log_audit, create_customer_db, get_transaction, store_refund, \
    update_transaction_status, handle_payment_success, handle_payment_failure, upsert_provider_config, get_transactions, \
    get_payment_summary, get_daily_payment, create_trade_account_db, get_trade_accounts_db, get_trade_account, \
    create_payment_intent_db, update_payment_intent_status_db, get_current_exchange_rate, get_payment_intent_db
from services.payments.repositories.db_config import  set_rls_context
from services.payments.repositories.payment_provider import StripeProvider
from services.payments.repositories.payment_saga import PaymentIntentSaga
from services.payments.schemas import PaymentIntentRequest, CustomerRequest, RefundRequest, TradeAccountResponse, \
    PaymentIntentResponse, MultiCurrencyConversionResponse
from services.payments.utils.metrics import webhook_requests_total, payment_requests_total
from services.payments.utils.payments_logger import logger
from services.payments.utils.user_auth import check_permission


async def create_payment_intent(request: PaymentIntentRequest, db: Session, user_context: Dict[str, Any]):
    """Create a payment intent with any supported provider"""
    try:
        # Set RLS context
        await set_rls_context(db, request.tenant_id, user_context.get("user_id"))

        # Check permissions
        if not check_permission("payments.create_intent", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        # Execute saga
        saga = PaymentIntentSaga(db)
        result = await saga.create_payment_intent(request)

        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error"))

        # Log audit
        await log_audit(
            db, "create_payment_intent", "payment_intent",
            result.get("payment_intent_id"), request.dict(),
            request.tenant_id, user_context.get("user_id")
        )
        return result

    except Exception as e:
        logger.error(f"Payment intent creation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def create_customer(request: CustomerRequest, db: Session, user_context: Dict[str, Any]):
    """Create or update a customer with any supported provider"""
    try:
        # Set RLS context
        await set_rls_context(db, request.tenant_id, user_context.get("user_id"))

        # Check permissions
        if not check_permission("payments.create_customer", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        # Get provider config
        provider_config = await PaymentIntentSaga(db)._get_provider_config(request.tenant_id, request.provider)
        if not provider_config:
            raise HTTPException(status_code=400, detail="Provider configuration not found")

        # Create customer with provider
        provider = await PaymentIntentSaga(db)._get_provider(request.provider, provider_config)
        provider_result = await provider.create_customer(
            request.email or "",
            request.name,
            request.metadata
        )

        if not provider_result.get("ok"):
            raise HTTPException(status_code=400, detail=provider_result.get("error"))

        # Store customer
        customer = create_customer_db(request, provider_result["customer_id"], db)

        # Log audit
        await log_audit(
            db, "create_customer", "customer",
            provider_result["customer_id"], request.dict(),
            request.tenant_id, user_context.get("user_id")
        )

        return {
            "ok": True,
            "customer_id": provider_result["customer_id"],
            "email": provider_result.get("email"),
            "name": provider_result.get("name")
        }

    except Exception as e:
        logger.error(f"Customer creation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def refund_payment(request: RefundRequest, db: Session, user_context: Dict[str, Any]):
    """Refund a payment"""
    try:
        # Set RLS context
        await set_rls_context(db, request.tenant_id, user_context.get("user_id"))

        # Check permissions
        if not check_permission("payments.refund", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        # Get payment transaction
        transaction = await get_transaction(db, request)

        if not transaction:
            raise HTTPException(status_code=404, detail="Payment transaction not found")

        # Get provider config and create provider instance
        provider_config = await PaymentIntentSaga(db)._get_provider_config(request.tenant_id, transaction.provider)
        provider = await PaymentIntentSaga(db)._get_provider(transaction.provider, provider_config)

        # Process refund with provider
        refund_amount = request.amount_minor or transaction.amount_minor
        provider_result = await provider.refund_payment(
            request.payment_intent_id,
            refund_amount,
            request.reason
        )

        if not provider_result.get("ok"):
            raise HTTPException(status_code=400, detail=provider_result.get("error"))

        # Store refund record
        refund = store_refund(db, transaction, provider_result["refund_id"], refund_amount, request)

        # Update transaction status
        await update_transaction_status(db, transaction, "refunded")

        # Publish event
        await PaymentIntentSaga(db)._publish_event(
            request.tenant_id,
            "PAYMENT_REFUNDED",
            {
                "payment_intent_id": request.payment_intent_id,
                "refund_id": provider_result["refund_id"],
                "amount_minor": refund_amount,
                "currency": transaction.currency
            }
        )

        # Log audit
        await log_audit(
            db, "refund_payment", "payment_refund",
            provider_result["refund_id"], request.dict(),
            request.tenant_id, user_context.get("user_id")
        )

        return {
            "ok": True,
            "refund_id": provider_result["refund_id"],
            "amount_minor": refund_amount,
            "status": "succeeded"
        }

    except Exception as e:
        logger.error(f"Payment refund failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


async def process_webhook(provider: str, request, background_tasks, db: Session):
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
                handle_payment_success,
                db, tenant_id, result
            )
        elif result.get("status") == "failed":
            background_tasks.add_task(
                handle_payment_failure,
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


async def configure_payment_provider(request, db: Session, user_context):
    """Configure payment provider for a tenant"""
    try:
        # Set RLS context
        await set_rls_context(db, request.tenant_id, user_context.get("user_id"))

        # Check permissions
        if not check_permission("payments.admin.configure", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        # Upsert provider configuration
        await upsert_provider_config(db, request)

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


async def fetch_transactions(tenant_id: str, provider, status, limit, offset, db: Session, user_context):
    """List payment transactions with filters"""
    try:
        # Set RLS context
        await set_rls_context(db, tenant_id, user_context.get("user_id"))

        # Check permissions
        if not check_permission("payments.view_transactions", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        transactions = await get_transactions(db, tenant_id, provider, status, limit, offset)

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


async def get_payment_reports(tenant_id: str, period_start: str, period_end: str,
                              currency: Optional[str], db: Session, user_context: Dict[str, Any]
                              ):
    """Get payment reports and analytics (blueprint-inspired)"""
    try:
        # Set RLS context
        await set_rls_context(db, tenant_id, user_context.get("user_id"))

        # Check permissions
        if not check_permission("payments.view_reports", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        # Get payment summary by provider
        summary_result = await get_payment_summary(db, tenant_id, currency, period_start, period_end)

        # Get daily payment trends
        daily_result = await get_daily_payment(db, tenant_id, currency, period_start, period_end)

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

async def create_trade_account(request, db, uctx):
    """Create a new trade account - Phase 5"""
    try:
        payment_requests_total.labels(endpoint="create_trade_account", status="start").inc()

        # Check permissions
        if not check_permission("payments.create", uctx):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        # Generate account number
        account_number = f"TA-{uuid.uuid4().hex[:8].upper()}"

        trade_account = await create_trade_account_db(db, request, uctx, account_number)

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

async def get_trade_accounts(tenant_id: str, limit: int, offset: int, db):
    """List trade accounts - Phase 5"""
    try:
        accounts = await get_trade_accounts_db(db, tenant_id, offset, limit)

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

async def create_payment_intent2(request: PaymentIntentRequest, db, uctx):
    """Create a payment intent - Phase 5"""
    try:
        payment_requests_total.labels(endpoint="create_payment_intent", status="start").inc()

        # Check permissions
        if not check_permission("payments.create", uctx):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        # Check if trade account exists and has sufficient credit
        if request.trade_account_id:
            trade_account = await get_trade_account(db, uctx["tenant_id"], request)

            if not trade_account:
                raise HTTPException(status_code=404, detail="Trade account not found")

            if trade_account.available_credit_minor < request.amount_minor:
                raise HTTPException(status_code=400, detail="Insufficient credit limit")

        # Create payment intent
        payment_intent = await create_payment_intent_db(db, request, uctx)

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

        await update_payment_intent_status_db(db, payment_intent, "processing")

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

async def convert_currency(request, db):
    """Convert currency using stored exchange rates - Phase 5"""
    try:
        payment_requests_total.labels(endpoint="convert_currency", status="start").inc()

        # Get current exchange rate
        rate_record = await get_current_exchange_rate(db, request)

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

async def get_payment_intent(payment_intent_id: str, db: Session):
    """Get payment intent details - Phase 5"""
    try:
        payment_intent = await get_payment_intent_db(db, payment_intent_id)

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


async def handle_payment_required_event(event_data: Dict[str, Any], db: Session):
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
