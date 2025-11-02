import redis
from core.config import get_settings

REDIS_URL = get_settings().REDIS_URL

# Redis setup
redis_client = redis.from_url(REDIS_URL, decode_responses=True)