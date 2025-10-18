import json
import httpx
from tenacity import retry, stop_after_attempt, wait_fixed
import pybreaker

from core.config import get_settings
from services.provisioning.core.redis_config import redis_client
from services.provisioning.utils.provisioning_logger import logger

SUBSCRIPTIONS_SERVICE_URL = get_settings().SUBSCRIPTIONS_SERVICE_URL

subscription_cb = pybreaker.CircuitBreaker(fail_max=3, reset_timeout=30)
# Subscription limits with retry + circuit breaker + cache
@retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
@subscription_cb
async def get_limits(tid):
    cache_key = f"lim:{tid}"
    if redis_client:
        try:
            cached = redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except:
            pass
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{SUBSCRIPTIONS_SERVICE_URL}/subscriptions/v4/limits", params={"tenant_id": tid})
            if r.status_code == 200:
                lims = r.json()
                if redis_client:
                    try:
                        redis_client.setex(cache_key, 300, json.dumps(lims))
                    except:
                        pass
                return lims
    except Exception as e:
        logger.warning(f"Limits fetch failed: {e}")
    return {"max_sites": 10, "max_stores": 50, "max_users": 100, "max_vendors": 20}