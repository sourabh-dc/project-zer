# services/identity/main.py - ZeroQue Identity Service V4.1
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from prometheus_client import  generate_latest
import redis
import pybreaker

from core.config import get_settings
from services.identity.repositories.db_config import check_db
from services.identity.services.identity_services import create_user, get_users, get_roles, generate_token_service, \
    get_reports_service, create_oauth_provider_service, list_oauth_providers_service, initiate_oauth_flow_service, \
    oauth_callback_service
from .utils.identity_logger import logger
from .schemas import *
from .utils.user_auth import get_user_context
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
    """Delegate role creation to service layer"""
    return await create_role(payload, request, user_context)

@app.get("/identity/v4/roles", response_model=List[RoleResponse])
async def list_roles(
    tenant_id: str = Query(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """List roles for tenant (delegates to service layer)"""
    return await get_roles(tenant_id, user_context)

@app.post("/identity/v4/role-assignments")
async def assign_role(
    payload: RoleAssignmentRequest,
    request: Request,
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Assign role to user (delegates to service layer)"""
    return await assign_role(payload, request, user_context)

@app.post("/identity/v4/token", response_model=TokenResponse)
async def generate_token(
    payload: TokenRequest,
    request: Request,
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Generate JWT token (delegates to service layer)"""
    return await generate_token_service(payload, request, user_context)

@app.get("/identity/v4/reports", response_model=ReportResponse)
async def get_reports(
    tenant_id: str = Query(...),
    report_type: str = Query(...),
    period_start: Optional[str] = Query(None),
    period_end: Optional[str] = Query(None),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """Get identity reports (blueprint-inspired analytics) (delegates to service layer)"""
    return await get_reports_service(tenant_id, report_type, period_start, period_end, user_context)

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
    return await create_oauth_provider_service(req, user_context)

@app.get("/identity/v4/oauth/providers")
async def list_oauth_providers(
    tenant_id: str = Query(...),
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """List OAuth/SSO providers for tenant (delegates to service layer)"""
    return await list_oauth_providers_service(tenant_id, user_context)

@app.post("/identity/v4/oauth/initiate")
async def initiate_oauth_flow(
    req: OAuthInitiateRequest,
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """
    Initiate OAuth/SSO authentication flow
    Returns authorization URL for user to visit
    """
    return await initiate_oauth_flow_service(req, user_context)

@app.post("/identity/v4/oauth/callback")
async def oauth_callback(
    req: OAuthCallbackRequest,
    user_context: Dict[str, Any] = Depends(get_user_context)
):
    """
    Handle OAuth callback after user authentication
    Exchanges code for tokens and creates/links user
    """
    return await oauth_callback_service(req, user_context)

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