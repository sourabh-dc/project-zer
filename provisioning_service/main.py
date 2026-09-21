from contextlib import asynccontextmanager
import os
import re
import traceback
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from provisioning_service.Models import Base
from provisioning_service.core.db_config import engine
from provisioning_service.core.helpers.load_permissions import seed_roles_and_permissions, seed_job_functions
from provisioning_service.core.helpers.load_product_features import load_product_features_on_startup
from provisioning_service.core.helpers.load_plans import seed_plans_and_features
from provisioning_service.services.tenants_routes import router as tenants_router
from provisioning_service.services.sites_routes import router as sites_router
from provisioning_service.services.stores_routes import router as stores_router
from provisioning_service.services.invitations_routes import router as invitations_router
from provisioning_service.services.users_routes import router as users_router
from provisioning_service.services.vendors_routes import router as vendors_router
from provisioning_service.services.cost_centre_routes import router as cost_centre_router
from provisioning_service.services.roles_admin_routes import router as roles_admin_router
from provisioning_service.services.tenant_role_routes import router as tenant_role_router
from provisioning_service.services.org_unit_routes import router as org_unit_router
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
from provisioning_service.services.setup_status_routes import router as setup_status_router
from provisioning_service.services.google_places_routes import router as google_places_router
from provisioning_service.services.creditsafe_routes import router as creditsafe_router
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
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": str(exc)}},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Standard error shape: {"error": {"code", "message"}}"""
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    code = re.sub(r"[^a-z0-9]+", "_", detail.lower()).strip("_")[:60] or "error"
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": code, "message": detail}},
        headers=getattr(exc, "headers", None),
    )

allow_origins = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]
logger.info(f"CORS allow_origins: {allow_origins}")
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
app.include_router(tenants_router)
app.include_router(sites_router)
app.include_router(stores_router)
app.include_router(invitations_router)
app.include_router(users_router)
app.include_router(vendors_router)
app.include_router(cost_centre_router)
app.include_router(roles_admin_router)
app.include_router(tenant_role_router)
app.include_router(org_unit_router)
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
app.include_router(setup_status_router)
app.include_router(google_places_router)
app.include_router(creditsafe_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "provisioning"}
