import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from sqlalchemy import text

from internal_api.db import SessionLocal
from internal_api.config import SERVICE_NAME, SERVICE_VERSION
from internal_api.internal_routes import router as internal_router

app = FastAPI(
    title="ZeroQue Internal API",
    version=SERVICE_VERSION,
    description="Admin/internal endpoints for plans, features, roles, permissions"
)

allow_origins = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

app.include_router(internal_router, tags=["internal"])


@app.get("/health")
async def health():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "healthy", "service": SERVICE_NAME, "version": SERVICE_VERSION}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "unhealthy", "error": str(e)})

