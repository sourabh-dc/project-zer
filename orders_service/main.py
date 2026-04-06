import asyncio
import os
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from orders_service.core.policy_client import policy_client
from orders_service.core.sb_client import messaging_service
from orders_service.services.orders_routes import router as orders_router
from orders_service.services.vendor_routes import router as vendor_router
from orders_service.services.aifi_store_routes import router as aifi_store_router
from orders_service.services.aifi_admin_routes import router as aifi_admin_router
from orders_service.services.aifi_customer_routes import router as aifi_customer_router
from orders_service.services.aifi_push_routes import router as aifi_push_router
from orders_service.utils.logger import logger
from orders_service.core.config import SETTINGS

from alembic.db_check import assert_db_at_alembic_head


@asynccontextmanager
async def lifespan(app: FastAPI):
    assert_db_at_alembic_head(SETTINGS.DATABASE_URL)

    try:
        await messaging_service.start()
    except Exception as e:
        logger.warning(f"Service bus client start failed: {e}")

    from orders_service.core.workers.notification_worker import process_notifications
    notification_task = asyncio.create_task(process_notifications())

    yield

    notification_task.cancel()
    try:
        await notification_task
    except asyncio.CancelledError:
        pass
    try:
        await messaging_service.close()
    except Exception as e:
        logger.warning(f"Service bus client close failed: {e}")
    try:
        await policy_client.close()
    except Exception as e:
        logger.warning(f"Policy client close failed: {e}")



app = FastAPI(
    title="Orders Service",
    version="1.0.0",
    description="Standalone purchase request and approval workflow microservice",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
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

app.include_router(orders_router)
app.include_router(vendor_router)
app.include_router(aifi_store_router)
app.include_router(aifi_admin_router)
app.include_router(aifi_customer_router)
app.include_router(aifi_push_router)

@app.get("/health")
async def health():
    return {"status": "ok", "service": "orders-service"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("ORDERS_PORT", "8008"))
    uvicorn.run(app, host="0.0.0.0", port=port)

