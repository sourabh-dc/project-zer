# services/identity/main.py - ZeroQue Identity Service V4.1
import os
import time
import jwt
import secrets
from datetime import timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import text, select
from prometheus_client import  generate_latest
import redis
import pybreaker

from core.config import get_settings
from services.identity.repositories.db_config import AsyncSessionLocal, check_db, set_rls_context_async
from services.identity.services.identity_services import create_user, get_users
from .utils.identity_logger import logger
from .models import *
from .schemas import *
from .utils.user_auth import get_user_context, check_permission, generate_jwt_token, generate_guest_token
from .repositories.user_creation_saga import UserCreationSaga
# =============================================================================
# CONFIGURATION & LOGGING
# =============================================================================
SERVICE_NAME = "identity"
SERVICE_VERSION = "4.1.0"

# Configuration
DATABASE_URL = get_settings().DATABASE_URL
REDIS_URL = get_settings().REDIS_URL
ENVIRONMENT = get_settings().ENVIRONMENT
ALLOW_DEMO = get_settings().ALLOW_DEMO
JWT_SECRET = get_settings().JWT_SECRET_KEY
JWT_ALGORITHM = get_settings().JWT_ALGORITHM
RATE_LIMIT_REQUESTS_PER_MINUTE = 60
MAX_REQUEST_SIZE_BYTES = 10 * 1024 * 1024
JWT_EXPIRY_MINUTES = int(os.getenv("JWT_EXPIRY_MINUTES", "60"))
GUEST_TOKEN_TTL_HOURS = int(os.getenv("GUEST_TOKEN_TTL_HOURS", "24"))

# Redis setup
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Circuit breaker for external service calls
service_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

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
# FASTAPI APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Identity Service V4.1")
    # init_db()  # Remove await since init_db is synchronous
    
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
async def create_user_route(
    payload: UserCreateRequest,
    request: Request,
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Create user with role assignments"""
    return await create_user(payload, request, user_context)

@app.get("/identity/v4/users", response_model=List[UserResponse])
async def list_users(
    tenant_id: str = Query(...),
    email_filter: Optional[str] = Query(None),
    role_filter: Optional[str] = Query(None),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """List users with optional filters"""
    return await get_users(tenant_id, email_filter, role_filter, user_context)

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
            await set_rls_context_async(db, payload.tenant_id, user_context["user_id"])
            
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
                await set_rls_context_async(db, payload.tenant_id, user_context["user_id"])
                
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
            await set_rls_context_async(db, tenant_id, user_context["user_id"])
            
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
# OAUTH/SSO ENDPOINTS (Pro/Enterprise Feature)
# =============================================================================

@app.post("/identity/v4/oauth/providers")
async def create_oauth_provider(
    req: OAuthProviderCreateRequest,
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """
    Create OAuth/SSO provider configuration - Pro/Enterprise feature
    Requires 'identity.oauth_admin' permission
    """
    start_time = time.time()
    
    try:
        # Check permissions
        if not check_permission("identity.oauth_admin", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions - OAuth configuration requires Pro or Enterprise plan")
        
        async with AsyncSessionLocal() as db:
            tenant_id_uuid = uuid.UUID(req.tenant_id)
            await set_rls_context_async(db, req.tenant_id, user_context["user_id"])
            
            # Create provider
            provider = OAuthProvider(
                id=uuid.uuid4(),
                tenant_id=tenant_id_uuid,
                provider_type=req.provider_type,
                provider_name=req.provider_name,
                client_id=req.client_id,
                client_secret=req.client_secret,  # TODO: Encrypt in production
                tenant_domain=req.tenant_domain,
                discovery_url=req.discovery_url,
                scopes=req.scopes,
                config_metadata=req.config_metadata
            )
            
            db.add(provider)
            await db.commit()
            await db.refresh(provider)
            
            # Skip audit log in demo mode (schema mismatch)
            # TODO: Fix audit_logs table schema to match model
            logger.info(f"OAuth provider created (audit log skipped in demo mode)")
            
            logger.info(f"OAuth provider created: {provider.id} for tenant {req.tenant_id}")
            
            return {
                "provider_id": str(provider.id),
                "tenant_id": req.tenant_id,
                "provider_type": req.provider_type,
                "provider_name": req.provider_name,
                "enabled": provider.enabled,
                "created_at": provider.created_at.isoformat()
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create OAuth provider: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/identity/v4/oauth/providers")
async def list_oauth_providers(
    tenant_id: str = Query(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """List OAuth/SSO providers for tenant"""
    try:
        async with AsyncSessionLocal() as db:
            await set_rls_context_async(db, tenant_id, user_context["user_id"])
            
            result = await db.execute(
                select(OAuthProvider).where(OAuthProvider.tenant_id == uuid.UUID(tenant_id))
            )
            providers = result.scalars().all()
            
            return {
                "tenant_id": tenant_id,
                "providers": [
                    {
                        "provider_id": str(p.id),
                        "provider_type": p.provider_type,
                        "provider_name": p.provider_name,
                        "enabled": p.enabled,
                        "created_at": p.created_at.isoformat()
                    }
                    for p in providers
                ]
            }
            
    except Exception as e:
        logger.error(f"Failed to list OAuth providers: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/identity/v4/oauth/initiate")
async def initiate_oauth_flow(
    req: OAuthInitiateRequest,
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """
    Initiate OAuth/SSO authentication flow
    Returns authorization URL for user to visit
    """
    try:
        async with AsyncSessionLocal() as db:
            tenant_id_uuid = uuid.UUID(req.tenant_id)
            provider_id_uuid = uuid.UUID(req.provider_id)
            
            # Get provider config
            result = await db.execute(
                select(OAuthProvider).where(
                    OAuthProvider.id == provider_id_uuid,
                    OAuthProvider.tenant_id == tenant_id_uuid,
                    OAuthProvider.enabled == True
                )
            )
            provider = result.scalar_one_or_none()
            
            if not provider:
                raise HTTPException(status_code=404, detail="OAuth provider not found or disabled")
            
            # Generate state and PKCE verifier
            state = secrets.token_urlsafe(32)
            code_verifier = secrets.token_urlsafe(32)
            
            # Create session
            session = OAuthSession(
                id=uuid.uuid4(),
                tenant_id=tenant_id_uuid,
                provider_id=provider_id_uuid,
                state=state,
                code_verifier=code_verifier,
                redirect_uri=req.redirect_uri,
                expires_at=datetime.utcnow() + timedelta(minutes=10)
            )
            
            db.add(session)
            await db.commit()
            
            # Build authorization URL based on provider type
            if provider.provider_type == "azure_ad":
                auth_url = f"https://login.microsoftonline.com/{provider.tenant_domain}/oauth2/v2.0/authorize"
            elif provider.provider_type == "google":
                auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
            elif provider.discovery_url:
                # Use OIDC discovery
                auth_url = provider.discovery_url.replace("/.well-known/openid-configuration", "/authorize")
            else:
                raise HTTPException(status_code=400, detail="Provider configuration incomplete")
            
            scopes_str = " ".join(provider.scopes)
            full_auth_url = (
                f"{auth_url}"
                f"?client_id={provider.client_id}"
                f"&response_type=code"
                f"&redirect_uri={req.redirect_uri}"
                f"&scope={scopes_str}"
                f"&state={state}"
            )
            
            logger.info(f"OAuth flow initiated for provider {provider.provider_name}, session {session.id}")
            
            return {
                "session_id": str(session.id),
                "authorization_url": full_auth_url,
                "state": state,
                "expires_at": session.expires_at.isoformat()
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to initiate OAuth flow: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/identity/v4/oauth/callback")
async def oauth_callback(
    req: OAuthCallbackRequest,
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """
    Handle OAuth callback after user authentication
    Exchanges code for tokens and creates/links user
    """
    try:
        if req.error:
            logger.error(f"OAuth error: {req.error} - {req.error_description}")
            raise HTTPException(status_code=400, detail=f"OAuth error: {req.error}")
        
        async with AsyncSessionLocal() as db:
            # Find session by state
            result = await db.execute(
                select(OAuthSession).where(
                    OAuthSession.state == req.state,
                    OAuthSession.status == 'initiated'
                )
            )
            session = result.scalar_one_or_none()
            
            if not session:
                raise HTTPException(status_code=404, detail="Invalid or expired OAuth session")
            
            if session.expires_at < datetime.utcnow():
                session.status = 'failed'
                await db.commit()
                raise HTTPException(status_code=400, detail="OAuth session expired")
            
            # Get provider
            result = await db.execute(
                select(OAuthProvider).where(OAuthProvider.id == session.provider_id)
            )
            provider = result.scalar_one_or_none()
            
            if not provider:
                raise HTTPException(status_code=404, detail="OAuth provider not found")
            
            # Exchange code for tokens (simplified - production needs proper OAuth client)
            # TODO: Use proper OAuth library (authlib, httpx-oauth, etc.)
            token_url = ""
            if provider.provider_type == "azure_ad":
                token_url = f"https://login.microsoftonline.com/{provider.tenant_domain}/oauth2/v2.0/token"
            elif provider.provider_type == "google":
                token_url = "https://oauth2.googleapis.com/token"
            
            # For demo purposes, we'll simulate successful token exchange
            # In production, make actual HTTP request to token endpoint
            external_user_id = f"{provider.provider_type}_user_{secrets.token_hex(8)}"
            external_email = f"user@{provider.provider_type}.example.com"
            
            # Find or create user
            result = await db.execute(
                select(UserNew).where(
                    UserNew.tenant_id == session.tenant_id,
                    UserNew.email == external_email
                )
            )
            user = result.scalar_one_or_none()
            
            if not user:
                user = UserNew(
                    id=uuid.uuid4(),
                    tenant_id=session.tenant_id,
                    email=external_email,
                    name=f"SSO User from {provider.provider_name}",
                    user_metadata={"sso_provider": provider.provider_type, "external_id": external_user_id}
                )
                db.add(user)
                await db.flush()
            
            # Update session
            session.status = 'completed'
            session.user_id = user.id
            session.external_user_id = external_user_id
            session.external_email = external_email
            session.completed_at = datetime.utcnow()
            
            await db.commit()
            await db.refresh(user)
            
            # Generate JWT for the user
            token_payload = {
                "user_id": str(user.id),
                "tenant_id": str(session.tenant_id),
                "email": user.email,
                "exp": datetime.utcnow() + timedelta(hours=24)
            }
            jwt_token = jwt.encode(token_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
            
            logger.info(f"OAuth callback successful, user {user.id} authenticated via {provider.provider_name}")
            
            return {
                "success": True,
                "user_id": str(user.id),
                "email": user.email,
                "token": jwt_token,
                "provider": provider.provider_name
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OAuth callback failed: {e}")
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
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8003")))
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )