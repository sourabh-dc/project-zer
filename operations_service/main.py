import os
import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Ensure local service modules are on path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from operations.orders import upsert_aifi_order  # noqa: F401 (ensure deps loaded)
from operations.ledger_routes import router as ledger_router
from services.auth_routes import router as auth_router

app = FastAPI(title="Operations Service", version="1.0.0")

allow_origins = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["*"],
)

# Operations-specific routers
app.include_router(auth_router, tags=["authentication"])
app.include_router(ledger_router, tags=["operations"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "operations"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8003"))
    uvicorn.run(app, host="0.0.0.0", port=port)

