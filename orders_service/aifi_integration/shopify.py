"""AiFi Push API — incoming webhook event handlers.

AiFi sends push events to a pre-configured endpoint on our service.
Each handler receives the parsed payload, performs any necessary side-effects
(logging, persistence, downstream notification), and returns an acknowledgement.

Add domain logic here (e.g. persisting orders, emitting internal events)
without touching the endpoint controllers in aifi_push_routes.py.
"""
from __future__ import annotations

import logging
from typing import Any

from .schemas import (
    PushCartMutatorPayload,
    PushCheckoutPayload,
    PushCustomerPayload,
    PushEntryCodePayload,
    PushEvaluateOrderPricePayload,
    PushHealthPayload,
    PushIdentityMatchingPayload,
    PushRestrictedProductsPayload,
    PushTrackingPayload,
    PushTransitionPayload,
)

logger = logging.getLogger("orders-service.aifi.push")

_ACK: dict[str, Any] = {"status": "received"}


async def handle_push_checkout(payload: PushCheckoutPayload) -> dict[str, Any]:
    """Handle push-checkout events from AiFi.

    Triggered when a customer's cart is checked out.
    Extend here: persist the order, trigger payment flow, emit outbox event.
    """
    logger.info(
        "Push checkout — orderId=%s customerId=%s total=%s",
        payload.order_id,
        payload.customer_id,
        payload.total,
    )
    return _ACK


async def handle_push_customer(payload: PushCustomerPayload) -> dict[str, Any]:
    """Handle push-customer events (created / updated) from AiFi.

    Extend here: sync customer record to local DB, send welcome email, etc.
    """
    logger.info(
        "Push customer — event=%s customerId=%s email=%s externalId=%s",
        payload.event,
        payload.customer_id,
        payload.email,
        payload.external_id,
    )
    return _ACK


async def handle_push_entry_code(payload: PushEntryCodePayload) -> dict[str, Any]:
    """Handle push-entry-codes events from AiFi.

    Triggered when an entry code is created or validated.
    Extend here: notify the customer, update session state.
    """
    logger.info(
        "Push entry code — code=%s customerId=%s storeId=%s",
        payload.code,
        payload.customer_id,
        payload.store_id,
    )
    return _ACK


async def handle_push_tracking(payload: PushTrackingPayload) -> dict[str, Any]:
    """Handle push-tracking events (shopper position updates) from AiFi.

    High-frequency; use DEBUG level logging in production.
    """
    logger.debug(
        "Push tracking — shopperId=%s storeId=%s",
        payload.shopper_id,
        payload.store_id,
    )
    return _ACK


async def handle_push_identity_matching(payload: PushIdentityMatchingPayload) -> dict[str, Any]:
    """Handle push-identity-matching events from AiFi.

    Triggered when AiFi successfully links a shopper to a customer account.
    Extend here: update session, personalize UX.
    """
    logger.info(
        "Push identity match — shopperId=%s → customerId=%s confidence=%.2f",
        payload.shopper_id,
        payload.customer_id,
        payload.confidence or 0.0,
    )
    return _ACK


async def handle_push_transition(payload: PushTransitionPayload) -> dict[str, Any]:
    """Handle push-transitions events (session state machine changes) from AiFi.

    Extend here: trigger downstream workflow based on the new state.
    """
    logger.info(
        "Push transition — sessionId=%s %s → %s",
        payload.session_id,
        payload.from_state,
        payload.to_state,
    )
    return _ACK


async def handle_push_cart_mutator(payload: PushCartMutatorPayload) -> dict[str, Any]:
    """Handle push-cart-mutator events from AiFi.

    Triggered when items are added or removed from a session cart.
    Extend here: apply discounts, validate restricted products, update UI.
    """
    logger.info(
        "Push cart mutator — sessionId=%s cartValue=%s items=%d",
        payload.session_id,
        payload.cart_value,
        len(payload.items or []),
    )
    return _ACK


async def handle_push_restricted_products(payload: PushRestrictedProductsPayload) -> dict[str, Any]:
    """Handle push-restricted-products-interactions events from AiFi.

    Triggered when a shopper interacts with an age-restricted or access-controlled product.
    Extend here: trigger age-verification flow, alert staff.
    """
    logger.info(
        "Push restricted product — productId=%s shopperId=%s type=%s",
        payload.product_id,
        payload.shopper_id,
        payload.interaction_type,
    )
    return _ACK


async def handle_push_evaluate_order_price(payload: PushEvaluateOrderPricePayload) -> dict[str, Any]:
    """Handle push-evaluate-order-price events from AiFi.

    AiFi requests a final pricing evaluation before checkout.
    Extend here: apply loyalty discounts, promotions, return adjusted price.
    """
    logger.info(
        "Push evaluate order price — orderId=%s sessionId=%s",
        payload.order_id,
        payload.session_id,
    )
    # TODO: implement pricing logic and return {"adjustedTotal": ...} when ready
    return _ACK


async def handle_push_health(payload: PushHealthPayload) -> dict[str, Any]:
    """Handle push-health events from AiFi (heartbeat / status updates).

    Extend here: update store health dashboard, trigger alerts on degraded status.
    """
    logger.debug(
        "Push health — storeId=%s status=%s",
        payload.store_id,
        payload.status,
    )
    return _ACK
