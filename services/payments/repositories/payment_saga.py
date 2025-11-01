from typing import Dict, Any, Optional
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.payments.models import PaymentTransactionNew
from services.payments.schemas import PaymentIntentRequest
from ..utils.metrics import payment_requests_total, payment_amount_total, payment_duration_seconds
from ..utils.payments_logger import logger
from ..models import OutboxEvent
from .payment_provider import BasePaymentProvider, StripeProvider


# =============================================================================
# SAGA IMPLEMENTATION
# =============================================================================

class PaymentIntentSaga:
    """Saga for payment intent creation with compensation"""

    def __init__(self, db: Session):
        self.db = db
        self.steps = []
        self.compensation_steps = []

    async def create_payment_intent(self, request: PaymentIntentRequest) -> Dict[str, Any]:
        """Execute payment intent creation saga"""
        start_time = datetime.now()

        try:
            # Step 1: Validate tenant and get provider config
            provider_config = await self._get_provider_config(request.tenant_id, request.provider)
            if not provider_config:
                return {"ok": False, "error": "Provider configuration not found"}

            # Step 2: Create payment intent with provider
            provider = await self._get_provider(request.provider, provider_config)
            provider_result = await provider.create_payment_intent(
                request.amount_minor,
                request.currency,
                request.metadata
            )

            if not provider_result.get("ok"):
                return {"ok": False, "error": provider_result.get("error")}

            # Step 3: Store payment transaction
            transaction = PaymentTransactionNew(
                tenant_id=request.tenant_id,
                vendor_id=request.metadata.get("vendor_id") if request.metadata else None,
                provider=request.provider,
                payment_intent_id=provider_result["payment_intent_id"],
                amount_minor=request.amount_minor,
                currency=request.currency,
                status="pending",
                order_id=request.order_id,
                site_id=request.site_id,
                store_id=request.store_id,
                user_id=request.user_id,
                transaction_metadata=request.metadata,
                raw_response=provider_result
            )

            self.db.add(transaction)
            self.db.commit()

            # Step 4: Publish event
            await self._publish_event(
                request.tenant_id,
                "PAYMENT_CREATED",
                {
                    "payment_intent_id": provider_result["payment_intent_id"],
                    "amount_minor": request.amount_minor,
                    "currency": request.currency,
                    "provider": request.provider,
                    "order_id": request.order_id
                }
            )

            # Update metrics
            payment_requests_total.labels(
                provider=request.provider,
                status="success",
                currency=request.currency
            ).inc()

            payment_amount_total.labels(
                provider=request.provider,
                currency=request.currency
            ).inc(request.amount_minor)

            duration = (datetime.now() - start_time).total_seconds()
            payment_duration_seconds.labels(
                provider=request.provider,
                operation="create_intent"
            ).observe(duration)

            return {
                "ok": True,
                "payment_intent_id": provider_result["payment_intent_id"],
                "client_secret": provider_result.get("client_secret"),
                "status": provider_result.get("status"),
                "transaction_id": str(transaction.id)
            }

        except Exception as e:
            logger.error(f"Payment intent saga failed: {str(e)}")
            await self._compensate()

            payment_requests_total.labels(
                provider=request.provider,
                status="failure",
                currency=request.currency
            ).inc()

            return {"ok": False, "error": str(e)}

    async def _get_provider_config(self, tenant_id: str, provider: str) -> Optional[Dict[str, Any]]:
        """Get provider configuration from zeroque_rails"""
        result = self.db.execute(text("""
                                      SELECT config
                                      FROM zeroque_rails
                                      WHERE tenant_id = :tenant_id
                                        AND type = 'payment'
                                        AND name = :provider
                                        AND active = true
                                      """), {"tenant_id": tenant_id, "provider": provider}).first()

        return result[0] if result else None

    async def _get_provider(self, provider_name: str, config: Dict[str, Any]) -> BasePaymentProvider:
        """Get provider instance based on name"""
        if provider_name == "stripe":
            return StripeProvider(config)
        else:
            raise ValueError(f"Unsupported payment provider: {provider_name}")

    async def _publish_event(self, tenant_id: str, event_type: str, event_data: Dict[str, Any]):
        """Publish event to outbox"""
        event = OutboxEvent(
            tenant_id=tenant_id,
            event_type=event_type,
            event_data=event_data,
            status="pending"
        )
        self.db.add(event)
        self.db.commit()

    async def _compensate(self):
        """Execute compensation steps"""
        # Rollback any changes made during the saga
        self.db.rollback()
        logger.info("Payment intent saga compensation executed")