from typing import Dict, Any
import uuid

from core.config import get_settings
from ..utils.payments_logger import logger

ALLOW_DEMO = get_settings().ALLOW_DEMO
# =============================================================================
# PAYMENT PROVIDERS
# =============================================================================

class BasePaymentProvider:
    """Base class for payment providers"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.api_key = config.get('api_key')
        self.base_url = config.get('base_url')

    async def create_payment_intent(self, amount_minor: int, currency: str, metadata: Dict[str, Any] = None) -> Dict[
        str, Any]:
        """Create a payment intent with the provider"""
        raise NotImplementedError

    async def create_customer(self, email: str, name: str = None, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """Create a customer with the provider"""
        raise NotImplementedError

    async def process_webhook(self, payload: Dict[str, Any], signature: str = None) -> Dict[str, Any]:
        """Process webhook from the provider"""
        raise NotImplementedError

    async def refund_payment(self, payment_intent_id: str, amount_minor: int = None, reason: str = None) -> Dict[
        str, Any]:
        """Refund a payment"""
        raise NotImplementedError


class StripeProvider(BasePaymentProvider):
    """Stripe payment provider implementation"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        import stripe
        stripe.api_key = self.api_key
        self.stripe = stripe

    async def create_payment_intent(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a Stripe payment intent - Phase 5"""
        try:
            # Demo mode: return mock response
            if ALLOW_DEMO:
                return {
                    "id": f"pi_demo_{uuid.uuid4().hex[:16]}",
                    "client_secret": f"pi_demo_{uuid.uuid4().hex[:16]}_secret_{uuid.uuid4().hex[:16]}",
                    "amount": intent_data.get("amount", 0),
                    "currency": intent_data.get("currency", "gbp"),
                    "status": "requires_payment_method",
                    "metadata": intent_data.get("metadata", {})
                }

            # Production: Create real Stripe payment intent
            payment_intent = self.stripe.PaymentIntent.create(
                amount=intent_data.get("amount", 0),
                currency=intent_data.get("currency", "gbp").lower(),
                payment_method_types=intent_data.get("payment_method_types", ["card"]),
                metadata=intent_data.get("metadata", {})
            )
            return {
                "id": payment_intent.id,
                "client_secret": payment_intent.client_secret,
                "amount": payment_intent.amount,
                "currency": payment_intent.currency,
                "status": payment_intent.status,
                "metadata": payment_intent.payment_metadata
            }
        except Exception as e:
            logger.error(f"Stripe payment intent creation failed: {str(e)}")
            return {"ok": False, "error": str(e)}

    async def create_customer(self, email: str, name: str = None, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """Create a Stripe customer"""
        try:
            customer = self.stripe.Customer.create(
                email=email,
                name=name,
                metadata=metadata or {}
            )
            return {
                "ok": True,
                "customer_id": customer.id,
                "email": customer.email,
                "name": customer.name
            }
        except Exception as e:
            logger.error(f"Stripe customer creation failed: {str(e)}")
            return {"ok": False, "error": str(e)}

    async def process_webhook(self, payload: Dict[str, Any], signature: str = None) -> Dict[str, Any]:
        """Process Stripe webhook"""
        try:
            # In production, verify webhook signature
            event_type = payload.get('type')
            data = payload.get('data', {}).get('object', {})

            if event_type == 'payment_intent.succeeded':
                return {
                    "ok": True,
                    "event_type": event_type,
                    "payment_intent_id": data.get('id'),
                    "status": "succeeded",
                    "amount_minor": data.get('amount'),
                    "currency": data.get('currency')
                }
            elif event_type == 'payment_intent.payment_failed':
                return {
                    "ok": True,
                    "event_type": event_type,
                    "payment_intent_id": data.get('id'),
                    "status": "failed",
                    "error": data.get('last_payment_error', {}).get('message')
                }

            return {"ok": True, "event_type": event_type, "status": "ignored"}

        except Exception as e:
            logger.error(f"Stripe webhook processing failed: {str(e)}")
            return {"ok": False, "error": str(e)}

    async def refund_payment(self, payment_intent_id: str, amount_minor: int = None, reason: str = None) -> Dict[
        str, Any]:
        """Refund a Stripe payment"""
        try:
            refund_data = {
                'payment_intent': payment_intent_id,
                'reason': reason or 'requested_by_customer'
            }
            if amount_minor:
                refund_data['amount'] = amount_minor

            refund = self.stripe.Refund.create(**refund_data)
            return {
                "ok": True,
                "refund_id": refund.id,
                "amount_minor": refund.amount,
                "status": refund.status
            }
        except Exception as e:
            logger.error(f"Stripe refund failed: {str(e)}")
            return {"ok": False, "error": str(e)}