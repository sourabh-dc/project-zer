import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import text
from starlette.responses import JSONResponse, Response

from core.config import SERVICE_NAME, SERVICE_VERSION
from core.db_config import SessionLocal
from services.tenant_onboarding import router as onboarding_router
from services.provisioning_routes import router as provisioning_router
from services.catalog_routes import router as catalog_router
from services.subscriptions_routes import router as subscriptions_router
from services.approval_routes import router as approval_router
from services.auth_routes import router as auth_router
from services.plan_routes import router as plan_router
from services.payments_routes import router as payments_router
from services.internal_routes import router as internal_router

# FastAPI app
app = FastAPI(
    title="ZeroQue Core API",
    version=SERVICE_VERSION,
    description="Simple Implementation"
)

# CORS - configure via environment
allow_origins = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

app.include_router(internal_router)
app.include_router(onboarding_router)
app.include_router(auth_router)
app.include_router(plan_router)
app.include_router(payments_router)
app.include_router(provisioning_router)
app.include_router(catalog_router)
app.include_router(subscriptions_router)
app.include_router(approval_router)


@app.get("/health")
async def health():
    """Health check endpoint"""
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "healthy", "service": SERVICE_NAME, "version": SERVICE_VERSION}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": str(e)}
        )

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
