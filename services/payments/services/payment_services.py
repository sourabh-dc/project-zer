from typing import Dict, Any
from fastapi import HTTPException
from sqlalchemy.orm import Session

from services.payments.repositories.database_ops import log_audit, create_customer_db, get_transaction, store_refund, \
    update_transaction_status
from services.payments.repositories.db_config import  set_rls_context
from services.payments.repositories.payment_saga import PaymentIntentSaga
from services.payments.schemas import PaymentIntentRequest, CustomerRequest, RefundRequest
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