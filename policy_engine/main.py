"""
Policy Engine Service
Main FastAPI application for the Policy Engine.

This service provides:
- Policy management (CRUD for policies, versions, rules)
- Policy evaluation (check if actions are allowed)
- Decision audit logging

Run with: uvicorn policy_engine.main:app --host 0.0.0.0 --port 8004
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

from policy_engine.core.config import SETTINGS
from policy_engine.core.db_config import init_db, SessionLocal
from policy_engine.core.redis_client import policy_cache
from policy_engine.core.helpers.load_policies import load_policies
from policy_engine.routes import policies, evaluate, decisions, action_types
from policy_engine.Schemas import HealthResponse, ErrorResponse
from policy_engine.utils.logger import logger


# =============================================================================
# Prometheus Metrics
# =============================================================================

REQUEST_COUNT = Counter(
    'policy_engine_requests_total',
    'Total requests',
    ['method', 'endpoint', 'status']
)

REQUEST_LATENCY = Histogram(
    'policy_engine_request_latency_seconds',
    'Request latency',
    ['method', 'endpoint']
)

EVALUATION_COUNT = Counter(
    'policy_engine_evaluations_total',
    'Total policy evaluations',
    ['decision']
)


# =============================================================================
# Application Lifecycle
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup and shutdown lifecycle.
    """
    # Startup
    logger.info(f"🚀 Starting {SETTINGS.SERVICE_NAME} v{SETTINGS.SERVICE_VERSION}")
    
    # Initialize database
    init_db()
    
    # Load policies from CSV
    try:
        with SessionLocal() as session:
            load_policies(session)
        logger.info("✅ Policies loaded from CSV")
    except Exception as e:
        logger.warning(f"⚠️ Could not load policies from CSV: {e}")

    # Connect to Redis
    await policy_cache.connect()
    
    logger.info(f"✅ {SETTINGS.SERVICE_NAME} ready on port {SETTINGS.PORT}")
    
    yield
    
    # Shutdown
    logger.info(f"🛑 Shutting down {SETTINGS.SERVICE_NAME}")
    await policy_cache.disconnect()


# =============================================================================
# FastAPI Application
# =============================================================================

app = FastAPI(
    title="ZeroQue Policy Engine",
    description="""
    Policy Engine service for ZeroQue commerce orchestration.
    
    ## Overview
    
    The Policy Engine evaluates business rules declaratively, separating
    decision logic from application code. It answers questions like:
    
    - Can this user place an order of this amount?
    - Does this order require manager approval?
    - Is this product available to this user?
    
    ## Key Features
    
    - **Declarative Policies**: Define rules without code changes
    - **Context-Aware**: Decisions based on user, resource, and environment
    - **Auditable**: Every decision is logged for compliance
    - **Cacheable**: Redis caching for high performance
    - **Versioned**: Policy changes are tracked with full history
    
    ## Endpoints
    
    - `/v1/policies/*` - Policy management (CRUD)
    - `/v1/policy-engine/evaluate` - Evaluate actions against policies
    - `/v1/policy-engine/decisions` - Query decision audit logs
    - `/v1/action-types` - Action type catalog
    """,
    version=SETTINGS.SERVICE_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)


# =============================================================================
# Middleware
# =============================================================================

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=SETTINGS.ALLOW_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Record request metrics."""
    import time
    start_time = time.time()
    
    response = await call_next(request)
    
    # Record metrics
    duration = time.time() - start_time
    endpoint = request.url.path
    
    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=endpoint,
        status=response.status_code
    ).inc()
    
    REQUEST_LATENCY.labels(
        method=request.method,
        endpoint=endpoint
    ).observe(duration)
    
    return response


# =============================================================================
# Exception Handlers
# =============================================================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            detail="Internal server error",
            error_code="INTERNAL_ERROR"
        ).model_dump()
    )


# =============================================================================
# Routes
# =============================================================================

# Include routers
app.include_router(policies.router)
app.include_router(evaluate.router)
app.include_router(decisions.router)
app.include_router(action_types.router)


# =============================================================================
# Health & Metrics Endpoints
# =============================================================================

@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """
    Health check endpoint.
    
    Returns service status for load balancers and monitoring.
    """
    return HealthResponse(
        status="healthy",
        service=SETTINGS.SERVICE_NAME,
        version=SETTINGS.SERVICE_VERSION,
        timestamp=datetime.now(timezone.utc)
    )


@app.get("/health/ready", tags=["Health"])
async def readiness_check():
    """
    Readiness check - verifies database and cache connectivity.
    """
    from policy_engine.core.db_config import engine
    
    issues = []
    
    # Check database
    try:
        with engine.connect() as conn:
            conn.execute("SELECT 1")
    except Exception as e:
        issues.append(f"Database: {str(e)}")
    
    # Check Redis (optional)
    if not policy_cache.is_connected:
        issues.append("Redis: Not connected (caching disabled)")
    
    if issues:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "issues": issues
            }
        )
    
    return {"status": "ready"}


@app.get("/metrics", tags=["Monitoring"])
async def metrics():
    """
    Prometheus metrics endpoint.
    """
    if not SETTINGS.ENABLE_METRICS:
        return JSONResponse(
            status_code=404,
            content={"detail": "Metrics disabled"}
        )
    
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint with service info."""
    return {
        "service": SETTINGS.SERVICE_NAME,
        "version": SETTINGS.SERVICE_VERSION,
        "docs": "/docs",
        "health": "/health"
    }


# =============================================================================
# Run with Uvicorn (for development)
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "policy_engine.main:app",
        host="0.0.0.0",
        port=SETTINGS.PORT,
        reload=True
    )
