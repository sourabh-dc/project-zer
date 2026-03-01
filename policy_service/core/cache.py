"""
Policy Engine — Redis cache layer.

Caching strategy (from architecture doc §11.2):
  "policies:{tenant_id}:{action}" → applicable policy IDs    (TTL: 5 min)
  "policy_rules:{policy_id}"      → current version rules     (TTL: 5 min)
  "user_context:{user_id}"        → enriched subject data     (TTL: 60s)
  "approved_products:{org_unit}"   → product ID set           (TTL: 5 min)

Cache invalidation:
  Policy CRUD → invalidate "policies:*" and "policy_rules:{id}"
  User role change → invalidate "user_context:{user_id}"
  Approved range change → invalidate "approved_products:{org_unit}"
"""
import json
from typing import Any, Dict, Optional

from policy_service.core.config import SETTINGS
from policy_service.utils.logger import logger

_redis_client = None

POLICY_TTL = 300       # 5 min
USER_CONTEXT_TTL = 60  # 60s


def _get_redis():
    """Lazy-init Redis client. Returns None if Redis is unavailable."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis
        _redis_client = redis.Redis.from_url(
            SETTINGS.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=1,
        )
        _redis_client.ping()
        logger.info("Redis cache connected")
        return _redis_client
    except Exception as exc:
        logger.warning(f"Redis unavailable, operating without cache: {exc}")
        _redis_client = None
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


def cache_set(key: str, value: Any, ttl: int = POLICY_TTL) -> None:
    r = _get_redis()
    if not r:
        return
    try:
        r.setex(key, ttl, json.dumps(value, default=str))
    except Exception:
        pass


def cache_delete_pattern(pattern: str) -> None:
    """Delete all keys matching a pattern. Safe no-op if Redis is down."""
    r = _get_redis()
    if not r:
        return
    try:
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                r.delete(*keys)
            if cursor == 0:
                break
    except Exception as exc:
        logger.warning(f"Cache invalidation failed for pattern {pattern}: {exc}")


def invalidate_policies(tenant_id: str = "*", policy_id: str = None) -> None:
    cache_delete_pattern(f"policies:{tenant_id}:*")
    if policy_id:
        cache_delete_pattern(f"policy_rules:{policy_id}")


def invalidate_user_context(user_id: str) -> None:
    r = _get_redis()
    if r:
        try:
            r.delete(f"user_context:{user_id}")
        except Exception:
            pass


def invalidate_approved_products(org_unit_id: str = "*") -> None:
    cache_delete_pattern(f"approved_products:{org_unit_id}")
