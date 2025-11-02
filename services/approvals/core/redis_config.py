import os
from typing import Optional

import redis
from core.config import get_settings

from ..utils.approvals_logger import log
from ..utils.metrics import CACHE_HITS, CACHE_MISSES

REDIS_URL = get_settings().REDIS_URL
REDIS_CACHE_TTL = int(os.getenv("REDIS_CACHE_TTL", "300"))
# Redis Cache
redis_client = None
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

async def get_redis_client():
    """Get Redis client with connection pooling"""
    global redis_client
    if redis_client is None:
        try:
            redis_client = redis.from_url(REDIS_URL, decode_responses=True)
            # Test connection
            redis_client.ping()
            log.info("Redis connection established")
        except Exception as e:
            log.warning(f"Redis connection failed: {str(e)}")
            redis_client = None
    return redis_client


async def cache_get(key: str) -> Optional[str]:
    """Get value from cache"""
    try:
        client = await get_redis_client()
        if client:
            value = client.get(key)
            if value:
                CACHE_HITS.labels(cache_type="general").inc()
                return value
            else:
                CACHE_MISSES.labels(cache_type="general").inc()
        return None
    except Exception as e:
        log.warning(f"Cache get failed: {str(e)}")
        return None


async def cache_set(key: str, value: str, ttl: int = REDIS_CACHE_TTL) -> bool:
    """Set value in cache"""
    try:
        client = await get_redis_client()
        if client:
            client.setex(key, ttl, value)
            return True
        return False
    except Exception as e:
        log.warning(f"Cache set failed: {str(e)}")
        return False


async def cache_delete(key: str) -> bool:
    """Delete value from cache"""
    try:
        client = await get_redis_client()
        if client:
            client.delete(key)
            return True
        return False
    except Exception as e:
        log.warning(f"Cache delete failed: {str(e)}")
        return False