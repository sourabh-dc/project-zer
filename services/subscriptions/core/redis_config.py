import redis

from core.config import get_settings

REDIS_URL = get_settings().REDIS_URL


redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)