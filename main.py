import os
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import text
from starlette.responses import JSONResponse, Response

from core.config import SETTINGS, SERVICE_NAME, SERVICE_VERSION
from core.db_config import SessionLocal
from utils.logger import logger
from utils.redis_client import redis_client
from services.background_jobs import run_background_jobs
from services.provisioning_routes import app as provisioning_router
from services.catalog_routes import app as catalog_router
from services.subscriptions_routes import app as subscriptions_router
from services.approval_routes import app as approval_router
from services.pricing_routes import app as pricing_router
from services.entitlements_routes import app as entitlements_router
from services.payments_routes import app as payments_router
from services.orders_router import app as orders_router
from services.ledger_routes import app as ledger_router
from services.billing_routes import app as billing_router
from services.auth_routes import app as auth_router
# FastAPI app
app = FastAPI(
    title="ZeroQue All in One API",
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
app.include_router(provisioning_router, tags=["provisioning"])
app.include_router(catalog_router, tags=["catalog"])
app.include_router(approval_router, tags=["approval"])
app.include_router(subscriptions_router, tags=["subscriptions"])
app.include_router(pricing_router, tags=["pricing"])
app.include_router(entitlements_router, tags=["entitlements"])
app.include_router(payments_router, tags=["payments"])
app.include_router(orders_router, tags=["orders"])
app.include_router(ledger_router, tags=["ledger"])
app.include_router(billing_router, tags=["billing"])
app.include_router(auth_router, tags=["authentication"])

@app.on_event("startup")
async def startup_event():
    """Start background jobs on application startup"""
    logger.info("🚀 Starting background jobs...")
    asyncio.create_task(run_background_jobs())
    logger.info("✅ Background jobs started")

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

if __name__ == "__main__":
    import uvicorn
    
    logger.info(f"🚀 Starting {SERVICE_NAME} v{SERVICE_VERSION}")
    logger.info(f"📊 Database: {SETTINGS.DATABASE_URL.split('@')[1] if '@' in SETTINGS.DATABASE_URL else 'configured'}")
    logger.info(f"💾 Redis: {'enabled' if redis_client else 'disabled'}")
    logger.info(f"🔒 RLS: enabled for tenant isolation")
    
    uvicorn.run(app, host="0.0.0.0", port=SETTINGS.PORT)

