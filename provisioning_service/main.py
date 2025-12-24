import os
import sys
import traceback
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Ensure local service modules are on path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from services.provisioning_routes import router as provisioning_router
from services.catalog_routes import router as catalog_router
from services.auth_routes import router as auth_router
from services.approval_routes import router as approval_router
from services.internal_routes import router as internal_router
from services.plan_routes import router as plan_router
from services.subscriptions_routes import router as subscriptions_router
from services.tenant_onboarding import router as onboarding_router
from utils.logger import logger

app = FastAPI(title="Provisioning Service", version="1.0.0")


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

app.include_router(auth_router, tags=["authentication"])
app.include_router(provisioning_router, tags=["provisioning"])
app.include_router(catalog_router, tags=["catalog"])
app.include_router(approval_router, tags=["approvals"])
app.include_router(internal_router, tags=["internal"])
app.include_router(plan_router, tags=["plans"])
app.include_router(subscriptions_router, tags=["subscriptions"])
app.include_router(onboarding_router, tags=["onboarding"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "provisioning"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port)

