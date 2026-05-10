from contextlib import asynccontextmanager
import os
import traceback
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from provisioning_service.Models import Base
from provisioning_service.core.db_config import engine
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context: start messaging service, initialise DB/tables and pre-load data.

    This replaces deprecated `@app.on_event("startup")` / `@app.on_event("shutdown")`.
    """
    # Startup
    try:
        # Start messaging service (Service Bus connections)
        try:
            await messaging_service.start()
            logger.info("✅ Messaging service started")
        except Exception as ex:
            logger.warning(f"Messaging service failed to start: {ex}")

        # Create tables and load initial data
        try:
            Base.metadata.create_all(bind=engine)
            logger.info("✅ Database tables initialized")
        except Exception as e:
            logger.error(f"❌ Table initialization failed: {e}")

        # Migrate outbox_events: add aggregate_type, aggregate_id, payload columns
        # if they don't exist yet (safe for existing databases)
        try:
            from sqlalchemy import text, inspect
            insp = inspect(engine)
            if insp.has_table("outbox_events"):
                existing_cols = {c["name"] for c in insp.get_columns("outbox_events")}
                with engine.begin() as conn:
                    if "aggregate_type" not in existing_cols:
                        conn.execute(text(
                            "ALTER TABLE outbox_events ADD COLUMN aggregate_type VARCHAR(100)"
                        ))
                        logger.info("✅ Added aggregate_type column to outbox_events")
                    if "aggregate_id" not in existing_cols:
                        conn.execute(text(
                            "ALTER TABLE outbox_events ADD COLUMN aggregate_id UUID"
                        ))
                        logger.info("✅ Added aggregate_id column to outbox_events")
                    if "payload" not in existing_cols and "event_data" in existing_cols:
                        conn.execute(text(
                            "ALTER TABLE outbox_events RENAME COLUMN event_data TO payload"
                        ))
                        logger.info("✅ Renamed event_data → payload column in outbox_events")
                    elif "payload" not in existing_cols:
                        conn.execute(text(
                            "ALTER TABLE outbox_events ADD COLUMN payload JSONB NOT NULL DEFAULT '{}'"
                        ))
                        logger.info("✅ Added payload column to outbox_events")
                    # Back-fill aggregate_type from event_type for existing rows
                    conn.execute(text("""
                        UPDATE outbox_events
                        SET    aggregate_type = split_part(event_type, '.', 1)
                        WHERE  aggregate_type IS NULL
                    """))
        except Exception as e:
            logger.warning(f"Outbox migration step skipped or failed: {e}")

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
