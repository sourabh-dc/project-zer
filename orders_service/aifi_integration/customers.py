"""Customer management — Admin API and Customer App API integration functions.

Admin functions call /api/admin/v2/customers/* with the fixed admin token.
Customer-app functions call /api/customer/v2/* forwarding the end-user's token.
"""
from __future__ import annotations

import logging
from typing import Any

from .http_client import (
    admin_delete,
    admin_get,
    admin_patch,
    admin_post,
    customer_delete,
    customer_get,
    customer_patch,
    customer_post,
)
from .schemas import (
    CardCreate,
    CardTokenUpdate,
    CustomerAppEntryCode,
    CustomerCreate,
    CustomerLogin,
    CustomerOrderPayment,
    CustomerRegister,
    CustomerUpdate,
    EntryCodeCreate,
    PasswordResetRequest,
    PasswordResetVerify,
    RemoteRegisterRequest,
    TokenRefresh,
    CustomerContestEntry,
)

logger = logging.getLogger("orders-service.aifi.customers")


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — Customer CRUD
# ─────────────────────────────────────────────────────────────────────────────

async def list_customers(
    external_id: str | None = None,
    email: str | None = None,
    payment_instrument_id: str | None = None,
    min_created_at: str | None = None,
    max_created_at: str | None = None,
    min_updated_at: str | None = None,
    max_updated_at: str | None = None,
    count: int = 50,
    sort: str | None = None,
    direction: str = "asc",
) -> dict[str, Any]:
    """List customers with optional filters. GET /api/admin/v2/customers"""
    params = {k: v for k, v in {
        "externalId": external_id,
        "email": email,
        "paymentInstrumentProviderId": payment_instrument_id,
        "minCreatedAt": min_created_at,
        "maxCreatedAt": max_created_at,
        "minUpdatedAt": min_updated_at,
        "maxUpdatedAt": max_updated_at,
        "count": count,
        "sort": sort,
        "direction": direction,
    }.items() if v is not None}
    return await admin_get("/api/admin/v2/customers", params=params)


async def get_customer(customer_id: int) -> dict[str, Any]:
    """Fetch a single customer by ID. GET /api/admin/v2/customers/{customerId}"""
    return await admin_get(f"/api/admin/v2/customers/{customer_id}")


async def create_customer(data: CustomerCreate) -> dict[str, Any]:
    """Create a new customer. POST /api/admin/v2/customers"""
    logger.info("Creating AiFi customer email=%s externalId=%s", data.email, data.external_id)
    return await admin_post(
        "/api/admin/v2/customers",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


async def update_customer(customer_id: int, data: CustomerUpdate) -> dict[str, Any]:
    """Partially update a customer. PATCH /api/admin/v2/customers/{customerId}"""
    return await admin_patch(
        f"/api/admin/v2/customers/{customer_id}",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


async def remote_register_customer(data: RemoteRegisterRequest) -> dict[str, Any]:
    """Remote-register a customer (no in-store interaction required).
    POST /api/admin/v2/customers/remote-register"""
    logger.info("Remote-registering AiFi customer email=%s", data.email)
    return await admin_post(
        "/api/admin/v2/customers/remote-register",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — Entry codes
# ─────────────────────────────────────────────────────────────────────────────

async def create_entry_code(customer_id: int, data: EntryCodeCreate) -> dict[str, Any]:
    """Create an entry code for a customer. POST /api/admin/v2/customers/{customerId}/entry-codes"""
    return await admin_post(
        f"/api/admin/v2/customers/{customer_id}/entry-codes",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — Payment cards
# ─────────────────────────────────────────────────────────────────────────────

async def update_card_token(customer_id: int, data: CardTokenUpdate) -> dict[str, Any]:
    """Add / update the customer's payment card token.
    PATCH /api/admin/v2/customers/{customerId}/card-token"""
    return await admin_patch(
        f"/api/admin/v2/customers/{customer_id}/card-token",
        json=data.model_dump(by_alias=True),
    )


async def create_card(customer_id: int, data: CardCreate) -> dict[str, Any]:
    """Create a payment card for a customer.
    POST /api/admin/v2/customers/{customerId}/card"""
    return await admin_post(
        f"/api/admin/v2/customers/{customer_id}/card",
        json=data.model_dump(by_alias=True),
    )


async def delete_card(customer_id: int, card_id: int) -> dict[str, Any]:
    """Delete a payment card. DELETE /api/admin/v2/customers/{customerId}/card/{id}"""
    return await admin_delete(f"/api/admin/v2/customers/{customer_id}/card/{card_id}")


async def set_default_card(customer_id: int, card_id: int) -> dict[str, Any]:
    """Mark a card as the customer's default.
    PATCH /api/admin/v2/customers/{customerId}/card/{id}/default"""
    return await admin_patch(f"/api/admin/v2/customers/{customer_id}/card/{card_id}/default")


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMER APP — Authentication / session
# ─────────────────────────────────────────────────────────────────────────────

async def customer_register(data: CustomerRegister) -> dict[str, Any]:
    """Register a new customer account. POST /api/customer/v2/customers"""
    return await customer_post(
        "/api/customer/v2/customers",
        token="",  # unauthenticated endpoint
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


async def customer_login(data: CustomerLogin) -> dict[str, Any]:
    """Authenticate and obtain a session token. POST /api/customer/v2/sessions"""
    return await customer_post(
        "/api/customer/v2/sessions",
        token="",  # unauthenticated endpoint
        json=data.model_dump(by_alias=True),
    )


async def customer_refresh_session(data: TokenRefresh, token: str) -> dict[str, Any]:
    """Refresh a customer session token. POST /api/customer/v2/sessions/refresh"""
    return await customer_post(
        "/api/customer/v2/sessions/refresh",
        token=token,
        json=data.model_dump(by_alias=True),
    )


async def customer_logout(token: str) -> dict[str, Any]:
    """Invalidate a customer session. DELETE /api/customer/v2/sessions"""
    return await customer_delete("/api/customer/v2/sessions", token=token)


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMER APP — Profile
# ─────────────────────────────────────────────────────────────────────────────

async def get_my_profile(token: str) -> dict[str, Any]:
    """Fetch the authenticated customer's own profile. GET /api/customer/v2/customers/me"""
    return await customer_get("/api/customer/v2/customers/me", token=token)


async def list_customer_app_customers(token: str) -> dict[str, Any]:
    """GET /api/customer/v2/customers"""
    return await customer_get("/api/customer/v2/customers", token=token)


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMER APP — Password reset
# ─────────────────────────────────────────────────────────────────────────────

async def request_password_reset(data: PasswordResetRequest) -> dict[str, Any]:
    """Initiate a password reset. POST /api/customer/v2/password-reset"""
    return await customer_post("/api/customer/v2/password-reset", token="", json={"email": data.email})


async def verify_password_reset(data: PasswordResetVerify) -> dict[str, Any]:
    """Complete a password reset with the verification code.
    POST /api/customer/v2/password-reset/verify"""
    return await customer_post(
        "/api/customer/v2/password-reset/verify",
        token="",
        json=data.model_dump(by_alias=True),
    )


async def keycloak_password_reset(data: PasswordResetRequest) -> dict[str, Any]:
    """Trigger a Keycloak-managed password reset. POST /api/customer/v2/keycloak/password-reset"""
    return await customer_post("/api/customer/v2/keycloak/password-reset", token="", json={"email": data.email})


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMER APP — Entry codes
# ─────────────────────────────────────────────────────────────────────────────

async def create_customer_entry_code(data: CustomerAppEntryCode, token: str) -> dict[str, Any]:
    """Generate an entry code for the authenticated customer.
    POST /api/customer/v2/entry-codes"""
    return await customer_post(
        "/api/customer/v2/entry-codes",
        token=token,
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


async def list_customer_entry_codes(token: str) -> dict[str, Any]:
    """List entry codes for the authenticated customer. GET /api/customer/v2/entry-codes"""
    return await customer_get("/api/customer/v2/entry-codes", token=token)


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMER APP — Orders
# ─────────────────────────────────────────────────────────────────────────────

async def list_customer_orders(token: str) -> dict[str, Any]:
    """List all orders for the authenticated customer. GET /api/customer/v2/orders"""
    return await customer_get("/api/customer/v2/orders", token=token)


async def get_customer_order(order_id: int, token: str) -> dict[str, Any]:
    """Fetch a single customer order. GET /api/customer/v2/orders/{orderId}"""
    return await customer_get(f"/api/customer/v2/orders/{order_id}", token=token)


async def get_customer_draft_orders(token: str) -> dict[str, Any]:
    """Get draft orders for the authenticated customer. GET /api/customer/v2/orders/draft"""
    return await customer_get("/api/customer/v2/orders/draft", token=token)


async def get_customer_draft_order(draft_id: str, token: str) -> dict[str, Any]:
    """Get a specific draft order. GET /api/customer/v2/orders/draft/{draftOrderID}"""
    return await customer_get(f"/api/customer/v2/orders/draft/{draft_id}", token=token)


async def process_order_payment(order_id: int, data: CustomerOrderPayment, token: str) -> dict[str, Any]:
    """Process / update payment for an order. POST /api/customer/v2/orders/{orderId}/payment"""
    return await customer_post(
        f"/api/customer/v2/orders/{order_id}/payment",
        token=token,
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMER APP — Products
# ─────────────────────────────────────────────────────────────────────────────

async def search_customer_products(
    token: str,
    search: str | None = None,
    count: int = 50,
    sort: str | None = None,
    direction: str = "asc",
) -> dict[str, Any]:
    """Search / list products visible to the customer. GET /api/customer/v2/products"""
    params = {k: v for k, v in {
        "search": search,
        "count": count,
        "sort": sort,
        "direction": direction,
    }.items() if v is not None}
    return await customer_get("/api/customer/v2/products", token=token, params=params)


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMER APP — Contests
# ─────────────────────────────────────────────────────────────────────────────

async def enter_contest(data: CustomerContestEntry, token: str) -> dict[str, Any]:
    """Enter a contest on behalf of the authenticated customer.
    POST /api/customer/v2/contests"""
    return await customer_post(
        "/api/customer/v2/contests",
        token=token,
        json=data.model_dump(by_alias=True, exclude_none=True),
    )
