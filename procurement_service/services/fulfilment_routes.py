from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from procurement_service.Schemas import ShipmentCreate
from procurement_service.core.helpers.serializers import shipment_dict
from procurement_service.core.policy_client import require_policy
from procurement_service.core.runtime import get_container
from procurement_service.core.user_auth import check_user_authorization


router = APIRouter(tags=["fulfilment"])


@router.post("/purchase-orders/{po_id}/shipments")
async def create_shipment(
    po_id: str,
    payload: ShipmentCreate,
    x_idempotency_key: Optional[str] = Header(default=None),
    ctx=Depends(check_user_authorization("shipments.create")),
    policy=Depends(require_policy("shipment.create")),
):
    container = get_container()
    with container.lock:
        cached = container.get_idempotent_response(ctx.tenant_id, f"POST:/purchase-orders/{po_id}/shipments", x_idempotency_key)
        if cached:
            return cached

        po = container.platform.store.purchase_orders.get(po_id)
        if not po or po.tenant_id != ctx.tenant_id:
            raise HTTPException(404, "purchase order not found")
        shipment = container.platform.create_shipment(po_id, payload.tracking_number, [line.model_dump() for line in payload.lines])
        response = shipment_dict(container.platform, shipment)
        container.save_idempotent_response(ctx.tenant_id, f"POST:/purchase-orders/{po_id}/shipments", x_idempotency_key, response)
        return response
