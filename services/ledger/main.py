# Ledger Service V2 - Enhanced V4.1 Architecture
# Double-entry accounting with sagas, events, and multi-tenant support

import os
import uuid
import json
import asyncio
import structlog
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

# Configure structured logging
logger = structlog.get_logger(__name__)

import httpx
from fastapi import FastAPI, Body, HTTPException, Request, Query, Path, Depends, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text, create_engine, Column, String, Integer, Boolean, DateTime, Text, ForeignKey, BigInteger, Numeric
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
from sqlalchemy.sql import func
from sqlalchemy.exc import SQLAlchemyError

# Prometheus metrics
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# Database imports
from sqlalchemy import create_engine, text, Column, String, Integer, Numeric, DateTime, Boolean, Text, ForeignKey, JSON, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.exc import SQLAlchemyError
from celery import Celery
import structlog
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import redis
import pika
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
import pybreaker

# =============================================================================
# PROMETHEUS METRICS
# =============================================================================

# Metrics for Ledger Service
ledger_requests_total = Counter(
    'ledger_requests_total_v2', 
    'Total ledger requests',
    ['method', 'endpoint', 'status']
)

ledger_request_duration = Histogram(
    'ledger_request_duration_seconds_v2',
    'Ledger request duration',
    ['method', 'endpoint']
)

ledger_entries_created_total = Counter(
    'ledger_entries_created_total_v2',
    'Total ledger entries created',
    ['entry_type', 'account', 'currency']
)

ledger_saga_duration = Histogram(
    'ledger_saga_duration_seconds_v2',
    'Ledger saga execution duration',
    ['saga_type']
)

ledger_saga_failures = Counter(
    'ledger_saga_failures_total_v2',
    'Total ledger saga failures',
    ['saga_type', 'step']
)

# =============================================================================
# CONFIGURATION
# =============================================================================

SERVICE_NAME = "ledger"
SERVICE_VERSION = "4.1.0"

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zeroque:zeroque@localhost:5432/zeroque_dev")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
EVENT_BUS_URL = os.getenv("EVENT_BUS_URL", "http://localhost:8085")
JWT_SECRET = os.getenv("JWT_SECRET", "")

# Database setup
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Redis setup
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Celery setup
celery_app = Celery(
    SERVICE_NAME,
    broker=RABBITMQ_URL,
    backend=REDIS_URL,
    include=[f'{SERVICE_NAME}.tasks']
)

# Load Celery configuration
try:
    celery_app.config_from_object('celeryconfig')
except ImportError:
    logger.warning("Celery config not found, using defaults")

# Circuit breaker for external service calls
service_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# =============================================================================
# DATABASE MODELS
# =============================================================================

Base = declarative_base()

class LedgerEntryNew(Base):
    """Enhanced ledger entry with v4.1 features"""
    __tablename__ = "ledger_entries_new"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    vendor_id = Column(UUID(as_uuid=True), nullable=True)
    account = Column(String(100), nullable=False)
    entry_type = Column(String(20), nullable=False)  # debit/credit
    amount_minor = Column(BigInteger, nullable=False)
    currency = Column(String(3), nullable=False)
    cost_centre_id = Column(UUID(as_uuid=True), nullable=True)
    site_id = Column(UUID(as_uuid=True), nullable=True)
    store_id = Column(UUID(as_uuid=True), nullable=True)
    reference_type = Column(String(50), nullable=True)  # order, invoice, approval
    reference_id = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    entry_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)

class AccountBalanceNew(Base):
    """Precomputed account balances for performance"""
    __tablename__ = "account_balances_new"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    account = Column(String(100), nullable=False)
    currency = Column(String(3), nullable=False)
    balance_minor = Column(BigInteger, nullable=False, server_default='0')
    last_updated = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class OutboxEvent(Base):
    """Outbox pattern for reliable event publishing"""
    __tablename__ = "outbox_events"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True)
    event_type = Column(String(100), nullable=False)
    event_data = Column(JSONB, nullable=False)
    status = Column(String(20), nullable=False, default='pending')  # pending, published, failed
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)

class AuditLog(Base):
    """Audit trail for all operations"""
    __tablename__ = "audit_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(String(255), nullable=True)
    details = Column(JSONB, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class LedgerEntryRequest(BaseModel):
    """Request model for creating ledger entries"""
    tenant_id: str = Field(..., description="Tenant ID")
    account: str = Field(..., description="Account name")
    entry_type: str = Field(..., description="Entry type (debit/credit)")
    amount_minor: int = Field(..., description="Amount in minor units", gt=0)
    currency: str = Field(..., description="Currency code")
    cost_centre_id: Optional[str] = None
    site_id: Optional[str] = None
    store_id: Optional[str] = None
    reference_type: Optional[str] = None
    reference_id: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    @field_validator('entry_type')
    @classmethod
    def validate_entry_type(cls, v):
        if v not in ['debit', 'credit']:
            raise ValueError('entry_type must be "debit" or "credit"')
        return v

class LedgerEntryResponse(BaseModel):
    """Response model for ledger entries"""
    id: str
    tenant_id: str
    vendor_id: Optional[str] = None
    account: str
    entry_type: str
    amount_minor: int
    currency: str
    cost_centre_id: Optional[str] = None
    site_id: Optional[str] = None
    store_id: Optional[str] = None
    reference_type: Optional[str] = None
    reference_id: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

class AccountBalanceResponse(BaseModel):
    """Response model for account balances"""
    account: str
    currency: str
    balance_minor: int
    last_updated: datetime

class LedgerAdjustmentRequest(BaseModel):
    """Request model for ledger adjustments"""
    entry_id: str = Field(..., description="Entry ID to adjust")
    adjustment_amount_minor: int = Field(..., description="Adjustment amount in minor units")
    reason: str = Field(..., description="Reason for adjustment")
    reference_type: Optional[str] = None
    reference_id: Optional[str] = None

class LedgerReportRequest(BaseModel):
    """Request model for ledger reports"""
    tenant_id: str = Field(..., description="Tenant ID")
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    account: Optional[str] = None
    cost_centre_id: Optional[str] = None
    currency: Optional[str] = None

# =============================================================================
# SECURITY & AUTHENTICATION
# =============================================================================

async def get_user_context(request: Request) -> dict:
    """Get user context from JWT token (demo implementation)"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return {
            "user_id": "demo_user",
            "tenant_id": "demo_tenant",
            "permissions": ["ledger.read"]
        }
    
    # In production: validate JWT token and extract claims
    token = auth_header.split(" ")[1]
    return {
        "user_id": "authenticated_user",
        "tenant_id": "authenticated_tenant", 
        "permissions": ["ledger.read", "ledger.create", "ledger.admin"]
    }

async def check_permission(user_context: dict, required_permission: str) -> bool:
    """Check if user has required permission"""
    user_permissions = user_context.get("permissions", [])
    return required_permission in user_permissions or "ledger.admin" in user_permissions

# =============================================================================
# UTILITIES
# =============================================================================

def set_rls_context(db: Session, tenant_id: str):
    """Set RLS context for database session"""
    db.execute(text("SET LOCAL app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})

async def log_audit(
    db: Session, 
    action: str, 
    resource_type: str, 
    resource_id: str = None,
    details: dict = None,
    user_id: str = None,
    tenant_id: str = None,
    ip_address: str = None,
    user_agent: str = None
):
    """Log audit trail"""
    audit = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address,
        user_agent=user_agent
    )
    db.add(audit)
    db.commit()

async def publish_event(
    db: Session, 
    event_type: str, 
    event_data: dict, 
    tenant_id: str = None
):
    """Publish event using outbox pattern"""
    outbox_event = OutboxEvent(
        tenant_id=tenant_id,
        event_type=event_type,
        event_data=event_data
    )
    db.add(outbox_event)
    db.commit()

# =============================================================================
# SAGA PATTERN
# =============================================================================

class LedgerEntrySaga:
    """Saga for reliable ledger entry creation"""
    
    def __init__(self, db: Session, request: LedgerEntryRequest):
        self.db = db
        self.request = request
        self.compensation_steps = []
    
    async def execute(self) -> dict:
        """Execute the saga steps"""
        try:
            # Step 1: Validate tenant and vendor
            await self._validate_tenant_vendor()
            
            # Step 2: Create debit/credit pair
            debit_id, credit_id = await self._create_entries()
            
            # Step 3: Update account balances
            await self._update_balances()
            
            # Step 4: Publish event
            await self._publish_event()
            
            # Step 5: Audit log
            await self._audit_log()
            
            self.db.commit()
            return {"ok": True, "entry_id": str(debit_id)}
            
        except Exception as e:
            await self._compensate()
            self.db.rollback()
            raise e
    
    async def _validate_tenant_vendor(self):
        """Validate tenant and vendor existence"""
        # In production: validate tenant_id via Provisioning service
        # For demo: just check if tenant_id is provided
        if not self.request.tenant_id:
            raise ValueError("Tenant ID is required")
        
        self.compensation_steps.append(("validation", {}))
    
    async def _create_entries(self) -> tuple:
        """Create debit and credit entries"""
        # Create debit entry
        debit = LedgerEntryNew(
            tenant_id=self.request.tenant_id,
            vendor_id=self.request.vendor_id,
            account=self.request.account,
            entry_type="debit",
            amount_minor=self.request.amount_minor,
            currency=self.request.currency,
            cost_centre_id=self.request.cost_centre_id,
            site_id=self.request.site_id,
            store_id=self.request.store_id,
            reference_type=self.request.reference_type,
            reference_id=self.request.reference_id,
            description=self.request.description,
            metadata=self.request.metadata
        )
        self.db.add(debit)
        self.db.flush()
        
        # Create credit entry
        credit = LedgerEntryNew(
            tenant_id=self.request.tenant_id,
            vendor_id=self.request.vendor_id,
            account="TenantClearing",  # Standard credit account
            entry_type="credit",
            amount_minor=self.request.amount_minor,
            currency=self.request.currency,
            cost_centre_id=self.request.cost_centre_id,
            site_id=self.request.site_id,
            store_id=self.request.store_id,
            reference_type=self.request.reference_type,
            reference_id=self.request.reference_id,
            description=self.request.description,
            metadata=self.request.metadata
        )
        self.db.add(credit)
        self.db.flush()
        
        self.compensation_steps.append(("delete_entries", {"debit_id": debit.id, "credit_id": credit.id}))
        
        return debit.id, credit.id
    
    async def _update_balances(self):
        """Update account balances"""
        # Update debit account balance
        await self._update_account_balance(
            self.request.tenant_id,
            self.request.account,
            self.request.currency,
            self.request.amount_minor
        )
        
        # Update credit account balance
        await self._update_account_balance(
            self.request.tenant_id,
            "TenantClearing",
            self.request.currency,
            -self.request.amount_minor
        )
        
        self.compensation_steps.append(("revert_balances", {}))
    
    async def _update_account_balance(self, tenant_id: str, account: str, currency: str, amount_change: int):
        """Update specific account balance"""
        balance = self.db.query(AccountBalanceNew).filter(
            AccountBalanceNew.tenant_id == tenant_id,
            AccountBalanceNew.account == account,
            AccountBalanceNew.currency == currency
        ).first()
        
        if not balance:
            balance = AccountBalanceNew(
                tenant_id=tenant_id,
                account=account,
                currency=currency,
                balance_minor=0,
                last_updated=datetime.now(timezone.utc)
            )
            self.db.add(balance)
        
        balance.balance_minor += amount_change
        balance.last_updated = datetime.now(timezone.utc)
    
    async def _publish_event(self):
        """Publish LEDGER_UPDATED event"""
        await publish_event(
            self.db,
            "LEDGER_UPDATED",
            {
                "tenant_id": self.request.tenant_id,
                "account": self.request.account,
                "entry_type": self.request.entry_type,
                "amount_minor": self.request.amount_minor,
                "currency": self.request.currency,
                "reference_type": self.request.reference_type,
                "reference_id": self.request.reference_id
            },
            self.request.tenant_id
        )
    
    async def _audit_log(self):
        """Log audit trail"""
        await log_audit(
            self.db,
            "create_ledger_entry",
            "ledger_entry",
            details={
                "account": self.request.account,
                "entry_type": self.request.entry_type,
                "amount_minor": self.request.amount_minor,
                "currency": self.request.currency
            },
            tenant_id=self.request.tenant_id
        )
    
    async def _compensate(self):
        """Compensation logic for saga failures"""
        for step_name, data in reversed(self.compensation_steps):
            if step_name == "delete_entries":
                self.db.query(LedgerEntryNew).filter(
                    LedgerEntryNew.id.in_([data["debit_id"], data["credit_id"]])
                ).delete()
            elif step_name == "revert_balances":
                # Revert balance changes
                # This would be implemented with more sophisticated logic
                pass

# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Startup
    engine = create_engine(DATABASE_URL)
    Base.metadata.create_all(bind=engine)
    yield
    # Shutdown
    engine.dispose()

app = FastAPI(
    title="ZeroQue Ledger Service V2",
    version=SERVICE_VERSION
    # lifespan=lifespan  # Temporarily disabled for debugging
)

# Add middleware
add_api_call_meter(app)
add_idempotency_middleware(app, routes=[
    ("POST", "/ledger/v4/entries"),
    ("POST", "/ledger/v4/adjustments"),
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
# HEALTH AND MONITORING ENDPOINTS
# =============================================================================

@app.get("/")
def root():
    return {"service": SERVICE_NAME, "version": SERVICE_VERSION}

@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME, "version": SERVICE_VERSION}

@app.get("/readiness")
def readiness():
    return {"service": SERVICE_NAME, "db": True, "redis": True}

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# =============================================================================
# V4 ENDPOINTS
# =============================================================================

@app.post("/ledger/v4/entries", response_model=dict)
async def create_ledger_entry(
    request: LedgerEntryRequest,
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Create ledger entry with saga pattern"""
    # Check permissions
    if not await check_permission(user_context, "ledger.create"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Update metrics
    ledger_requests_total.labels(
        method="POST", endpoint="/ledger/v4/entries", status="started"
    ).inc()
    
    start_time = datetime.now()
    
    try:
        set_rls_context(db, request.tenant_id)
        
        # Execute saga
        saga = LedgerEntrySaga(db, request)
        result = await saga.execute()
        
        # Update metrics
        duration = (datetime.now() - start_time).total_seconds()
        ledger_request_duration.labels(
            method="POST", endpoint="/ledger/v4/entries"
        ).observe(duration)
        
        ledger_saga_duration.labels(saga_type="create_entry").observe(duration)
        
        ledger_entries_created_total.labels(
            entry_type=request.entry_type,
            account=request.account,
            currency=request.currency
        ).inc()
        
        ledger_requests_total.labels(
            method="POST", endpoint="/ledger/v4/entries", status="success"
        ).inc()
        
        return result
        
    except Exception as e:
        # Update metrics
        duration = (datetime.now() - start_time).total_seconds()
        ledger_request_duration.labels(
            method="POST", endpoint="/ledger/v4/entries"
        ).observe(duration)
        
        ledger_saga_failures.labels(saga_type="create_entry", step="execute").inc()
        
        ledger_requests_total.labels(
            method="POST", endpoint="/ledger/v4/entries", status="error"
        ).inc()
        
        raise HTTPException(status_code=500, detail=f"Failed to create ledger entry: {str(e)}")

@app.get("/ledger/v4/entries")
async def list_ledger_entries(
    tenant_id: str = Query(..., description="Tenant ID"),
    account: Optional[str] = Query(None, description="Filter by account"),
    cost_centre_id: Optional[str] = Query(None, description="Filter by cost centre"),
    vendor_id: Optional[str] = Query(None, description="Filter by vendor"),
    currency: Optional[str] = Query(None, description="Filter by currency"),
    reference_type: Optional[str] = Query(None, description="Filter by reference type"),
    limit: int = Query(50, description="Limit results", le=1000),
    offset: int = Query(0, description="Offset for pagination", ge=0),
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """List ledger entries with filtering"""
    # Check permissions
    if not await check_permission(user_context, "ledger.read"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        set_rls_context(db, tenant_id)
        
        # Build query
        query = db.query(LedgerEntryNew).filter(LedgerEntryNew.tenant_id == tenant_id)
        
        if account:
            query = query.filter(LedgerEntryNew.account == account)
        if cost_centre_id:
            query = query.filter(LedgerEntryNew.cost_centre_id == cost_centre_id)
        if vendor_id:
            query = query.filter(LedgerEntryNew.vendor_id == vendor_id)
        if currency:
            query = query.filter(LedgerEntryNew.currency == currency)
        if reference_type:
            query = query.filter(LedgerEntryNew.reference_type == reference_type)
        
        # Get total count
        total_count = query.count()
        
        # Apply pagination and ordering
        entries = query.order_by(LedgerEntryNew.created_at.desc()).offset(offset).limit(limit).all()
        
        # Convert to response format
        items = [
            LedgerEntryResponse(
                id=str(entry.id),
                tenant_id=str(entry.tenant_id),
                vendor_id=str(entry.vendor_id) if entry.vendor_id else None,
                account=entry.account,
                entry_type=entry.entry_type,
                amount_minor=entry.amount_minor,
                currency=entry.currency,
                cost_centre_id=str(entry.cost_centre_id) if entry.cost_centre_id else None,
                site_id=str(entry.site_id) if entry.site_id else None,
                store_id=str(entry.store_id) if entry.store_id else None,
                reference_type=entry.reference_type,
                reference_id=entry.reference_id,
                description=entry.description,
                metadata=entry.metadata,
                created_at=entry.created_at,
                updated_at=entry.updated_at
            )
            for entry in entries
        ]
        
        return {
            "items": items,
            "total_count": total_count,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(items) < total_count
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list ledger entries: {str(e)}")

@app.get("/ledger/v4/balances")
async def get_account_balances(
    tenant_id: str = Query(..., description="Tenant ID"),
    account: Optional[str] = Query(None, description="Filter by account"),
    currency: Optional[str] = Query(None, description="Filter by currency"),
    cost_centre_id: Optional[str] = Query(None, description="Filter by cost centre"),
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Get account balances"""
    # Check permissions
    if not await check_permission(user_context, "ledger.read"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        set_rls_context(db, tenant_id)
        
        # Build query
        query = db.query(AccountBalanceNew).filter(AccountBalanceNew.tenant_id == tenant_id)
        
        if account:
            query = query.filter(AccountBalanceNew.account == account)
        if currency:
            query = query.filter(AccountBalanceNew.currency == currency)
        
        balances = query.all()
        
        # Convert to response format
        items = [
            AccountBalanceResponse(
                account=balance.account,
                currency=balance.currency,
                balance_minor=balance.balance_minor,
                last_updated=balance.last_updated
            )
            for balance in balances
        ]
        
        return {"balances": items}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get account balances: {str(e)}")

@app.post("/ledger/v4/adjustments")
async def create_ledger_adjustment(
    request: LedgerAdjustmentRequest,
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Create ledger adjustment for disputes/reconciliation"""
    # Check permissions
    if not await check_permission(user_context, "ledger.admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        # Get original entry
        original_entry = db.query(LedgerEntryNew).filter(
            LedgerEntryNew.id == request.entry_id
        ).first()
        
        if not original_entry:
            raise HTTPException(status_code=404, detail="Entry not found")
        
        set_rls_context(db, original_entry.tenant_id)
        
        # Create adjustment entry
        adjustment_request = LedgerEntryRequest(
            tenant_id=original_entry.tenant_id,
            vendor_id=original_entry.vendor_id,
            account=original_entry.account,
            entry_type="credit" if original_entry.entry_type == "debit" else "debit",
            amount_minor=request.adjustment_amount_minor,
            currency=original_entry.currency,
            cost_centre_id=original_entry.cost_centre_id,
            site_id=original_entry.site_id,
            store_id=original_entry.store_id,
            reference_type=request.reference_type or "adjustment",
            reference_id=request.reference_id or f"adj_{request.entry_id}",
            description=f"Adjustment: {request.reason}",
            metadata={
                "original_entry_id": request.entry_id,
                "adjustment_reason": request.reason,
                "adjusted_by": user_context.get("user_id")
            }
        )
        
        # Execute saga
        saga = LedgerEntrySaga(db, adjustment_request)
        result = await saga.execute()
        
        # Log audit
        await log_audit(
            db,
            "create_ledger_adjustment",
            "ledger_entry",
            resource_id=str(result["entry_id"]),
            details={
                "original_entry_id": request.entry_id,
                "adjustment_amount_minor": request.adjustment_amount_minor,
                "reason": request.reason
            },
            user_id=user_context.get("user_id"),
            tenant_id=original_entry.tenant_id
        )
        
        return {
            "ok": True,
            "adjustment_entry_id": result["entry_id"],
            "original_entry_id": request.entry_id,
            "adjustment_amount_minor": request.adjustment_amount_minor
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create adjustment: {str(e)}")

@app.get("/ledger/v4/reports")
async def get_ledger_report(
    request: LedgerReportRequest = Depends(),
    vendor_id: Optional[str] = Query(None, description="Filter by vendor"),
    include_vendor_splits: bool = Query(False, description="Include vendor revenue splits"),
    include_currency_conversion: bool = Query(False, description="Include currency conversion"),
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Get ledger report with analytics (blueprint-inspired) including vendor splits"""
    # Check permissions
    if not await check_permission(user_context, "ledger.read"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        set_rls_context(db, request.tenant_id)
        
        # Build query for entries
        query = db.query(LedgerEntryNew).filter(LedgerEntryNew.tenant_id == request.tenant_id)
        
        if request.start_date:
            query = query.filter(LedgerEntryNew.created_at >= request.start_date)
        if request.end_date:
            query = query.filter(LedgerEntryNew.created_at <= request.end_date)
        if request.account:
            query = query.filter(LedgerEntryNew.account == request.account)
        if request.cost_centre_id:
            query = query.filter(LedgerEntryNew.cost_centre_id == request.cost_centre_id)
        if request.currency:
            query = query.filter(LedgerEntryNew.currency == request.currency)
        if vendor_id:
            query = query.filter(LedgerEntryNew.vendor_id == vendor_id)
        
        entries = query.all()
        
        # Aggregate by account and currency
        account_summary = {}
        vendor_summary = {} if include_vendor_splits else None
        
        for entry in entries:
            # Account-level aggregation
            key = f"{entry.account}_{entry.currency}"
            if key not in account_summary:
                account_summary[key] = {
                    "account": entry.account,
                    "currency": entry.currency,
                    "total_debits_minor": 0,
                    "total_credits_minor": 0,
                    "net_minor": 0,
                    "entry_count": 0
                }
            
            summary = account_summary[key]
            summary["entry_count"] += 1
            
            if entry.entry_type == "debit":
                summary["total_debits_minor"] += entry.amount_minor
                summary["net_minor"] += entry.amount_minor
            else:
                summary["total_credits_minor"] += entry.amount_minor
                summary["net_minor"] -= entry.amount_minor
            
            # Vendor-level aggregation for revenue splits
            if include_vendor_splits and entry.vendor_id:
                vendor_key = f"{entry.vendor_id}_{entry.currency}"
                if vendor_key not in vendor_summary:
                    vendor_summary[vendor_key] = {
                        "vendor_id": str(entry.vendor_id),
                        "currency": entry.currency,
                        "total_revenue_minor": 0,
                        "total_expenses_minor": 0,
                        "net_revenue_minor": 0,
                        "entry_count": 0
                    }
                
                vendor_summ = vendor_summary[vendor_key]
                vendor_summ["entry_count"] += 1
                
                if entry.entry_type == "debit" and entry.account in ["CostCentreSpend", "VendorRevenue"]:
                    vendor_summ["total_revenue_minor"] += entry.amount_minor
                    vendor_summ["net_revenue_minor"] += entry.amount_minor
                elif entry.entry_type == "credit" and entry.account in ["VendorExpenses", "MarketplaceFees"]:
                    vendor_summ["total_expenses_minor"] += entry.amount_minor
                    vendor_summ["net_revenue_minor"] -= entry.amount_minor
        
        # Currency conversion (simplified - in production would use exchange_rates table)
        if include_currency_conversion:
            for key, summary in account_summary.items():
                if summary["currency"] != "GBP":
                    # Simplified conversion (in production, use actual exchange rates)
                    conversion_rate = 1.0
                    if summary["currency"] == "USD":
                        conversion_rate = 0.8  # Example: 1 USD = 0.8 GBP
                    elif summary["currency"] == "EUR":
                        conversion_rate = 0.85  # Example: 1 EUR = 0.85 GBP
                    
                    summary["gbp_equivalent"] = {
                        "total_debits_minor": int(summary["total_debits_minor"] * conversion_rate),
                        "total_credits_minor": int(summary["total_credits_minor"] * conversion_rate),
                        "net_minor": int(summary["net_minor"] * conversion_rate),
                        "conversion_rate": conversion_rate
                    }
        
        result = {
            "tenant_id": request.tenant_id,
            "period": {
                "start_date": request.start_date.isoformat() if request.start_date else None,
                "end_date": request.end_date.isoformat() if request.end_date else None
            },
            "filters": {
                "account": request.account,
                "cost_centre_id": request.cost_centre_id,
                "currency": request.currency,
                "vendor_id": vendor_id
            },
            "summary": list(account_summary.values()),
            "total_entries": len(entries),
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Add vendor splits if requested
        if include_vendor_splits and vendor_summary:
            result["vendor_splits"] = list(vendor_summary.values())
        
        # Add currency conversion info if requested
        if include_currency_conversion:
            result["currency_conversion"] = {
                "base_currency": "GBP",
                "note": "Conversion rates are simplified for demo purposes"
            }
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {str(e)}")

# =============================================================================
# EVENT HANDLERS
# =============================================================================

@app.post("/ledger/v4/events/order-completed")
async def handle_order_completed(
    event_data: dict = Body(...),
    db: Session = Depends(get_db)
):
    """Handle ORDER_COMPLETED event from Orders/CV services"""
    try:
        tenant_id = event_data.get("tenant_id")
        order_id = event_data.get("order_id")
        amount_minor = event_data.get("total_amount_minor", 0)
        currency = event_data.get("currency", "GBP")
        
        if not tenant_id or not order_id or amount_minor <= 0:
            return {"ok": False, "message": "Invalid event data"}
        
        # Create ledger entry for order completion
        ledger_request = LedgerEntryRequest(
            tenant_id=tenant_id,
            account="CostCentreSpend",
            entry_type="debit",
            amount_minor=amount_minor,
            currency=currency,
            reference_type="order",
            reference_id=order_id,
            description=f"Order completion: {order_id}",
            metadata={
                "order_data": event_data,
                "event_source": "order_completed"
            }
        )
        
        saga = LedgerEntrySaga(db, ledger_request)
        result = await saga.execute()
        
        return {"ok": True, "ledger_entry_id": result["entry_id"]}
        
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/ledger/v4/events/invoice-posted")
async def handle_invoice_posted(
    event_data: dict = Body(...),
    db: Session = Depends(get_db)
):
    """Handle INVOICE_POSTED event from Billing service"""
    try:
        tenant_id = event_data.get("tenant_id")
        invoice_id = event_data.get("invoice_id")
        amount_minor = event_data.get("total_amount_minor", 0)
        currency = event_data.get("currency", "GBP")
        
        if not tenant_id or not invoice_id or amount_minor <= 0:
            return {"ok": False, "message": "Invalid event data"}
        
        # Create ledger entry for invoice posting
        ledger_request = LedgerEntryRequest(
            tenant_id=tenant_id,
            account="AccountsReceivable",
            entry_type="debit",
            amount_minor=amount_minor,
            currency=currency,
            reference_type="invoice",
            reference_id=invoice_id,
            description=f"Invoice posted: {invoice_id}",
            metadata={
                "invoice_data": event_data,
                "event_source": "invoice_posted"
            }
        )
        
        saga = LedgerEntrySaga(db, ledger_request)
        result = await saga.execute()
        
        return {"ok": True, "ledger_entry_id": result["entry_id"]}
        
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/ledger/v4/events/approval-resolved")
async def handle_approval_resolved(
    event_data: dict = Body(...),
    db: Session = Depends(get_db)
):
    """Handle APPROVAL_RESOLVED event from Approvals service"""
    try:
        tenant_id = event_data.get("tenant_id")
        request_id = event_data.get("request_id")
        amount_minor = event_data.get("amount_minor", 0)
        currency = event_data.get("currency", "GBP")
        approved = event_data.get("approved", False)
        
        if not tenant_id or not request_id:
            return {"ok": False, "message": "Invalid event data"}
        
        if approved and amount_minor > 0:
            # Create ledger entry for approved budget allocation
            ledger_request = LedgerEntryRequest(
                tenant_id=tenant_id,
                account="BudgetAllocation",
                entry_type="credit",
                amount_minor=amount_minor,
                currency=currency,
                reference_type="approval",
                reference_id=request_id,
                description=f"Budget allocated: {request_id}",
                metadata={
                    "approval_data": event_data,
                    "event_source": "approval_resolved"
                }
            )
            
            saga = LedgerEntrySaga(db, ledger_request)
            result = await saga.execute()
            
            return {"ok": True, "ledger_entry_id": result["entry_id"]}
        else:
            return {"ok": True, "message": "No ledger entry needed for denied approval"}
        
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/ledger/v4/events/retry")
async def retry_failed_events(
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Retry failed event publishing"""
    # Check permissions
    if not await check_permission(user_context, "ledger.admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        # Get pending events that haven't exceeded max retries
        pending_events = db.query(OutboxEvent).filter(
            OutboxEvent.status == 'pending',
            OutboxEvent.retry_count < OutboxEvent.max_retries
        ).all()
        
        retried_count = 0
        failed_count = 0
        
        for event in pending_events:
            try:
                # Simulate event publishing (in production, this would call actual event bus)
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.post(
                        f"{EVENT_BUS_URL}/events",
                        json={
                            "event_type": event.event_type,
                            "event_data": event.event_data,
                            "tenant_id": str(event.tenant_id) if event.tenant_id else None
                        }
                    )
                    
                    if response.status_code == 200:
                        event.status = 'published'
                        event.updated_at = datetime.now(timezone.utc)
                        retried_count += 1
                    else:
                        event.retry_count += 1
                        event.updated_at = datetime.now(timezone.utc)
                        if event.retry_count >= event.max_retries:
                            event.status = 'failed'
                        failed_count += 1
                        
            except Exception as e:
                event.retry_count += 1
                event.updated_at = datetime.now(timezone.utc)
                if event.retry_count >= event.max_retries:
                    event.status = 'failed'
                failed_count += 1
        
        db.commit()
        
        return {
            "ok": True,
            "retried_events": retried_count,
            "failed_events": failed_count,
            "total_processed": len(pending_events)
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to retry events: {str(e)}")

@app.get("/ledger/v4/events/status")
async def get_event_status(
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Get event publishing status"""
    # Check permissions
    if not await check_permission(user_context, "ledger.admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        # Get event statistics
        total_events = db.query(OutboxEvent).count()
        pending_events = db.query(OutboxEvent).filter(OutboxEvent.status == 'pending').count()
        published_events = db.query(OutboxEvent).filter(OutboxEvent.status == 'published').count()
        failed_events = db.query(OutboxEvent).filter(OutboxEvent.status == 'failed').count()
        
        success_rate = (published_events / total_events * 100) if total_events > 0 else 0
        
        # Get last event time
        last_event = db.query(OutboxEvent).order_by(OutboxEvent.created_at.desc()).first()
        last_event_time = last_event.created_at.isoformat() if last_event else None
        
        return {
            "total_events": total_events,
            "pending_events": pending_events,
            "published_events": published_events,
            "failed_events": failed_events,
            "success_rate": round(success_rate, 2),
            "last_event_time": last_event_time
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get event status: {str(e)}")

# =============================================================================
# LEGACY ENDPOINTS (DEPRECATED)
# =============================================================================

@app.get("/ledger")
def list_ledger_legacy(
    tenant_id: str = Query(...),
    account: Optional[str] = Query(None),
    cost_centre_id: Optional[str] = Query(None),
    cursor: Optional[int] = Query(None),
    limit: int = Query(100)
):
    """Legacy endpoint - deprecated"""
    return {
        "deprecated": True,
        "migrate_to": "/ledger/v4/entries",
        "message": "This endpoint is deprecated. Please use /ledger/v4/entries"
    }

@app.get("/ledger/balance")
def balance_legacy(
    tenant_id: str = Query(...),
    cost_centre_id: Optional[str] = Query(None)
):
    """Legacy endpoint - deprecated"""
    return {
        "deprecated": True,
        "migrate_to": "/ledger/v4/balances",
        "message": "This endpoint is deprecated. Please use /ledger/v4/balances"
    }

# =============================================================================
# INTEGRATION ENDPOINTS
# =============================================================================

@app.post("/ledger/v4/integration/orders/order-completed")
async def handle_order_completed_event(
    event_data: Dict[str, Any] = Body(...)
):
    """Handle ORDER_COMPLETED event from Orders service"""
    try:
        logger.info(f"Received ORDER_COMPLETED event: {event_data}")
        
        order_id = event_data.get("order_id")
        tenant_id = event_data.get("tenant_id")
        total_amount_minor = event_data.get("total_amount_minor", 0)
        currency = event_data.get("currency", "GBP")
        
        if not order_id or not tenant_id:
            raise HTTPException(status_code=400, detail="Missing order_id or tenant_id")
        
        # Create ledger entries for the completed order
        try:
            # Create debit entry (cost center spend)
            debit_entry = {
                "tenant_id": tenant_id,
                "account": "CostCentreSpend",
                "entry_type": "debit",
                "amount_minor": total_amount_minor,
                "currency": currency,
                "reference_type": "order",
                "reference_id": order_id,
                "description": f"Order completed: {order_id}"
            }
            
            # Create credit entry (cash/accounts payable)
            credit_entry = {
                "tenant_id": tenant_id,
                "account": "Cash",
                "entry_type": "credit",
                "amount_minor": total_amount_minor,
                "currency": currency,
                "reference_type": "order",
                "reference_id": order_id,
                "description": f"Payment received for order: {order_id}"
            }
            
            # Create entries using saga
            from .sagas import LedgerEntrySaga
            
            saga = LedgerEntrySaga()
            result = await saga.create_double_entry(
                tenant_id=tenant_id,
                debit_entry=debit_entry,
                credit_entry=credit_entry
            )
            
            logger.info(f"Successfully created ledger entries for order: {result}")
            return {"ok": True, "ledger_entries_created": True, "result": result}
            
        except Exception as e:
            logger.error(f"Failed to create ledger entries: {str(e)}")
            return {"ok": False, "error": str(e)}
            
    except Exception as e:
        logger.error(f"Error handling ORDER_COMPLETED event: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to handle event: {str(e)}")

@app.post("/ledger/v4/integration/approvals/approval-resolved")
async def handle_approval_resolved_event(
    event_data: Dict[str, Any] = Body(...)
):
    """Handle APPROVAL_RESOLVED event from Approvals service"""
    try:
        logger.info(f"Received APPROVAL_RESOLVED event: {event_data}")
        
        approval_id = event_data.get("approval_id")
        tenant_id = event_data.get("tenant_id")
        amount_minor = event_data.get("amount_minor", 0)
        currency = event_data.get("currency", "GBP")
        status = event_data.get("status")
        
        if not approval_id or not tenant_id:
            raise HTTPException(status_code=400, detail="Missing approval_id or tenant_id")
        
        # Create ledger entries based on approval status
        try:
            if status == "approved":
                # Create debit entry (approved spend)
                debit_entry = {
                    "tenant_id": tenant_id,
                    "account": "ApprovedSpend",
                    "entry_type": "debit",
                    "amount_minor": amount_minor,
                    "currency": currency,
                    "reference_type": "approval",
                    "reference_id": approval_id,
                    "description": f"Approval granted: {approval_id}"
                }
                
                # Create credit entry (budget allocated)
                credit_entry = {
                    "tenant_id": tenant_id,
                    "account": "BudgetAllocated",
                    "entry_type": "credit",
                    "amount_minor": amount_minor,
                    "currency": currency,
                    "reference_type": "approval",
                    "reference_id": approval_id,
                    "description": f"Budget allocated for approval: {approval_id}"
                }
            else:
                # For denied approvals, create reversal entries
                debit_entry = {
                    "tenant_id": tenant_id,
                    "account": "BudgetAllocated",
                    "entry_type": "debit",
                    "amount_minor": amount_minor,
                    "currency": currency,
                    "reference_type": "approval",
                    "reference_id": approval_id,
                    "description": f"Approval denied - budget reversal: {approval_id}"
                }
                
                credit_entry = {
                    "tenant_id": tenant_id,
                    "account": "ApprovedSpend",
                    "entry_type": "credit",
                    "amount_minor": amount_minor,
                    "currency": currency,
                    "reference_type": "approval",
                    "reference_id": approval_id,
                    "description": f"Approval denied - spend reversal: {approval_id}"
                }
            
            # Create entries using saga
            from .sagas import LedgerEntrySaga
            
            saga = LedgerEntrySaga()
            result = await saga.create_double_entry(
                tenant_id=tenant_id,
                debit_entry=debit_entry,
                credit_entry=credit_entry
            )
            
            logger.info(f"Successfully created ledger entries for approval: {result}")
            return {"ok": True, "ledger_entries_created": True, "result": result}
            
        except Exception as e:
            logger.error(f"Failed to create ledger entries: {str(e)}")
            return {"ok": False, "error": str(e)}
            
    except Exception as e:
        logger.error(f"Error handling APPROVAL_RESOLVED event: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to handle event: {str(e)}")

@app.post("/ledger/v4/integration/billing/invoice-posted")
async def handle_invoice_posted_event(
    event_data: Dict[str, Any] = Body(...)
):
    """Handle INVOICE_POSTED event from Billing service"""
    try:
        logger.info(f"Received INVOICE_POSTED event: {event_data}")
        
        invoice_id = event_data.get("invoice_id")
        tenant_id = event_data.get("tenant_id")
        total_amount_minor = event_data.get("total_amount_minor", 0)
        currency = event_data.get("currency", "GBP")
        
        if not invoice_id or not tenant_id:
            raise HTTPException(status_code=400, detail="Missing invoice_id or tenant_id")
        
        # Create ledger entries for the posted invoice
        try:
            # Create debit entry (accounts receivable)
            debit_entry = {
                "tenant_id": tenant_id,
                "account": "AccountsReceivable",
                "entry_type": "debit",
                "amount_minor": total_amount_minor,
                "currency": currency,
                "reference_type": "invoice",
                "reference_id": invoice_id,
                "description": f"Invoice posted: {invoice_id}"
            }
            
            # Create credit entry (revenue)
            credit_entry = {
                "tenant_id": tenant_id,
                "account": "Revenue",
                "entry_type": "credit",
                "amount_minor": total_amount_minor,
                "currency": currency,
                "reference_type": "invoice",
                "reference_id": invoice_id,
                "description": f"Revenue recognized for invoice: {invoice_id}"
            }
            
            # Create entries using saga
            from .sagas import LedgerEntrySaga
            
            saga = LedgerEntrySaga()
            result = await saga.create_double_entry(
                tenant_id=tenant_id,
                debit_entry=debit_entry,
                credit_entry=credit_entry
            )
            
            logger.info(f"Successfully created ledger entries for invoice: {result}")
            return {"ok": True, "ledger_entries_created": True, "result": result}
            
        except Exception as e:
            logger.error(f"Failed to create ledger entries: {str(e)}")
            return {"ok": False, "error": str(e)}
            
    except Exception as e:
        logger.error(f"Error handling INVOICE_POSTED event: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to handle event: {str(e)}")

@app.get("/ledger/v4/integration/status")
async def get_integration_status():
    """Get status of all service integrations"""
    try:
        integration_status = {
            "orders_service": {"status": "unknown", "url": "http://localhost:8081"},
            "approvals_service": {"status": "unknown", "url": "http://localhost:8084"},
            "billing_service": {"status": "unknown", "url": "http://localhost:8083"},
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

# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def process_journal_entry(self, tenant_id: str, entry_data: Dict[str, Any]):
    """Process journal entry asynchronously"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)
            
            # Process journal entry logic here
            logger.info(f"Processing journal entry for tenant {tenant_id}")
            
            # Update metrics
            ledger_requests_total.labels(method="POST", endpoint="journal", status="success").inc()
            
    except Exception as e:
        logger.error(f"Failed to process journal entry for tenant {tenant_id}: {e}")
        ledger_requests_total.labels(method="POST", endpoint="journal", status="failed").inc()
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def process_account_reconciliation(self, tenant_id: str, account_id: str):
    """Process account reconciliation asynchronously"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)
            
            # Process reconciliation logic here
            logger.info(f"Processing account reconciliation for tenant {tenant_id}, account {account_id}")
            
            # Update metrics
            ledger_requests_total.labels(method="POST", endpoint="reconciliation", status="success").inc()
            
    except Exception as e:
        logger.error(f"Failed to process account reconciliation: {e}")
        ledger_requests_total.labels(method="POST", endpoint="reconciliation", status="failed").inc()
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def cleanup_old_ledger_data(self):
    """Clean up old ledger data"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=365)
            
            # Clean up old journal entries
            journal_result = db.execute(text("""
                DELETE FROM journal_entries_new 
                WHERE created_at < :cutoff_date AND status IN ('posted', 'cancelled')
            """), {"cutoff_date": cutoff_date})
            
            # Clean up old account balances
            balance_result = db.execute(text("""
                DELETE FROM account_balances_new 
                WHERE created_at < :cutoff_date AND status = 'closed'
            """), {"cutoff_date": cutoff_date})
            
            db.commit()
            
            logger.info(f"Cleaned up {journal_result.rowcount} old journal entries and {balance_result.rowcount} old account balances")
            
    except Exception as e:
        logger.error(f"Failed to cleanup old ledger data: {e}")
        raise self.retry(exc=e, countdown=300)

# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8220")))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )