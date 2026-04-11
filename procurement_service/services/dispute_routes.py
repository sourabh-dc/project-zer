from fastapi import APIRouter, Depends, HTTPException

from procurement_service.Schemas import CustomerDisputeRaiseIn, DisputeResolveIn
from procurement_service.core.helpers.serializers import dispute_dict
from procurement_service.core.policy_client import require_policy
from procurement_service.core.runtime import get_container
from procurement_service.core.user_auth import check_user_authorization


router = APIRouter(tags=["disputes"])


@router.post("/orders/{order_id}/disputes")
async def raise_customer_dispute(
    order_id: str,
    payload: CustomerDisputeRaiseIn,
    ctx=Depends(check_user_authorization("disputes.create")),
    policy=Depends(require_policy("dispute.create")),
):
    container = get_container()
    with container.lock:
        order = container.platform.store.orders.get(order_id)
        if not order or order.tenant_id != ctx.tenant_id:
            raise HTTPException(404, "order not found")
        if payload.order_line_id not in container.platform.store.order_lines:
            raise HTTPException(404, "order line not found")
        try:
            dispute = container.platform.raise_customer_dispute(
                order_id=order_id,
                order_line_id=payload.order_line_id,
                claimed_quantity=payload.claimed_quantity,
                reason=payload.reason,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return dispute_dict(dispute)


@router.get("/disputes")
async def list_disputes(
    order_id: str | None = None,
    vendor_id: str | None = None,
    status: str | None = None,
    source: str | None = None,
    ctx=Depends(check_user_authorization("disputes.view")),
    policy=Depends(require_policy("dispute.read")),
):
    container = get_container()
    items = []
    for dispute in container.platform.store.disputes.values():
        if dispute.tenant_id != ctx.tenant_id:
            continue
        if order_id and dispute.order_id != order_id:
            continue
        if vendor_id and dispute.vendor_id != vendor_id:
            continue
        if status and dispute.status != status:
            continue
        if source and dispute.source != source:
            continue
        items.append(dispute_dict(dispute))
    return {"items": items}


@router.get("/disputes/{dispute_id}")
async def get_dispute(
    dispute_id: str,
    ctx=Depends(check_user_authorization("disputes.view")),
    policy=Depends(require_policy("dispute.read")),
):
    container = get_container()
    dispute = container.platform.store.disputes.get(dispute_id)
    if not dispute or dispute.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "dispute not found")
    return dispute_dict(dispute)


@router.post("/disputes/{dispute_id}/resolve")
async def resolve_dispute(
    dispute_id: str,
    payload: DisputeResolveIn,
    ctx=Depends(check_user_authorization("disputes.resolve")),
    policy=Depends(require_policy("dispute.resolve")),
):
    container = get_container()
    with container.lock:
        dispute = container.platform.store.disputes.get(dispute_id)
        if not dispute or dispute.tenant_id != ctx.tenant_id:
            raise HTTPException(404, "dispute not found")
        result = container.platform.resolve_dispute(dispute_id, payload.resolution)
        return dispute_dict(result)
