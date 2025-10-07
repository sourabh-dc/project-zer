# services/approvals/main.py - ZeroQue Approvals Service V2
# Step-by-step implementation with database integration

from fastapi import FastAPI, HTTPException, Body, Query
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from sqlalchemy import create_engine, Column, String, Boolean, DateTime, Integer, BigInteger, Text, func, UUID, text, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.exc import SQLAlchemyError
import logging, os, uuid, json, asyncio, hashlib, secrets, time
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List
import httpx
from fastapi import HTTPException, Depends, Header, Query, Request, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
import jwt
from pydantic import BaseModel, Field, validator
import redis
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST, REGISTRY
import structlog

# Production Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_CACHE_TTL = int(os.getenv("REDIS_CACHE_TTL", "3600"))  # 1 hour
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
SERVICE_NAME = "approvals-service"
SERVICE_VERSION = "2.0.0"

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

log = structlog.get_logger()

# Clear registry to avoid duplicate metrics on reload
try:
    REGISTRY.clear()
except:
    pass

# Prometheus Metrics
REQUEST_COUNT = Counter(
    'approvals_requests_total', 
    'Total number of requests', 
    ['method', 'endpoint', 'status_code']
)

REQUEST_DURATION = Histogram(
    'approvals_request_duration_seconds', 
    'Request duration in seconds',
    ['method', 'endpoint']
)

ACTIVE_CONNECTIONS = Gauge(
    'approvals_active_connections', 
    'Number of active connections'
)

APPROVAL_REQUESTS_CREATED_V2 = Counter(
    'approvals_v2_requests_created_total',
    'Total number of approval requests created',
    ['request_type', 'status']
)

APPROVAL_REQUESTS_RESOLVED_V2 = Counter(
    'approvals_v2_requests_resolved_total',
    'Total number of approval requests resolved',
    ['request_type', 'resolution']
)

EVENTS_PUBLISHED = Counter(
    'approvals_events_published_total',
    'Total number of events published',
    ['event_type', 'status']
)

CACHE_HITS = Counter(
    'approvals_cache_hits_total',
    'Total number of cache hits',
    ['cache_type']
)

CACHE_MISSES = Counter(
    'approvals_cache_misses_total',
    'Total number of cache misses',
    ['cache_type']
)

# Event Publishing Configuration
EVENT_BUS_URL = os.getenv("EVENT_BUS_URL", "http://localhost:8080/events")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://localhost:8081/notifications")
ORDERS_SERVICE_URL = os.getenv("ORDERS_SERVICE_URL", "http://localhost:8082/orders")
BUDGETS_SERVICE_URL = os.getenv("BUDGETS_SERVICE_URL", "http://localhost:8083/budgets")

# Security Configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 30
API_KEY_HEADER = "X-API-Key"
RATE_LIMIT_REQUESTS_PER_MINUTE = 100
MAX_REQUEST_SIZE_BYTES = 1024 * 1024  # 1MB

# Security Dependencies
security = HTTPBearer(auto_error=False)

# Redis Cache
redis_client = None

async def get_redis_client():
    """Get Redis client with connection pooling"""
    global redis_client
    if redis_client is None:
        try:
            redis_client = redis.from_url(REDIS_URL, decode_responses=True)
            # Test connection
            redis_client.ping()
            log.info("Redis connection established")
        except Exception as e:
            log.warning(f"Redis connection failed: {str(e)}")
            redis_client = None
    return redis_client

async def cache_get(key: str) -> Optional[str]:
    """Get value from cache"""
    try:
        client = await get_redis_client()
        if client:
            value = client.get(key)
            if value:
                CACHE_HITS.labels(cache_type="general").inc()
                return value
            else:
                CACHE_MISSES.labels(cache_type="general").inc()
        return None
    except Exception as e:
        log.warning(f"Cache get failed: {str(e)}")
        return None

async def cache_set(key: str, value: str, ttl: int = REDIS_CACHE_TTL) -> bool:
    """Set value in cache"""
    try:
        client = await get_redis_client()
        if client:
            client.setex(key, ttl, value)
            return True
        return False
    except Exception as e:
        log.warning(f"Cache set failed: {str(e)}")
        return False
    
async def cache_delete(key: str) -> bool:
    """Delete value from cache"""
    try:
        client = await get_redis_client()
        if client:
            client.delete(key)
            return True
        return False
    except Exception as e:
        log.warning(f"Cache delete failed: {str(e)}")
        return False

# Custom Exceptions for Saga Pattern
class SagaStepFailed(Exception):
    """Raised when a saga step fails"""
    pass

class EventPublishingError(Exception):
    """Raised when event publishing fails"""
    pass

class CompensationFailed(Exception):
    """Raised when saga compensation fails"""
    pass

class SecurityError(Exception):
    """Raised when security validation fails"""
    pass

class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded"""
    pass

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zeroque:zeroque@localhost:5000/zeroque_dev")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# SQLAlchemy Models - Matching actual database schema
class ApprovalChain(Base):
    """Approval Chain: Workflow templates for approval processes"""
    __tablename__ = "approval_chains"
    
    chain_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    chain_type = Column(String(50), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True)

class ApprovalChainStep(Base):
    """Approval Chain Step: Individual steps in an approval chain"""
    __tablename__ = "approval_chain_steps"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    approval_chain_id = Column(UUID(as_uuid=True), nullable=False)
    step_number = Column(Integer, nullable=False)
    approver_role = Column(Text, nullable=False)
    approver_scope = Column(String(50), nullable=False)
    escalation_after_hours = Column(Integer, nullable=True)
    is_required = Column(Boolean, nullable=False, default=True)

class ApprovalRequest(Base):
    """Approval Request: Individual approval requests"""
    __tablename__ = "approval_requests_new"
    
    request_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_number = Column(String(50), nullable=False, unique=True)
    chain_id = Column(UUID(as_uuid=True), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)  # Added for tenant isolation
    request_type = Column(String(50), nullable=False)
    request_data = Column(Text, nullable=False)  # JSONB stored as text
    requested_by = Column(UUID(as_uuid=True), nullable=False)
    request_status = Column(String(20), nullable=False, default='pending')
    current_step_id = Column(UUID(as_uuid=True), nullable=True)
    current_step_number = Column(Integer, nullable=False, default=1)  # Added for workflow tracking
    total_amount_minor = Column(BigInteger, nullable=True)
    currency = Column(String(3), nullable=True)
    due_date = Column(DateTime(timezone=True), nullable=True)
    completed_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    approvers = relationship("ApprovalRequestApprover", back_populates="request")

class ApprovalRequestApprover(Base):
    """Approval Request Approver: Tracks individual approver responses"""
    __tablename__ = "approval_request_approvers"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey('approval_requests_new.request_id'), nullable=False)
    approver_user_id = Column(UUID(as_uuid=True), nullable=False)
    approver_role = Column(String(100), nullable=False)
    step_number = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default='pending')  # pending, approved, denied, skipped
    notes = Column(Text, nullable=True)
    responded_at = Column(DateTime(timezone=True), nullable=True)
    escalation_sent = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    request = relationship("ApprovalRequest", back_populates="approvers")

class OutboxEvent(Base):
    """Outbox Event: For reliable event publishing"""
    __tablename__ = "outbox_events"
    
    event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(String(100), nullable=False)
    aggregate_id = Column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    event_data = Column(Text, nullable=False)  # JSONB stored as text
    event_version = Column(Integer, nullable=False, default=1)
    event_timestamp = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    status = Column(String(20), nullable=False, default='pending')
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
class AuditLog(Base):
    """Audit Log: Security and access logging"""
    __tablename__ = "audit_logs"
    
    log_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    table_name = Column(String(100), nullable=False)
    record_id = Column(UUID(as_uuid=True), nullable=False)
    operation = Column(String(20), nullable=False)
    old_values = Column(Text, nullable=True)  # JSONB stored as text
    new_values = Column(Text, nullable=True)  # JSONB stored as text
    changed_by = Column(UUID(as_uuid=True), nullable=True)
    changed_at = Column(DateTime(timezone=True), server_default=func.now())
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)

# Phase 4: Security Models
class UserContext(BaseModel):
    """User context for RLS and authorization"""
    user_id: str
    tenant_id: str
    roles: List[str] = []
    permissions: List[str] = []
    site_id: Optional[str] = None
    store_id: Optional[str] = None

class SecurityValidation(BaseModel):
    """Security validation result"""
    is_valid: bool
    user_context: Optional[UserContext] = None
    error_message: Optional[str] = None

# Pydantic Models
class CreateApprovalChainRequest(BaseModel):
    """Request model for creating approval chains"""
    name: str = Field(..., description="Chain name", min_length=1)
    description: Optional[str] = Field(None, description="Chain description")
    chain_type: str = Field(..., description="Chain type")
    is_active: bool = Field(True, description="Whether chain is active")

class CreateApprovalChainStepRequest(BaseModel):
    """Request model for creating approval chain steps"""
    approval_chain_id: str = Field(..., description="Chain ID")
    step_number: int = Field(..., description="Step number", gt=0)
    approver_role: str = Field(..., description="Approver role")
    approver_scope: str = Field(..., description="Approver scope")
    escalation_after_hours: Optional[int] = Field(None, description="Escalation timeout in hours", gt=0)
    is_required: bool = Field(True, description="Whether this step is required")

class CreateApprovalRequestRequest(BaseModel):
    """Request model for creating approval requests"""
    request_type: str = Field(..., description="Request type")
    requested_by: str = Field(..., description="Requester user ID")
    chain_id: str = Field(..., description="Chain ID")
    tenant_id: str = Field(..., description="Tenant ID for multi-tenancy")
    request_data: Dict[str, Any] = Field(..., description="Request data")
    total_amount_minor: Optional[int] = Field(None, description="Amount in minor units")
    currency: str = Field("GBP", description="Currency code")
    due_date: Optional[datetime] = Field(None, description="Due date")

class ApproveRequest(BaseModel):
    """Request model for responding to approval requests"""
    approver_user_id: str = Field(..., description="Approver user ID")
    approved: bool = Field(..., description="Whether to approve or deny")
    notes: Optional[str] = Field(None, description="Approval notes", max_length=500)

class RespondToRequestRequest(BaseModel):
    """Request model for responding to approval requests (new workflow logic)"""
    approver_user_id: str = Field(..., description="Approver user ID")
    approved: bool = Field(..., description="Whether to approve or deny")
    notes: Optional[str] = Field(None, description="Approver notes", max_length=500)
    step_number: int = Field(..., description="Step number being responded to")

class ApprovalRequestApproverResponse(BaseModel):
    """Response model for approval request approvers"""
    id: str
    request_id: str
    approver_user_id: str
    approver_role: str
    step_number: int
    status: str
    notes: Optional[str]
    responded_at: Optional[datetime]
    escalation_sent: bool
    created_at: datetime
    updated_at: Optional[datetime]

# Phase 4: Security Functions

def validate_uuid(uuid_string: str) -> None:
    """Validate UUID format"""
    try:
        uuid.UUID(uuid_string)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid UUID format: {uuid_string}")

async def validate_jwt_token(token: str) -> Optional[UserContext]:
    """Validate JWT token and extract user context"""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        
        # Extract user context from JWT payload
        user_context = UserContext(
            user_id=payload.get("user_id", ""),
            tenant_id=payload.get("tenant_id", ""),
            roles=payload.get("roles", []),
            permissions=payload.get("permissions", []),
            site_id=payload.get("site_id"),
            store_id=payload.get("store_id")
        )
        
        return user_context
        
    except jwt.ExpiredSignatureError:
        log.warning("JWT token expired")
        return None
    except jwt.InvalidTokenError:
        log.warning("Invalid JWT token")
        return None
    except Exception as e:
        log.error(f"JWT validation error: {str(e)}")
        return None

async def get_user_context(
    authorization: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
) -> UserContext:
    """Extract user context from request"""
    
    # For demo purposes, create a default user context
    # In production, this would validate JWT or API key
    if authorization and authorization.credentials:
        user_context = await validate_jwt_token(authorization.credentials)
        if user_context:
            return user_context
    
    # Fallback for demo/testing - create a default context
    log.warning("No valid authentication provided, using demo context")
    return UserContext(
        user_id="550e8400-e29b-41d4-a716-446655440004",
        tenant_id="550e8400-e29b-41d4-a716-446655440000",
        roles=["admin", "approver"],
        permissions=["approval.create", "approval.approve", "approval.view"],
        site_id="550e8400-e29b-41d4-a716-446655440001",
        store_id="550e8400-e29b-41d4-a716-446655440002"
    )

async def log_audit_event(
    user_context: UserContext,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    request_data: Optional[Dict] = None,
    response_status: Optional[int] = None,
    error_message: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    db_session=None
):
    """Log security audit event"""
    try:
        # Map custom actions to allowed operations
        operation_map = {
            "create_approval_request": "INSERT",
            "approve_request": "UPDATE", 
            "validate_permission": "INSERT",
            "view_audit_logs": "INSERT"
        }
        operation = operation_map.get(action, "INSERT")
        
        audit_log = AuditLog(
            table_name=resource_type,
            record_id=uuid.uuid4() if not resource_id else uuid.UUID(resource_id),
            operation=operation,
            new_values=json.dumps({
                "request_data": request_data,
                "response_status": response_status,
                "error_message": error_message,
                "user_id": user_context.user_id,
                "tenant_id": user_context.tenant_id
            }) if request_data or response_status or error_message else None,
            changed_by=uuid.UUID(user_context.user_id),
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        if db_session:
            db_session.add(audit_log)
            db_session.flush()
        else:
            # If no session provided, create a temporary one
            db = SessionLocal()
            try:
                db.add(audit_log)
                db.commit()
            finally:
                db.close()
                
        log.info(f"Audit logged: {action} on {resource_type} by {user_context.user_id}")
        
    except Exception as e:
        log.error(f"Failed to log audit event: {str(e)}")

def set_rls_context(user_context: UserContext, db_session):
    """Set Row Level Security context for database session"""
    try:
        # Set RLS variables for tenant isolation
        db_session.execute(text(f"SET LOCAL app.current_tenant_id = '{user_context.tenant_id}'"))
        db_session.execute(text(f"SET LOCAL app.current_user_id = '{user_context.user_id}'"))
        db_session.execute(text("SET LOCAL row_security = on"))
        
        log.debug(f"RLS context set for tenant: {user_context.tenant_id}, user: {user_context.user_id}")
        
    except Exception as e:
        log.error(f"Failed to set RLS context: {str(e)}")
        raise SecurityError(f"Failed to set RLS context: {str(e)}")

def check_permission(user_context: UserContext, required_permission: str) -> bool:
    """Check if user has required permission"""
    if "admin" in user_context.roles:
        return True
    
    return required_permission in user_context.permissions

def validate_tenant_access(user_context: UserContext, resource_tenant_id: str) -> bool:
    """Validate user has access to tenant resource"""
    return user_context.tenant_id == resource_tenant_id

async def validate_request_size(request_size: int) -> bool:
    """Validate request size is within limits"""
    return request_size <= MAX_REQUEST_SIZE_BYTES

# Rate limiting (simplified in-memory implementation)
rate_limit_store = {}

async def check_rate_limit(user_id: str) -> bool:
    """Check if user has exceeded rate limit"""
    current_time = datetime.now()
    minute_key = current_time.replace(second=0, microsecond=0)
    
    if user_id not in rate_limit_store:
        rate_limit_store[user_id] = {}
    
    user_requests = rate_limit_store[user_id]
    
    # Clean old entries
    for time_key in list(user_requests.keys()):
        if time_key < minute_key - timedelta(minutes=1):
            del user_requests[time_key]
    
    # Check current minute
    current_count = user_requests.get(minute_key, 0)
    if current_count >= RATE_LIMIT_REQUESTS_PER_MINUTE:
        return False
    
    # Increment counter
    user_requests[minute_key] = current_count + 1
    return True

# Phase 3: Event Publishing & Saga Functions

async def publish_event(event_type: str, event_data: Dict[str, Any], db_session) -> bool:
    """Publish event using outbox pattern for reliability"""
    try:
        # Create outbox event
        outbox_event = OutboxEvent(
            event_type=event_type,
            event_data=json.dumps(event_data),
            status='pending'
        )
        
        db_session.add(outbox_event)
        db_session.flush()  # Get the event_id
        
        log.info(f"Event queued for publishing: {event_type} - {outbox_event.event_id}")
        
        # Try to publish immediately (non-blocking)
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    f"{EVENT_BUS_URL}/publish",
                    json={
                        "event_id": str(outbox_event.event_id),
                        "event_type": event_type,
                        "event_data": event_data,
                        "source": "approvals-service",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                )
                
                if response.status_code == 200:
                    outbox_event.status = 'published'
                    outbox_event.processed_at = datetime.now(timezone.utc)
                    log.info(f"Event published successfully: {event_type}")
                    EVENTS_PUBLISHED.labels(event_type=event_type, status="success").inc()
                    return True
                else:
                    log.warning(f"Event publishing failed: {response.status_code}")
                    EVENTS_PUBLISHED.labels(event_type=event_type, status="failed").inc()
                    
        except Exception as e:
            log.warning(f"Event publishing failed, will retry: {str(e)}")
        
        return False
        
    except Exception as e:
        log.error(f"Failed to queue event {event_type}: {str(e)}")
        raise EventPublishingError(f"Failed to queue event: {str(e)}")

async def notify_approvers(request_id: str, approvers: List[str], request_data: Dict[str, Any], db_session):
    """Notify approvers about new approval request"""
    try:
        # Get approver details (simplified - in production, you'd query user service)
        notification_data = {
            "request_id": request_id,
            "request_type": request_data.get("request_type", "budget"),
            "amount": request_data.get("total_amount_minor", 0),
            "currency": request_data.get("currency", "GBP"),
            "requester": request_data.get("requested_by"),
            "approvers": approvers,
            "due_date": request_data.get("due_date"),
            "message": f"New approval request {request_id} requires your attention"
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{NOTIFICATION_SERVICE_URL}/notify/approval-request",
                json=notification_data
            )
            
            if response.status_code == 200:
                log.info(f"Notified approvers for request {request_id}")
                return True
            else:
                log.warning(f"Failed to notify approvers: {response.status_code}")
                return False
                
    except Exception as e:
        log.error(f"Failed to notify approvers for request {request_id}: {str(e)}")
        return False

async def update_budget_on_approval(request_id: str, approved: bool, amount_minor: int, db_session):
    """Update budget when approval is resolved"""
    try:
        if not approved:
            log.info(f"Request {request_id} denied, no budget update needed")
            return True
            
        budget_data = {
            "request_id": request_id,
            "amount_minor": amount_minor,
            "action": "allocate",
            "reason": f"Approval granted for request {request_id}"
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{BUDGETS_SERVICE_URL}/allocate",
                json=budget_data
            )
            
            if response.status_code == 200:
                log.info(f"Budget allocated for request {request_id}")
                return True
            else:
                log.error(f"Failed to allocate budget: {response.status_code}")
                return False
                
    except Exception as e:
        log.error(f"Failed to update budget for request {request_id}: {str(e)}")
        return False

class ApprovalRequestSaga:
    """Saga pattern for approval request creation with compensation"""
    
    def __init__(self, db_session):
        self.db_session = db_session
        self.steps_completed = []
        self.compensation_actions = []
    
    async def execute_step(self, step_name: str, step_func, compensation_func=None):
        """Execute a saga step with compensation tracking"""
        try:
            log.info(f"Executing saga step: {step_name}")
            result = await step_func()
            self.steps_completed.append(step_name)
            if compensation_func:
                self.compensation_actions.append((step_name, compensation_func))
            return result
        except Exception as e:
            log.error(f"Saga step failed: {step_name} - {str(e)}")
            await self.compensate()
            raise SagaStepFailed(f"Step {step_name} failed: {str(e)}")
    
    async def compensate(self):
        """Execute compensation actions in reverse order"""
        log.info("Starting saga compensation")
        for step_name, compensation_func in reversed(self.compensation_actions):
            try:
                log.info(f"Compensating step: {step_name}")
                await compensation_func()
            except Exception as e:
                log.error(f"Compensation failed for step {step_name}: {str(e)}")
                # Continue with other compensations
        log.info("Saga compensation completed")

async def create_approval_request_saga(request_data: CreateApprovalRequestRequest, db_session):
    """Saga for creating approval request with full workflow"""
    saga = ApprovalRequestSaga(db_session)
    
    try:
        # Step 1: Create the approval request
        request_id = await saga.execute_step(
            "create_request",
            lambda: _create_request_record(request_data, db_session),
            lambda: _delete_request_record(request_id, db_session)
        )
        
        # Step 2: Get approval chain steps
        chain_steps = await saga.execute_step(
            "get_chain_steps",
            lambda: _get_approval_chain_steps(request_data.chain_id, db_session)
        )
        
        # Step 3: Assign approvers
        approvers = await saga.execute_step(
            "assign_approvers",
            lambda: _assign_approvers_from_chain(chain_steps, db_session)
        )
        
        # Step 4: Publish APPROVAL_CREATED event
        await saga.execute_step(
            "publish_event",
            lambda: publish_event("APPROVAL_CREATED", {
                "request_id": request_id,
                "request_type": request_data.request_type,
                "requested_by": request_data.requested_by,
                "chain_id": request_data.chain_id,
                "amount_minor": request_data.total_amount_minor,
                "currency": request_data.currency,
                "approvers": approvers
            }, db_session)
        )
        
        # Step 5: Notify approvers
        await saga.execute_step(
            "notify_approvers",
            lambda: notify_approvers(request_id, approvers, request_data.dict(), db_session)
        )
        
        log.info(f"Approval request saga completed successfully: {request_id}")
        return request_id
        
    except SagaStepFailed as e:
        log.error(f"Approval request saga failed: {str(e)}")
        raise e

# Helper functions for saga steps
async def _create_request_record(request_data: CreateApprovalRequestRequest, db_session):
    """Create the approval request record"""
    request_number = f"REQ-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    
    approval_request = ApprovalRequest(
        request_number=request_number,
        request_type=request_data.request_type,
        requested_by=uuid.UUID(request_data.requested_by),
        chain_id=uuid.UUID(request_data.chain_id),
        tenant_id=uuid.UUID(request_data.tenant_id),
        request_data=json.dumps(request_data.request_data),
        total_amount_minor=request_data.total_amount_minor,
        currency=request_data.currency,
        due_date=request_data.due_date
    )
    
    db_session.add(approval_request)
    db_session.flush()  # Get the request_id
    return str(approval_request.request_id)

async def _delete_request_record(request_id: str, db_session):
    """Compensation: Delete the request record"""
    db_session.query(ApprovalRequest).filter(
        ApprovalRequest.request_id == uuid.UUID(request_id)
    ).delete()

async def _get_approval_chain_steps(chain_id: str, db_session):
    """Get approval chain steps"""
    steps = db_session.query(ApprovalChainStep).filter(
        ApprovalChainStep.approval_chain_id == uuid.UUID(chain_id)
    ).order_by(ApprovalChainStep.step_number).all()
    
    return [{
        "step_number": step.step_number,
        "approver_role": step.approver_role,
        "approver_scope": step.approver_scope,
        "is_required": step.is_required
    } for step in steps]

async def _assign_approvers_from_chain(chain_steps: List[Dict], db_session):
    """Assign approvers based on chain steps with proper database storage"""
    try:
        approvers = []
        request_id = None  # This should be passed from the saga
        
        # Get the request_id from the current request being processed
        # This is a simplified approach - in production, pass request_id as parameter
        
        for step in chain_steps:
            # Query role_assignments to get actual user_ids for the approver_role
            approver_user_ids = await _get_user_ids_for_role(db_session, step['approver_role'])
            
            if not approver_user_ids:
                log.warning(f"No users found for role {step['approver_role']}")
                continue
            
            # Assign all users with the role to this step
            for user_id in approver_user_ids:
                approvers.append(user_id)
                
                # Store in database if we have request_id
                if request_id:
                    approver = ApprovalRequestApprover(
                        request_id=request_id,
                        approver_user_id=user_id,
                        approver_role=step['approver_role'],
                        step_number=step['step_number'],
                        status='pending'
                    )
                    db_session.add(approver)
        
        return approvers
        
    except Exception as e:
        log.error(f"Failed to assign approvers: {str(e)}")
        return []

async def _get_user_ids_for_role(db_session, role_name: str) -> List[str]:
    """Get user IDs for a given role from role_assignments"""
    try:
        # This is a placeholder - in production, integrate with Provisioning service
        # For now, return a demo user ID
        return ["550e8400-e29b-41d4-a716-446655440004"]  # Demo user
        
        # Production implementation would be:
        # result = db_session.execute(text("""
        #     SELECT user_id FROM role_assignments 
        #     WHERE role_name = :role_name AND is_active = true
        # """), {"role_name": role_name})
        # return [row[0] for row in result.fetchall()]
        
    except Exception as e:
        log.error(f"Failed to get user IDs for role {role_name}: {str(e)}")
        return []

# FastAPI App with lifespan management
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Startup
    log.info("Starting Approvals Service V2 with Event Publishing")
    
    # Create tables if they don't exist
    try:
        Base.metadata.create_all(bind=engine)
        log.info("Database tables created/verified successfully")
    except Exception as e:
        log.error(f"Failed to create database tables: {str(e)}")
        raise
    
    yield
    
    # Shutdown
    log.info("Shutting down Approvals Service V2")

app = FastAPI(
    title="ZeroQue Approvals Service V2",
    description="Enterprise-grade approval workflow management service with event publishing, saga patterns, and comprehensive security",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs" if ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if ENVIRONMENT != "production" else None
)

# Production Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if ENVIRONMENT == "development" else ["https://*.zeroque.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

if ENVIRONMENT == "production":
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["*.zeroque.com", "zeroque.com"]
    )

@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Middleware for metrics collection and request logging"""
    start_time = time.time()
    
    # Get endpoint for metrics
    endpoint = request.url.path
    method = request.method
    
    # Increment active connections
    ACTIVE_CONNECTIONS.inc()
    
    try:
        response = await call_next(request)
        
        # Record metrics
        duration = time.time() - start_time
        REQUEST_DURATION.labels(method=method, endpoint=endpoint).observe(duration)
        REQUEST_COUNT.labels(method=method, endpoint=endpoint, status_code=response.status_code).inc()
        
        # Log request
        log.info(
            "Request completed",
            method=method,
            endpoint=endpoint,
            status_code=response.status_code,
            duration=duration,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None
        )
        
        return response
        
    except Exception as e:
        # Record error metrics
        duration = time.time() - start_time
        REQUEST_DURATION.labels(method=method, endpoint=endpoint).observe(duration)
        REQUEST_COUNT.labels(method=method, endpoint=endpoint, status_code=500).inc()
        
        # Log error
        log.error(
            "Request failed",
            method=method,
            endpoint=endpoint,
            error=str(e),
            duration=duration,
            exc_info=True
        )
        
        raise
        
    finally:
        # Decrement active connections
        ACTIVE_CONNECTIONS.dec()

# Health endpoint
@app.get("/health")
async def health():
    """Comprehensive health check endpoint"""
    try:
        health_status = {
            "status": "ok",
            "service": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "environment": ENVIRONMENT,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": {}
        }
        
        # Database health check
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            health_status["checks"]["database"] = {"status": "healthy"}
        except Exception as e:
            health_status["checks"]["database"] = {"status": "unhealthy", "error": str(e)}
            health_status["status"] = "degraded"
        
        # Redis health check
        try:
            client = await get_redis_client()
            if client:
                client.ping()
                health_status["checks"]["redis"] = {"status": "healthy"}
            else:
                health_status["checks"]["redis"] = {"status": "unavailable"}
                health_status["status"] = "degraded"
        except Exception as e:
            health_status["checks"]["redis"] = {"status": "unhealthy", "error": str(e)}
            health_status["status"] = "degraded"
        
        # Event bus health check
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{EVENT_BUS_URL}/health")
                if response.status_code == 200:
                    health_status["checks"]["event_bus"] = {"status": "healthy"}
                else:
                    health_status["checks"]["event_bus"] = {"status": "unhealthy", "status_code": response.status_code}
                    health_status["status"] = "degraded"
        except Exception as e:
            health_status["checks"]["event_bus"] = {"status": "unhealthy", "error": str(e)}
            health_status["status"] = "degraded"
        
        # Return appropriate status code
        status_code = 200 if health_status["status"] == "ok" else 503
        return Response(content=json.dumps(health_status), media_type="application/json", status_code=status_code)
        
    except Exception as e:
        log.error(f"Health check failed: {str(e)}")
        return Response(
            content=json.dumps({
                "status": "unhealthy",
                "service": SERVICE_NAME,
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }),
            media_type="application/json",
            status_code=500
        )

# Metrics endpoint
@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )

# Phase 2: Database-integrated endpoints

@app.post("/approvals/v2/chains")
async def create_approval_chain(request: CreateApprovalChainRequest = Body(...)):
    """Create a new approval chain"""
    try:
        db = SessionLocal()
        try:
            chain = ApprovalChain(
                name=request.name,
                description=request.description,
                chain_type=request.chain_type,
                is_active=request.is_active
            )
            
            db.add(chain)
            db.commit()
            db.refresh(chain)
            
            log.info(f"Created approval chain: {chain.chain_id}")
            
            return {
                "chain_id": str(chain.chain_id),
                "name": chain.name,
                "description": chain.description,
                "chain_type": chain.chain_type,
                "is_active": chain.is_active,
                "created_at": chain.created_at.isoformat()
            }
            
        finally:
            db.close()
            
    except SQLAlchemyError as e:
        log.error(f"Database error in create_approval_chain: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        log.error(f"Unexpected error in create_approval_chain: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")

@app.get("/approvals/v2/chains")
async def list_approval_chains(
    chain_type: Optional[str] = Query(None, description="Filter by chain type"),
    is_active: Optional[bool] = Query(None, description="Filter by active status")
):
    """List approval chains with caching"""
    try:
        # Create cache key
        cache_key = f"approval_chains:{chain_type}:{is_active}"
        
        # Try to get from cache first
        cached_result = await cache_get(cache_key)
        if cached_result:
            return json.loads(cached_result)
        
        db = SessionLocal()
        try:
            query = db.query(ApprovalChain)
            
            if chain_type:
                query = query.filter(ApprovalChain.chain_type == chain_type)
            if is_active is not None:
                query = query.filter(ApprovalChain.is_active == is_active)
            
            chains = query.order_by(ApprovalChain.created_at.desc()).all()
            
            results = []
            for chain in chains:
                results.append({
                    "chain_id": str(chain.chain_id),
                    "name": chain.name,
                    "description": chain.description,
                    "chain_type": chain.chain_type,
                    "is_active": chain.is_active,
                    "created_at": chain.created_at.isoformat()
                })
            
            result = {"chains": results}
            
            # Cache the result
            await cache_set(cache_key, json.dumps(result), ttl=300)  # 5 minutes
            
            return result
            
        finally:
            db.close()
            
    except SQLAlchemyError as e:
        log.error(f"Database error in list_approval_chains: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        log.error(f"Unexpected error in list_approval_chains: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")

@app.post("/approvals/v2/requests")
async def create_approval_request(
    request: CreateApprovalRequestRequest = Body(...),
    user_context: UserContext = Depends(get_user_context),
    x_forwarded_for: Optional[str] = Header(None),
    user_agent: Optional[str] = Header(None)
):
    """Create a new approval request with saga pattern and security"""
    try:
        # Security validations
        if not check_permission(user_context, "approval.create"):
            await log_audit_event(
                user_context, "create_approval_request", "approval_request",
                response_status=403, error_message="Insufficient permissions"
            )
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        if not await check_rate_limit(user_context.user_id):
            await log_audit_event(
                user_context, "create_approval_request", "approval_request",
                response_status=429, error_message="Rate limit exceeded"
            )
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        
        db = SessionLocal()
        try:
            # Set RLS context
            set_rls_context(user_context, db)
            
            # Use saga pattern for reliable request creation
            request_id = await create_approval_request_saga(request, db)
            
            # Get the created request
            approval_request = db.query(ApprovalRequest).filter(
                ApprovalRequest.request_id == uuid.UUID(request_id)
            ).first()
            
            db.commit()
            
            # Log successful audit event
            await log_audit_event(
                user_context, "create_approval_request", "approval_request",
                resource_id=request_id, request_data=request.dict(),
                response_status=200, ip_address=x_forwarded_for, user_agent=user_agent,
                db_session=db
            )
            
            log.info(f"Created approval request with saga: {request_id}")
            
            # Record metrics
            APPROVAL_REQUESTS_CREATED_V2.labels(request_type=request.request_type, status="success").inc()
            
            return {
                "request_id": str(approval_request.request_id),
                "request_number": approval_request.request_number,
                "request_type": approval_request.request_type,
                "requested_by": str(approval_request.requested_by),
                "chain_id": str(approval_request.chain_id),
                "request_data": json.loads(approval_request.request_data) if approval_request.request_data and isinstance(approval_request.request_data, str) else (approval_request.request_data if approval_request.request_data else {}),
                "total_amount_minor": approval_request.total_amount_minor,
                "currency": approval_request.currency,
                "request_status": approval_request.request_status,
                "due_date": approval_request.due_date.isoformat() if approval_request.due_date else None,
                "created_at": approval_request.created_at.isoformat(),
                "message": "Request created successfully with event publishing and notifications"
            }
            
        finally:
            db.close()
            
    except HTTPException:
        raise
    except SagaStepFailed as e:
        await log_audit_event(
            user_context, "create_approval_request", "approval_request",
            response_status=500, error_message=f"Saga failed: {str(e)}"
        )
        log.error(f"Saga failed in create_approval_request: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Request creation failed: {str(e)}")
    except SQLAlchemyError as e:
        await log_audit_event(
            user_context, "create_approval_request", "approval_request",
            response_status=500, error_message=f"Database error: {str(e)}"
        )
        log.error(f"Database error in create_approval_request: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        await log_audit_event(
            user_context, "create_approval_request", "approval_request",
            response_status=500, error_message=f"Unexpected error: {str(e)}"
        )
        log.error(f"Unexpected error in create_approval_request: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")

@app.get("/approvals/v2/requests")
async def list_approval_requests(
    tenant_id: Optional[str] = Query(None, description="Filter by tenant ID"),
    request_type: Optional[str] = Query(None, description="Filter by request type"),
    request_status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, le=100, description="Number of results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip")
):
    """List approval requests"""
    try:
        db = SessionLocal()
        try:
            query = db.query(ApprovalRequest)
            
            if tenant_id:
                validate_uuid(tenant_id)
                query = query.filter(ApprovalRequest.tenant_id == uuid.UUID(tenant_id))
            if request_type:
                query = query.filter(ApprovalRequest.request_type == request_type)
            if request_status:
                query = query.filter(ApprovalRequest.request_status == request_status)
            
            total = query.count()
            requests = query.order_by(ApprovalRequest.created_at.desc()).offset(offset).limit(limit).all()
            
            results = []
            for req in requests:
                results.append({
                    "request_id": str(req.request_id),
                    "request_number": req.request_number,
                    "request_type": req.request_type,
                    "requested_by": str(req.requested_by),
                    "chain_id": str(req.chain_id),
                    "request_data": json.loads(req.request_data) if req.request_data and isinstance(req.request_data, str) else (req.request_data if req.request_data else {}),
                    "total_amount_minor": req.total_amount_minor,
                    "currency": req.currency,
                    "request_status": req.request_status,
                    "due_date": req.due_date.isoformat() if req.due_date else None,
                    "created_at": req.created_at.isoformat()
            })
            
            return {
                "requests": results,
                "total": total,
                "limit": limit,
                "offset": offset
            }
            
        finally:
            db.close()
            
    except SQLAlchemyError as e:
        log.error(f"Database error in list_approval_requests: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        log.error(f"Unexpected error in list_approval_requests: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")

# Phase 2: Workflow Management Endpoints

@app.post("/approvals/v2/chains/{chain_id}/steps")
async def create_approval_chain_step(
    chain_id: str,
    request: CreateApprovalChainStepRequest = Body(...)
):
    """Add a step to an approval chain"""
    try:
        db = SessionLocal()
        try:
            # Verify chain exists
            chain = db.query(ApprovalChain).filter(ApprovalChain.chain_id == uuid.UUID(chain_id)).first()
            if not chain:
                raise HTTPException(status_code=404, detail=f"Approval chain not found: {chain_id}")
            
            step = ApprovalChainStep(
                approval_chain_id=uuid.UUID(chain_id),
                step_number=request.step_number,
                approver_role=request.approver_role,
                approver_scope=request.approver_scope,
                escalation_after_hours=request.escalation_after_hours,
                is_required=request.is_required
            )
            
            db.add(step)
            db.commit()
            db.refresh(step)
            
            log.info(f"Created approval chain step: {step.id}")
            
            return {
                "id": str(step.id),
                "approval_chain_id": str(step.approval_chain_id),
                "step_number": step.step_number,
                "approver_role": step.approver_role,
                "approver_scope": step.approver_scope,
                "escalation_after_hours": step.escalation_after_hours,
                "is_required": step.is_required
            }
            
        finally:
            db.close()
            
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        log.error(f"Database error in create_approval_chain_step: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        log.error(f"Unexpected error in create_approval_chain_step: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")

@app.get("/approvals/v2/chains/{chain_id}/steps")
async def list_approval_chain_steps(chain_id: str):
    """List steps for an approval chain"""
    try:
        db = SessionLocal()
        try:
            steps = db.query(ApprovalChainStep).filter(
                ApprovalChainStep.approval_chain_id == uuid.UUID(chain_id)
            ).order_by(ApprovalChainStep.step_number).all()
            
            results = []
            for step in steps:
                results.append({
                    "id": str(step.id),
                    "approval_chain_id": str(step.approval_chain_id),
                    "step_number": step.step_number,
                    "approver_role": step.approver_role,
                    "approver_scope": step.approver_scope,
                    "escalation_after_hours": step.escalation_after_hours,
                    "is_required": step.is_required
                })
            
            return {"steps": results}
            
        finally:
            db.close()
            
    except SQLAlchemyError as e:
        log.error(f"Database error in list_approval_chain_steps: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        log.error(f"Unexpected error in list_approval_chain_steps: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")

@app.post("/approvals/v2/requests/{request_id}/approve")
async def approve_request(request_id: str, approval: ApproveRequest = Body(...)):
    """Approve or deny an approval request"""
    try:
        db = SessionLocal()
        try:
            # Get the approval request
            approval_request = db.query(ApprovalRequest).filter(
                ApprovalRequest.request_id == uuid.UUID(request_id)
            ).first()
            
            if not approval_request:
                raise HTTPException(status_code=404, detail=f"Approval request not found: {request_id}")
            
            if approval_request.request_status != 'pending':
                raise HTTPException(status_code=400, detail=f"Request is no longer pending (status: {approval_request.request_status})")
            
            # Update request status based on approval
            if approval.approved:
                approval_request.request_status = 'approved'
                approval_request.completed_date = datetime.now(timezone.utc)
            else:
                approval_request.request_status = 'denied'
                approval_request.completed_date = datetime.now(timezone.utc)
            
            approval_request.updated_at = datetime.now(timezone.utc)
            
            # Publish APPROVAL_RESOLVED event
            try:
                await publish_event("APPROVAL_RESOLVED", {
                        "request_id": request_id,
                    "request_type": approval_request.request_type,
                    "final_status": approval_request.request_status,
                    "approved": approval.approved,
                    "approver_user_id": approval.approver_user_id,
                    "amount_minor": approval_request.total_amount_minor,
                    "currency": approval_request.currency,
                    "completed_date": approval_request.completed_date.isoformat() if approval_request.completed_date else None
                }, db)
            except EventPublishingError as e:
                    log.warning(f"Failed to publish APPROVAL_RESOLVED event: {str(e)}")
            
            # Update budget if approved
            if approval.approved and approval_request.total_amount_minor:
                try:
                    await update_budget_on_approval(
                        request_id, 
                        approval.approved, 
                        approval_request.total_amount_minor, 
                        db
                    )
                except Exception as e:
                    log.warning(f"Failed to update budget: {str(e)}")
            
            db.commit()
            
            log.info(f"Request {request_id} {'approved' if approval.approved else 'denied'} by {approval.approver_user_id}")
            
            return {
                "request_id": request_id,
                "status": approval_request.request_status,
                "approved": approval.approved,
                "approver_user_id": approval.approver_user_id,
                "notes": approval.notes,
                "completed_date": approval_request.completed_date.isoformat(),
                "message": f"Request {'approved' if approval.approved else 'denied'} successfully with event publishing"
            }
            
        finally:
            db.close()
            
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        log.error(f"Database error in approve_request: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        log.error(f"Unexpected error in approve_request: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")

@app.get("/approvals/v2/requests/{request_id}")
async def get_approval_request(request_id: str):
    """Get details of a specific approval request"""
    try:
        db = SessionLocal()
        try:
            approval_request = db.query(ApprovalRequest).filter(
                ApprovalRequest.request_id == uuid.UUID(request_id)
            ).first()
            
            if not approval_request:
                raise HTTPException(status_code=404, detail=f"Approval request not found: {request_id}")
            
            return {
                "request_id": str(approval_request.request_id),
                "request_number": approval_request.request_number,
                "request_type": approval_request.request_type,
                "requested_by": str(approval_request.requested_by),
                "chain_id": str(approval_request.chain_id),
                "request_data": json.loads(approval_request.request_data) if approval_request.request_data and isinstance(approval_request.request_data, str) else (approval_request.request_data if approval_request.request_data else {}),
                "total_amount_minor": approval_request.total_amount_minor,
                "currency": approval_request.currency,
                "request_status": approval_request.request_status,
                "due_date": approval_request.due_date.isoformat() if approval_request.due_date else None,
                "completed_date": approval_request.completed_date.isoformat() if approval_request.completed_date else None,
                "created_at": approval_request.created_at.isoformat(),
                "updated_at": approval_request.updated_at.isoformat() if approval_request.updated_at else None
            }
            
        finally:
            db.close()
            
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        log.error(f"Database error in get_approval_request: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        log.error(f"Unexpected error in get_approval_request: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")

# New Endpoints for Approver Management

@app.get("/approvals/v2/requests/{request_id}/approvers")
async def get_request_approvers(request_id: str):
    """Get all approvers for a specific approval request"""
    try:
        validate_uuid(request_id)
        
        db = SessionLocal()
        try:
            approvers = db.query(ApprovalRequestApprover).filter(
                ApprovalRequestApprover.request_id == uuid.UUID(request_id)
            ).order_by(ApprovalRequestApprover.step_number, ApprovalRequestApprover.created_at).all()
            
            results = []
            for approver in approvers:
                results.append(ApprovalRequestApproverResponse(
                    id=str(approver.id),
                    request_id=str(approver.request_id),
                    approver_user_id=str(approver.approver_user_id),
                    approver_role=approver.approver_role,
                    step_number=approver.step_number,
                    status=approver.status,
                    notes=approver.notes,
                    responded_at=approver.responded_at,
                    escalation_sent=approver.escalation_sent,
                    created_at=approver.created_at,
                    updated_at=approver.updated_at
                ))
            
            return {
                "request_id": request_id,
                "approvers": results,
                "total": len(results)
            }
            
        finally:
            db.close()
            
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {str(e)}")
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")

@app.post("/approvals/v2/requests/{request_id}/respond")
async def respond_to_request(request_id: str, response: RespondToRequestRequest):
    """Respond to an approval request with proper workflow validation"""
    try:
        validate_uuid(request_id)
        validate_uuid(response.approver_user_id)
        
        db = SessionLocal()
        try:
            # Get the approval request
            approval_request = db.query(ApprovalRequest).filter(
                ApprovalRequest.request_id == uuid.UUID(request_id)
            ).first()
            
            if not approval_request:
                raise HTTPException(status_code=404, detail="Approval request not found")
            
            if approval_request.request_status not in ['pending']:
                raise HTTPException(status_code=400, detail="Request is not in pending status")
            
            # Get the specific approver record
            approver = db.query(ApprovalRequestApprover).filter(
                ApprovalRequestApprover.request_id == uuid.UUID(request_id),
                ApprovalRequestApprover.approver_user_id == uuid.UUID(response.approver_user_id),
                ApprovalRequestApprover.step_number == response.step_number
            ).first()
            
            if not approver:
                raise HTTPException(status_code=404, detail="Approver assignment not found")
            
            if approver.status != 'pending':
                raise HTTPException(status_code=400, detail="Approver has already responded")
            
            # Update approver response
            approver.status = 'approved' if response.approved else 'denied'
            approver.notes = response.notes
            approver.responded_at = datetime.now(timezone.utc)
            
            # Check if this step is complete
            step_approvers = db.query(ApprovalRequestApprover).filter(
                ApprovalRequestApprover.request_id == uuid.UUID(request_id),
                ApprovalRequestApprover.step_number == response.step_number
            ).all()
            
            # Get chain step to check required approvals
            chain_step = db.query(ApprovalChainStep).filter(
                ApprovalChainStep.chain_id == approval_request.chain_id,
                ApprovalChainStep.step_number == response.step_number
            ).first()
            
            required_approvals = chain_step.required_approvals if chain_step else 1
            approved_count = sum(1 for a in step_approvers if a.status == 'approved')
            denied_count = sum(1 for a in step_approvers if a.status == 'denied')
            
            # Update request status based on step completion
            if denied_count > 0:
                # Any denial fails the request
                approval_request.request_status = 'denied'
                approval_request.completed_date = datetime.now(timezone.utc)
            elif approved_count >= required_approvals:
                # Check if this is the last step
                max_step = db.query(func.max(ApprovalChainStep.step_number)).filter(
                    ApprovalChainStep.chain_id == approval_request.chain_id
                ).scalar()
                
                if response.step_number >= max_step:
                    # Last step completed
                    approval_request.request_status = 'approved'
                    approval_request.completed_date = datetime.now(timezone.utc)
                    
                    # Update budget if approved
                    await update_budget_on_approval(approval_request)
                    
                    # Publish APPROVAL_RESOLVED event
                    await publish_event("APPROVAL_RESOLVED", {
                        "request_id": request_id,
                        "request_type": approval_request.request_type,
                        "status": "approved",
                        "resolved_at": datetime.now(timezone.utc).isoformat()
                    }, db)
                else:
                    # Move to next step
                    approval_request.current_step_number = response.step_number + 1
            
            db.commit()
            
            return {
                "request_id": request_id,
                "approver_user_id": response.approver_user_id,
                "step_number": response.step_number,
                "status": approver.status,
                "notes": approver.notes,
                "responded_at": approver.responded_at.isoformat(),
                "request_status": approval_request.request_status,
                "message": "Response recorded successfully"
            }
            
        finally:
            db.close()
            
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {str(e)}")
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")

# Phase 3: Event Management Endpoints

@app.post("/approvals/v2/events/retry")
async def retry_failed_events():
    """Retry failed event publishing"""
    try:
        db = SessionLocal()
        try:
            # Get pending events that haven't exceeded max retries
            pending_events = db.query(OutboxEvent).filter(
                OutboxEvent.status == 'pending',
                OutboxEvent.retry_count < OutboxEvent.max_retries
            ).all()
            
            retried_count = 0
            for event in pending_events:
                try:
                    event_data = json.loads(event.event_data)
                    
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        response = await client.post(
                            f"{EVENT_BUS_URL}/publish",
                            json={
                                "event_id": str(event.event_id),
                                "event_type": event.event_type,
                                "event_data": event_data,
                                "source": "approvals-service",
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            }
                        )
                        
                        if response.status_code == 200:
                            event.status = 'published'
                            event.processed_at = datetime.now(timezone.utc)
                            retried_count += 1
                            log.info(f"Retried event successfully: {event.event_type} - {event.event_id}")
                        else:
                            event.retry_count += 1
                            log.warning(f"Retry failed for event: {event.event_type} - {event.event_id}")
                            
                except Exception as e:
                    event.retry_count += 1
                    log.error(f"Failed to retry event {event.event_id}: {str(e)}")
            
            db.commit()
            
            return {
                "message": f"Retried {retried_count} events",
                "total_pending": len(pending_events),
                "successful_retries": retried_count
            }
            
        finally:
            db.close()
            
    except Exception as e:
        log.error(f"Failed to retry events: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to retry events: {str(e)}")

@app.get("/approvals/v2/events/status")
async def get_event_status():
    """Get event publishing status"""
    try:
        db = SessionLocal()
        try:
            total_events = db.query(OutboxEvent).count()
            published_events = db.query(OutboxEvent).filter(
                OutboxEvent.status == 'published'
            ).count()
            pending_events = db.query(OutboxEvent).filter(
                OutboxEvent.status == 'pending'
            ).count()
            failed_events = db.query(OutboxEvent).filter(
                OutboxEvent.retry_count >= OutboxEvent.max_retries
            ).count()
            
            return {
                "total_events": total_events,
                "published_events": published_events,
                "pending_events": pending_events,
                "failed_events": failed_events,
                "success_rate": (published_events / total_events * 100) if total_events > 0 else 0
            }
            
        finally:
            db.close()
            
    except Exception as e:
        log.error(f"Failed to get event status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get event status: {str(e)}")

# Phase 4: Security Endpoints

@app.get("/approvals/v2/security/audit-logs")
async def get_audit_logs(
    user_context: UserContext = Depends(get_user_context),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    action: Optional[str] = Query(None, description="Filter by action"),
    limit: int = Query(50, description="Number of logs to return", le=100),
    offset: int = Query(0, description="Number of logs to skip", ge=0)
):
    """Get audit logs with security filtering"""
    try:
        # Check permissions
        if not check_permission(user_context, "audit.view"):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        db = SessionLocal()
        try:
            # Set RLS context
            set_rls_context(user_context, db)
            
            # Build query with user isolation (since existing table doesn't have tenant_id)
            query = db.query(AuditLog).filter(
                AuditLog.changed_by == uuid.UUID(user_context.user_id)
            )
            
            if resource_type:
                query = query.filter(AuditLog.table_name == resource_type)
            if action:
                # Map action to operation for filtering
                operation_map = {
                    "create_approval_request": "INSERT",
                    "approve_request": "UPDATE", 
                    "validate_permission": "INSERT",
                    "view_audit_logs": "INSERT"
                }
                operation = operation_map.get(action, "INSERT")
                query = query.filter(AuditLog.operation == operation)
            
            # Get total count
            total_count = query.count()
            
            # Get paginated results
            audit_logs = query.order_by(AuditLog.changed_at.desc()).offset(offset).limit(limit).all()
            
            results = []
            for log_entry in audit_logs:
                # Parse new_values to extract audit data
                audit_data = {}
                if log_entry.new_values:
                    try:
                        audit_data = json.loads(log_entry.new_values)
                    except:
                        pass
                
                results.append({
                    "log_id": str(log_entry.log_id),
                    "user_id": str(log_entry.changed_by),
                    "action": log_entry.operation,
                    "resource_type": log_entry.table_name,
                    "resource_id": str(log_entry.record_id),
                    "ip_address": log_entry.ip_address,
                    "response_status": audit_data.get("response_status"),
                    "error_message": audit_data.get("error_message"),
                    "timestamp": log_entry.changed_at.isoformat()
                })
            
            return {
                "audit_logs": results,
                "total_count": total_count,
                "limit": limit,
                "offset": offset
            }
            
        finally:
            db.close()
            
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to get audit logs: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get audit logs: {str(e)}")

@app.get("/approvals/v2/security/user-context")
async def get_user_context_info(user_context: UserContext = Depends(get_user_context)):
    """Get current user context information"""
    return {
        "user_id": user_context.user_id,
        "tenant_id": user_context.tenant_id,
        "roles": user_context.roles,
        "permissions": user_context.permissions,
        "site_id": user_context.site_id,
        "store_id": user_context.store_id
    }

@app.post("/approvals/v2/security/validate-permission")
async def validate_permission(
    permission: str = Body(..., embed=True),
    user_context: UserContext = Depends(get_user_context)
):
    """Validate if user has specific permission"""
    has_permission = check_permission(user_context, permission)
    
    await log_audit_event(
        user_context, "validate_permission", "security",
        request_data={"permission": permission},
        response_status=200 if has_permission else 403
    )
    
    return {
        "permission": permission,
        "has_permission": has_permission,
        "user_id": user_context.user_id,
        "roles": user_context.roles
    }

# Main execution
if __name__ == "__main__":
    import uvicorn
    print("Starting Approvals Service V2...")
    uvicorn.run(app, host="0.0.0.0", port=8213)