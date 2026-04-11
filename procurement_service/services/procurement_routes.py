from fastapi import APIRouter, Depends, Header, HTTPException

from procurement_service.Schemas import AckDecisionIn, CancelLineIn, ReallocateLineIn, VendorDisputeRaiseIn
from procurement_service.core.helpers.serializers import po_dict
from procurement_service.core.policy_client import require_policy
from procurement_service.core.procurement_engine import verify_vendor_token
from procurement_service.core.runtime import get_container
from procurement_service.core.user_auth import check_user_authorization


router = APIRouter(tags=["procurement"])


@router.get("/purchase-orders/{po_id}")
async def get_po(
    po_id: str,
    ctx=Depends(check_user_authorization("purchase_orders.view")),
    policy=Depends(require_policy("purchase_order.read")),
):
    container = get_container()
    po = container.platform.store.purchase_orders.get(po_id)
    if not po or po.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "purchase order not found")
    return po_dict(container.platform, po)


@router.post("/purchase-orders/{po_id}/acknowledge")
async def acknowledge_po(
    po_id: str,
    decisions: list[AckDecisionIn],
    ctx=Depends(check_user_authorization("purchase_orders.acknowledge")),
    policy=Depends(require_policy("purchase_order.acknowledge")),
):
    container = get_container()
    with container.lock:
        po = container.platform.store.purchase_orders.get(po_id)
        if not po or po.tenant_id != ctx.tenant_id:
            raise HTTPException(404, "purchase order not found")
        updated = container.platform.vendor_acknowledge(po_id, [item.model_dump() for item in decisions])
        return po_dict(container.platform, updated)


@router.post("/purchase-orders/{po_id}/vendor-disputes")
async def raise_vendor_dispute(po_id: str, payload: VendorDisputeRaiseIn, x_vendor_access_token: str = Header(default="")):
    container = get_container()
    try:
        token = verify_vendor_token(x_vendor_access_token)
    except Exception as exc:
        raise HTTPException(403, f"vendor token invalid: {exc}") from exc

    if token["po_id"] != po_id:
        raise HTTPException(403, "vendor token po mismatch")

    with container.lock:
        po = container.platform.store.purchase_orders.get(po_id)
        if not po:
            raise HTTPException(404, "purchase order not found")
        if po.vendor_id != token["vendor_id"] or po.tenant_id != token["tenant_id"]:
            raise HTTPException(403, "vendor token scope denied")

        updated = container.platform.vendor_acknowledge(
            po_id,
            [
                {
                    "po_line_id": payload.po_line_id,
                    "accepted_quantity": payload.accepted_quantity,
                    "proposed_unit_price_minor": payload.proposed_unit_price_minor,
                    "status": payload.status,
                    "reason": payload.reason,
                }
            ],
        )
        return po_dict(container.platform, updated)


@router.post("/orders/{order_id}/cancel-line")
async def cancel_order_line(
    order_id: str,
    payload: CancelLineIn,
    ctx=Depends(check_user_authorization("orders.cancel")),
    policy=Depends(require_policy("order.cancel")),
):
    container = get_container()
    with container.lock:
        order = container.platform.store.orders.get(order_id)
        if not order or order.tenant_id != ctx.tenant_id:
            raise HTTPException(404, "order not found")
        try:
            line = container.platform.cancel_order_line(order_id, payload.order_line_id, payload.reason)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"order_line_id": line.order_line_id, "status": line.status}


@router.post("/orders/{order_id}/reallocate-line")
async def reallocate_order_line(
    order_id: str,
    payload: ReallocateLineIn,
    ctx=Depends(check_user_authorization("orders.reallocate")),
    policy=Depends(require_policy("order.reallocate")),
):
    container = get_container()
    with container.lock:
        order = container.platform.store.orders.get(order_id)
        if not order or order.tenant_id != ctx.tenant_id:
            raise HTTPException(404, "order not found")
        if payload.new_vendor_id not in container.platform.store.vendors:
            raise HTTPException(404, "vendor not found")
        try:
            po = container.platform.reallocate_order_line(order_id, payload.order_line_id, payload.new_vendor_id, payload.reason)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return po_dict(container.platform, po)
