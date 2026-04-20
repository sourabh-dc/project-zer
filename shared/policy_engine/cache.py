"""
shared/policy_engine/cache.py
------------------------------
Redis cache layer for the policy engine.

Caching strategy:
  "user_context:{user_id}"  — enriched subject data  (TTL: 60s)

Redis is optional — all cache operations are no-ops if Redis is unavailable.
Set POLICY_REDIS_URL (or REDIS_URL) in the environment to enable caching.
"""
import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("policy_engine.cache")

_REDIS_URL = os.getenv("POLICY_REDIS_URL") or os.getenv("REDIS_URL", "redis://localhost:6379/0")

USER_CONTEXT_TTL = 60   # seconds

_redis_client = None


def _get_redis():
    """Lazy-init Redis client. Returns None if Redis is unavailable."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis
        client = redis.Redis.from_url(
            _REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=1,
        )
        client.ping()
        _redis_client = client
        logger.info("Policy engine Redis cache connected")
        return _redis_client
    except Exception as exc:
        logger.debug(f"Redis unavailable, operating without cache: {exc}")
        return None


def cache_get(key: str) -> Optional[Dict[str, Any]]:
    r = _get_redis()
    if not r:
        return None
    try:
        data = r.get(key)
        return json.loads(data) if data else None
    except Exception:
        return None


def cache_set(key: str, value: Any, ttl: int = USER_CONTEXT_TTL) -> None:
    r = _get_redis()
    if not r:
        return
    try:
        r.setex(key, ttl, json.dumps(value, default=str))
    except Exception:
        pass


def invalidate_user_context(user_id: str) -> None:
    r = _get_redis()
    if r:
        try:
            r.delete(f"user_context:{user_id}")
        except Exception:
            pass
