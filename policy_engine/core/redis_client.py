"""
Policy Engine Redis Client
Redis connection for caching policies and rules
"""
import json
from typing import Optional, Any
import redis.asyncio as redis
from redis.asyncio import Redis

from policy_engine.core.config import SETTINGS
from policy_engine.utils.logger import logger


class PolicyCache:
    """
    Redis-based cache for policy data.
    Provides async methods for caching and retrieving policies.
    """
    
    def __init__(self):
        self._client: Optional[Redis] = None
        self._connected = False
    
    async def connect(self) -> bool:
        """Initialize Redis connection"""
        if self._connected and self._client:
            return True
        
        try:
            self._client = redis.from_url(
                SETTINGS.REDIS_URL,
                encoding="utf-8",
                decode_responses=True
            )
            # Test connection
            await self._client.ping()
            self._connected = True
            logger.info("✅ Policy Engine Redis connected")
            return True
        except Exception as e:
            logger.warning(f"⚠️ Redis connection failed (caching disabled): {e}")
            self._connected = False
            self._client = None
            return False
    
    async def disconnect(self):
        """Close Redis connection"""
        if self._client:
            await self._client.close()
            self._connected = False
            self._client = None
            logger.info("Redis connection closed")
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        if not self._connected or not self._client:
            return None
        
        try:
            value = await self._client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.warning(f"Cache get error for {key}: {e}")
            return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set value in cache with optional TTL"""
        if not self._connected or not self._client:
            return False
        
        try:
            ttl = ttl or SETTINGS.POLICY_CACHE_TTL_SECONDS
            await self._client.setex(key, ttl, json.dumps(value, default=str))
            return True
        except Exception as e:
            logger.warning(f"Cache set error for {key}: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete key from cache"""
        if not self._connected or not self._client:
            return False
        
        try:
            await self._client.delete(key)
            return True
        except Exception as e:
            logger.warning(f"Cache delete error for {key}: {e}")
            return False
    
    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern"""
        if not self._connected or not self._client:
            return 0
        
        try:
            keys = []
            async for key in self._client.scan_iter(match=pattern):
                keys.append(key)
            
            if keys:
                return await self._client.delete(*keys)
            return 0
        except Exception as e:
            logger.warning(f"Cache delete pattern error for {pattern}: {e}")
            return 0
    
    async def invalidate_policy(self, policy_id: str, tenant_id: Optional[str] = None):
        """Invalidate cache for a specific policy"""
        # Delete all cached entries related to this policy
        patterns = [
            f"policy:{policy_id}:*",
            f"policies:*:{policy_id}",
        ]
        if tenant_id:
            patterns.append(f"policies:{tenant_id}:*")
        
        for pattern in patterns:
            await self.delete_pattern(pattern)
    
    async def invalidate_tenant_policies(self, tenant_id: str):
        """Invalidate all cached policies for a tenant"""
        await self.delete_pattern(f"policies:{tenant_id}:*")
    
    @property
    def is_connected(self) -> bool:
        return self._connected


# Global cache instance
policy_cache = PolicyCache()


async def get_cache() -> PolicyCache:
    """FastAPI dependency for cache access"""
    return policy_cache
