"""
API key authentication + Redis rate limiting middleware.

Protected paths: /intelligence/*
Auth header:     X-API-Key: <value>

RATE LIMITING (Redis sliding window):
  Uses a per-tenant, per-minute counter stored in Redis.
  Key: ratelimit:{tenant_id}:{minute_bucket}
  Tenant ID is extracted from the request body (best-effort JSON parse).
  Falls back to IP-based limiting if no tenant_id in body.

  When REDIS_URL is not set, rate limiting is disabled (dev mode).
  When INTELLIGENCE_API_KEY is empty, auth is disabled (dev mode).

WHY sliding window via Redis INCR?
  INCR is atomic — no race conditions across multiple instances.
  TTL of 60s ensures the counter auto-expires at the end of the window.
  This is the standard pattern: simple, correct, zero extra dependencies.
"""
import json
import os
import time
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from data_intelligence_service.core.config import SETTINGS
from data_intelligence_service.core.logger import logger


# ---------------------------------------------------------------------------
# Redis client (shared with memory.py — initialised independently here
# to keep middleware self-contained and avoid circular imports)
# ---------------------------------------------------------------------------

def _make_redis():
    url = os.getenv("REDIS_URL", "")
    if not url:
        return None
    try:
        import redis as _redis
        client = _redis.from_url(url, decode_responses=True, socket_connect_timeout=2)
        client.ping()
        logger.info("[RateLimit] Redis rate-limit backend connected")
        return client
    except Exception as exc:
        logger.warning(f"[RateLimit] Redis unavailable ({exc}) — rate limiting disabled")
        return None


_redis = _make_redis()

_PROTECTED_PREFIXES = ("/intelligence/",)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if not any(path.startswith(p) for p in _PROTECTED_PREFIXES):
            return await call_next(request)

        # ── Auth check ────────────────────────────────────────────────────────
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

        # ── Rate limiting (Redis sliding window) ──────────────────────────────
        if _redis and SETTINGS.RATE_LIMIT_RPM > 0:
            tenant_id = await _extract_tenant_id(request)
            bucket_key = _rate_limit_key(tenant_id, request)
            try:
                count = _redis.incr(bucket_key)
                if count == 1:
                    # First request in this window — set TTL
                    _redis.expire(bucket_key, 60)

                if count > SETTINGS.RATE_LIMIT_RPM:
                    logger.warning(
                        f"[RateLimit] tenant={tenant_id} count={count} "
                        f"limit={SETTINGS.RATE_LIMIT_RPM} path={path}"
                    )
                    return JSONResponse(
                        status_code=429,
                        headers={
                            "Retry-After": "60",
                            "X-RateLimit-Limit": str(SETTINGS.RATE_LIMIT_RPM),
                            "X-RateLimit-Remaining": "0",
                        },
                        content={
                            "detail": f"Rate limit exceeded. Max {SETTINGS.RATE_LIMIT_RPM} requests/minute.",
                        },
                    )
            except Exception as exc:
                # Fail-open: Redis error must never block legitimate queries
                logger.warning(f"[RateLimit] Redis error (allowing request): {exc}")

        return await call_next(request)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _extract_tenant_id(request: Request) -> str:
    """Best-effort extract tenant_id from request body for rate-limit key.

    Reads the body without consuming it (starlette supports body caching).
    Falls back to client IP if body is not JSON or has no tenant_id.
    """
    try:
        body_bytes = await request.body()
        if body_bytes:
            body = json.loads(body_bytes)
            tid = body.get("tenant_id", "")
            if tid:
                return str(tid)
    except Exception:
        pass
    # Fallback: client IP (covers non-JSON endpoints or missing tenant_id)
    client = request.client
    return client.host if client else "unknown"


def _rate_limit_key(tenant_id: str, request: Request) -> str:
    """Redis key: ratelimit:{tenant_id}:{minute_bucket}"""
    minute_bucket = int(time.time() // 60)
    return f"ratelimit:{tenant_id}:{minute_bucket}"
