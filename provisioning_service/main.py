import os
import traceback
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from provisioning_service.Models import Base
from provisioning_service.core.db_config import engine
from provisioning_service.core.helpers.load_permissions import insert_permissions_from_csv
from provisioning_service.services.provisioning_routes import router as provisioning_router
from provisioning_service.services.catalog_routes import router as catalog_router
from provisioning_service.services.auth_routes import router as auth_router
from provisioning_service.services.approval_routes import router as approval_router
from provisioning_service.services.internal_routes import router as internal_router
from provisioning_service.services.plan_routes import router as plan_router
from provisioning_service.services.subscriptions_routes import router as subscriptions_router
from provisioning_service.services.tenant_onboarding import router as onboarding_router
from provisioning_service.services.payments_routes import router as payments_router
from provisioning_service.utils.logger import logger

app = FastAPI(title="Provisioning Service", version="1.0.0")

# Create tables
try:
    Base.metadata.create_all(bind=engine)
    logger.info("✅ Database tables initialized")
except Exception as e:
    logger.error(f"❌ Table initialization failed: {e}")

insert_permissions_from_csv(r'provisioning_service/permissions.csv')


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Log all unhandled exceptions"""
    tb = traceback.format_exc()
    logger.error(f"Unhandled exception in {request.url.path}: {exc}\n{tb}")
    return JSONResponse(status_code=500, content={"detail": str(exc)})

allow_origins = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["*"],
)

app.include_router(onboarding_router)
app.include_router(auth_router)
app.include_router(internal_router)
app.include_router(payments_router)
app.include_router(provisioning_router)
app.include_router(catalog_router)
app.include_router(approval_router)
app.include_router(plan_router)
app.include_router(subscriptions_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "provisioning"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port)
