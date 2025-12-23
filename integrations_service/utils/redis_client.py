# Redis setup
import redis

from core.config import SETTINGS
from utils.logger import logger

try:
    redis_client = redis.Redis.from_url(SETTINGS.REDIS_URL, decode_responses=True)
    redis_client.ping()
    logger.info("✅ Redis connected")
except Exception as e:
    redis_client = None
    logger.warning(f"⚠️  Redis unavailable: {e}, caching disabled")