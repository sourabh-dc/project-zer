from contextlib import asynccontextmanager
import os
import traceback
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from provisioning_service.core.helpers.load_permissions import insert_permissions_from_csv
from provisioning_service.core.helpers.load_features import insert_features_from_csv
from provisioning_service.core.helpers.load_product_features import load_product_features_on_startup
from provisioning_service.services.provisioning_routes import router as provisioning_router
from provisioning_service.services.catalog_routes import router as catalog_router
from provisioning_service.services.auth_routes import router as auth_router
from provisioning_service.services.internal_routes import router as internal_router
from provisioning_service.services.plan_routes import router as plan_router
from provisioning_service.services.subscriptions_routes import router as subscriptions_router
from provisioning_service.services.tenant_onboarding import router as onboarding_router
from provisioning_service.services.payments_routes import router as payments_router
from provisioning_service.services.approved_range_routes import router as approved_range_router
from provisioning_service.services.calendar_routes import router as calendar_router
from provisioning_service.services.budget_routes import router as budget_router
from provisioning_service.services.user_budget_routes import router as user_budget_router
from provisioning_service.services.approval_policy_routes import router as approval_policy_router
from provisioning_service.services.purchase_request_routes import router as purchase_request_router
from provisioning_service.services.budget_change_request_routes import router as budget_change_router
from provisioning_service.utils.logger import logger
from provisioning_service.core.sb_client import messaging_service
from provisioning_service.core.policy_client import policy_client
from provisioning_service.core.config import SETTINGS

from alembic.db_check import assert_db_at_alembic_head


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context: verify DB revision, start messaging service, pre-load data."""
    # Startup
    try:
        assert_db_at_alembic_head(SETTINGS.DATABASE_URL)

        # Start messaging service (Service Bus connections)
        try:
            await messaging_service.start()
            logger.info("✅ Messaging service started")
        except Exception as ex:
            logger.warning(f"Messaging service failed to start: {ex}")

        # Load static data (permissions/features)
        try:
            insert_permissions_from_csv(r'provisioning_service/permissions.csv')
            insert_features_from_csv(r'provisioning_service/features.csv')
            load_product_features_on_startup()
        except Exception as ex:
            logger.warning(f"Initial data load failed: {ex}")

        yield

    finally:
        # Shutdown - stop messaging service and policy client cleanly
        try:
            await messaging_service.stop()
            logger.info("✅ Messaging service stopped")
        except Exception as ex:
            logger.warning(f"Messaging service stop failed: {ex}")
        try:
            await policy_client.close()
            logger.info("✅ Policy client closed")
        except Exception as ex:
            logger.warning(f"Policy client close failed: {ex}")


app = FastAPI(title="Provisioning Service", version="1.0.0", lifespan=lifespan)


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
app.include_router(plan_router)
app.include_router(subscriptions_router)
app.include_router(approved_range_router)
app.include_router(calendar_router)
app.include_router(budget_router)
app.include_router(user_budget_router)
app.include_router(approval_policy_router)
app.include_router(purchase_request_router)
app.include_router(budget_change_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "provisioning"}
