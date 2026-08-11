# Redis setup
import redis

from provisioning_service.core.config import SETTINGS
from provisioning_service.utils.logger import logger

try:
    redis_client = redis.Redis.from_url(
        SETTINGS.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    redis_client.ping()
    logger.info("✅ Redis connected")
except Exception as e:
    redis_client = None
    logger.warning(f"⚠️  Redis unavailable: {e}, caching disabled")