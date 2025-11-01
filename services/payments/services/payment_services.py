from typing import Dict, Any
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from services.payments.repositories.database_ops import log_audit, create_customer_db, get_transaction, store_refund, \
    update_transaction_status, handle_payment_success, handle_payment_failure, upsert_provider_config, get_transactions
from services.payments.repositories.db_config import  set_rls_context
from services.payments.repositories.payment_saga import PaymentIntentSaga
from services.payments.schemas import PaymentIntentRequest, CustomerRequest, RefundRequest
from services.payments.utils.metrics import webhook_requests_total
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
