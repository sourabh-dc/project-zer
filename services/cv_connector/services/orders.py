import httpx
from ..config import settings

async def post_checkout_to_cv_gateway(mapped_order: dict) -> dict:
    # Use provider_order_id as Idempotency-Key for safe retries
    idem = mapped_order.get("provider_order_id") or ""
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"{settings.CV_GATEWAY_BASE_URL}/cv/aifi/webhook/order",
            json=mapped_order,
            headers={"Idempotency-Key": idem} if idem else {}
        )
    r.raise_for_status()
    return r.json()