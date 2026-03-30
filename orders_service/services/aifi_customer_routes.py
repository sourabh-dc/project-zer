"""CUSTOMER APP API endpoints — thin controllers proxying to AiFi's /api/customer/v2/* endpoints.

The end-user's AiFi Bearer token is forwarded on every authenticated call.
Unauthenticated endpoints (registration, login, password reset) pass an empty token.
All AiFi logic lives in the aifi_integration package.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from orders_service.aifi_integration import (
    create_customer_entry_code,
    customer_login,
    customer_logout,
    customer_refresh_session,
    customer_register,
    enter_contest,
    get_customer_draft_order,
    get_customer_draft_orders,
    get_customer_order,
    get_my_profile,
    initialize_payment_methods,
    keycloak_password_reset,
    list_customer_entry_codes,
    list_customer_orders,
    list_customer_app_customers,
    process_order_payment,
    request_password_reset,
    search_customer_products,
    verify_password_reset,
)
from orders_service.aifi_integration.dependencies import require_customer_token
from orders_service.aifi_integration.exceptions import AiFiError, AiFiNotFoundError
from orders_service.aifi_integration.schemas import (
    CustomerAppEntryCode,
    CustomerContestEntry,
    CustomerLogin,
    CustomerOrderPayment,
    CustomerRegister,
    PaymentMethodInit,
    PasswordResetRequest,
    PasswordResetVerify,
    TokenRefresh,
)

router = APIRouter(prefix="/aifi/customer", tags=["AiFi — Customer App API"])


def _http(exc: AiFiError) -> HTTPException:
    return HTTPException(status_code=exc.status_code or 502, detail=str(exc))


def _404(exc: AiFiNotFoundError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Registration & authentication (unauthenticated)
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/customers",
    summary="List customers (customer app)",
    description="List customers available in the Customer App context.",
)
async def list_customers_customer_app(token: str = Depends(require_customer_token)):
    try:
        return await list_customer_app_customers(token=token)
    except AiFiError as exc:
        raise _http(exc)


@router.post(
    "/customers",
    status_code=201,
    summary="Register new customer",
    description="Create a new customer account. Does not require an existing session.",
)
async def register_customer_endpoint(body: CustomerRegister):
    try:
        return await customer_register(body)
    except AiFiError as exc:
        raise _http(exc)


@router.post(
    "/sessions",
    status_code=201,
    summary="Login / create session",
    description="Authenticate with email and password to obtain an AiFi session token.",
)
async def login_endpoint(body: CustomerLogin):
    try:
        return await customer_login(body)
    except AiFiError as exc:
        raise _http(exc)


@router.post(
    "/sessions/refresh",
    summary="Refresh session token",
    description="Obtain a new session token using the current refresh token.",
)
async def refresh_session_endpoint(body: TokenRefresh, token: str = Depends(require_customer_token)):
    try:
        return await customer_refresh_session(body, token=token)
    except AiFiError as exc:
        raise _http(exc)


@router.delete(
    "/sessions",
    summary="Logout / delete session",
    description="Invalidate the current customer session.",
)
async def logout_endpoint(token: str = Depends(require_customer_token)):
    try:
        return await customer_logout(token=token)
    except AiFiError as exc:
        raise _http(exc)


# ─────────────────────────────────────────────────────────────────────────────
# Profile
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/customers/me",
    summary="Get my profile",
    description="Fetch the authenticated customer's own profile.",
)
async def get_my_profile_endpoint(token: str = Depends(require_customer_token)):
    try:
        return await get_my_profile(token=token)
    except AiFiError as exc:
        raise _http(exc)


# ─────────────────────────────────────────────────────────────────────────────
# Password reset (unauthenticated)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/password-reset",
    summary="Request password reset",
    description="Trigger a password reset email for the given address.",
)
async def request_password_reset_endpoint(body: PasswordResetRequest):
    try:
        return await request_password_reset(body)
    except AiFiError as exc:
        raise _http(exc)


@router.post(
    "/password-reset/verify",
    summary="Verify password reset",
    description="Complete the password reset using the code sent to the customer's email.",
)
async def verify_password_reset_endpoint(body: PasswordResetVerify):
    try:
        return await verify_password_reset(body)
    except AiFiError as exc:
        raise _http(exc)


@router.post(
    "/keycloak/password-reset",
    summary="Keycloak password reset",
    description="Trigger a Keycloak-managed password reset.",
)
async def keycloak_password_reset_endpoint(body: PasswordResetRequest):
    try:
        return await keycloak_password_reset(body)
    except AiFiError as exc:
        raise _http(exc)


# ─────────────────────────────────────────────────────────────────────────────
# Entry codes
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/entry-codes",
    status_code=201,
    summary="Create entry code",
    description="Generate an entry code for the authenticated customer to use at the store gate.",
)
async def create_entry_code_endpoint(body: CustomerAppEntryCode, token: str = Depends(require_customer_token)):
    try:
        return await create_customer_entry_code(body, token=token)
    except AiFiError as exc:
        raise _http(exc)


@router.get(
    "/entry-codes",
    summary="List entry codes",
    description="List all active entry codes for the authenticated customer.",
)
async def list_entry_codes_endpoint(token: str = Depends(require_customer_token)):
    try:
        return await list_customer_entry_codes(token=token)
    except AiFiError as exc:
        raise _http(exc)


# ─────────────────────────────────────────────────────────────────────────────
# Orders
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/orders",
    summary="List customer orders",
    description="Retrieve all orders associated with the authenticated customer.",
)
async def list_orders_endpoint(token: str = Depends(require_customer_token)):
    try:
        return await list_customer_orders(token=token)
    except AiFiError as exc:
        raise _http(exc)


@router.get(
    "/orders/draft",
    summary="List draft orders",
    description="Retrieve all in-progress (draft) orders for the authenticated customer.",
)
async def list_draft_orders_endpoint(token: str = Depends(require_customer_token)):
    try:
        return await get_customer_draft_orders(token=token)
    except AiFiError as exc:
        raise _http(exc)


@router.get(
    "/orders/draft/{draft_id}",
    summary="Get draft order",
    description="Retrieve a specific draft order by ID.",
)
async def get_draft_order_endpoint(draft_id: str, token: str = Depends(require_customer_token)):
    try:
        return await get_customer_draft_order(draft_id, token=token)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.get(
    "/orders/{order_id}",
    summary="Get customer order",
    description="Retrieve a specific order for the authenticated customer.",
)
async def get_order_endpoint(order_id: int, token: str = Depends(require_customer_token)):
    try:
        return await get_customer_order(order_id, token=token)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.post(
    "/orders/{order_id}/payment",
    status_code=201,
    summary="Process order payment",
    description="Submit payment for a completed shopping session order.",
)
async def process_payment_endpoint(
    order_id: int, body: CustomerOrderPayment, token: str = Depends(require_customer_token)
):
    try:
        return await process_order_payment(order_id, body, token=token)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


# ─────────────────────────────────────────────────────────────────────────────
# Products
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/products",
    summary="Search / list products",
    description="Browse or search products visible to customers in the store app.",
)
async def list_products_endpoint(
    token: str = Depends(require_customer_token),
    search: Optional[str] = Query(None),
    count: int = Query(50, ge=1, le=200),
    sort: Optional[str] = Query(None),
    direction: str = Query("asc", pattern="^(asc|desc)$"),
):
    try:
        return await search_customer_products(token=token, search=search, count=count, sort=sort, direction=direction)
    except AiFiError as exc:
        raise _http(exc)


# ─────────────────────────────────────────────────────────────────────────────
# Payments initialisation
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/payments/methods/initialize",
    summary="Initialize payment methods",
    description="Fetch available payment providers and configuration for the customer.",
)
async def initialize_payment_methods_endpoint(
    body: PaymentMethodInit, token: str = Depends(require_customer_token)
):
    try:
        return await initialize_payment_methods(token=token, data=body)
    except AiFiError as exc:
        raise _http(exc)


# ─────────────────────────────────────────────────────────────────────────────
# Contests
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/contests",
    status_code=201,
    summary="Enter contest",
    description="Submit a contest entry on behalf of the authenticated customer.",
)
async def enter_contest_endpoint(body: CustomerContestEntry, token: str = Depends(require_customer_token)):
    try:
        return await enter_contest(body, token=token)
    except AiFiError as exc:
        raise _http(exc)
