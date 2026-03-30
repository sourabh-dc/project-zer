"""PUSH API endpoints — receive incoming webhook events from AiFi.

AiFi posts events to a pre-configured callback URL on this service.
Each endpoint deserialises the payload and delegates to the handler in
aifi_integration.shopify, which contains all domain logic.

To add a new event type:
  1. Add a schema to aifi_integration/schemas.py
  2. Add a handler function to aifi_integration/shopify.py
  3. Add an endpoint below — the controller stays thin.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from orders_service.aifi_integration.shopify import (
    handle_push_cart_mutator,
    handle_push_checkout,
    handle_push_customer,
    handle_push_entry_code,
    handle_push_evaluate_order_price,
    handle_push_health,
    handle_push_identity_matching,
    handle_push_restricted_products,
    handle_push_tracking,
    handle_push_transition,
)
from orders_service.aifi_integration.schemas import (
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

logger = logging.getLogger("orders-service.aifi.push.routes")

router = APIRouter(prefix="/aifi/push", tags=["AiFi — Push API"])


# ─────────────────────────────────────────────────────────────────────────────
# Checkout
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/checkout",
    summary="Push — checkout event",
    description=(
        "Receive a push-checkout webhook from AiFi. "
        "Triggered when a customer's shopping session is checked out."
    ),
)
async def push_checkout(body: PushCheckoutPayload):
    try:
        return await handle_push_checkout(body)
    except Exception as exc:
        logger.error("Error handling push-checkout: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error processing checkout event")


# ─────────────────────────────────────────────────────────────────────────────
# Customer
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/customer",
    summary="Push — customer event",
    description=(
        "Receive a push-customer webhook from AiFi. "
        "Triggered on customer creation or profile updates."
    ),
)
async def push_customer(body: PushCustomerPayload):
    try:
        return await handle_push_customer(body)
    except Exception as exc:
        logger.error("Error handling push-customer: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error processing customer event")


# ─────────────────────────────────────────────────────────────────────────────
# Entry codes
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/entry-codes",
    summary="Push — entry code event",
    description=(
        "Receive a push-entry-codes webhook from AiFi. "
        "Triggered when an entry code is created or validated at the gate."
    ),
)
async def push_entry_code(body: PushEntryCodePayload):
    try:
        return await handle_push_entry_code(body)
    except Exception as exc:
        logger.error("Error handling push-entry-code: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error processing entry code event")


# ─────────────────────────────────────────────────────────────────────────────
# Tracking
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/tracking",
    summary="Push — tracking event",
    description=(
        "Receive a push-tracking webhook from AiFi. "
        "High-frequency shopper position updates from the CV system."
    ),
)
async def push_tracking(body: PushTrackingPayload):
    try:
        return await handle_push_tracking(body)
    except Exception as exc:
        logger.error("Error handling push-tracking: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error processing tracking event")


# ─────────────────────────────────────────────────────────────────────────────
# Identity matching
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/identity-matching",
    summary="Push — identity matching event",
    description=(
        "Receive a push-identity-matching webhook from AiFi. "
        "Triggered when the CV system successfully links a shopper to a customer account."
    ),
)
async def push_identity_matching(body: PushIdentityMatchingPayload):
    try:
        return await handle_push_identity_matching(body)
    except Exception as exc:
        logger.error("Error handling push-identity-matching: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error processing identity matching event")


# ─────────────────────────────────────────────────────────────────────────────
# State transitions
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/transitions",
    summary="Push — session transition event",
    description=(
        "Receive a push-transitions webhook from AiFi. "
        "Triggered on session state machine changes (e.g. shopping → checkout → complete)."
    ),
)
async def push_transition(body: PushTransitionPayload):
    try:
        return await handle_push_transition(body)
    except Exception as exc:
        logger.error("Error handling push-transition: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error processing transition event")


# ─────────────────────────────────────────────────────────────────────────────
# Cart mutations
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/cart-mutator",
    summary="Push — cart mutation event",
    description=(
        "Receive a push-cart-mutator webhook from AiFi. "
        "Triggered when items are added or removed from a session cart."
    ),
)
async def push_cart_mutator(body: PushCartMutatorPayload):
    try:
        return await handle_push_cart_mutator(body)
    except Exception as exc:
        logger.error("Error handling push-cart-mutator: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error processing cart mutator event")


# ─────────────────────────────────────────────────────────────────────────────
# Restricted products
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/restricted-products",
    summary="Push — restricted product interaction",
    description=(
        "Receive a push-restricted-products-interactions webhook from AiFi. "
        "Triggered when a shopper interacts with an age-restricted or access-controlled item."
    ),
)
async def push_restricted_products(body: PushRestrictedProductsPayload):
    try:
        return await handle_push_restricted_products(body)
    except Exception as exc:
        logger.error("Error handling push-restricted-products: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error processing restricted products event")


# ─────────────────────────────────────────────────────────────────────────────
# Order price evaluation
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/evaluate-order-price",
    summary="Push — evaluate order price",
    description=(
        "Receive a push-evaluate-order-price webhook from AiFi. "
        "AiFi requests a pricing evaluation before finalising the checkout total. "
        "Return adjusted pricing in the response body when implementing discounts / loyalty."
    ),
)
async def push_evaluate_order_price(body: PushEvaluateOrderPricePayload):
    try:
        return await handle_push_evaluate_order_price(body)
    except Exception as exc:
        logger.error("Error handling push-evaluate-order-price: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error processing evaluate-order-price event")


# ─────────────────────────────────────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/health",
    summary="Push — health event",
    description=(
        "Receive a push-health webhook from AiFi. "
        "Periodic heartbeat / system health status updates from the store."
    ),
)
async def push_health(body: PushHealthPayload):
    try:
        return await handle_push_health(body)
    except Exception as exc:
        logger.error("Error handling push-health: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error processing health event")
