# services/identity/main.py - ZeroQue Identity Service V4.1
import os
import json
import uuid
import time
import jwt
import httpx
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Request, Query, BackgroundTasks, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text, select, insert, update, delete, Column, String, Integer, Numeric, DateTime, Boolean, Text, ForeignKey, JSON, func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
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
# CONFIGURATION & LOGGING
# =============================================================================

SERVICE_NAME = "identity"
SERVICE_VERSION = "4.1.0"

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zeroque:zeroque@localhost:5432/zeroque_dev")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRY_MINUTES = int(os.getenv("JWT_EXPIRY_MINUTES", "60"))
GUEST_TOKEN_TTL_HOURS = int(os.getenv("GUEST_TOKEN_TTL_HOURS", "24"))
ALLOW_DEMO = os.getenv("ALLOW_DEMO", "true").lower() == "true"
RATE_LIMIT_REQUESTS_PER_MINUTE = 60

"""Synchronous and asynchronous DB setup
We primarily use async sessions below; keep sync engine for utility if needed.
"""
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Async engine/session for endpoints using AsyncSessionLocal
ASYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
async_engine = create_async_engine(ASYNC_DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

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
    pass

# Circuit breaker for external service calls
service_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

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

logger = structlog.get_logger(__name__)

# Prometheus metrics - temporarily disabled to avoid conflicts
# identity_requests_total = Counter('identity_requests_v2', 'Total identity requests', ['endpoint', 'status'])
# identity_request_duration = Histogram('identity_request_duration_seconds_v2', 'Identity request duration', ['endpoint'])
# identity_tokens_generated = Counter('identity_tokens_generated_v2', 'Total tokens generated', ['token_type', 'tenant_id'])
# identity_saga_duration = Histogram('identity_saga_duration_seconds_v2', 'Identity saga duration', ['saga_type'])
# identity_saga_failures = Counter('identity_saga_failures_v2', 'Identity saga failures', ['saga_type', 'reason'])

# Dummy metrics to avoid NameError
identity_requests_total = None
identity_request_duration = None
identity_tokens_generated = None
identity_saga_duration = None
identity_saga_failures = None

# Helper functions for safe metric calls
def safe_metric_call(metric, method, *args, **kwargs):
    """Safely call metric methods if metric is available"""
    if metric is not None and hasattr(metric, method):
        getattr(metric, method)(*args, **kwargs)

# =============================================================================
# DATABASE CONNECTION (ASYNC)
# =============================================================================

def get_engine():
    return engine

def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)

def check_db():
    """Check database connectivity"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False

# =============================================================================
# DATABASE MODELS
# =============================================================================

class Base(DeclarativeBase):
    pass

class UserNew(Base):
    __tablename__ = 'users_new'
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    email: Mapped[str] = mapped_column(nullable=False)
    name: Mapped[Optional[str]] = mapped_column(nullable=True)
    primary_cost_centre_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    user_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

class RoleNew(Base):
    __tablename__ = 'roles_new'
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[Optional[str]] = mapped_column(nullable=True)
    permissions: Mapped[List[str]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

class RoleAssignmentNew(Base):
    __tablename__ = 'role_assignments_new'
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

class OutboxEvent(Base):
    __tablename__ = 'outbox_events'
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(nullable=False)
    event_data: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(default='pending')
    retry_count: Mapped[int] = mapped_column(default=0)
    max_retries: Mapped[int] = mapped_column(default=3)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

class AuditLog(Base):
    __tablename__ = 'audit_logs'
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(nullable=False)
    resource_type: Mapped[str] = mapped_column(nullable=False)
    resource_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class UserCreateRequest(BaseModel):
    tenant_id: str
    email: str
    name: Optional[str] = None
    primary_cost_centre_id: Optional[str] = None
    role_ids: List[str] = Field(default=[], description="List of role IDs to assign")
    user_metadata: Optional[Dict[str, Any]] = None

class UserUpdateRequest(BaseModel):
    name: Optional[str] = None
    primary_cost_centre_id: Optional[str] = None
    user_metadata: Optional[Dict[str, Any]] = None

class RoleCreateRequest(BaseModel):
    tenant_id: str
    name: str
    description: Optional[str] = None
    permissions: List[str] = Field(description="List of permission strings")

class RoleUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permissions: Optional[List[str]] = None

class RoleAssignmentRequest(BaseModel):
    tenant_id: str
    user_id: str
    role_id: str

class TokenRequest(BaseModel):
    tenant_id: str
    token_type: str = Field(description="'guest' or 'loyalty'")
    user_id: Optional[str] = Field(default=None, description="Required for loyalty tokens")
    guest_info: Optional[Dict[str, Any]] = Field(default=None, description="Guest-specific information")

class ReportRequest(BaseModel):
    tenant_id: str
    report_type: str = Field(description="'users', 'roles', 'active_users', 'role_counts'")
    period_start: Optional[str] = Field(default=None, description="ISO date string")
    period_end: Optional[str] = Field(default=None, description="ISO date string")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Additional filters")

class UserResponse(BaseModel):
    id: str
    tenant_id: str
    email: str
    name: Optional[str]
    primary_cost_centre_id: Optional[str]
    metadata: Optional[Dict[str, Any]]
    created_at: str
    updated_at: Optional[str]
    roles: List[Dict[str, Any]] = Field(default=[], description="Assigned roles")

class RoleResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: Optional[str]
    permissions: List[str]
    created_at: str
    updated_at: Optional[str]
    user_count: int = Field(default=0, description="Number of users with this role")

class TokenResponse(BaseModel):
    token: str
    token_type: str
    expires_at: str
    user_id: Optional[str] = None
    permissions: List[str] = Field(default=[])

class ReportResponse(BaseModel):
    report_type: str
    tenant_id: str
    generated_at: str
    period: Optional[Dict[str, str]]
    summary: Dict[str, Any]
    data: List[Dict[str, Any]]

# =============================================================================
# AUTHENTICATION & SECURITY
# =============================================================================

security = HTTPBearer()

async def get_user_context(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    """Get user context from JWT token"""
    try:
        # In production, this would validate the JWT token
        # For now, return demo context
        return {
            "user_id": "550e8400-e29b-41d4-a716-446655440000",
            "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
            "roles": ["identity.admin"],
            "permissions": ["identity.create_user", "identity.view_user", "identity.admin"]
        }
    except Exception as e:
        logger.error(f"Failed to get user context: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid authentication")

def check_permission(required_permission: str, user_context: Dict[str, Any]) -> bool:
    """Check if user has required permission"""
    user_permissions = user_context.get("permissions", [])
    return required_permission in user_permissions

def set_rls_context(db, tenant_id: str, user_id: Optional[str] = None):
    """Set Row Level Security context (sync sessions)"""
    try:
        db.execute(text("SET app.tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        if user_id:
            db.execute(text("SET app.user_id = :user_id"), {"user_id": user_id})
        db.commit()
    except Exception as e:
        logger.error(f"Failed to set RLS context: {str(e)}")
        raise

async def set_rls_context_async(db: AsyncSession, tenant_id: str, user_id: Optional[str] = None):
    """Set Row Level Security context (async sessions)"""
    try:
        await db.execute(text("SET app.tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        if user_id:
            await db.execute(text("SET app.user_id = :user_id"), {"user_id": user_id})
        await db.commit()
    except Exception as e:
        logger.error(f"Failed to set RLS context: {str(e)}")

# Rate limiting with Redis (production-ready)
async def check_rate_limit(user_id: str) -> bool:
    """Check if user has exceeded rate limit using Redis"""
    global redis_client

    if redis_client is None:
        return True  # Allow if Redis not available

    current_time = datetime.now()
    minute_key = current_time.replace(second=0, microsecond=0)

    try:
        # Use Redis pipeline for atomic operations
        pipe = redis_client.pipeline()

        # Clean old entries (older than 1 minute)
        cutoff_time = minute_key - timedelta(minutes=1)
        cutoff_key = cutoff_time.strftime("%Y%m%d%H%M")

        # Get current count
        current_key = f"identity_rate_limit:{user_id}:{minute_key.strftime('%Y%m%d%H%M')}"
        pipe.incr(current_key)
        pipe.expire(current_key, 60)  # Expire after 60 seconds

        results = pipe.execute()
        current_count = results[-2]  # The INCR result

        if current_count > RATE_LIMIT_REQUESTS_PER_MINUTE:
            return False

        return True

    except Exception as e:
        logger.warning(f"Redis rate limit check failed, allowing request: {e}")
        return True  # Fail open for rate limiting

# RabbitMQ Publishing
def publish_to_rabbitmq(event_type: str, event_data: Dict[str, Any], tenant_id: str) -> bool:
    """Publish event directly to RabbitMQ"""
    try:
        connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
        channel = connection.channel()
        channel.exchange_declare(exchange='zeroque_events', exchange_type='topic', durable=True)
        message = json.dumps({
            "event_type": event_type,
            "tenant_id": tenant_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": event_data
        })
        channel.basic_publish(
            exchange='zeroque_events',
            routing_key=event_type,
            body=message,
            properties=pika.BasicProperties(delivery_mode=2)
        )
        connection.close()
        logger.info(f"Published {event_type} to RabbitMQ")
        return True
    except Exception as e:
        logger.error(f"RabbitMQ publish failed: {e}")
        return False

# Event consumption workers (if needed for this service)
# The Identity service primarily manages users and authentication, so event consumption may not be needed

# =============================================================================
# SAGA PATTERN
# =============================================================================

class UserCreationSaga:
    """Saga for user creation operations with compensation"""
    
    def __init__(self, db):
        self.db = db
        self.compensation_steps = []
    
    def execute_create_user(self, payload: UserCreateRequest, user_context: Dict[str, Any]) -> UserResponse:
        """Execute user creation saga"""
        saga_start = time.time()
        
        try:
            # Step 1: Validate tenant exists
            self._validate_tenant(payload.tenant_id)
            self.compensation_steps.append(("validate_tenant", None))
            
            # Step 2: Create user
            user = self._create_user(payload, user_context)
            self.compensation_steps.append(("create_user", user.id))
            
            # Step 3: Assign roles
            roles = self._assign_roles(user.id, payload.role_ids, payload.tenant_id, user_context)
            self.compensation_steps.append(("assign_roles", {"user_id": user.id, "role_ids": payload.role_ids}))
            
            # Step 4: Publish USER_CREATED event
            self._publish_user_created_event(user, roles, user_context)
            self.compensation_steps.append(("publish_event", None))
            
            # Step 5: Audit log
            self._audit_log("CREATE_USER", payload, user_context)
            
            # Metrics temporarily disabled
            pass
            
            return user
            
        except Exception as e:
            logger.error(f"User creation saga failed: {str(e)}")
            # Metrics temporarily disabled
            pass
            self._compensate()
            raise
    
    def _validate_tenant(self, tenant_id: str):
        """Validate tenant exists"""
        query = text("SELECT tenant_id FROM tenants WHERE tenant_id = :tenant_id")
        result = self.db.execute(query, {"tenant_id": tenant_id})
        if not result.first():
            raise HTTPException(status_code=400, detail="Tenant not found")
    
    def _create_user(self, payload: UserCreateRequest, user_context: Dict[str, Any]) -> UserNew:
        """Create user in database"""
        user = UserNew(
            tenant_id=uuid.UUID(payload.tenant_id),
            email=payload.email,
            name=payload.name,
            primary_cost_centre_id=uuid.UUID(payload.primary_cost_centre_id) if payload.primary_cost_centre_id else None,
            user_metadata=payload.user_metadata
        )
        
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        
        return user
    
    def _assign_roles(self, user_id: uuid.UUID, role_ids: List[str], tenant_id: str, user_context: Dict[str, Any]) -> List[RoleNew]:
        """Assign roles to user"""
        roles = []
        for role_id in role_ids:
            # Verify role exists and belongs to tenant
            role_query = text("""
                SELECT id, name, description, permissions FROM roles_new
                WHERE id = :role_id AND tenant_id = :tenant_id
            """)
            result = self.db.execute(role_query, {"role_id": role_id, "tenant_id": tenant_id})
            role_row = result.first()
            
            if not role_row:
                raise HTTPException(status_code=400, detail=f"Role {role_id} not found")
            
            # Create role assignment
            assignment = RoleAssignmentNew(
                tenant_id=uuid.UUID(tenant_id),
                user_id=user_id,
                role_id=uuid.UUID(role_id)
            )
            
            self.db.add(assignment)
            roles.append(role_row)
        
        self.db.commit()
        return roles
    
    async def _publish_user_created_event(self, user: UserNew, roles: List[Any], user_context: Dict[str, Any]):
        """Publish USER_CREATED event"""
        event_data = {
            "user_id": str(user.id),
            "tenant_id": str(user.tenant_id),
            "email": user.email,
            "name": user.name,
            "roles": [{"id": str(role[0]), "name": role[1], "permissions": role[3]} for role in roles],
            "created_at": user.created_at.isoformat()
        }
        
        # Store in outbox for reliable delivery
        outbox_event = OutboxEvent(
            tenant_id=user.tenant_id,
            event_type="USER_CREATED",
            event_data=event_data
        )
        
        self.db.add(outbox_event)
        await self.db.commit()
    
    async def _audit_log(self, action: str, payload: Any, user_context: Dict[str, Any]):
        """Create audit log entry"""
        audit_log = AuditLog(
            tenant_id=uuid.UUID(user_context["tenant_id"]),
            user_id=uuid.UUID(user_context["user_id"]),
            action=action,
            resource_type="user",
            resource_id=getattr(payload, 'email', str(uuid.uuid4())),
            details=payload.dict() if hasattr(payload, 'dict') else {}
        )
        
        self.db.add(audit_log)
        await self.db.commit()
    
    async def _compensate(self):
        """Execute compensation steps in reverse order"""
        for step_name, step_data in reversed(self.compensation_steps):
            try:
                if step_name == "assign_roles" and step_data:
                    # Remove role assignments
                    delete_query = text("DELETE FROM role_assignments_new WHERE user_id = :user_id")
                    await self.db.execute(delete_query, {"user_id": step_data["user_id"]})
                    await self.db.commit()
                
                elif step_name == "create_user" and step_data:
                    # Delete user
                    delete_query = text("DELETE FROM users_new WHERE id = :id")
                    await self.db.execute(delete_query, {"id": step_data})
                    await self.db.commit()
                
                # Add more compensation steps as needed
                
            except Exception as e:
                logger.error(f"Compensation step {step_name} failed: {str(e)}")

# =============================================================================
# JWT TOKEN MANAGEMENT
# =============================================================================

def generate_jwt_token(user_id: str, tenant_id: str, permissions: List[str], token_type: str = "loyalty") -> str:
    """Generate JWT token"""
    now = datetime.utcnow()
    expiry = now + timedelta(minutes=JWT_EXPIRY_MINUTES)
    
    payload = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "permissions": permissions,
        "token_type": token_type,
        "iat": now,
        "exp": expiry
    }
    
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def generate_guest_token(tenant_id: str, guest_info: Optional[Dict[str, Any]] = None) -> str:
    """Generate guest JWT token"""
    now = datetime.utcnow()
    expiry = now + timedelta(hours=GUEST_TOKEN_TTL_HOURS)
    
    payload = {
        "tenant_id": tenant_id,
        "permissions": ["guest.access"],
        "token_type": "guest",
        "guest_info": guest_info or {},
        "iat": now,
        "exp": expiry
    }
    
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Identity Service V4.1")
    init_db()  # Remove await since init_db is synchronous
    
    yield
    
    # Shutdown
    logger.info("Shutting down Identity Service V4.1")

app = FastAPI(
    title="ZeroQue Identity Service V4.1",
    version="4.1.0"
    # lifespan=lifespan  # Temporarily disabled for debugging
)

# Production Middleware - Restrict CORS origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8501",  # Streamlit apps
        "http://localhost:8502",
        "http://localhost:8503",
        "http://localhost:8510",
        "https://*.zeroque.com"
    ] if ENVIRONMENT == "development" else ["https://*.zeroque.com", "https://zeroque.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

if ENVIRONMENT == "production":
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*.zeroque.com", "zeroque.com"])
else:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

# =============================================================================
# HEALTH CHECKS
# =============================================================================

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok", "service": SERVICE_NAME, "version": "4.1.0"}

@app.get("/readiness")
async def readiness():
    """Readiness check endpoint"""
    db_ok = check_db()
    
    return {
        "service": SERVICE_NAME,
        "version": "4.1.0",
        "db": db_ok,
        "ready": db_ok
    }

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return generate_latest()

# =============================================================================
# V4.1 ENDPOINTS
# =============================================================================

@app.post("/identity/v4/users", response_model=UserResponse)
async def create_user(
    payload: UserCreateRequest,
    request: Request,
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Create user with role assignments"""
    start_time = time.time()
    
    try:
        # Check permissions
        if not check_permission("identity.create_user", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        # Execute saga
        async with AsyncSessionLocal() as db:
            await set_rls_context_async(db, payload.tenant_id, user_context["user_id"])
            saga = UserCreationSaga(db)
            user = await saga.execute_create_user(payload, user_context)
        
        # Get user with roles
        async with AsyncSessionLocal() as db:
            await set_rls_context_async(db, payload.tenant_id, user_context["user_id"])
            
            # Get user roles
            roles_query = text("""
                SELECT r.id, r.name, r.description, r.permissions
                FROM roles_new r
                JOIN role_assignments_new ra ON r.id = ra.role_id
                WHERE ra.user_id = :user_id AND ra.tenant_id = :tenant_id
            """)
            
            result = await db.execute(roles_query, {"user_id": user.id, "tenant_id": payload.tenant_id})
            roles = []
            for row in result:
                roles.append({
                    "id": str(row[0]),
                    "name": row[1],
                    "description": row[2],
                    "permissions": row[3]
                })
        
        pass  # Metrics disabled - start_time)
        
        return UserResponse(
            id=str(user.id),
            tenant_id=str(user.tenant_id),
            email=user.email,
            name=user.name,
            primary_cost_centre_id=str(user.primary_cost_centre_id) if user.primary_cost_centre_id else None,
            user_metadata=user.user_metadata,
            created_at=user.created_at.isoformat(),
            updated_at=user.updated_at.isoformat() if user.updated_at else None,
            roles=roles
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create user: {str(e)}")
        pass  # Metrics disabled
        pass  # Metrics disabled - start_time)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/identity/v4/users", response_model=List[UserResponse])
async def list_users(
    tenant_id: str = Query(...),
    email_filter: Optional[str] = Query(None),
    role_filter: Optional[str] = Query(None),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """List users with optional filters"""
    start_time = time.time()
    
    try:
        # Check permissions
        if not check_permission("identity.view_user", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        async with AsyncSessionLocal() as db:
            await set_rls_context_async(db, tenant_id, user_context["user_id"])
            
            # Build query with filters
            query = text("""
                SELECT DISTINCT u.id, u.tenant_id, u.email, u.name, u.primary_cost_centre_id, 
                       u.metadata, u.created_at, u.updated_at
                FROM users_new u
                LEFT JOIN role_assignments_new ra ON u.id = ra.user_id
                LEFT JOIN roles_new r ON ra.role_id = r.id
                WHERE u.tenant_id = :tenant_id
            """)
            
            params = {"tenant_id": tenant_id}
            
            if email_filter:
                query = text(str(query) + " AND u.email ILIKE :email_filter")
                params["email_filter"] = f"%{email_filter}%"
            
            if role_filter:
                query = text(str(query) + " AND r.name = :role_filter")
                params["role_filter"] = role_filter
            
            query = text(str(query) + " ORDER BY u.created_at DESC")
            
            result = await db.execute(query, params)
            users = []
            
            for row in result:
                # Get roles for each user
                roles_query = text("""
                    SELECT r.id, r.name, r.description, r.permissions
                    FROM roles_new r
                    JOIN role_assignments_new ra ON r.id = ra.role_id
                    WHERE ra.user_id = :user_id AND ra.tenant_id = :tenant_id
                """)
                
                roles_result = await db.execute(roles_query, {"user_id": row[0], "tenant_id": tenant_id})
                roles = []
                for role_row in roles_result:
                    roles.append({
                        "id": str(role_row[0]),
                        "name": role_row[1],
                        "description": role_row[2],
                        "permissions": role_row[3]
                    })
                
                users.append(UserResponse(
                    id=str(row[0]),
                    tenant_id=str(row[1]),
                    email=row[2],
                    name=row[3],
                    primary_cost_centre_id=str(row[4]) if row[4] else None,
                    user_metadata=row[5],
                    created_at=row[6].isoformat(),
                    updated_at=row[7].isoformat() if row[7] else None,
                    roles=roles
                ))
        
        pass  # Metrics disabled - start_time)
        
        return users
        
    except Exception as e:
        logger.error(f"Failed to list users: {str(e)}")
        pass  # Metrics disabled
        pass  # Metrics disabled - start_time)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/identity/v4/roles", response_model=RoleResponse)
async def create_role(
    payload: RoleCreateRequest,
    request: Request,
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Create role with permissions"""
    start_time = time.time()
    
    try:
        # Check permissions
        if not check_permission("identity.admin", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        async with AsyncSessionLocal() as db:
            await set_rls_context_async(db, payload.tenant_id, user_context["user_id"])
            
            # Create role
            role = RoleNew(
                tenant_id=uuid.UUID(payload.tenant_id),
                name=payload.name,
                description=payload.description,
                permissions=payload.permissions
            )
            
            db.add(role)
            await db.commit()
            await db.refresh(role)
            
            # Audit log
            audit_log = AuditLog(
                tenant_id=uuid.UUID(payload.tenant_id),
                user_id=uuid.UUID(user_context["user_id"]),
                action="CREATE_ROLE",
                resource_type="role",
                resource_id=payload.name,
                details=payload.dict()
            )
            db.add(audit_log)
            await db.commit()
        
        pass  # Metrics disabled - start_time)
        pass  # Metrics disabled
        
        return RoleResponse(
            id=str(role.id),
            tenant_id=str(role.tenant_id),
            name=role.name,
            description=role.description,
            permissions=role.permissions,
            created_at=role.created_at.isoformat(),
            updated_at=role.updated_at.isoformat() if role.updated_at else None,
            user_count=0
        )
        
    except Exception as e:
        logger.error(f"Failed to create role: {str(e)}")
        pass  # Metrics disabled
        pass  # Metrics disabled - start_time)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/identity/v4/roles", response_model=List[RoleResponse])
async def list_roles(
    tenant_id: str = Query(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """List roles for tenant"""
    start_time = time.time()
    
    try:
        # Check permissions
        if not check_permission("identity.view_role", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        async with AsyncSessionLocal() as db:
            await set_rls_context_async(db, tenant_id, user_context["user_id"])
            
            query = text("""
                SELECT r.id, r.tenant_id, r.name, r.description, r.permissions, r.created_at, r.updated_at,
                       COUNT(ra.user_id) as user_count
                FROM roles_new r
                LEFT JOIN role_assignments_new ra ON r.id = ra.role_id
                WHERE r.tenant_id = :tenant_id
                GROUP BY r.id, r.tenant_id, r.name, r.description, r.permissions, r.created_at, r.updated_at
                ORDER BY r.created_at DESC
            """)
            
            result = await db.execute(query, {"tenant_id": tenant_id})
            roles = []
            
            for row in result:
                roles.append(RoleResponse(
                    id=str(row[0]),
                    tenant_id=str(row[1]),
                    name=row[2],
                    description=row[3],
                    permissions=row[4],
                    created_at=row[5].isoformat(),
                    updated_at=row[6].isoformat() if row[6] else None,
                    user_count=row[7]
                ))
        
        pass  # Metrics disabled - start_time)
        
        return roles
        
    except Exception as e:
        logger.error(f"Failed to list roles: {str(e)}")
        pass  # Metrics disabled
        pass  # Metrics disabled - start_time)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/identity/v4/role-assignments")
async def assign_role(
    payload: RoleAssignmentRequest,
    request: Request,
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Assign role to user"""
    start_time = time.time()
    
    try:
        # Check permissions
        if not check_permission("identity.admin", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        async with AsyncSessionLocal() as db:
            await set_rls_context(db, payload.tenant_id, user_context["user_id"])
            
            # Create role assignment
            assignment = RoleAssignmentNew(
                tenant_id=uuid.UUID(payload.tenant_id),
                user_id=uuid.UUID(payload.user_id),
                role_id=uuid.UUID(payload.role_id)
            )
            
            db.add(assignment)
            await db.commit()
            
            # Audit log
            audit_log = AuditLog(
                tenant_id=uuid.UUID(payload.tenant_id),
                user_id=uuid.UUID(user_context["user_id"]),
                action="ASSIGN_ROLE",
                resource_type="role_assignment",
                resource_id=f"{payload.user_id}:{payload.role_id}",
                details=payload.dict()
            )
            db.add(audit_log)
            await db.commit()
        
        pass  # Metrics disabled - start_time)
        pass  # Metrics disabled
        
        return {"ok": True, "message": "Role assigned successfully"}
        
    except Exception as e:
        logger.error(f"Failed to assign role: {str(e)}")
        pass  # Metrics disabled
        pass  # Metrics disabled - start_time)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/identity/v4/token", response_model=TokenResponse)
async def generate_token(
    payload: TokenRequest,
    request: Request,
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Generate JWT token (unified guest/loyalty)"""
    start_time = time.time()
    
    try:
        # Check permissions
        if not check_permission("identity.generate_token", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        if payload.token_type == "guest":
            # Generate guest token
            token = generate_guest_token(payload.tenant_id, payload.guest_info)
            expires_at = datetime.utcnow() + timedelta(hours=GUEST_TOKEN_TTL_HOURS)
            permissions = ["guest.access"]
            user_id = None
            
        elif payload.token_type == "loyalty":
            # Generate loyalty token - validate user exists
            if not payload.user_id:
                raise HTTPException(status_code=400, detail="user_id required for loyalty tokens")
            
            async with AsyncSessionLocal() as db:
                await set_rls_context(db, payload.tenant_id, user_context["user_id"])
                
                # Get user and roles
                user_query = text("""
                    SELECT u.id, r.permissions
                    FROM users_new u
                    LEFT JOIN role_assignments_new ra ON u.id = ra.user_id
                    LEFT JOIN roles_new r ON ra.role_id = r.id
                    WHERE u.id = :user_id AND u.tenant_id = :tenant_id
                """)
                
                result = await db.execute(user_query, {"user_id": payload.user_id, "tenant_id": payload.tenant_id})
                user_data = result.fetchall()
                
                if not user_data:
                    raise HTTPException(status_code=404, detail="User not found")
                
                # Collect all permissions
                all_permissions = []
                for row in user_data:
                    if row[1]:  # permissions
                        all_permissions.extend(row[1])
                
                # Remove duplicates
                permissions = list(set(all_permissions))
                user_id = str(user_data[0][0])
            
            token = generate_jwt_token(user_id, payload.tenant_id, permissions, "loyalty")
            expires_at = datetime.utcnow() + timedelta(minutes=JWT_EXPIRY_MINUTES)
            
        else:
            raise HTTPException(status_code=400, detail="Invalid token_type. Must be 'guest' or 'loyalty'")
        
        pass  # Metrics disabled
        pass  # Metrics disabled - start_time)
        pass  # Metrics disabled
        
        return TokenResponse(
            token=token,
            token_type=payload.token_type,
            expires_at=expires_at.isoformat(),
            user_id=user_id,
            permissions=permissions
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate token: {str(e)}")
        pass  # Metrics disabled
        pass  # Metrics disabled - start_time)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/identity/v4/reports", response_model=ReportResponse)
async def get_reports(
    tenant_id: str = Query(...),
    report_type: str = Query(...),
    period_start: Optional[str] = Query(None),
    period_end: Optional[str] = Query(None),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Get identity reports (blueprint-inspired analytics)"""
    start_time = time.time()
    
    try:
        # Check permissions
        if not check_permission("identity.view_reports", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        async with AsyncSessionLocal() as db:
            await set_rls_context(db, tenant_id, user_context["user_id"])
            
            if report_type == "active_users":
                # Active users report
                query = text("""
                    SELECT 
                        COUNT(*) as total_users,
                        COUNT(CASE WHEN created_at >= CURRENT_DATE - INTERVAL '30 days' THEN 1 END) as new_users_30d,
                        COUNT(CASE WHEN updated_at >= CURRENT_DATE - INTERVAL '7 days' THEN 1 END) as active_users_7d
                    FROM users_new
                    WHERE tenant_id = :tenant_id
                """)
                
                result = await db.execute(query, {"tenant_id": tenant_id})
                row = result.first()
                
                summary = {
                    "total_users": row[0],
                    "new_users_30d": row[1],
                    "active_users_7d": row[2]
                }
                
                data = []
                
            elif report_type == "role_counts":
                # Role counts report
                query = text("""
                    SELECT 
                        r.name,
                        r.description,
                        COUNT(ra.user_id) as user_count,
                        r.permissions
                    FROM roles_new r
                    LEFT JOIN role_assignments_new ra ON r.id = ra.role_id
                    WHERE r.tenant_id = :tenant_id
                    GROUP BY r.id, r.name, r.description, r.permissions
                    ORDER BY user_count DESC
                """)
                
                result = await db.execute(query, {"tenant_id": tenant_id})
                
                summary = {"total_roles": 0, "total_assignments": 0}
                data = []
                
                for row in result:
                    data.append({
                        "role_name": row[0],
                        "description": row[1],
                        "user_count": row[2],
                        "permissions": row[3]
                    })
                    summary["total_roles"] += 1
                    summary["total_assignments"] += row[2]
                
            else:
                raise HTTPException(status_code=400, detail=f"Unsupported report type: {report_type}")
        
        pass  # Metrics disabled - start_time)
        
        return ReportResponse(
            report_type=report_type,
            tenant_id=tenant_id,
            generated_at=datetime.utcnow().isoformat(),
            period={"start": period_start, "end": period_end} if period_start and period_end else None,
            summary=summary,
            data=data
        )
        
    except Exception as e:
        logger.error(f"Failed to get reports: {str(e)}")
        pass  # Metrics disabled
        pass  # Metrics disabled - start_time)
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# LEGACY ENDPOINTS (DEPRECATED)
# =============================================================================

@app.post("/guest-token", deprecated=True)
async def guest_token_legacy(
    tenant_id: str = Query(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Legacy endpoint - redirects to V4"""
    logger.warning(f"Legacy endpoint /guest-token called, redirecting to V4")
    payload = TokenRequest(tenant_id=tenant_id, token_type="guest")
    # Forward to v4 without needing a Request instance
    return await generate_token(payload, None, user_context)

@app.post("/loyalty-token", deprecated=True)
async def loyalty_token_legacy(
    tenant_id: str = Query(...),
    user_id: str = Query(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Legacy endpoint - redirects to V4"""
    logger.warning(f"Legacy endpoint /loyalty-token called, redirecting to V4")
    payload = TokenRequest(tenant_id=tenant_id, token_type="loyalty", user_id=user_id)
    # Forward to v4 without needing a Request instance
    return await generate_token(payload, None, user_context)

# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def cleanup_expired_tokens(self):
    """Clean up expired tokens"""
    try:
        with SessionLocal() as db:
            # Clean up expired tokens
            result = db.execute(text("""
                DELETE FROM identity_tokens_new 
                WHERE expires_at < NOW() AND status = 'active'
            """))
            
            db.commit()
            
            logger.info(f"Cleaned up {result.rowcount} expired tokens")
            
    except Exception as e:
        logger.error(f"Failed to cleanup expired tokens: {e}")
        raise self.retry(exc=e, countdown=300)

@celery_app.task(bind=True, max_retries=3)
def process_token_revocation(self, token_id: str, reason: str):
    """Process token revocation asynchronously"""
    try:
        with SessionLocal() as db:
            # Revoke token
            db.execute(text("""
                UPDATE identity_tokens_new 
                SET status = 'revoked', revoked_at = NOW(), revoked_reason = :reason
                WHERE id = :token_id
            """), {"token_id": token_id, "reason": reason})
            
            db.commit()
            
            logger.info(f"Revoked token {token_id} with reason: {reason}")
            
    except Exception as e:
        logger.error(f"Failed to revoke token {token_id}: {e}")
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def process_guest_token_cleanup(self, tenant_id: str):
    """Process guest token cleanup for a tenant"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)
            
            # Clean up expired guest tokens
            result = db.execute(text("""
                DELETE FROM identity_tokens_new 
                WHERE tenant_id = :tenant_id 
                AND token_type = 'guest' 
                AND expires_at < NOW()
            """), {"tenant_id": tenant_id})
            
            db.commit()
            
            logger.info(f"Cleaned up {result.rowcount} expired guest tokens for tenant {tenant_id}")
            
    except Exception as e:
        logger.error(f"Failed to cleanup guest tokens for tenant {tenant_id}: {e}")
        raise self.retry(exc=e, countdown=60)

# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8219")))
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )