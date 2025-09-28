from fastapi import FastAPI
from .config import settings

# Reuse your common middlewares if you want metering/idempotency on connector too
from zeroque_common.db.session import get_engine, init_db
from zeroque_common.middleware.usage_middleware import add_api_call_meter
from zeroque_common.middleware.idempotency import add_idempotency_middleware

from .routers.admin import router as admin_router
from .routers.entry import router as entry_router
from .routers.webhooks import router as webhooks_router
from .routers.sync import router as sync_router

app = FastAPI(title="ZeroQue CV Connector", version="1.0.0")

# Metering for all requests where X-Tenant-Id header is set (dev-friendly)
add_api_call_meter(app)

# Idempotency on webhooks/checkout (provider may retry)
add_idempotency_middleware(app, routes=[("POST", "/webhooks/checkout")])

@app.on_event("startup")
def on_startup():
    # Needed because usage/idempotency middlewares use SessionLocal
    get_engine(); init_db()

# Routers
app.include_router(admin_router)
app.include_router(entry_router)
app.include_router(webhooks_router)
app.include_router(sync_router)

@app.get("/")
def root():
    return {"service": settings.SERVICE_NAME, "provider": settings.PROVIDER}