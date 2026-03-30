"""STORE API endpoints — thin controllers proxying to AiFi's /api/aifi/* endpoints.

All business logic lives in orders_service.aifi_integration.service.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from orders_service.aifi_integration import (
    checkout_zone_entered,
    checkout_zone_left,
    create_checkout,
    customer_entered,
    customer_walked_out,
    forward_restricted_product_interaction,
    forward_tracking_association,
    get_aifi_store_status,
    get_product_inventory,
    register_customer_with_token,
    store_verify_entry_code,
)
from orders_service.aifi_integration.exceptions import AiFiError, AiFiNotFoundError
from orders_service.aifi_integration.schemas import (
    CheckoutZoneEvent,
    CustomerEnteredEvent,
    CustomerWalkedOutEvent,
    EntryCodeVerify,
    RegisterWithTokenRequest,
    RestrictedProductInteractionForward,
    StoreCheckoutCreate,
    TrackingAssociationForward,
)

router = APIRouter(prefix="/aifi/store", tags=["AiFi — Store API"])


def _http(exc: AiFiError) -> HTTPException:
    return HTTPException(status_code=exc.status_code or 502, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Checkout zone events
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/checkout-zone/entered",
    summary="Shopper entered checkout zone",
    description="Notify AiFi that a shopper has entered the checkout zone.",
)
async def checkout_zone_entered_endpoint(body: CheckoutZoneEvent):
    try:
        return await checkout_zone_entered(body)
    except AiFiError as exc:
        raise _http(exc)


@router.post(
    "/checkout-zone/left",
    summary="Shopper left checkout zone",
    description="Notify AiFi that a shopper has left the checkout zone.",
)
async def checkout_zone_left_endpoint(body: CheckoutZoneEvent):
    try:
        return await checkout_zone_left(body)
    except AiFiError as exc:
        raise _http(exc)


# ─────────────────────────────────────────────────────────────────────────────
# Customer entry / exit
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/customers/entered",
    summary="Customer entered store",
    description="Record that an identified customer has entered the store.",
)
async def customer_entered_endpoint(body: CustomerEnteredEvent):
    try:
        return await customer_entered(body)
    except AiFiError as exc:
        raise _http(exc)


@router.post(
    "/customers/walked-out",
    summary="Customer walked out",
    description="Record that a customer has exited the store.",
)
async def customer_walked_out_endpoint(body: CustomerWalkedOutEvent):
    try:
        return await customer_walked_out(body)
    except AiFiError as exc:
        raise _http(exc)


@router.post(
    "/customers/register-with-token",
    summary="Register customer with session token",
    description="Register a customer using a kiosk / mobile-generated session token.",
)
async def register_with_token_endpoint(body: RegisterWithTokenRequest):
    try:
        return await register_customer_with_token(body)
    except AiFiError as exc:
        raise _http(exc)


# ─────────────────────────────────────────────────────────────────────────────
# Checkouts
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/checkouts",
    status_code=201,
    summary="Create checkout",
    description="Initiate a checkout transaction from the on-premise store system.",
)
async def create_checkout_endpoint(body: StoreCheckoutCreate):
    try:
        return await create_checkout(body)
    except AiFiError as exc:
        raise _http(exc)


# ─────────────────────────────────────────────────────────────────────────────
# Inventory
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/inventory/products/{product_id}",
    summary="Get product inventory",
    description="Fetch live inventory for a product from the store system.",
)
async def get_product_inventory_endpoint(product_id: int):
    try:
        return await get_product_inventory(product_id)
    except AiFiNotFoundError:
        raise HTTPException(status_code=404, detail="Product not found")
    except AiFiError as exc:
        raise _http(exc)


# ─────────────────────────────────────────────────────────────────────────────
# Entry codes
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/entry-codes/verify",
    summary="Verify entry code",
    description="Validate an entry code against the AiFi store system at the gate.",
)
async def verify_entry_code_endpoint(body: EntryCodeVerify):
    try:
        return await store_verify_entry_code(body)
    except AiFiError as exc:
        raise _http(exc)


# ─────────────────────────────────────────────────────────────────────────────
# Store status
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/status",
    summary="Get AiFi store status",
    description="Retrieve the current operational status of the AiFi store system.",
)
async def get_store_status_endpoint():
    try:
        return await get_aifi_store_status()
    except AiFiError as exc:
        raise _http(exc)


# ─────────────────────────────────────────────────────────────────────────────
# Tracking & restricted products
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/tracking-association/forward",
    summary="Forward tracking association",
    description="Forward a shopper tracking association event to AiFi.",
)
async def forward_tracking_endpoint(body: TrackingAssociationForward):
    try:
        return await forward_tracking_association(body)
    except AiFiError as exc:
        raise _http(exc)


@router.post(
    "/restricted-products/forward",
    summary="Forward restricted product interaction",
    description="Forward a restricted-product interaction event to AiFi for age/access verification.",
)
async def forward_restricted_products_endpoint(body: RestrictedProductInteractionForward):
    try:
        return await forward_restricted_product_interaction(body)
    except AiFiError as exc:
        raise _http(exc)
