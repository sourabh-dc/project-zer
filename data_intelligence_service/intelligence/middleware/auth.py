"""
JWT Bearer authentication + Redis rate limiting middleware.

AUTH MODEL
  Primary:  Authorization: Bearer <jwt>  — token issued by provisioning_service.
            Decoded with the shared JWT_SECRET (HS256) or JWKS (asymmetric).
            Claims carry: sub (user_id), tenant_id, roles, permissions, email.
  Fallback: X-API-Key: <value>          — service-to-service / dev key.
            Accepted when INTELLIGENCE_API_KEY is configured.

  A request is authenticated when EITHER credential is valid.
  When neither is configured (local dev), auth is disabled.

  Decoded JWT claims are stored on request.state.user_claims so endpoints
  can read user_id / tenant_id / roles / permissions without re-decoding.

  /health and /metrics are public. OPTIONS (CORS preflight) is public.

RATE LIMITING (Redis sliding window):
  Per-tenant, per-minute counter. Key: ratelimit:{tenant_id}:{minute_bucket}
  Tenant ID comes from the JWT claim, else the request body, else client IP.
  Disabled when REDIS_URL is unset or RATE_LIMIT_RPM is 0.
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
from data_intelligence_service.core.user_auth import decode_bearer_token


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

_PUBLIC_PATHS = ("/health", "/metrics", "/docs", "/openapi.json", "/redoc")


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Authenticates every request via JWT Bearer token or X-API-Key."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Public endpoints + CORS preflight never require auth.
        if request.method == "OPTIONS" or any(path.startswith(p) for p in _PUBLIC_PATHS):
            return await call_next(request)

        claims = await self._authenticate(request)
        if claims is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required: Bearer token or X-API-Key"},
            )
        # claims == {} means API-key auth (no JWT claims available)
        request.state.user_claims = claims

        # ── Rate limiting (Redis sliding window) ─────────────────────────────
        if _redis and SETTINGS.RATE_LIMIT_RPM > 0:
            tenant_id = claims.get("tenant_id") or await _extract_tenant_id(request)
            bucket_key = _rate_limit_key(str(tenant_id), request)
            try:
                count = _redis.incr(bucket_key)
                if count == 1:
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

    async def _authenticate(self, request: Request) -> Optional[dict]:
        """Return JWT claims dict, {} for API-key auth, or None if unauthenticated."""
        # ── Primary: Bearer JWT ───────────────────────────────────────────────
        auth_header = request.headers.get("Authorization", "")
        if auth_header:
            try:
                return await decode_bearer_token(auth_header)
            except Exception as exc:
                logger.warning(f"[Auth] JWT decode failed for {request.url.path}: {exc}")
                return None

        # ── Fallback: X-API-Key ───────────────────────────────────────────────
        configured_key = SETTINGS.INTELLIGENCE_API_KEY
        if configured_key:
            provided_key = request.headers.get("X-API-Key", "")
            if provided_key and provided_key == configured_key:
                return {}
            if provided_key:
                logger.warning(f"[Auth] Invalid X-API-Key for {request.url.path}")
                return None
            return None  # key configured but not provided

        # No Bearer token and no API key configured/provided → unauthenticated.
        # (JWT is always available — JWT_SECRET has a dev default — so there is
        # no legitimate "nothing configured" path. All endpoints require auth.)
        return None


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
    client = request.client
    return client.host if client else "unknown"


def _rate_limit_key(tenant_id: str, request: Request) -> str:
    """Redis key: ratelimit:{tenant_id}:{minute_bucket}"""
    minute_bucket = int(time.time() // 60)
    return f"ratelimit:{tenant_id}:{minute_bucket}"
