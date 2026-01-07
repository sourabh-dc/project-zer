from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request

from integrations_service.core.helpers import aifi_services as aifi
from operations_service.operations.orders import upsert_aifi_order
from integrations_service.utils.logger import logger

router = APIRouter(prefix="/integrations/vendors/aifi/webhooks", tags=["integrations"])


@router.post("/orders")
async def aifi_orders_webhook(
    request: Request,
    x_aifi_signature: Optional[str] = Header(default=None, convert_underscores=False),
):
    """
    Lightweight AiFi orders webhook receiver.

    We currently accept and log the payload; extend this to verify signatures
    (if provided by AiFi) and map into our orders/ledger pipeline.
    """
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}")

    # If payload lacks items, try to fetch full order detail using id.
    if isinstance(payload, dict) and "items" not in payload and payload.get("id"):
        try:
            payload = await aifi.fetch_order_detail(str(payload["id"]))
        except Exception as exc:
            logger.warning(f"Failed to fetch order detail for id={payload.get('id')}: {exc}")

    ingest_result = upsert_aifi_order(payload)

    logger.info(
        "Received AiFi orders webhook",
        extra={"signature": x_aifi_signature, "payload": payload, "ingest_result": ingest_result},
    )
    return {"status": "ok", "ingest": ingest_result}

