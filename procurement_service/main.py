from contextlib import asynccontextmanager
import time
import traceback
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from procurement_service.core.config import SERVICE_VERSION, SETTINGS
from procurement_service.core.db_config import init_db
from procurement_service.core.runtime import get_container
from procurement_service.services.dispute_routes import router as dispute_router
from procurement_service.services.fulfilment_routes import router as fulfilment_router
from procurement_service.services.invoice_routes import router as invoice_router
from procurement_service.services.ops_routes import router as ops_router
from procurement_service.services.order_routes import router as order_router
from procurement_service.services.procurement_routes import router as procurement_router
from procurement_service.services.vendor_routes import router as vendor_router
from procurement_service.utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    get_container()
    logger.info("Procurement service runtime initialized")
    yield
    # Shutdown
    logger.info("Procurement service shutdown complete")


app = FastAPI(title="Procurement Service", version=SERVICE_VERSION, lifespan=lifespan)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    logger.error(f"Unhandled exception in {request.url.path}: {exc}\n{tb}")
    return JSONResponse(status_code=500, content={"detail": str(exc)})


allow_origins = [o.strip() for o in SETTINGS.CORS_ALLOW_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid4()))
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    response.headers["x-request-id"] = request_id
    response.headers["x-response-time-ms"] = str(elapsed_ms)
    return response


app.include_router(vendor_router)
app.include_router(order_router)
app.include_router(procurement_router)
app.include_router(fulfilment_router)
app.include_router(dispute_router)
app.include_router(invoice_router)
app.include_router(ops_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "procurement"}


@app.get("/ready")
async def ready():
    return {"status": "ready"}


@app.get("/metrics")
async def metrics():
    return {"service": "procurement", "status": "ok"}


@app.get("/events")
async def events():
    container = get_container()
    return {"events": container.platform.store.events}
