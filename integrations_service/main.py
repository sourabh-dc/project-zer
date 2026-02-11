import os
import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Ensure local service modules are on path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from integrations.aifi_routes import router as aifi_router
from integrations.aifi_sessions_routes import router as aifi_sessions_router
from integrations.aifi_webhooks_routes import router as aifi_webhooks_router
from integrations.zeroque_admin_routes import router as aifi_admin_router
from integrations.aifi_store import router as aifi_store_router
from integrations.aifi_cutomer_app import router as aifi_customer_app_router
from integrations.aifi_admin_orders import router as aifi_admin_orders_router
from integrations.aifi_admin_products import router as aifi_admin_products_router
from integrations.aifi_store_customer import router as aifi_store_customer_router

app = FastAPI(title="Integrations Service", version="1.0.0")

allow_origins = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["*"],
)

app.include_router(aifi_router, tags=["integrations"])
app.include_router(aifi_sessions_router, tags=["integrations"])
app.include_router(aifi_webhooks_router, tags=["integrations"])
app.include_router(aifi_admin_router, tags=["integrations"])
app.include_router(aifi_store_router, tags=["aifi-store"])
app.include_router(aifi_customer_app_router, tags=["AiFi Customer App"])
app.include_router(aifi_admin_orders_router, tags=["AiFi Admin Orders"])
app.include_router(aifi_admin_products_router, tags=["AiFi Admin Products"])
app.include_router(aifi_store_customer_router, tags=["AiFi Store Customer"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "integrations"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8002"))
    uvicorn.run(app, host="0.0.0.0", port=port)

