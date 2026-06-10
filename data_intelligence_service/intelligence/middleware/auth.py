"""
API key authentication middleware for intelligence endpoints.

Protected paths: /intelligence/*
Auth header:     X-API-Key: <value>

When INTELLIGENCE_API_KEY is empty in settings, auth is disabled
(useful for local dev). In production always set this secret.
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from data_intelligence_service.core.config import SETTINGS
from data_intelligence_service.core.logger import logger

_PROTECTED_PREFIXES = ("/intelligence/",)


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if any(path.startswith(p) for p in _PROTECTED_PREFIXES):
            configured_key = SETTINGS.INTELLIGENCE_API_KEY
            if configured_key:
                provided_key = request.headers.get("X-API-Key", "")
                if not provided_key:
                    logger.warning(f"[Auth] Missing X-API-Key for {path}")
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "X-API-Key header required"},
                    )
                if provided_key != configured_key:
                    logger.warning(f"[Auth] Invalid X-API-Key for {path}")
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Invalid API key"},
                    )

        return await call_next(request)
