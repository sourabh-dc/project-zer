import redis
from core.config import get_settings
from ..utils.provisioning_logger import logger

REDIS_URL = get_settings().REDIS_URL

try:
    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
    logger.info("Redis connected")
except:
    redis_client = None
    logger.warning("Redis unavailable, caching disabled")