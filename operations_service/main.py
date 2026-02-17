import os
import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from operations_service.Models import Base
from operations_service.core.db_config import engine
from operations_service.utils.logger import logger

# Ensure local service modules are on path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from operations.ledger_routes import router as ledger_router
from operations.approval_routes import router as approval_router
from operations.orders_router import router as orders_router

app = FastAPI(title="Operations Service", version="1.0.0")

try:
    Base.metadata.create_all(bind=engine)
    logger.info("✅ Database tables initialized")
except Exception as e:
    logger.error(f"❌ Table initialization failed: {e}")

allow_origins = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["*"],
)

# Operations-specific routers
app.include_router(approval_router, tags=["approval"])
app.include_router(ledger_router, tags=["operations"])
app.include_router(orders_router, tags=["orders"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "operations"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8003"))
    uvicorn.run(app, host="0.0.0.0", port=port)

