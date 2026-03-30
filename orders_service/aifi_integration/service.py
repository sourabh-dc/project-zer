"""AiFi Store API and Admin operations integration.

Store API (/api/aifi/*) — called by on-premise in-store systems:
  checkout zone events, customer entry/exit, checkouts, inventory,
  entry-code verification, store status, tracking, restricted products.

Admin operations — orders, sessions, contests, audits, configuration.
"""
from __future__ import annotations

import logging
from typing import Any

from .http_client import admin_get, admin_patch, admin_post, store_get, store_post, store_put
from .schemas import (
    AdminCheckoutCreate,
    CartUpdate,
    CheckoutZoneEvent,
    ContestCreate,
    CustomerEnteredEvent,
    CustomerWalkedOutEvent,
    EntryCodeVerify,
    OrderCreate,
    OrderUpdate,
    RegisterWithTokenRequest,
    RestrictedProductInteractionForward,
    RetailerConfigUpdate,
    SessionUpdate,
    StoreCheckoutCreate,
    TrackingAssociationForward,
)

logger = logging.getLogger("orders-service.aifi.service")


# ─────────────────────────────────────────────────────────────────────────────
# STORE API — Checkout zone events
# ─────────────────────────────────────────────────────────────────────────────

async def checkout_zone_entered(data: CheckoutZoneEvent) -> dict[str, Any]:
    """Notify AiFi that a shopper entered the checkout zone.
    POST /api/aifi/checkout_zone/entered"""
    logger.info("Checkout zone entered shopperId=%s", data.shopper_id)
    return await store_post(
        "/api/aifi/checkout_zone/entered",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


async def checkout_zone_left(data: CheckoutZoneEvent) -> dict[str, Any]:
    """Notify AiFi that a shopper left the checkout zone.
    POST /api/aifi/checkout_zone/left"""
    logger.info("Checkout zone left shopperId=%s", data.shopper_id)
    return await store_post(
        "/api/aifi/checkout_zone/left",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


# ─────────────────────────────────────────────────────────────────────────────
# STORE API — Customer entry / exit events
# ─────────────────────────────────────────────────────────────────────────────

async def customer_entered(data: CustomerEnteredEvent) -> dict[str, Any]:
    """Record that a customer entered the store. POST /api/aifi/customers/entered"""
    logger.info("Customer entered customerId=%s storeId=%s", data.customer_id, data.store_id)
    return await store_post(
        "/api/aifi/customers/entered",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


async def customer_walked_out(data: CustomerWalkedOutEvent) -> dict[str, Any]:
    """Record that a customer walked out of the store. POST /api/aifi/customers/walked-out"""
    logger.info("Customer walked out customerId=%s storeId=%s", data.customer_id, data.store_id)
    return await store_post(
        "/api/aifi/customers/walked-out",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


async def register_customer_with_token(data: RegisterWithTokenRequest) -> dict[str, Any]:
    """Register a customer using a session token (kiosk / mobile handoff).
    POST /api/aifi/customers/register-with-token"""
    return await store_post(
        "/api/aifi/customers/register-with-token",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


# ─────────────────────────────────────────────────────────────────────────────
# STORE API — Checkouts
# ─────────────────────────────────────────────────────────────────────────────

async def create_checkout(data: StoreCheckoutCreate) -> dict[str, Any]:
    """Initiate a checkout transaction from the store system.
    POST /api/aifi/checkouts"""
    logger.info("Creating store checkout sessionId=%s", data.session_id)
    return await store_post(
        "/api/aifi/checkouts",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


# ─────────────────────────────────────────────────────────────────────────────
# STORE API — Inventory
# ─────────────────────────────────────────────────────────────────────────────

async def get_product_inventory(product_id: int) -> dict[str, Any]:
    """Fetch live inventory for a product from the store system.
    GET /api/aifi/inventory/products/{productId}"""
    return await store_get(f"/api/aifi/inventory/products/{product_id}")


# ─────────────────────────────────────────────────────────────────────────────
# STORE API — Entry codes
# ─────────────────────────────────────────────────────────────────────────────

async def store_verify_entry_code(data: EntryCodeVerify) -> dict[str, Any]:
    """Verify an entry code against the AiFi store system.
    POST /api/aifi/entry-codes/verify"""
    return await store_post(
        "/api/aifi/entry-codes/verify",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


# ─────────────────────────────────────────────────────────────────────────────
# STORE API — Store status
# ─────────────────────────────────────────────────────────────────────────────

async def get_aifi_store_status() -> dict[str, Any]:
    """Fetch the current operational status of the AiFi store.
    GET /api/aifi/stores/status"""
    return await store_get("/api/aifi/stores/status")


# ─────────────────────────────────────────────────────────────────────────────
# STORE API — Tracking & restricted products
# ─────────────────────────────────────────────────────────────────────────────

async def forward_tracking_association(data: TrackingAssociationForward) -> dict[str, Any]:
    """Forward a tracking association event to AiFi.
    POST /api/aifi/tracking-association/forward"""
    return await store_post(
        "/api/aifi/tracking-association/forward",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


async def forward_restricted_product_interaction(
    data: RestrictedProductInteractionForward,
) -> dict[str, Any]:
    """Forward a restricted-product interaction event to AiFi.
    POST /api/aifi/restricted-products-interactions/forward"""
    return await store_post(
        "/api/aifi/restricted-products-interactions/forward",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — Orders
# ─────────────────────────────────────────────────────────────────────────────

async def list_orders(
    count: int = 50, sort: str | None = None, direction: str = "asc"
) -> dict[str, Any]:
    """GET /api/admin/v2/orders"""
    params = {k: v for k, v in {"count": count, "sort": sort, "direction": direction}.items() if v is not None}
    return await admin_get("/api/admin/v2/orders", params=params)


async def create_order(data: OrderCreate) -> dict[str, Any]:
    """POST /api/admin/v2/orders"""
    logger.info("Creating AiFi order customerId=%s", data.customer_id)
    return await admin_post("/api/admin/v2/orders", json=data.model_dump(by_alias=True, exclude_none=True))


async def get_order(order_id: int) -> dict[str, Any]:
    """GET /api/admin/v2/orders/{orderId}"""
    return await admin_get(f"/api/admin/v2/orders/{order_id}")


async def update_order(order_id: int, data: OrderUpdate) -> dict[str, Any]:
    """PATCH /api/admin/v2/orders/{orderId}"""
    return await admin_patch(
        f"/api/admin/v2/orders/{order_id}",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


async def retry_order(order_id: int) -> dict[str, Any]:
    """Retry processing a failed order. POST /api/admin/v2/orders/{orderId}/retry"""
    logger.info("Retrying AiFi order id=%d", order_id)
    return await admin_post(f"/api/admin/v2/orders/{order_id}/retry")


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — Sessions
# ─────────────────────────────────────────────────────────────────────────────

async def list_sessions(count: int = 50) -> dict[str, Any]:
    """GET /api/admin/v2/sessions"""
    return await admin_get("/api/admin/v2/sessions", params={"count": count})


async def get_session_cart(session_id: str) -> dict[str, Any]:
    """GET /api/admin/v2/sessions/{sessionId}/cart"""
    return await admin_get(f"/api/admin/v2/sessions/{session_id}/cart")


async def update_session_cart(session_id: str, data: CartUpdate) -> dict[str, Any]:
    """POST /api/admin/v2/sessions/{sessionId}/cart"""
    return await admin_post(
        f"/api/admin/v2/sessions/{session_id}/cart",
        json=data.model_dump(by_alias=True),
    )


async def update_session(session_id: str, data: SessionUpdate) -> dict[str, Any]:
    """PATCH /api/admin/v2/sessions/{sessionId}"""
    return await admin_patch(
        f"/api/admin/v2/sessions/{session_id}",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


async def create_session_checkout(session_id: str, data: AdminCheckoutCreate) -> dict[str, Any]:
    """POST /api/admin/v2/sessions/{sessionId}/checkout"""
    return await admin_post(
        f"/api/admin/v2/sessions/{session_id}/checkout",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — Contests & Audits
# ─────────────────────────────────────────────────────────────────────────────

async def list_contests() -> dict[str, Any]:
    """GET /api/admin/v2/contests"""
    return await admin_get("/api/admin/v2/contests")


async def create_contest(data: ContestCreate) -> dict[str, Any]:
    """POST /api/admin/v2/contests"""
    return await admin_post("/api/admin/v2/contests", json=data.model_dump(by_alias=True, exclude_none=True))


async def list_audits() -> dict[str, Any]:
    """GET /api/admin/v2/audits"""
    return await admin_get("/api/admin/v2/audits")


async def get_audit(audit_id: str) -> dict[str, Any]:
    """GET /api/admin/v2/audits/{auditId}"""
    return await admin_get(f"/api/admin/v2/audits/{audit_id}")


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — Configuration
# ─────────────────────────────────────────────────────────────────────────────

async def get_config() -> dict[str, Any]:
    """GET /api/admin/v2/config"""
    return await admin_get("/api/admin/v2/config")


async def get_retailer_config() -> dict[str, Any]:
    """GET /api/admin/v2/retailer/config"""
    return await admin_get("/api/admin/v2/retailer/config")


async def update_retailer_config(data: RetailerConfigUpdate) -> dict[str, Any]:
    """PATCH /api/admin/v2/retailer/config"""
    return await admin_patch("/api/admin/v2/retailer/config", json=data.model_dump(by_alias=True))
