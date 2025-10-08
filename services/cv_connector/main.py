# CV Connector Service - Enhanced V4.1 Architecture
# Multi-provider CV integration with sagas, events, and RLS

import os
import uuid
import json
import hmac
import hashlib
import base64
import io
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

import httpx
import qrcode
from PIL import Image
from fastapi import FastAPI, Body, HTTPException, Request, Query, Path, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text, create_engine, Column, String, Integer, Boolean, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
from sqlalchemy.sql import func

# Prometheus metrics
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

# Common imports
from zeroque_common.db.session import get_engine, init_db, SessionLocal
from zeroque_common.middleware.usage_middleware import add_api_call_meter
from zeroque_common.middleware.idempotency import add_idempotency_middleware

# =============================================================================
# PROMETHEUS METRICS
# =============================================================================

# Metrics for CV Connector
cv_connector_requests_total = Counter(
    'cv_connector_requests_total', 
    'Total CV connector requests',
    ['method', 'endpoint', 'provider', 'status']
)

cv_connector_request_duration = Histogram(
    'cv_connector_request_duration_seconds',
    'CV connector request duration',
    ['method', 'endpoint', 'provider']
)

cv_provider_api_calls_total = Counter(
    'cv_provider_api_calls_total',
    'Total CV provider API calls',
    ['provider', 'operation', 'status']
)

cv_provider_api_duration = Histogram(
    'cv_provider_api_duration_seconds',
    'CV provider API call duration',
    ['provider', 'operation']
)

cv_sync_operations_total = Counter(
    'cv_sync_operations_total',
    'Total CV sync operations',
    ['operation', 'provider', 'status']
)

# =============================================================================
# CONFIGURATION
# =============================================================================

class Settings(BaseModel):
    SERVICE_NAME: str = "cv_connector_v4"
    DEFAULT_PROVIDER: str = os.getenv("CV_PROVIDER", "aifi")
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/zeroque")
    
    # Service URLs
    CV_GATEWAY_BASE_URL: str = os.getenv("CV_GATEWAY_BASE_URL", "http://localhost:8000")
    PROVISIONING_BASE_URL: str = os.getenv("PROVISIONING_BASE_URL", "http://localhost:8080")
    CATALOG_BASE_URL: str = os.getenv("CATALOG_BASE_URL", "http://localhost:8081")
    
    # Security
    JWT_SECRET: str = os.getenv("JWT_SECRET", "")
    WEBHOOK_SHARED_SECRET: str = os.getenv("WEBHOOK_SHARED_SECRET", "")
    
    # Provider-specific configs (fallback)
    AIFI_BASE_URL: str = os.getenv("AIFI_BASE_URL", "https://api.aifi.example")
    AIFI_API_KEY: str = os.getenv("AIFI_API_KEY", "")
    
    # QR Code settings
    QR_CODE_SIZE: int = int(os.getenv("QR_CODE_SIZE", "10"))
    QR_CODE_BORDER: int = int(os.getenv("QR_CODE_BORDER", "4"))

settings = Settings()

# =============================================================================
# DATABASE MODELS
# =============================================================================

Base = declarative_base()

class ZeroqueRail(Base):
    """CV provider configuration"""
    __tablename__ = "zeroque_rails"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    type = Column(String(50), nullable=False)  # 'cv', 'payment', etc.
    name = Column(String(100), nullable=False)  # 'aifi', 'stripe', etc.
    config = Column(JSONB, nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    __table_args__ = (
        UniqueConstraint('tenant_id', 'type', 'name', name='uq_zeroque_rails_tenant_type_name'),
    )

class ProviderMapping(Base):
    """External provider ID mappings"""
    __tablename__ = "provider_mappings"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    provider = Column(String(50), nullable=False)
    entity_type = Column(String(50), nullable=False)  # 'user', 'store', 'product', etc.
    local_id = Column(String(255), nullable=False)
    external_id = Column(String(255), nullable=False)
    metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    __table_args__ = (
        UniqueConstraint('provider', 'entity_type', 'local_id', name='uq_provider_mappings_provider_entity_local'),
        UniqueConstraint('provider', 'entity_type', 'external_id', name='uq_provider_mappings_provider_entity_external'),
    )

class CvUnknownItemReview(Base):
    """Unknown item reviews for reconciliation"""
    __tablename__ = "cv_unknown_item_reviews"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    site_id = Column(UUID(as_uuid=True), ForeignKey('sites.site_id'), nullable=True)
    store_id = Column(UUID(as_uuid=True), ForeignKey('stores.store_id'), nullable=True)
    provider = Column(String(50), nullable=False)
    external_sku = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    qty = Column(Integer, nullable=False)
    price_minor = Column(Integer, nullable=False)
    payload_json = Column(JSONB, nullable=False)
    status = Column(String(20), nullable=False, default='pending')
    mapped_sku = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    resolved_by = Column(String(255), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class OutboxEvent(Base):
    """Reliable event publishing"""
    __tablename__ = "outbox_events"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=True)
    event_type = Column(String(100), nullable=False)
    event_data = Column(JSONB, nullable=False)
    status = Column(String(20), nullable=False, default='pending')
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class AuditLog(Base):
    """Audit trail for operations"""
    __tablename__ = "audit_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.user_id'), nullable=True)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(String(255), nullable=True)
    details = Column(JSONB, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

# =============================================================================
# PYDANTIC SCHEMAS
# =============================================================================

class ProviderConfig(BaseModel):
    """Provider configuration schema"""
    provider: str = Field(..., description="Provider name (aifi, etc.)")
    api_key: str = Field(..., description="API key")
    base_url: str = Field(..., description="Base URL")
    location_id: Optional[str] = Field(None, description="Location ID if required")
    store_id: Optional[str] = Field(None, description="Store ID if required")

class ZeroqueRailRequest(BaseModel):
    """Request to create/update zeroque rail"""
    type: str = Field("cv", description="Rail type")
    name: str = Field(..., description="Provider name")
    config: ProviderConfig = Field(..., description="Provider configuration")
    active: bool = Field(True, description="Whether rail is active")

class ProviderParam(BaseModel):
    """Provider parameter for multi-provider support"""
    provider: str = Field(..., description="Provider name")

class EntryCodeCreate(BaseModel):
    """Create entry code request"""
    tenant_id: str = Field(..., description="Tenant ID")
    user_id: str = Field(..., description="User ID")
    provider: Optional[str] = Field(None, description="Provider override")
    group_size: Optional[int] = Field(None, description="Group size")
    displayable: bool = Field(True, description="Generate QR code")
    extra: Optional[Dict[str, Any]] = Field(None, description="Additional data")
    
    @field_validator('tenant_id', 'user_id')
    @classmethod
    def validate_uuids(cls, v):
        try:
            uuid.UUID(v)
            return v
        except ValueError:
            raise ValueError('Invalid UUID format')

class EntryVerifyRequest(BaseModel):
    """Verify entry code request"""
    tenant_id: str = Field(..., description="Tenant ID")
    verification_code: str = Field(..., description="Verification code")
    store_id: str = Field(..., description="Store ID")
    entry_id: str = Field(..., description="Entry ID")
    provider: Optional[str] = Field(None, description="Provider override")
    group_size: Optional[int] = Field(None, description="Group size")
    check_in_device_id: Optional[int] = Field(None, description="Check-in device ID")
    
    @field_validator('tenant_id', 'store_id')
    @classmethod
    def validate_uuids(cls, v):
        try:
            uuid.UUID(v)
            return v
        except ValueError:
            raise ValueError('Invalid UUID format')

class EntryVerifyResponse(BaseModel):
    """Entry verification response"""
    status: str = Field(..., description="Verification status")
    session_id: Optional[str] = Field(None, description="Session ID")
    reason: Optional[str] = Field(None, description="Failure reason")
    shopper_role: Optional[str] = Field(None, description="Shopper role")

class EntryWebhookDecision(BaseModel):
    """Entry webhook decision"""
    status: str = Field(..., description="Decision status")
    reason: Optional[str] = Field(None, description="Decision reason")

class SimpleOK(BaseModel):
    """Simple OK response"""
    ok: bool = Field(..., description="Success status")

class CustomerUpsert(BaseModel):
    """Customer upsert schema"""
    external_id: str = Field(..., description="External customer ID")
    email: Optional[str] = Field(None, description="Customer email")
    first_name: Optional[str] = Field(None, description="First name")
    last_name: Optional[str] = Field(None, description="Last name")
    phone: Optional[str] = Field(None, description="Phone number")
    role: str = Field("customer", description="Customer role")
    password: Optional[str] = Field(None, description="Password")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")

class ProductUpsert(BaseModel):
    """Product upsert schema"""
    external_id: str = Field(..., description="External product ID")
    name: str = Field(..., description="Product name")
    price: Optional[float] = Field(None, description="Product price")
    barcode: Optional[str] = Field(None, description="Product barcode")
    restricted: bool = Field(False, description="Restricted item")
    tax_code: Optional[str] = Field(None, description="Tax code")
    variants: List[dict] = Field(default_factory=list, description="Product variants")

class InventoryAdjust(BaseModel):
    """Inventory adjustment schema"""
    product_id: str = Field(..., description="Product ID")
    quantity_difference: Optional[int] = Field(None, description="Quantity difference")
    quantity: Optional[int] = Field(None, description="Absolute quantity")

class SyncBatchRequest(BaseModel):
    """Batch sync request"""
    tenant_id: str = Field(..., description="Tenant ID")
    provider: Optional[str] = Field(None, description="Provider override")
    customers: List[CustomerUpsert] = Field(default_factory=list, description="Customers to sync")
    products: List[ProductUpsert] = Field(default_factory=list, description="Products to sync")
    inventory: List[InventoryAdjust] = Field(default_factory=list, description="Inventory adjustments")
    
    @field_validator('tenant_id')
    @classmethod
    def validate_tenant_id(cls, v):
        try:
            uuid.UUID(v)
            return v
        except ValueError:
            raise ValueError('Invalid tenant_id format')

# =============================================================================
# PROVIDER INTERFACE
# =============================================================================

class CVProvider:
    """Base CV provider interface"""
    
    def __init__(self, config: ProviderConfig):
        self.config = config
        self.name = config.provider
    
    async def create_entry_code(self, payload: dict) -> dict:
        """Create entry code for customer"""
        raise NotImplementedError
    
    async def verify_entry_code(self, verification_code: str, **kwargs) -> EntryVerifyResponse:
        """Verify entry code"""
        raise NotImplementedError
    
    async def push_customer(self, customer: dict) -> dict:
        """Push customer to provider"""
        raise NotImplementedError
    
    async def push_product(self, product: dict) -> dict:
        """Push product to provider"""
        raise NotImplementedError
    
    async def update_inventory(self, product_id: str, **kwargs) -> dict:
        """Update inventory in provider"""
        raise NotImplementedError
    
    def adapt_entry_webhook_to_decision(self, payload: dict) -> EntryWebhookDecision:
        """Adapt entry webhook to decision format"""
        raise NotImplementedError
    
    def adapt_checkout_to_order(self, payload: dict) -> dict:
        """Adapt checkout webhook to order format"""
        raise NotImplementedError

class AiFiProvider(CVProvider):
    """AiFi CV provider implementation"""
    
    async def create_entry_code(self, payload: dict) -> dict:
        """Create entry code for AiFi customer"""
        customer_id = payload.get("customerId")
        user_external_id = payload.get("userExternalId")
        displayable = payload.get("displayable", True)
        
        if not customer_id and user_external_id:
            # Resolve from mapping
            customer_id = await self._resolve_mapping("user", user_external_id)
        
        if not customer_id:
            raise ValueError("customerId_required")
        
        path = f"/api/admin/v2/customers/{customer_id}/entry-codes"
        params = {"displayable": str(displayable).lower()}
        body = payload.get("body") or {}
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.config.base_url}{path}",
                headers=self._get_headers(),
                params=params,
                json=body
            )
        response.raise_for_status()
        return response.json()
    
    async def verify_entry_code(self, verification_code: str, **kwargs) -> EntryVerifyResponse:
        """Verify entry code for AiFi"""
        store_id = kwargs.get("store_id")
        entry_id = kwargs.get("entry_id")
        
        path = f"/api/admin/v2/stores/{store_id}/entry/{entry_id}/entry-codes/verify"
        body = {"verificationCode": verification_code}
        
        if "group_size" in kwargs:
            body["groupSize"] = kwargs["group_size"]
        if "check_in_device_id" in kwargs:
            body["checkInDeviceId"] = kwargs["check_in_device_id"]
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.config.base_url}{path}",
                headers=self._get_headers(),
                json=body
            )
        response.raise_for_status()
        return EntryVerifyResponse(**response.json())
    
    async def push_customer(self, customer: dict) -> dict:
        """Push customer to AiFi"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.config.base_url}/api/admin/v2/customers",
                headers=self._get_headers(),
                json=customer
            )
        return {
            "ok": response.status_code in (200, 201),
            "status": response.status_code,
            "body": response.json() if response.status_code in (200, 201) else response.text
        }
    
    async def push_product(self, product: dict) -> dict:
        """Push product to AiFi"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.config.base_url}/api/admin/v2/products:upsert",
                headers=self._get_headers(),
                json=product
            )
        
        if response.status_code in (404, 405):
            # Fallback to create
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.config.base_url}/api/admin/v2/products",
                    headers=self._get_headers(),
                    json=product
                )
        
        return {
            "ok": response.status_code in (200, 201),
            "status": response.status_code,
            "body": response.json() if response.status_code in (200, 201) else response.text
        }
    
    async def update_inventory(self, product_id: str, **kwargs) -> dict:
        """Update inventory in AiFi"""
        path = f"/api/aifi/inventory/products/{product_id}"
        body = {}
        
        if "quantity_difference" in kwargs:
            body["quantityDifference"] = kwargs["quantity_difference"]
        if "quantity" in kwargs:
            body["quantity"] = kwargs["quantity"]
        
        params = {}
        if self.config.store_id:
            params["storeId"] = self.config.store_id
        
        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{self.config.base_url}{path}",
                headers=self._get_headers(),
                json=body,
                params=params
            )
        
        return {
            "ok": response.status_code in (200, 204),
            "status": response.status_code,
            "body": response.json() if response.text else None
        }
    
    def adapt_entry_webhook_to_decision(self, payload: dict) -> EntryWebhookDecision:
        """Adapt entry webhook to decision format"""
        ok = bool((payload or {}).get("payment"))
        return EntryWebhookDecision(
            status="OK" if ok else "FAILED",
            reason=None if ok else "Payment verification failed"
        )
    
    def adapt_checkout_to_order(self, payload: dict) -> dict:
        """Adapt checkout webhook to order format"""
        customer = payload.get("customer") or {}
        store = payload.get("store") or {}
        cart = payload.get("cart") or []
        currency = ((payload.get("amount") or {}).get("currency") or "GBP").upper()
        
        items = []
        for item in cart:
            sku = item.get("sku") or item.get("id") or item.get("barcode") or "UNKNOWN"
            qty = int(item.get("quantity", item.get("qty", 1)))
            items.append({
                "sku": sku,
                "name": item.get("name") or sku,
                "qty": qty,
                "price_minor": int(item.get("priceMinor", 0))
            })
        
        return {
            "provider_order_id": str(payload.get("orderId") or payload.get("id") or ""),
            "tenant_ext_id": None,
            "site_ext_id": None,
            "store_ext_id": str(payload.get("storeExternalId") or store.get("externalId") or ""),
            "user_ext_id": str(customer.get("externalId") or customer.get("id") or ""),
            "currency": currency,
            "items": items,
            "occurred_at": payload.get("timeOfOrigin") or payload.get("timeOfIssue"),
        }
    
    def _get_headers(self) -> dict:
        """Get AiFi headers"""
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        if self.config.location_id:
            headers["X-Location-Id"] = self.config.location_id
        return headers
    
    async def _resolve_mapping(self, entity_type: str, local_id: str) -> Optional[str]:
        """Resolve external ID from mapping"""
        # This would be implemented with database access
        # For now, return None to indicate not found
        return None

# =============================================================================
# SECURITY & AUTHENTICATION
# =============================================================================

async def get_user_context(request: Request) -> dict:
    """Get user context from JWT token (demo implementation)"""
    # In production, this would validate JWT and extract user info
    # For demo purposes, return a mock user context
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        # For demo, allow requests without auth but with limited permissions
        return {
            "user_id": "demo_user",
            "tenant_id": "demo_tenant",
            "permissions": ["cv.read"]
        }
    
    # In production: validate JWT token and extract claims
    token = auth_header.split(" ")[1]
    return {
        "user_id": "authenticated_user",
        "tenant_id": "authenticated_tenant", 
        "permissions": ["cv.read", "cv.sync", "cv.admin"]
    }

async def check_permission(user_context: dict, required_permission: str) -> bool:
    """Check if user has required permission"""
    user_permissions = user_context.get("permissions", [])
    return required_permission in user_permissions or "cv.admin" in user_permissions

# =============================================================================
# UTILITIES
# =============================================================================

def verify_webhook_signature(request: Request, payload: dict):
    """Verify webhook signature"""
    secret = settings.WEBHOOK_SHARED_SECRET
    if not secret:
        return
    
    provided = request.headers.get("X-Signature", "")
    if not provided.startswith("sha256="):
        raise HTTPException(status_code=401, detail="missing_signature")
    
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="bad_signature")

def generate_qr_code(data: str) -> str:
    """Generate QR code and return as base64 image"""
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=settings.QR_CODE_SIZE,
            border=settings.QR_CODE_BORDER,
        )
        qr.add_data(data)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert to base64
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        img_str = base64.b64encode(buffer.getvalue()).decode()
        
        return f"data:image/png;base64,{img_str}"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QR code generation failed: {str(e)}")

def set_rls_context(db: Session, tenant_id: str):
    """Set RLS context for database session"""
    db.execute(text("SET LOCAL app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})

async def get_provider_config(db: Session, tenant_id: str, provider_name: str) -> Optional[ProviderConfig]:
    """Get provider configuration from zeroque_rails"""
    rail = db.query(ZeroqueRail).filter(
        ZeroqueRail.tenant_id == tenant_id,
        ZeroqueRail.type == "cv",
        ZeroqueRail.name == provider_name,
        ZeroqueRail.active == True
    ).first()
    
    if not rail:
        return None
    
    return ProviderConfig(**rail.config)

async def get_provider(provider_config: ProviderConfig) -> CVProvider:
    """Get provider instance based on configuration"""
    if provider_config.provider == "aifi":
        return AiFiProvider(provider_config)
    else:
        raise ValueError(f"Unsupported provider: {provider_config.provider}")

async def publish_event(db: Session, event_type: str, event_data: dict, tenant_id: Optional[str] = None):
    """Publish event to outbox for reliable delivery"""
    event = OutboxEvent(
        tenant_id=tenant_id,
        event_type=event_type,
        event_data=event_data,
        status="pending"
    )
    db.add(event)
    db.commit()

async def log_audit(db: Session, action: str, resource_type: str, resource_id: Optional[str] = None,
                   details: Optional[dict] = None, user_id: Optional[str] = None, tenant_id: Optional[str] = None):
    """Log audit trail"""
    audit = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details
    )
    db.add(audit)
    db.commit()

# =============================================================================
# EVENT AUTOMATION
# =============================================================================

async def handle_product_created_event(event_data: dict, db: Session):
    """Handle PRODUCT_CREATED event for auto-sync"""
    try:
        tenant_id = event_data.get("tenant_id")
        product_data = event_data.get("product")
        
        if not tenant_id or not product_data:
            return
        
        # Get provider configuration
        provider_config = await get_provider_config(db, tenant_id, settings.DEFAULT_PROVIDER)
        if not provider_config:
            return
        
        # Get provider instance
        provider = await get_provider(provider_config)
        
        # Push product to provider
        result = await provider.push_product(product_data)
        
        # Update metrics
        cv_sync_operations_total.labels(
            operation="product_sync",
            provider=provider_config.provider,
            status="success" if result.get("ok") else "failure"
        ).inc()
        
        # Log audit
        await log_audit(
            db, "auto_sync_product", "product",
            details={"product_id": product_data.get("external_id"), "provider": provider_config.provider},
            tenant_id=tenant_id
        )
        
    except Exception as e:
        cv_sync_operations_total.labels(
            operation="product_sync",
            provider="unknown",
            status="error"
        ).inc()
        print(f"Auto-sync product failed: {e}")

async def handle_user_created_event(event_data: dict, db: Session):
    """Handle USER_CREATED event for auto-sync"""
    try:
        tenant_id = event_data.get("tenant_id")
        user_data = event_data.get("user")
        
        if not tenant_id or not user_data:
            return
        
        # Get provider configuration
        provider_config = await get_provider_config(db, tenant_id, settings.DEFAULT_PROVIDER)
        if not provider_config:
            return
        
        # Get provider instance
        provider = await get_provider(provider_config)
        
        # Push customer to provider
        result = await provider.push_customer(user_data)
        
        # Update metrics
        cv_sync_operations_total.labels(
            operation="user_sync",
            provider=provider_config.provider,
            status="success" if result.get("ok") else "failure"
        ).inc()
        
        # Log audit
        await log_audit(
            db, "auto_sync_user", "user",
            details={"user_id": user_data.get("external_id"), "provider": provider_config.provider},
            tenant_id=tenant_id
        )
        
    except Exception as e:
        cv_sync_operations_total.labels(
            operation="user_sync",
            provider="unknown",
            status="error"
        ).inc()
        print(f"Auto-sync user failed: {e}")

# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Startup
    engine = create_engine(settings.DATABASE_URL)
    Base.metadata.create_all(bind=engine)
    yield
    # Shutdown
    engine.dispose()

app = FastAPI(
    title="ZeroQue CV Connector V4.1",
    version="2.0.0",
    lifespan=lifespan
)

# Add middleware
add_api_call_meter(app)
add_idempotency_middleware(app, routes=[
    ("POST", "/cv/webhook/checkout"),
    ("POST", "/cv/entry/codes"),
])

# =============================================================================
# DEPENDENCY INJECTION
# =============================================================================

def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# =============================================================================
# HEALTH AND ROOT ENDPOINTS
# =============================================================================

@app.get("/")
def root():
    return {"service": settings.SERVICE_NAME, "version": "2.0.0"}

@app.get("/health")
def health():
    return {"status": "ok", "service": settings.SERVICE_NAME}

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    from fastapi.responses import Response
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# =============================================================================
# RAIL MANAGEMENT ENDPOINTS
# =============================================================================

@app.post("/admin/rails/cv")
async def create_cv_rail(request: ZeroqueRailRequest, db: Session = Depends(get_db)):
    """Create or update CV provider rail"""
    try:
        # Set RLS context
        set_rls_context(db, request.config.provider)  # Using provider as tenant for now
        
        # Check if rail exists
        existing = db.query(ZeroqueRail).filter(
            ZeroqueRail.tenant_id == request.config.provider,  # Simplified for demo
            ZeroqueRail.type == request.type,
            ZeroqueRail.name == request.name
        ).first()
        
        if existing:
            # Update existing
            existing.config = request.config.model_dump()
            existing.active = request.active
            existing.updated_at = datetime.now(timezone.utc)
        else:
            # Create new
            rail = ZeroqueRail(
                tenant_id=request.config.provider,  # Simplified for demo
                type=request.type,
                name=request.name,
                config=request.config.model_dump(),
                active=request.active
            )
            db.add(rail)
        
        db.commit()
        
        # Log audit
        await log_audit(
            db, "create_cv_rail", "zeroque_rail", 
            details=request.model_dump(),
            tenant_id=request.config.provider
        )
        
        return {"ok": True, "message": "CV rail created/updated successfully"}
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create CV rail: {str(e)}")

@app.get("/admin/rails/cv")
async def list_cv_rails(tenant_id: str = Query(...), db: Session = Depends(get_db)):
    """List CV provider rails for tenant"""
    try:
        set_rls_context(db, tenant_id)
        
        rails = db.query(ZeroqueRail).filter(
            ZeroqueRail.tenant_id == tenant_id,
            ZeroqueRail.type == "cv"
        ).all()
        
        return {
            "rails": [
                {
                    "id": str(rail.id),
                    "name": rail.name,
                    "config": rail.config,
                    "active": rail.active,
                    "created_at": rail.created_at.isoformat(),
                    "updated_at": rail.updated_at.isoformat() if rail.updated_at else None
                }
                for rail in rails
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list CV rails: {str(e)}")

# =============================================================================
# ENTRY CODE ENDPOINTS
# =============================================================================

@app.post("/cv/entry/codes")
async def create_entry_code(request: EntryCodeCreate, db: Session = Depends(get_db)):
    """Create entry code for CV provider"""
    try:
        set_rls_context(db, request.tenant_id)
        
        # Get provider configuration
        provider_name = request.provider or settings.DEFAULT_PROVIDER
        provider_config = await get_provider_config(db, request.tenant_id, provider_name)
        
        if not provider_config:
            # Fallback to environment config
            provider_config = ProviderConfig(
                provider=provider_name,
                api_key=settings.AIFI_API_KEY,
                base_url=settings.AIFI_BASE_URL
            )
        
        # Get provider instance
        provider = await get_provider(provider_config)
        
        # Create entry code payload
        payload = {
            "customerId": None,
            "userExternalId": request.user_id,
            "displayable": request.displayable,
            "groupSize": request.group_size,
            "body": request.extra or {}
        }
        
        # Create entry code
        result = await provider.create_entry_code(payload)
        
        # Log audit
        await log_audit(
            db, "create_entry_code", "entry_code",
            details={"user_id": request.user_id, "provider": provider_name},
            user_id=request.user_id,
            tenant_id=request.tenant_id
        )
        
        # Update metrics
        cv_provider_api_calls_total.labels(
            provider=provider_name, operation="create_entry_code", status="success"
        ).inc()
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Provider error: {str(e)}")

@app.post("/cv/entry/verify", response_model=EntryVerifyResponse)
async def verify_entry_code(request: EntryVerifyRequest, db: Session = Depends(get_db)):
    """Verify entry code for CV provider"""
    try:
        set_rls_context(db, request.tenant_id)
        
        # Get provider configuration
        provider_name = request.provider or settings.DEFAULT_PROVIDER
        provider_config = await get_provider_config(db, request.tenant_id, provider_name)
        
        if not provider_config:
            # Fallback to environment config
            provider_config = ProviderConfig(
                provider=provider_name,
                api_key=settings.AIFI_API_KEY,
                base_url=settings.AIFI_BASE_URL
            )
        
        # Get provider instance
        provider = await get_provider(provider_config)
        
        # Verify entry code
        result = await provider.verify_entry_code(
            request.verification_code,
            store_id=request.store_id,
            entry_id=request.entry_id,
            group_size=request.group_size,
            check_in_device_id=request.check_in_device_id
        )
        
        # Log audit
        await log_audit(
            db, "verify_entry_code", "entry_code",
            details={"store_id": request.store_id, "provider": provider_name},
            tenant_id=request.tenant_id
        )
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Provider error: {str(e)}")

@app.post("/cv/entry/qr")
async def generate_entry_qr_code(
    request: EntryCodeCreate,
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Generate QR code for entry code"""
    # Check permissions
    if not await check_permission(user_context, "cv.read"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        set_rls_context(db, request.tenant_id)
        
        # Get provider configuration
        provider_name = request.provider or settings.DEFAULT_PROVIDER
        provider_config = await get_provider_config(db, request.tenant_id, provider_name)
        
        if not provider_config:
            # Fallback to environment config
            provider_config = ProviderConfig(
                provider=provider_name,
                api_key=settings.AIFI_API_KEY,
                base_url=settings.AIFI_BASE_URL
            )
        
        # Get provider instance
        provider = await get_provider(provider_config)
        
        # Create entry code payload
        payload = {
            "customerId": None,
            "userExternalId": request.user_id,
            "displayable": True,
            "groupSize": request.group_size,
            "body": request.extra or {}
        }
        
        # Create entry code
        result = await provider.create_entry_code(payload)
        
        # Generate QR code
        qr_data = json.dumps({
            "entry_code": result.get("code", ""),
            "user_id": request.user_id,
            "tenant_id": request.tenant_id,
            "provider": provider_name,
            "expires_at": result.get("expires_at", "")
        })
        
        qr_image = generate_qr_code(qr_data)
        
        # Log audit
        await log_audit(
            db, "generate_entry_qr", "qr_code",
            details={"user_id": request.user_id, "provider": provider_name},
            user_id=user_context.get("user_id"),
            tenant_id=request.tenant_id
        )
        
        return {
            "qr_image": qr_image,
            "entry_code": result,
            "expires_at": result.get("expires_at")
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QR generation failed: {str(e)}")

# =============================================================================
# WEBHOOK ENDPOINTS
# =============================================================================

@app.post("/cv/webhook/entry-codes/validate", response_model=EntryWebhookDecision)
async def entry_codes_validate(
    request: Request,
    payload: dict = Body(...),
    provider_param: ProviderParam = Body(..., embed=True),
    db: Session = Depends(get_db)
):
    """Validate entry codes webhook"""
    try:
        verify_webhook_signature(request, payload)
        
        # Get provider configuration
        provider_config = await get_provider_config(db, provider_param.provider, provider_param.provider)
        
        if not provider_config:
            # Fallback to environment config
            provider_config = ProviderConfig(
                provider=provider_param.provider,
                api_key=settings.AIFI_API_KEY,
                base_url=settings.AIFI_BASE_URL
            )
        
        # Get provider instance
        provider = await get_provider(provider_config)
        
        # Adapt webhook to decision
        decision = provider.adapt_entry_webhook_to_decision(payload)
        
        # Log audit
        await log_audit(
            db, "entry_webhook_validate", "webhook",
            details={"provider": provider_param.provider},
            tenant_id=provider_param.provider
        )
        
        return decision
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Webhook processing error: {str(e)}")

@app.post("/cv/webhook/checkout", response_model=SimpleOK)
async def checkout_webhook(
    request: Request,
    payload: dict = Body(...),
    provider_param: ProviderParam = Body(..., embed=True),
    db: Session = Depends(get_db)
):
    """Process checkout webhook"""
    try:
        verify_webhook_signature(request, payload)
        
        # Get provider configuration
        provider_config = await get_provider_config(db, provider_param.provider, provider_param.provider)
        
        if not provider_config:
            # Fallback to environment config
            provider_config = ProviderConfig(
                provider=provider_param.provider,
                api_key=settings.AIFI_API_KEY,
                base_url=settings.AIFI_BASE_URL
            )
        
        # Get provider instance
        provider = await get_provider(provider_config)
        
        # Adapt checkout to order format
        mapped_order = provider.adapt_checkout_to_order(payload)
        
        # Forward to CV Gateway
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{settings.CV_GATEWAY_BASE_URL}/cv/webhook/order",
                json={**mapped_order, "provider": provider_param.provider},
                headers={"Idempotency-Key": mapped_order.get("provider_order_id", "")}
            )
        response.raise_for_status()
        
        # Log audit
        await log_audit(
            db, "checkout_webhook", "webhook",
            details={"provider": provider_param.provider, "order_id": mapped_order.get("provider_order_id")},
            tenant_id=provider_param.provider
        )
        
        return SimpleOK(ok=True)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Checkout processing error: {str(e)}")

# =============================================================================
# SYNC ENDPOINTS
# =============================================================================

@app.post("/cv/sync/batch")
async def sync_batch(
    request: SyncBatchRequest, 
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Batch sync customers, products, and inventory"""
    # Check permissions
    if not await check_permission(user_context, "cv.sync"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    try:
        set_rls_context(db, request.tenant_id)
        
        # Get provider configuration
        provider_name = request.provider or settings.DEFAULT_PROVIDER
        provider_config = await get_provider_config(db, request.tenant_id, provider_name)
        
        if not provider_config:
            # Fallback to environment config
            provider_config = ProviderConfig(
                provider=provider_name,
                api_key=settings.AIFI_API_KEY,
                base_url=settings.AIFI_BASE_URL
            )
        
        # Get provider instance
        provider = await get_provider(provider_config)
        
        results = {"customers": [], "products": [], "inventory": []}
        
        # Sync customers
        for customer in request.customers:
            try:
                result = await provider.push_customer(customer.model_dump())
                results["customers"].append(result)
            except Exception as e:
                results["customers"].append({"error": str(e)})
        
        # Sync products
        for product in request.products:
            try:
                result = await provider.push_product(product.model_dump())
                results["products"].append(result)
            except Exception as e:
                results["products"].append({"error": str(e)})
        
        # Sync inventory
        for adjustment in request.inventory:
            try:
                result = await provider.update_inventory(
                    adjustment.product_id,
                    quantity_difference=adjustment.quantity_difference,
                    quantity=adjustment.quantity
                )
                results["inventory"].append(result)
            except Exception as e:
                results["inventory"].append({"error": str(e)})
        
        # Log audit
        await log_audit(
            db, "sync_batch", "sync",
            details={"provider": provider_name, "counts": {
                "customers": len(request.customers),
                "products": len(request.products),
                "inventory": len(request.inventory)
            }},
            tenant_id=request.tenant_id
        )
        
        return results
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch sync error: {str(e)}")

# =============================================================================
# LEGACY ENDPOINTS (DEPRECATED)
# =============================================================================

@app.post("/entry/codes")
async def create_entry_code_legacy(payload: dict = Body(...)):
    """Legacy entry code creation endpoint - DEPRECATED"""
    return {
        "deprecated": True,
        "migrate_to": "/cv/entry/codes",
        "message": "This endpoint is deprecated. Please use /cv/entry/codes with proper payload structure."
    }

@app.post("/webhooks/checkout")
async def checkout_legacy(request: Request, payload: dict = Body(...)):
    """Legacy checkout webhook - DEPRECATED"""
    return {
        "deprecated": True,
        "migrate_to": "/cv/webhook/checkout",
        "message": "This endpoint is deprecated. Please use /cv/webhook/checkout with provider parameter."
    }

# =============================================================================
# EVENT HANDLERS
# =============================================================================

@app.post("/events/product-created")
async def handle_product_created(
    event_data: dict = Body(...),
    db: Session = Depends(get_db)
):
    """Handle PRODUCT_CREATED event for auto-sync"""
    await handle_product_created_event(event_data, db)
    return {"ok": True, "message": "Product auto-sync triggered"}

@app.post("/events/user-created")
async def handle_user_created(
    event_data: dict = Body(...),
    db: Session = Depends(get_db)
):
    """Handle USER_CREATED event for auto-sync"""
    await handle_user_created_event(event_data, db)
    return {"ok": True, "message": "User auto-sync triggered"}

# =============================================================================
# STALE REVIEW CLEANUP
# =============================================================================

@app.post("/admin/reviews/cleanup")
async def cleanup_stale_reviews(
    days_threshold: int = 7,
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Cleanup stale reviews and notify admins"""
    # Check permissions
    if not await check_permission(user_context, "cv.admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        # Find stale reviews
        stale_reviews = db.execute(text("""
            SELECT id, tenant_id, external_sku, name, created_at
            FROM cv_unknown_item_reviews
            WHERE status = 'pending' 
            AND created_at < NOW() - INTERVAL '%s days'
        """), {"days": days_threshold}).all()
        
        if stale_reviews:
            # Group by tenant for notifications
            tenant_reviews = {}
            for review in stale_reviews:
                tenant_id = review[1]
                if tenant_id not in tenant_reviews:
                    tenant_reviews[tenant_id] = []
                tenant_reviews[tenant_id].append({
                    "id": str(review[0]),
                    "external_sku": review[2],
                    "name": review[3],
                    "created_at": review[4].isoformat()
                })
            
            # Send notifications for each tenant
            for tenant_id, reviews in tenant_reviews.items():
                db.execute(text("""
                    INSERT INTO notifications(tenant_id, target_user_id, channel, subject, body)
                    VALUES(:tenant_id, NULL, 'admin', 'Stale CV Reviews', :body)
                """), {
                    "tenant_id": tenant_id,
                    "body": f"Found {len(reviews)} stale CV reviews requiring attention. Review IDs: {[r['id'] for r in reviews]}"
                })
            
            db.commit()
            
            # Log audit
            await log_audit(
                db, "cleanup_stale_reviews", "cleanup",
                details={"stale_count": len(stale_reviews), "days_threshold": days_threshold},
                user_id=user_context.get("user_id"),
                tenant_id=None
            )
        
        return {
            "ok": True,
            "stale_reviews_found": len(stale_reviews),
            "notifications_sent": len(tenant_reviews)
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")

# =============================================================================
# INTEGRATION ENDPOINTS
# =============================================================================

@app.post("/cv/v4/integration/catalog/product-created")
async def handle_product_created_event(
    event_data: Dict[str, Any] = Body(...)
):
    """Handle PRODUCT_CREATED event from Catalog service"""
    try:
        logger.info(f"Received PRODUCT_CREATED event: {event_data}")
        
        product_data = event_data.get("product", {})
        tenant_id = event_data.get("tenant_id")
        
        if not product_data or not tenant_id:
            raise HTTPException(status_code=400, detail="Missing product data or tenant_id")
        
        # Sync the product to CV provider
        try:
            # Get tenant's CV configuration
            cv_config = await get_cv_config(tenant_id)
            if not cv_config:
                logger.warning(f"No CV configuration found for tenant {tenant_id}")
                return {"ok": False, "error": "No CV configuration"}
            
            # Push product to CV provider
            result = await push_product_to_provider(
                tenant_id=tenant_id,
                product_data=product_data,
                provider_config=cv_config
            )
            
            logger.info(f"Successfully synced product to CV provider: {result}")
            return {"ok": True, "sync_result": result}
            
        except Exception as e:
            logger.error(f"Failed to sync product to CV provider: {str(e)}")
            return {"ok": False, "error": str(e)}
            
    except Exception as e:
        logger.error(f"Error handling PRODUCT_CREATED event: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to handle event: {str(e)}")

@app.post("/cv/v4/integration/provisioning/user-created")
async def handle_user_created_event(
    event_data: Dict[str, Any] = Body(...)
):
    """Handle USER_CREATED event from Provisioning service"""
    try:
        logger.info(f"Received USER_CREATED event: {event_data}")
        
        user_data = event_data.get("user", {})
        tenant_id = event_data.get("tenant_id")
        
        if not user_data or not tenant_id:
            raise HTTPException(status_code=400, detail="Missing user data or tenant_id")
        
        # Sync the user to CV provider
        try:
            # Get tenant's CV configuration
            cv_config = await get_cv_config(tenant_id)
            if not cv_config:
                logger.warning(f"No CV configuration found for tenant {tenant_id}")
                return {"ok": False, "error": "No CV configuration"}
            
            # Push user to CV provider
            result = await push_user_to_provider(
                tenant_id=tenant_id,
                user_data=user_data,
                provider_config=cv_config
            )
            
            logger.info(f"Successfully synced user to CV provider: {result}")
            return {"ok": True, "sync_result": result}
            
        except Exception as e:
            logger.error(f"Failed to sync user to CV provider: {str(e)}")
            return {"ok": False, "error": str(e)}
            
    except Exception as e:
        logger.error(f"Error handling USER_CREATED event: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to handle event: {str(e)}")

@app.post("/cv/v4/integration/provisioning/tenant-created")
async def handle_tenant_created_event(
    event_data: Dict[str, Any] = Body(...)
):
    """Handle TENANT_CREATED event from Provisioning service"""
    try:
        logger.info(f"Received TENANT_CREATED event: {event_data}")
        
        tenant_id = event_data.get("tenant_id")
        
        if not tenant_id:
            raise HTTPException(status_code=400, detail="Missing tenant_id")
        
        # Set up initial CV configuration for new tenant
        try:
            # Create default CV configuration
            default_config = {
                "provider": "aifi",
                "api_key": "default-api-key",
                "base_url": "https://api.aifi.io",
                "store_id": "default-store",
                "enabled": True
            }
            
            # Store CV configuration
            await set_cv_config(tenant_id, default_config)
            
            logger.info(f"Successfully set up CV configuration for new tenant: {tenant_id}")
            return {"ok": True, "config_created": True}
            
        except Exception as e:
            logger.error(f"Failed to set up CV configuration: {str(e)}")
            return {"ok": False, "error": str(e)}
            
    except Exception as e:
        logger.error(f"Error handling TENANT_CREATED event: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to handle event: {str(e)}")

@app.get("/cv/v4/integration/status")
async def get_integration_status():
    """Get status of all service integrations"""
    try:
        integration_status = {
            "catalog_service": {"status": "unknown", "url": "http://localhost:8080"},
            "provisioning_service": {"status": "unknown", "url": "http://localhost:8082"},
            "cv_gateway_service": {"status": "unknown", "url": "http://localhost:8101"}
        }
        
        # Test each service connectivity
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            for service_name, config in integration_status.items():
                try:
                    response = await client.get(f"{config['url']}/health")
                    if response.status_code == 200:
                        config["status"] = "healthy"
                        config["response_time_ms"] = response.elapsed.total_seconds() * 1000
                    else:
                        config["status"] = "unhealthy"
                except Exception as e:
                    config["status"] = "unreachable"
                    config["error"] = str(e)
        
        return {
            "integration_status": integration_status,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting integration status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get integration status: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8100)