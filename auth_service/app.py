"""
auth_service.app
----------------
Standalone FastAPI application for the auth service.

Can run independently for testing, or be mounted as a sub-app in the main API.
"""
from fastapi import FastAPI
from auth_service.routes import router

app = FastAPI(
    title="ZeroQue Auth Service",
    version="1.0.0",
    description="Multi-tenant authentication using Auth0 Organizations",
)

app.include_router(router)


@app.get("/health")
async def health():
    from auth_service.config import AUTH_MODE
    return {"status": "ok", "service": "auth_service", "auth_mode": AUTH_MODE}
