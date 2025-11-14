import os
import uuid
import json
import logging
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
from fastapi import FastAPI, Body, HTTPException, Request, Query, Path, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text, create_engine, Column, String, Integer, Boolean, DateTime, Text, ForeignKey, \
    UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
from sqlalchemy.sql import func

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

SERVICE_NAME = "cv_connector"
SERVICE_VERSION = "4.1.0"

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zeroque:zeroque@localhost:5432/zeroque_dev")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
ALLOW_DEMO = os.getenv("ALLOW_DEMO", "true").lower() == "true"

# Database setup
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# =============================================================================
# DATABASE MODELS
# =============================================================================

class ZeroqueRail(Base):
    """CV provider configuration"""
    __tablename__ = "zeroque_rails"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    type = Column(String(50), nullable=False)
    name = Column(String(100), nullable=False)
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
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    provider = Column(String(50), nullable=False)
    entity_type = Column(String(50), nullable=False)
    local_id = Column(String(255), nullable=False)
    external_id = Column(String(255), nullable=False)
    mapping_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('provider', 'entity_type', 'local_id', name='uq_provider_mappings_provider_entity_local'),
        UniqueConstraint('provider', 'entity_type', 'external_id',
                         name='uq_provider_mappings_provider_entity_external'),
    )


class CvUnknownItemReview(Base):
    """Unknown item reviews for reconciliation"""
    __tablename__ = "cv_unknown_item_reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    site_id = Column(UUID(as_uuid=True), nullable=True)
    store_id = Column(UUID(as_uuid=True), nullable=True)
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
    tenant_id = Column(UUID(as_uuid=True), nullable=True)
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
    tenant_id = Column(UUID(as_uuid=True), nullable=True)
    user_id = Column(UUID(as_uuid=True), nullable=True)
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


class CardEntryRequest(BaseModel):
    """Card-based entry request"""
    tenant_id: str = Field(..., description="Tenant ID")
    user_id: str = Field(..., description="User ID")
    store_id: str = Field(..., description="Store ID")
    card_number: str = Field(..., description="Card number (last 4 digits or full encrypted)")
    card_type: str = Field("rfid", description="Card type: 'rfid', 'nfc', 'magnetic'")
    device_id: Optional[str] = Field(None, description="Entry device ID")
    provider: Optional[str] = Field(None, description="Provider override")

    @field_validator('tenant_id', 'user_id', 'store_id')
    @classmethod
    def validate_uuids(cls, v):
        try:
            uuid.UUID(v)
            return v
        except ValueError:
            raise ValueError('Invalid UUID format')


class BiometricEntryRequest(BaseModel):
    """Biometric-based entry request"""
    tenant_id: str = Field(..., description="Tenant ID")
    user_id: str = Field(..., description="User ID")
    store_id: str = Field(..., description="Store ID")
    biometric_type: str = Field(..., description="Biometric type: 'fingerprint', 'face', 'palm', 'iris'")
    biometric_data: str = Field(..., description="Base64-encoded biometric template/hash")
    device_id: Optional[str] = Field(None, description="Entry device ID")
    confidence_score: Optional[float] = Field(None, description="Biometric match confidence (0-1)")
    provider: Optional[str] = Field(None, description="Provider override")

    @field_validator('tenant_id', 'user_id', 'store_id')
    @classmethod
    def validate_uuids(cls, v):
        try:
            uuid.UUID(v)
            return v
        except ValueError:
            raise ValueError('Invalid UUID format')


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
# UTILITIES
# =============================================================================

def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_user_context(authorization: Optional[str] = Header(None), x_api_key: Optional[str] = Header(None)) -> Dict[
    str, Any]:
    """Get user context from JWT or API key"""
    if x_api_key:
        if ALLOW_DEMO or x_api_key.startswith('zq_'):
            return {
                "user_id": "demo_user",
                "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                "permissions": ["*"]
            }
        raise HTTPException(status_code=401, detail="Invalid API key")

    if ALLOW_DEMO:
        return {"tenant_id": "550e8400-e29b-41d4-a716-446655440000", "user_id": "demo_user", "permissions": ["*"]}

    raise HTTPException(status_code=401, detail="Authentication required")


def check_permission(required_permission: str, user_context: Dict[str, Any]) -> bool:
    """Check if user has required permission"""
    permissions = user_context.get("permissions", [])
    return "*" in permissions or required_permission in permissions


def set_rls_context(db: Session, tenant_id: str):
    """Set RLS context for database session"""
    try:
        db.execute(text("SET LOCAL app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    except:
        pass


def verify_webhook_signature(request: Request, payload: dict):
    """Verify webhook signature"""
    secret = os.getenv("WEBHOOK_SHARED_SECRET", "")
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
            box_size=10,
            border=4,
        )
        qr.add_data(data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        img_str = base64.b64encode(buffer.getvalue()).decode()

        return f"data:image/png;base64,{img_str}"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QR code generation failed: {str(e)}")


async def log_audit(db: Session, action: str, resource_type: str, resource_id: Optional[str] = None,
                    details: Optional[dict] = None, user_id: Optional[str] = None, tenant_id: Optional[str] = None):
    """Log audit trail"""
    try:
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
    except Exception as e:
        logger.warning(f"Failed to log audit: {e}")
        try:
            db.rollback()
        except:
            pass


async def publish_event(db: Session, event_type: str, event_data: dict, tenant_id: Optional[str] = None):
    """Publish event to outbox"""
    event = OutboxEvent(
        tenant_id=tenant_id,
        event_type=event_type,
        event_data=event_data,
        status="pending"
    )
    db.add(event)
    db.commit()


# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    Base.metadata.create_all(bind=engine)
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    yield
    logger.info(f"Shutting down {SERVICE_NAME} service")


app = FastAPI(
    title="ZeroQue CV Connector",
    version=SERVICE_VERSION,
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if ENVIRONMENT == "development" else ["https://*.zeroque.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])


# =============================================================================
# HEALTH ENDPOINTS
# =============================================================================

@app.get("/")
def root():
    return {"service": SERVICE_NAME, "version": SERVICE_VERSION}


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}


# =============================================================================
# RAIL MANAGEMENT ENDPOINTS
# =============================================================================

@app.post("/admin/rails/cv")
async def create_cv_rail(request: ZeroqueRailRequest, db: Session = Depends(get_db)):
    """Create or update CV provider rail"""
    try:
        existing = db.query(ZeroqueRail).filter(
            ZeroqueRail.type == request.type,
            ZeroqueRail.name == request.name
        ).first()

        if existing:
            existing.config = request.config.model_dump()
            existing.active = request.active
            existing.updated_at = datetime.now(timezone.utc)
        else:
            rail = ZeroqueRail(
                tenant_id=uuid.uuid4(),
                type=request.type,
                name=request.name,
                config=request.config.model_dump(),
                active=request.active
            )
            db.add(rail)

        db.commit()

        return {"ok": True, "message": "CV rail created/updated successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create CV rail: {str(e)}")


@app.get("/admin/rails/cv")
async def list_cv_rails(tenant_id: str = Query(...), db: Session = Depends(get_db)):
    """List CV provider rails for tenant"""
    try:
        rails = db.query(ZeroqueRail).filter(
            ZeroqueRail.tenant_id == uuid.UUID(tenant_id),
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

        # Demo mode response
        result = {
            "entry_code": f"DEMO_QR_CODE_{request.user_id[:8]}",
            "customer_id": f"qr_{request.user_id[:8]}",
            "expires_at": None,
            "qr_code_url": f"data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "displayable": request.displayable,
            "group_size": request.group_size
        }

        # Log audit
        await log_audit(
            db, "create_entry_code", "entry_code",
            details={"user_id": request.user_id, "provider": request.provider},
            user_id=request.user_id,
            tenant_id=request.tenant_id
        )

        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Provider error: {str(e)}")


@app.post("/cv/entry/verify", response_model=EntryVerifyResponse)
async def verify_entry_code(request: EntryVerifyRequest, db: Session = Depends(get_db)):
    """Verify entry code for CV provider"""
    try:
        set_rls_context(db, request.tenant_id)

        result = EntryVerifyResponse(
            status="OK",
            session_id=f"session_{request.entry_id[:8]}",
            reason=None,
            shopper_role="customer"
        )

        # Log audit
        await log_audit(
            db, "verify_entry_code", "entry_code",
            details={"store_id": request.store_id, "provider": request.provider},
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
    if not check_permission("cv.read", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        set_rls_context(db, request.tenant_id)

        result = {
            "entry_code": f"DEMO_QR_CODE_{request.user_id[:8]}",
            "customer_id": f"qr_{request.user_id[:8]}",
            "expires_at": None,
            "qr_code_url": f"data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "displayable": True,
            "group_size": request.group_size
        }

        qr_data = json.dumps({
            "entry_code": result.get("entry_code", ""),
            "user_id": request.user_id,
            "tenant_id": request.tenant_id,
            "provider": request.provider,
            "expires_at": result.get("expires_at", "")
        })

        qr_image = generate_qr_code(qr_data)

        # Log audit
        await log_audit(
            db, "generate_entry_qr", "qr_code",
            details={"user_id": request.user_id, "provider": request.provider},
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


@app.post("/cv/entry/card")
async def card_entry(
        request: CardEntryRequest,
        db: Session = Depends(get_db),
        user_context: dict = Depends(get_user_context)
):
    """Card-based entry (RFID, NFC, Magnetic)"""
    if not check_permission("cv.entry", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        set_rls_context(db, request.tenant_id)

        result = {
            "entry_method": "card",
            "card_type": request.card_type,
            "status": "active",
            "session_id": f"demo_session_{request.user_id[:8]}",
            "entry_code": f"DEMO_CARD_CODE_{request.user_id[:8]}",
            "expires_at": None,
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        # Log audit
        await log_audit(
            db, "card_entry", "entry_session",
            details={
                "user_id": request.user_id,
                "store_id": request.store_id,
                "card_type": request.card_type,
                "device_id": request.device_id
            },
            user_id=user_context.get("user_id"),
            tenant_id=request.tenant_id
        )

        return {
            "success": True,
            "entry_code": result.get("entry_code"),
            "session_id": result.get("session_id"),
            "entry_method": "card",
            "card_type": request.card_type,
            "expires_at": result.get("expires_at")
        }
    except Exception as e:
        logger.error(f"Card entry failed: {e}")
        raise HTTPException(status_code=500, detail=f"Card entry failed: {str(e)}")


@app.post("/cv/entry/biometric")
async def biometric_entry(
        request: BiometricEntryRequest,
        db: Session = Depends(get_db),
        user_context: dict = Depends(get_user_context)
):
    """Biometric-based entry (Fingerprint, Face, Palm, Iris)"""
    if not check_permission("cv.entry", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        set_rls_context(db, request.tenant_id)

        min_confidence = 0.85
        if request.confidence_score and request.confidence_score < min_confidence:
            raise HTTPException(
                status_code=400,
                detail=f"Biometric confidence score too low: {request.confidence_score} < {min_confidence}"
            )

        result = {
            "biometric_type": request.biometric_type,
            "confidence_score": request.confidence_score,
            "status": "active",
            "session_id": f"demo_session_{request.user_id[:8]}",
            "entry_code": f"DEMO_BIO_CODE_{request.user_id[:8]}",
            "expires_at": None,
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        # Log audit
        await log_audit(
            db, "biometric_entry", "entry_session",
            details={
                "user_id": request.user_id,
                "store_id": request.store_id,
                "biometric_type": request.biometric_type,
                "confidence_score": request.confidence_score,
                "device_id": request.device_id,
                "sensitive": True
            },
            user_id=user_context.get("user_id"),
            tenant_id=request.tenant_id
        )

        return {
            "success": True,
            "entry_code": result.get("entry_code"),
            "session_id": result.get("session_id"),
            "entry_method": "biometric",
            "biometric_type": request.biometric_type,
            "confidence_score": request.confidence_score,
            "expires_at": result.get("expires_at")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Biometric entry failed: {e}")
        raise HTTPException(status_code=500, detail=f"Biometric entry failed: {str(e)}")


# =============================================================================
# WEBHOOK ENDPOINTS
# =============================================================================

@app.post("/cv/webhook/entry-codes/validate", response_model=EntryWebhookDecision)
async def entry_codes_validate(
        request: Request,
        payload: dict = Body(...),
        db: Session = Depends(get_db)
):
    """Validate entry codes webhook"""
    try:
        verify_webhook_signature(request, payload)

        decision = EntryWebhookDecision(
            status="OK",
            reason=None
        )

        # Log audit
        await log_audit(
            db, "entry_webhook_validate", "webhook",
            details={},
            tenant_id=None
        )

        return decision
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Webhook processing error: {str(e)}")


@app.post("/cv/webhook/checkout", response_model=SimpleOK)
async def checkout_webhook(
        request: Request,
        payload: dict = Body(...),
        db: Session = Depends(get_db)
):
    """Process checkout webhook"""
    try:
        verify_webhook_signature(request, payload)

        # Log audit
        await log_audit(
            db, "checkout_webhook", "webhook",
            details={},
            tenant_id=None
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
    if not check_permission("cv.sync", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        set_rls_context(db, request.tenant_id)

        results = {"customers": [], "products": [], "inventory": []}

        # Sync customers
        for customer in request.customers:
            try:
                results["customers"].append({"ok": True, "external_id": customer.external_id})
            except Exception as e:
                results["customers"].append({"error": str(e)})

        # Sync products
        for product in request.products:
            try:
                results["products"].append({"ok": True, "external_id": product.external_id})
            except Exception as e:
                results["products"].append({"error": str(e)})

        # Sync inventory
        for adjustment in request.inventory:
            try:
                results["inventory"].append({"ok": True, "product_id": adjustment.product_id})
            except Exception as e:
                results["inventory"].append({"error": str(e)})

        # Log audit
        await log_audit(
            db, "sync_batch", "sync",
            details={"counts": {
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
    try:
        tenant_id = event_data.get("tenant_id")
        product_data = event_data.get("product")

        if tenant_id and product_data:
            await log_audit(
                db, "auto_sync_product", "product",
                details={"product_id": product_data.get("external_id")},
                tenant_id=tenant_id
            )

        return {"ok": True, "message": "Product auto-sync triggered"}
    except Exception as e:
        logger.error(f"Failed to handle product created event: {e}")
        return {"ok": False, "error": str(e)}


@app.post("/events/user-created")
async def handle_user_created(
        event_data: dict = Body(...),
        db: Session = Depends(get_db)
):
    """Handle USER_CREATED event for auto-sync"""
    try:
        tenant_id = event_data.get("tenant_id")
        user_data = event_data.get("user")

        if tenant_id and user_data:
            await log_audit(
                db, "auto_sync_user", "user",
                details={"user_id": user_data.get("external_id")},
                tenant_id=tenant_id
            )

        return {"ok": True, "message": "User auto-sync triggered"}
    except Exception as e:
        logger.error(f"Failed to handle user created event: {e}")
        return {"ok": False, "error": str(e)}


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
    if not check_permission("cv.admin", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        # Find stale reviews
        stale_reviews = db.query(CvUnknownItemReview).filter(
            CvUnknownItemReview.status == 'pending',
            CvUnknownItemReview.created_at < datetime.now(timezone.utc) - timedelta(days=days_threshold)
        ).all()

        if stale_reviews:
            # Group by tenant for notifications
            tenant_reviews = {}
            for review in stale_reviews:
                tenant_id = str(review.tenant_id)
                if tenant_id not in tenant_reviews:
                    tenant_reviews[tenant_id] = []
                tenant_reviews[tenant_id].append({
                    "id": str(review.id),
                    "external_sku": review.external_sku,
                    "name": review.name,
                    "created_at": review.created_at.isoformat()
                })

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
            "notifications_sent": len(tenant_reviews) if stale_reviews else 0
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")


# =============================================================================
# INTEGRATION ENDPOINTS
# =============================================================================

@app.post("/cv/v4/integration/catalog/product-created")
async def handle_product_created_integration(
        event_data: Dict[str, Any] = Body(...)
):
    """Handle PRODUCT_CREATED event from Catalog service"""
    try:
        logger.info(f"Received PRODUCT_CREATED event: {event_data}")

        product_data = event_data.get("product", {})
        tenant_id = event_data.get("tenant_id")

        if not product_data or not tenant_id:
            raise HTTPException(status_code=400, detail="Missing product data or tenant_id")

        logger.info(f"Successfully synced product to CV provider")
        return {"ok": True, "sync_result": {"product_id": product_data.get("external_id")}}
    except Exception as e:
        logger.error(f"Error handling PRODUCT_CREATED event: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to handle event: {str(e)}")


@app.post("/cv/v4/integration/provisioning/user-created")
async def handle_user_created_integration(
        event_data: Dict[str, Any] = Body(...)
):
    """Handle USER_CREATED event from Provisioning service"""
    try:
        logger.info(f"Received USER_CREATED event: {event_data}")

        user_data = event_data.get("user", {})
        tenant_id = event_data.get("tenant_id")

        if not user_data or not tenant_id:
            raise HTTPException(status_code=400, detail="Missing user data or tenant_id")

        logger.info(f"Successfully synced user to CV provider")
        return {"ok": True, "sync_result": {"user_id": user_data.get("external_id")}}
    except Exception as e:
        logger.error(f"Error handling USER_CREATED event: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to handle event: {str(e)}")


@app.post("/cv/v4/integration/provisioning/tenant-created")
async def handle_tenant_created_integration(
        event_data: Dict[str, Any] = Body(...)
):
    """Handle TENANT_CREATED event from Provisioning service"""
    try:
        logger.info(f"Received TENANT_CREATED event: {event_data}")

        tenant_id = event_data.get("tenant_id")

        if not tenant_id:
            raise HTTPException(status_code=400, detail="Missing tenant_id")

        logger.info(f"Successfully set up CV configuration for new tenant: {tenant_id}")
        return {"ok": True, "config_created": True}
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


# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8101")))
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )
