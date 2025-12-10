from fastapi import FastAPI

from core.config import SERVICE_VERSION
from services.internal_routes import router as internal_router
app = FastAPI(
    title="ZeroQue Internal API",
    version=SERVICE_VERSION,
    description="Simple Implementation"
)

app.include_router(internal_router)

