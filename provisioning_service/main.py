from contextlib import asynccontextmanager
import os
import traceback
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from provisioning_service.Models import Base
from provisioning_service.core.db_config import engine
from provisioning_service.core.helpers.load_permissions import seed_roles_and_permissions, seed_job_functions
from provisioning_service.core.helpers.load_product_features import load_product_features_on_startup
from provisioning_service.core.helpers.load_plans import seed_plans_and_features
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
from provisioning_service.services.budget_change_request_routes import router as budget_change_router
from provisioning_service.services.companies_house_routes import router as companies_house_router
from provisioning_service.services.roles_routes import router as roles_router
from provisioning_service.services.approval_controls_routes import router as approval_controls_router
from provisioning_service.services.delegation_routes import router as delegation_router
from provisioning_service.services.audit_routes import router as audit_router
from provisioning_service.services.advanced_access_routes import router as advanced_access_router
from provisioning_service.services.integration_pack_routes import router as integration_pack_router
from provisioning_service.services.branding_routes import router as branding_router
from provisioning_service.services.connector_routes import router as connector_router
from provisioning_service.core.helpers.load_connectors import seed_connector_providers
from provisioning_service.core.connectors.scheduler import start_scheduler, stop_scheduler
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

        # Migrate users: add display_job_title, job_function columns
        try:
            from sqlalchemy import text, inspect
            insp = inspect(engine)
            if insp.has_table("users"):
                existing_cols = {c["name"] for c in insp.get_columns("users")}
                with engine.begin() as conn:
                    if "display_job_title" not in existing_cols:
                        conn.execute(text(
                            "ALTER TABLE users ADD COLUMN display_job_title VARCHAR(255)"
                        ))
                        logger.info("✅ Added display_job_title column to users")
                    if "job_function" not in existing_cols:
                        conn.execute(text(
                            "ALTER TABLE users ADD COLUMN job_function VARCHAR(100)"
                        ))
                        logger.info("✅ Added job_function column to users")
        except Exception as e:
            logger.warning(f"User columns migration skipped or failed: {e}")

        # Migrate tenants: add strict_sod_enabled column
        try:
            from sqlalchemy import text, inspect
            insp = inspect(engine)
            if insp.has_table("tenants"):
                existing_cols = {c["name"] for c in insp.get_columns("tenants")}
                with engine.begin() as conn:
                    if "strict_sod_enabled" not in existing_cols:
                        conn.execute(text(
                            "ALTER TABLE tenants ADD COLUMN strict_sod_enabled BOOLEAN NOT NULL DEFAULT FALSE"
                        ))
                        logger.info("✅ Added strict_sod_enabled column to tenants")
        except Exception as e:
            logger.warning(f"Tenant columns migration skipped or failed: {e}")

        # Migrate tenants: add parent_tenant_id for sub-tenant hierarchy (Phase 6)
        try:
            from sqlalchemy import text, inspect
            insp = inspect(engine)
            if insp.has_table("tenants"):
                existing_cols = {c["name"] for c in insp.get_columns("tenants")}
                with engine.begin() as conn:
                    if "parent_tenant_id" not in existing_cols:
                        conn.execute(text(
                            "ALTER TABLE tenants ADD COLUMN parent_tenant_id UUID"
                        ))
                        logger.info("✅ Added parent_tenant_id column to tenants")
        except Exception as e:
            logger.warning(f"Parent tenant migration skipped or failed: {e}")

        # Migrate mandates: add admin_job_title, company_size, country_of_registration
        try:
            from sqlalchemy import text, inspect
            insp = inspect(engine)
            if insp.has_table("mandates"):
                existing_cols = {c["name"] for c in insp.get_columns("mandates")}
                with engine.begin() as conn:
                    for col, col_type in [
                        ("admin_job_title", "VARCHAR(255)"),
                        ("company_size", "VARCHAR(50)"),
                        ("country_of_registration", "VARCHAR(100)"),
                    ]:
                        if col not in existing_cols:
                            conn.execute(text(f"ALTER TABLE mandates ADD COLUMN {col} {col_type}"))
                            logger.info(f"✅ Added {col} column to mandates")
        except Exception as e:
            logger.warning(f"Mandate columns migration skipped or failed: {e}")

        # Migrate integration packs (Phase B): pricing + subscription period columns
        try:
            from sqlalchemy import text, inspect
            insp = inspect(engine)
            with engine.begin() as conn:
                if insp.has_table("integration_packs"):
                    existing_cols = {c["name"] for c in insp.get_columns("integration_packs")}
                    for col, col_type in [
                        ("stripe_price_id", "VARCHAR(100)"),
                        ("price_monthly_minor", "INTEGER"),
                        ("currency", "VARCHAR(3) DEFAULT 'GBP'"),
                        ("billing_interval", "VARCHAR(10) DEFAULT 'month'"),
                    ]:
                        if col not in existing_cols:
                            conn.execute(text(f"ALTER TABLE integration_packs ADD COLUMN {col} {col_type}"))
                            logger.info(f"✅ Added {col} column to integration_packs")
                if insp.has_table("tenant_integration_packs"):
                    existing_cols = {c["name"] for c in insp.get_columns("tenant_integration_packs")}
                    for col, col_type in [
                        ("current_period_start", "TIMESTAMPTZ"),
                        ("current_period_end", "TIMESTAMPTZ"),
                        ("shared_with_subtenants", "BOOLEAN NOT NULL DEFAULT FALSE"),
                    ]:
                        if col not in existing_cols:
                            conn.execute(text(f"ALTER TABLE tenant_integration_packs ADD COLUMN {col} {col_type}"))
                            logger.info(f"✅ Added {col} column to tenant_integration_packs")
        except Exception as e:
            logger.warning(f"Integration pack columns migration skipped or failed: {e}")

        # Migrate subscription plans (Phase D4): public vs sales-only visibility
        try:
            from sqlalchemy import text, inspect
            insp = inspect(engine)
            if insp.has_table("subscription_plans"):
                existing_cols = {c["name"] for c in insp.get_columns("subscription_plans")}
                with engine.begin() as conn:
                    if "is_public" not in existing_cols:
                        conn.execute(text(
                            "ALTER TABLE subscription_plans ADD COLUMN is_public BOOLEAN NOT NULL DEFAULT TRUE"
                        ))
                        logger.info("✅ Added is_public column to subscription_plans")
        except Exception as e:
            logger.warning(f"Subscription plan columns migration skipped or failed: {e}")

        # Migrate plan pricing (Phase D2/D3): implementation fee + seat blocks
        try:
            from sqlalchemy import text, inspect
            insp = inspect(engine)
            if insp.has_table("plan_price"):
                existing_cols = {c["name"] for c in insp.get_columns("plan_price")}
                with engine.begin() as conn:
                    for col, col_type in [
                        ("implementation_fee_minor", "NUMERIC NOT NULL DEFAULT 0"),
                        ("seat_block_size", "INTEGER NOT NULL DEFAULT 5"),
                        ("seat_block_price_minor", "NUMERIC NOT NULL DEFAULT 0"),
                    ]:
                        if col not in existing_cols:
                            conn.execute(text(f"ALTER TABLE plan_price ADD COLUMN {col} {col_type}"))
                            logger.info(f"✅ Added {col} column to plan_price")
        except Exception as e:
            logger.warning(f"Plan price columns migration skipped or failed: {e}")

        # Migrate tenant_subscriptions: add pending_plan_code for scheduled downgrades
        try:
            from sqlalchemy import text, inspect
            insp = inspect(engine)
            if insp.has_table("tenant_subscriptions"):
                existing_cols = {c["name"] for c in insp.get_columns("tenant_subscriptions")}
                with engine.begin() as conn:
                    if "pending_plan_code" not in existing_cols:
                        conn.execute(text(
                            "ALTER TABLE tenant_subscriptions ADD COLUMN pending_plan_code VARCHAR(50)"
                        ))
                        logger.info("✅ Added pending_plan_code column to tenant_subscriptions")
        except Exception as e:
            logger.warning(f"Tenant subscription migration skipped or failed: {e}")

        # Migrate products: add source_connection_id for ERP connector origin
        try:
            from sqlalchemy import text, inspect
            insp = inspect(engine)
            if insp.has_table("products"):
                existing_cols = {c["name"] for c in insp.get_columns("products")}
                with engine.begin() as conn:
                    if "source_connection_id" not in existing_cols:
                        conn.execute(text(
                            "ALTER TABLE products ADD COLUMN source_connection_id UUID"
                        ))
                        logger.info("✅ Added source_connection_id column to products")
        except Exception as e:
            logger.warning(f"Product connector column migration skipped or failed: {e}")

        # Load static data (roles/permissions/plans/features/job functions)
        try:
            seed_roles_and_permissions()
            load_product_features_on_startup()
            seed_job_functions()
            seed_plans_and_features()
            seed_connector_providers()
        except Exception as ex:
            logger.warning(f"Initial data load failed: {ex}")

        # Start ERP connector scheduler (APScheduler, in-process)
        try:
            start_scheduler()
        except Exception as ex:
            logger.warning(f"Connector scheduler failed to start: {ex}")

        yield

    finally:
        # Shutdown - stop messaging service and policy client cleanly
        try:
            stop_scheduler()
        except Exception as ex:
            logger.warning(f"Connector scheduler stop failed: {ex}")
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
app.include_router(budget_change_router)
app.include_router(companies_house_router)
app.include_router(roles_router)
app.include_router(approval_controls_router)
app.include_router(delegation_router)
app.include_router(audit_router)
app.include_router(advanced_access_router)
app.include_router(integration_pack_router)
app.include_router(branding_router)
app.include_router(connector_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "provisioning"}
