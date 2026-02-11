"""
AiFi Customer App API Integration
This module provides endpoints to connect to all Customer App API endpoints from the Oasis API.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
import httpx
from datetime import datetime

router = APIRouter(prefix="/aifi/customer", tags=["AiFi Customer App"])

# Base URL for AiFi API - should be configured from environment
AIFI_BASE_URL = "https://api.retailer-codename.cloud.aifi.io"


# ============================================================================
# CUSTOMER APP - CUSTOMERS
# ============================================================================

class CustomerCreate(BaseModel):
    firstName: str
    lastName: str
    email: str
    phone: str
    password: str = Field(min_length=8)


class CustomerUpdate(BaseModel):
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[int] = None
    notificationToken: Optional[str] = None


@router.post("/v2/customers", summary="Create (register) customer")
async def create_customer(customer: CustomerCreate):
    """
    Register a new customer in the AiFi system.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AIFI_BASE_URL}/api/customer/v2/customers",
            json=customer.dict()
        )
        return response.json()


@router.get("/v2/customers/me", summary="Get customer details")
async def get_customer_details(authorization: str):
    """
    Get authenticated customer details including card information.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{AIFI_BASE_URL}/api/customer/v2/customers/me",
            headers={"Authorization": authorization}
        )
        return response.json()


@router.patch("/v2/customers/me", summary="Update customer")
async def update_customer(
    customer_update: CustomerUpdate,
    authorization: str
):
    """
    Update customer information.
    Note: None of the body properties are required. Just at least one needs to be provided.
    """
    async with httpx.AsyncClient() as client:
        response = await client.patch(
            f"{AIFI_BASE_URL}/api/customer/v2/customers/me",
            json=customer_update.dict(exclude_none=True),
            headers={"Authorization": authorization}
        )
        return response.json()


# ============================================================================
# CUSTOMER APP - ENTRY CODES
# ============================================================================

class EntryCodeCreate(BaseModel):
    groupSize: Optional[float] = None


@router.post("/v2/entry-codes", summary="Create customer entry code")
async def create_entry_code(
    entry_code: EntryCodeCreate,
    authorization: str
):
    """
    Create an entry code for the customer to enter a store.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AIFI_BASE_URL}/api/customer/v2/entry-codes",
            json=entry_code.dict(exclude_none=True),
            headers={"Authorization": authorization}
        )
        return response.json()


# ============================================================================
# CUSTOMER APP - ORDERS
# ============================================================================

@router.get("/v2/orders", summary="Get orders")
async def get_orders(
    authorization: str,
    count: int = Query(..., description="Number of orders to be listed"),
    paymentTransactionId: Optional[str] = Query(None, example="paymentTransactionId=ABCDE1234"),
    direction: str = Query(..., regex="^(asc|desc)$", example="direction=desc"),
    after: str = Query(..., example="after=2314"),
    before: str = Query(..., example="before=1234"),
    storeId: Optional[int] = Query(None, example="storeId=1")
):
    """
    Get a list of customer's orders with pagination support.
    """
    params = {
        "count": count,
        "direction": direction,
        "after": after,
        "before": before
    }
    if paymentTransactionId:
        params["paymentTransactionId"] = paymentTransactionId
    if storeId:
        params["storeId"] = storeId

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{AIFI_BASE_URL}/api/customer/v2/orders",
            params=params,
            headers={"Authorization": authorization}
        )
        return response.json()


@router.get("/v2/orders/{orderId}", summary="Get order details")
async def get_order_details(
    orderId: str = Path(..., description="Order ID (URL-encoded)"),
    authorization: str = None
):
    """
    Get detailed information about a specific order.
    Make sure that order id is url-encoded.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{AIFI_BASE_URL}/api/customer/v2/orders/{orderId}",
            headers={"Authorization": authorization}
        )
        return response.json()


@router.post("/v2/orders/{orderId}/payment", summary="Initiate processing of order payment")
async def init_manual_order_payment(
    orderId: str = Path(..., description="Order ID (URL-encoded)"),
    authorization: str = None
):
    """
    Initiate processing the payment for an order if status is UNPAID.
    Make sure that order id is url-encoded.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AIFI_BASE_URL}/api/customer/v2/orders/{orderId}/payment",
            headers={"Authorization": authorization}
        )
        return response.json()


class FinishPaymentRequest(BaseModel):
    initialisedPaymentId: str = Field(..., example="pm_1K6fRJDSugCw1CsrsmKacISg")


@router.patch("/v2/orders/{orderId}/payment", summary="Finish processing of order payment")
async def finish_manual_order_payment(
    orderId: str = Path(..., description="Order ID (URL-encoded)"),
    payment_request: FinishPaymentRequest = Body(...),
    authorization: str = None
):
    """
    Finish processing the payment for an order if status is UNPAID.
    Make sure that order id is url-encoded.
    """
    async with httpx.AsyncClient() as client:
        response = await client.patch(
            f"{AIFI_BASE_URL}/api/customer/v2/orders/{orderId}/payment",
            json=payment_request.dict(),
            headers={"Authorization": authorization}
        )
        return response.json()


class SatisfactionRequest(BaseModel):
    satisfactionLevel: int = Field(..., ge=0, le=100, example=70)


@router.post("/v2/orders/{orderId}/satisfaction", summary="Submit customer satisfaction level")
async def post_order_satisfaction(
    orderId: str = Path(..., description="Order ID"),
    satisfaction: SatisfactionRequest = Body(...),
    authorization: str = None
):
    """
    Submit the customer satisfaction level in range 0-100 (both inclusive)
    about the shopping session related to a given order.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AIFI_BASE_URL}/api/customer/v2/orders/{orderId}/satisfaction",
            json=satisfaction.dict(),
            headers={"Authorization": authorization}
        )
        return response.json()


@router.get("/v2/orders/draft", summary="Get draft orders")
async def get_draft_orders(
    authorization: str,
    count: int = Query(..., description="Number of orders to be listed"),
    direction: str = Query(..., regex="^(asc|desc)$", example="direction=desc"),
    after: str = Query(..., example="after=2314"),
    before: str = Query(..., example="before=1234"),
    storeId: Optional[int] = Query(None, example="storeId=1")
):
    """
    Get a list of customer's draft orders.
    """
    params = {
        "count": count,
        "direction": direction,
        "after": after,
        "before": before
    }
    if storeId:
        params["storeId"] = storeId

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{AIFI_BASE_URL}/api/customer/v2/orders/draft",
            params=params,
            headers={"Authorization": authorization}
        )
        return response.json()


@router.get("/v2/orders/draft/{draftOrderID}", summary="Get draft order details")
async def get_draft_order_details(
    draftOrderID: str = Path(..., example="12345", description="Id of a draft order"),
    authorization: str = None
):
    """
    Get detailed information about a specific draft order.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{AIFI_BASE_URL}/api/customer/v2/orders/draft/{draftOrderID}",
            headers={"Authorization": authorization}
        )
        return response.json()


# ============================================================================
# CUSTOMER APP - CONTESTS
# ============================================================================

class ContestItem(BaseModel):
    productId: str
    quantity: int


class ContestCreate(BaseModel):
    orderId: int = Field(..., ge=1, description="Order id. Required if sessionId not provided.")
    sessionId: Optional[int] = Field(None, description="Session id. Mutually exclusive with orderId.")
    message: Optional[str] = None
    items: Optional[List[ContestItem]] = None


@router.post("/v2/contests", summary="Create a contest for order")
async def create_contested_order(
    contest: ContestCreate,
    authorization: str
):
    """
    Create a contest/dispute for an order.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AIFI_BASE_URL}/api/customer/v2/contests",
            json=contest.dict(exclude_none=True),
            headers={"Authorization": authorization}
        )
        return response.json()


# ============================================================================
# CUSTOMER APP - PASSWORD RESET
# ============================================================================

class PasswordResetRequest(BaseModel):
    token: str
    email: str


@router.post("/v2/password-reset", summary="Reset password")
async def reset_password(reset_request: PasswordResetRequest):
    """
    This request will send an email to the user with 5 digits code
    which is used in the following request.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AIFI_BASE_URL}/api/customer/v2/password-reset",
            json=reset_request.dict()
        )
        return response.json()


class SetNewPasswordRequest(BaseModel):
    token: str
    password: str


@router.patch("/v2/password-reset", summary="Set new password")
async def set_new_password(password_request: SetNewPasswordRequest):
    """
    Request to set a new password with a password-reset token.
    """
    async with httpx.AsyncClient() as client:
        response = await client.patch(
            f"{AIFI_BASE_URL}/api/customer/v2/password-reset",
            json=password_request.dict()
        )
        return response.json()


class VerifyResetCodeRequest(BaseModel):
    token: str = Field(..., description="A randomly generated by client, unique string")
    code: str = Field(..., description="5 digit code received via email")


@router.post("/v2/password-reset/verify", summary="Verify reset code")
async def verify_reset_code(verify_request: VerifyResetCodeRequest):
    """
    Verify the 5-digit reset code sent to the customer's email.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AIFI_BASE_URL}/api/customer/v2/password-reset/verify",
            json=verify_request.dict()
        )
        return response.json()


# ============================================================================
# CUSTOMER APP - KEYCLOAK PASSWORD RESET
# ============================================================================

class KeycloakPasswordResetRequest(BaseModel):
    email: str


@router.post("/v2/keycloak/password-reset", summary="Reset keycloak password")
async def reset_keycloak_password(reset_request: KeycloakPasswordResetRequest):
    """
    This request will trigger keycloak to send password reset email.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AIFI_BASE_URL}/api/customer/v2/keycloak/password-reset",
            json=reset_request.dict()
        )
        return response.json()


# ============================================================================
# CUSTOMER APP - PRODUCTS SEARCH
# ============================================================================

@router.get("/v2/products", summary="Get products")
async def get_products(
    authorization: str,
    search: str = Query(..., description="Search query for product name"),
    storeId: Optional[int] = Query(None, description="Optional store ID to filter products")
):
    """
    Get a list of products searched by name.
    """
    params = {"search": search}
    if storeId:
        params["storeId"] = storeId

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{AIFI_BASE_URL}/api/customer/v2/products",
            params=params,
            headers={"Authorization": authorization}
        )
        return response.json()


# ============================================================================
# CUSTOMER APP - SESSIONS
# ============================================================================

class LoginRequestEmail(BaseModel):
    email: str
    password: str


class LoginRequestPhone(BaseModel):
    phone: str
    password: str


@router.post("/v2/sessions", summary="Login customer")
async def login_customer(login_data: Dict[str, Any] = Body(...)):
    """
    Logs the customer in and creates a new session.
    Accepts either email+password or phone+password.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AIFI_BASE_URL}/api/customer/v2/sessions",
            json=login_data
        )
        return response.json()


@router.delete("/v2/sessions", summary="Logout customer")
async def logout_customer(authorization: str):
    """
    Calling this endpoint will log customer out of all devices.
    """
    async with httpx.AsyncClient() as client:
        response = await client.delete(
            f"{AIFI_BASE_URL}/api/customer/v2/sessions",
            headers={"Authorization": authorization}
        )
        return response.json()


@router.post("/v2/sessions/refresh", summary="Refresh token")
async def refresh_token(authorization: str):
    """
    Refresh the authentication token.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AIFI_BASE_URL}/api/customer/v2/sessions/refresh",
            headers={"Authorization": authorization}
        )
        return response.json()


# ============================================================================
# CUSTOMER APP - PAYMENTS
# ============================================================================

@router.get("/v2/payments/methods/initialize", summary="Retrieve data to initialize card token addition")
async def initialize_payment_method_page(
    authorization: str,
    provider: Optional[str] = Query(None, description="Payment provider (e.g., FirstData)")
):
    """
    An endpoint that provides data that should be run on the client side
    to initialize the payment method addition flow.
    Only provides meaningful data for supported payment providers (currently FirstData only).
    """
    params = {}
    if provider:
        params["provider"] = provider

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{AIFI_BASE_URL}/api/customer/v2/payments/methods/initialize",
            params=params,
            headers={"Authorization": authorization}
        )
        return response.json()

