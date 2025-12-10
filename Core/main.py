import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.responses import JSONResponse

from core.config import SETTINGS, SERVICE_NAME, SERVICE_VERSION
from core.db_config import SessionLocal
from services.auth.routes import router as auth_router
from services.onboarding.routes import router as onboarding_router
from services.catalog.routes import router as catalog_router
from services.entitlements.routes import router as entitlements_router
from services.subscriptions.routes import router as subscriptions_router
from services.approvals.routes import router as approval_router
from services.provisioning.users_routes import router as users_router
from services.provisioning.sites_routes import router as sites_router
from services.provisioning.stores_routes import router as stores_router
from services.provisioning.vendors_routes import router as vendors_router
from services.provisioning.cost_centres_routes import router as cost_centres_router
from services.provisioning.org_units_routes import router as org_units_router
from services.provisioning.roles_routes import router as roles_router

app = FastAPI(
    title="Zeroque: Core API",
    version=SERVICE_VERSION,
    description="Core services (provisioning, catalog, entitlements, subscriptions, approvals, auth, onboarding)",
)

allow_origins = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(onboarding_router)
app.include_router(users_router)
app.include_router(sites_router)
app.include_router(stores_router)
app.include_router(vendors_router)
app.include_router(cost_centres_router)
app.include_router(org_units_router)
app.include_router(roles_router)
app.include_router(catalog_router)
app.include_router(entitlements_router)
app.include_router(subscriptions_router)
app.include_router(approval_router)


@app.get("/health")
async def health():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "healthy", "service": SERVICE_NAME, "version": SERVICE_VERSION}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "unhealthy", "error": str(e)})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=SETTINGS.PORT)

