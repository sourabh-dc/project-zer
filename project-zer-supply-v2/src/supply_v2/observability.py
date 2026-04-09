from __future__ import annotations

import time
from uuid import uuid4

from fastapi import FastAPI, Request

from supply_v2.config import get_settings


def attach_observability(app: FastAPI) -> FastAPI:
    settings = get_settings()
    if settings.applicationinsights_connection_string:
        try:
            from azure.monitor.opentelemetry import configure_azure_monitor

            configure_azure_monitor(connection_string=settings.applicationinsights_connection_string)
        except ImportError:
            pass

    @app.middleware("http")
    async def request_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id", str(uuid4()))
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        response.headers["x-request-id"] = request_id
        response.headers["x-response-time-ms"] = str(elapsed_ms)
        return response

    return app
