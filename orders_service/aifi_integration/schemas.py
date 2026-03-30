"""Pydantic models for all AiFi API request / response payloads.

Sections:
  - Common
  - Admin API  — Customer management
  - Admin API  — Product management
  - Admin API  — Store / gondola / shelf / device management
  - Admin API  — Order / session / contest / audit / config management
  - Admin API  — RFID Tags
  - Store API  (/api/aifi/*)   — in-store events
  - Customer App API (/api/customer/v2/*)
  - Push API   — incoming webhook payloads from AiFi
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─────────────────────────────────────────────────────────────────────────────
# COMMON
# ─────────────────────────────────────────────────────────────────────────────

class _AiFiBase(BaseModel):
    """Base with alias population enabled for all AiFi models."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — CUSTOMER MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

class CustomerCreate(_AiFiBase):
    """POST /api/admin/v2/customers"""
    email: Optional[str] = None
    external_id: Optional[str] = Field(None, alias="externalId")
    first_name: Optional[str] = Field(None, alias="firstName")
    last_name: Optional[str] = Field(None, alias="lastName")
    phone: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class CustomerUpdate(_AiFiBase):
    """PATCH /api/admin/v2/customers/{customerId}"""
    email: Optional[str] = None
    first_name: Optional[str] = Field(None, alias="firstName")
    last_name: Optional[str] = Field(None, alias="lastName")
    phone: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class CustomerResponse(_AiFiBase):
    id: Optional[int] = None
    email: Optional[str] = None
    external_id: Optional[str] = Field(None, alias="externalId")
    first_name: Optional[str] = Field(None, alias="firstName")
    last_name: Optional[str] = Field(None, alias="lastName")
    phone: Optional[str] = None
    role: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")


class RemoteRegisterRequest(_AiFiBase):
    """POST /api/admin/v2/customers/remote-register"""
    email: str
    external_id: Optional[str] = Field(None, alias="externalId")
    first_name: Optional[str] = Field(None, alias="firstName")
    last_name: Optional[str] = Field(None, alias="lastName")
    phone: Optional[str] = None


class EntryCodeCreate(_AiFiBase):
    """POST /api/admin/v2/customers/{customerId}/entry-codes"""
    code: Optional[str] = None
    group_size: Optional[int] = Field(None, alias="groupSize")
    session_id: Optional[str] = Field(None, alias="sessionId")
    expires_at: Optional[datetime] = Field(None, alias="expiresAt")
    priority: int = 0


class EntryCodeResponse(_AiFiBase):
    code: str


class CardTokenUpdate(_AiFiBase):
    """PATCH /api/admin/v2/customers/{customerId}/card-token"""
    card_token: str = Field(alias="cardToken")
    provider: Any = None


class CardCreate(_AiFiBase):
    """POST /api/admin/v2/customers/{customerId}/card"""
    card_token: str = Field(alias="cardToken")
    provider: Any = None


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — PRODUCT MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

class ProductVariantCreate(_AiFiBase):
    """POST /api/admin/v2/products/{productId}/variants"""
    name: Optional[str] = None
    price: Optional[float] = None
    barcode: Optional[str] = None
    barcodes: Optional[list[str]] = None
    external_id: Optional[str] = Field(None, alias="externalId")
    metadata: Optional[dict[str, Any]] = None


class ProductVariantUpdate(_AiFiBase):
    """PATCH /api/admin/v2/products/variants/{variantId}"""
    name: Optional[str] = None
    price: Optional[float] = None
    barcode: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class ProductVariantResponse(_AiFiBase):
    id: Optional[int] = None
    name: Optional[str] = None
    price: Optional[float] = None
    barcode: Optional[str] = None
    barcodes: Optional[list[str]] = None
    external_id: Optional[str] = Field(None, alias="externalId")
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")


class ProductCreate(_AiFiBase):
    """POST /api/admin/v2/products"""
    name: str
    price: Optional[float] = None
    quantity: Optional[int] = None
    barcode: Optional[str] = None
    barcodes: Optional[list[str]] = None
    category: Optional[str] = None
    external_id: Optional[str] = Field(None, alias="externalId")
    thumbnail: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class ProductUpdate(_AiFiBase):
    """PUT /api/admin/v2/products/{productId}"""
    name: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[int] = None
    barcode: Optional[str] = None
    barcodes: Optional[list[str]] = None
    category: Optional[str] = None
    thumbnail: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class ProductUpsert(ProductCreate):
    """PUT /api/admin/v2/products  (upsert by externalId)"""


class ProductResponse(_AiFiBase):
    id: Optional[int] = None
    name: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[int] = None
    barcode: Optional[str] = None
    barcodes: Optional[list[str]] = None
    category: Optional[str] = None
    external_id: Optional[str] = Field(None, alias="externalId")
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")


class BarcodeAdd(_AiFiBase):
    """POST /api/admin/v2/products/variants/{variantId}/barcodes"""
    barcode: str


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — STORE / GONDOLA / SHELF / DEVICE MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

class StoreCreate(_AiFiBase):
    """POST /api/admin/v2/stores"""
    name: str
    external_id: Optional[str] = Field(None, alias="externalId")
    address: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class StoreUpdate(_AiFiBase):
    """PATCH /api/admin/v2/stores/{storeId}"""
    name: Optional[str] = None
    external_id: Optional[str] = Field(None, alias="externalId")
    address: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class StoreResponse(_AiFiBase):
    id: Optional[str] = None
    name: Optional[str] = None
    external_id: Optional[str] = Field(None, alias="externalId")
    address: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")


class ShelfCreate(_AiFiBase):
    """POST /api/admin/v2/stores/{storeId}/shelves"""
    gondola_id: Optional[str] = Field(None, alias="gondolaId")
    position: Optional[dict[str, Any]] = None
    metadata: Optional[dict[str, Any]] = None


class ShelfUpdate(_AiFiBase):
    """PATCH /api/admin/v2/stores/{storeId}/shelves/{shelfId}"""
    position: Optional[dict[str, Any]] = None
    metadata: Optional[dict[str, Any]] = None


class InventoryUpdate(_AiFiBase):
    """PUT /api/admin/v2/stores/{storeId}/shelves/{shelfId}/bins/{binIndex}/inventory"""
    quantity: int
    product_id: Optional[int] = Field(None, alias="productId")


class DeviceEventCreate(_AiFiBase):
    """POST /api/admin/v2/stores/{storeId}/thirdPartyDevices/{deviceId}/events"""
    event_type: str = Field(alias="eventType")
    payload: Optional[dict[str, Any]] = None
    timestamp: Optional[datetime] = None


class FrameAnnotationEvent(_AiFiBase):
    """POST /api/admin/v2/stores/{storeId}/idapDevices/{idapDeviceId}/frame-annotation-event"""
    annotation_type: Optional[str] = Field(None, alias="annotationType")
    frame_id: Optional[str] = Field(None, alias="frameId")
    payload: Optional[dict[str, Any]] = None


class ShopperEvent(_AiFiBase):
    """POST /api/admin/v2/stores/{storeId}/shoppers/{shopperId}"""
    event_type: str = Field(alias="eventType")
    payload: Optional[dict[str, Any]] = None
    timestamp: Optional[datetime] = None


class ShopperUpdate(_AiFiBase):
    """PATCH /api/admin/v2/stores/{storeId}/shoppers/{shopperId}"""
    customer_id: Optional[int] = Field(None, alias="customerId")
    metadata: Optional[dict[str, Any]] = None


class EntryCodeVerifyAdmin(_AiFiBase):
    """POST /api/admin/v2/stores/{storeId}/check-in/{checkInDeviceId}/entry-codes/verify"""
    code: str
    group_size: Optional[int] = Field(None, alias="groupSize")


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — ORDERS / SESSIONS / CONTESTS / AUDITS / CONFIG
# ─────────────────────────────────────────────────────────────────────────────

class OrderItem(_AiFiBase):
    product_id: int = Field(alias="productId")
    quantity: int
    price: Optional[float] = None


class OrderCreate(_AiFiBase):
    """POST /api/admin/v2/orders"""
    customer_id: Optional[int] = Field(None, alias="customerId")
    store_id: Optional[str] = Field(None, alias="storeId")
    items: list[OrderItem] = Field(default_factory=list)
    metadata: Optional[dict[str, Any]] = None


class OrderUpdate(_AiFiBase):
    """PATCH /api/admin/v2/orders/{orderId}"""
    status: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class OrderResponse(_AiFiBase):
    id: Optional[int] = None
    customer_id: Optional[int] = Field(None, alias="customerId")
    store_id: Optional[str] = Field(None, alias="storeId")
    status: Optional[str] = None
    amount: Optional[float] = None
    items: Optional[list[dict[str, Any]]] = None
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")


class CartItem(_AiFiBase):
    product_id: int = Field(alias="productId")
    quantity: int
    price: Optional[float] = None


class CartUpdate(_AiFiBase):
    """POST /api/admin/v2/sessions/{sessionId}/cart"""
    items: list[CartItem] = Field(default_factory=list)


class SessionUpdate(_AiFiBase):
    """PATCH /api/admin/v2/sessions/{sessionId}"""
    status: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class AdminCheckoutCreate(_AiFiBase):
    """POST /api/admin/v2/sessions/{sessionId}/checkout"""
    payment_method: Optional[str] = Field(None, alias="paymentMethod")
    card_id: Optional[int] = Field(None, alias="cardId")
    metadata: Optional[dict[str, Any]] = None


class ContestCreate(_AiFiBase):
    """POST /api/admin/v2/contests"""
    name: str
    store_id: Optional[str] = Field(None, alias="storeId")
    start_date: Optional[datetime] = Field(None, alias="startDate")
    end_date: Optional[datetime] = Field(None, alias="endDate")
    metadata: Optional[dict[str, Any]] = None


class RetailerConfigUpdate(_AiFiBase):
    """PATCH /api/admin/v2/retailer/config"""
    config: dict[str, Any] = Field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — RFID TAGS
# ─────────────────────────────────────────────────────────────────────────────

class TagCreate(_AiFiBase):
    """POST /api/admin/v2/stores/{storeId}/tags"""
    tag_id: str = Field(alias="tagId")
    product_id: Optional[int] = Field(None, alias="productId")
    metadata: Optional[dict[str, Any]] = None


class TagResponse(_AiFiBase):
    id: Optional[str] = None
    tag_id: Optional[str] = Field(None, alias="tagId")
    product_id: Optional[int] = Field(None, alias="productId")
    created_at: Optional[datetime] = Field(None, alias="createdAt")


# ─────────────────────────────────────────────────────────────────────────────
# STORE API (/api/aifi/*) — in-store event models
# ─────────────────────────────────────────────────────────────────────────────

class CheckoutZoneEvent(_AiFiBase):
    """POST /api/aifi/checkout_zone/entered|left"""
    shopper_id: Optional[str] = Field(None, alias="shopperId")
    store_id: Optional[str] = Field(None, alias="storeId")
    timestamp: Optional[datetime] = None
    metadata: Optional[dict[str, Any]] = None


class CustomerEnteredEvent(_AiFiBase):
    """POST /api/aifi/customers/entered"""
    customer_id: Optional[int] = Field(None, alias="customerId")
    store_id: Optional[str] = Field(None, alias="storeId")
    entry_code: Optional[str] = Field(None, alias="entryCode")
    timestamp: Optional[datetime] = None


class CustomerWalkedOutEvent(_AiFiBase):
    """POST /api/aifi/customers/walked-out"""
    customer_id: Optional[int] = Field(None, alias="customerId")
    store_id: Optional[str] = Field(None, alias="storeId")
    timestamp: Optional[datetime] = None


class RegisterWithTokenRequest(_AiFiBase):
    """POST /api/aifi/customers/register-with-token"""
    session_token: str = Field(alias="sessionToken")
    email: Optional[str] = None
    first_name: Optional[str] = Field(None, alias="firstName")
    last_name: Optional[str] = Field(None, alias="lastName")
    phone: Optional[str] = None


class StoreCheckoutCreate(_AiFiBase):
    """POST /api/aifi/checkouts"""
    session_id: Optional[str] = Field(None, alias="sessionId")
    items: Optional[list[dict[str, Any]]] = None
    total: Optional[float] = None
    payment: Optional[dict[str, Any]] = None


class EntryCodeVerify(_AiFiBase):
    """POST /api/aifi/entry-codes/verify"""
    code: str
    group_size: Optional[int] = Field(None, alias="groupSize")


class TrackingAssociationForward(_AiFiBase):
    """POST /api/aifi/tracking-association/forward"""
    tracking_data: Optional[dict[str, Any]] = Field(None, alias="trackingData")


class RestrictedProductInteractionForward(_AiFiBase):
    """POST /api/aifi/restricted-products-interactions/forward"""
    interaction_data: Optional[dict[str, Any]] = Field(None, alias="interactionData")


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMER APP API (/api/customer/v2/*)
# ─────────────────────────────────────────────────────────────────────────────

class CustomerRegister(_AiFiBase):
    """POST /api/customer/v2/customers"""
    email: str
    password: str
    first_name: Optional[str] = Field(None, alias="firstName")
    last_name: Optional[str] = Field(None, alias="lastName")
    phone: Optional[str] = None
    external_id: Optional[str] = Field(None, alias="externalId")


class CustomerLogin(_AiFiBase):
    """POST /api/customer/v2/sessions"""
    email: str
    password: str


class TokenRefresh(_AiFiBase):
    """POST /api/customer/v2/sessions/refresh"""
    refresh_token: str = Field(alias="refreshToken")


class PasswordResetRequest(_AiFiBase):
    """POST /api/customer/v2/password-reset"""
    email: str


class PasswordResetVerify(_AiFiBase):
    """POST /api/customer/v2/password-reset/verify"""
    code: str
    new_password: str = Field(alias="newPassword")


class CustomerAppEntryCode(_AiFiBase):
    """POST /api/customer/v2/entry-codes"""
    code: Optional[str] = None
    group_size: Optional[int] = Field(None, alias="groupSize")


class CustomerOrderPayment(_AiFiBase):
    """POST /api/customer/v2/orders/{orderId}/payment"""
    amount: float
    payment_method: Optional[str] = Field(None, alias="paymentMethod")
    card_id: Optional[int] = Field(None, alias="cardId")


class CustomerContestEntry(_AiFiBase):
    """POST /api/customer/v2/contests"""
    contest_id: Optional[str] = Field(None, alias="contestId")
    metadata: Optional[dict[str, Any]] = None


class PaymentMethodInit(_AiFiBase):
    """POST /api/customer/v2/payments/methods/initialize"""
    provider: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


# ─────────────────────────────────────────────────────────────────────────────
# PUSH API — incoming webhook payloads sent by AiFi to our service
# ─────────────────────────────────────────────────────────────────────────────

class PushCheckoutPayload(_AiFiBase):
    order_id: Optional[int] = Field(None, alias="orderId")
    customer_id: Optional[int] = Field(None, alias="customerId")
    total: Optional[float] = None
    items: Optional[list[dict[str, Any]]] = None
    timestamp: Optional[datetime] = None


class PushCustomerPayload(_AiFiBase):
    customer_id: Optional[int] = Field(None, alias="customerId")
    email: Optional[str] = None
    external_id: Optional[str] = Field(None, alias="externalId")
    event: Optional[str] = None
    timestamp: Optional[datetime] = None


class PushEntryCodePayload(_AiFiBase):
    code: Optional[str] = None
    customer_id: Optional[int] = Field(None, alias="customerId")
    store_id: Optional[str] = Field(None, alias="storeId")
    expires_at: Optional[datetime] = Field(None, alias="expiresAt")


class PushTrackingPayload(_AiFiBase):
    shopper_id: Optional[str] = Field(None, alias="shopperId")
    store_id: Optional[str] = Field(None, alias="storeId")
    coordinates: Optional[dict[str, Any]] = None
    timestamp: Optional[datetime] = None


class PushIdentityMatchingPayload(_AiFiBase):
    shopper_id: Optional[str] = Field(None, alias="shopperId")
    customer_id: Optional[int] = Field(None, alias="customerId")
    confidence: Optional[float] = None
    timestamp: Optional[datetime] = None


class PushTransitionPayload(_AiFiBase):
    session_id: Optional[str] = Field(None, alias="sessionId")
    from_state: Optional[str] = Field(None, alias="fromState")
    to_state: Optional[str] = Field(None, alias="toState")
    timestamp: Optional[datetime] = None


class PushCartMutatorPayload(_AiFiBase):
    session_id: Optional[str] = Field(None, alias="sessionId")
    items: Optional[list[dict[str, Any]]] = None
    cart_value: Optional[float] = Field(None, alias="cartValue")
    timestamp: Optional[datetime] = None


class PushRestrictedProductsPayload(_AiFiBase):
    product_id: Optional[int] = Field(None, alias="productId")
    shopper_id: Optional[str] = Field(None, alias="shopperId")
    interaction_type: Optional[str] = Field(None, alias="interactionType")
    timestamp: Optional[datetime] = None


class PushEvaluateOrderPricePayload(_AiFiBase):
    session_id: Optional[str] = Field(None, alias="sessionId")
    order_id: Optional[int] = Field(None, alias="orderId")
    items: Optional[list[dict[str, Any]]] = None
    timestamp: Optional[datetime] = None


class PushHealthPayload(_AiFiBase):
    store_id: Optional[str] = Field(None, alias="storeId")
    status: Optional[str] = None
    metrics: Optional[dict[str, Any]] = None
    timestamp: Optional[datetime] = None
