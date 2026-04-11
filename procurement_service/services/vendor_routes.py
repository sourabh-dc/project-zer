from fastapi import APIRouter, Depends, HTTPException

from procurement_service.Schemas import VendorCreate
from procurement_service.core.helpers.serializers import dispute_dict, po_dict, shipment_dict, vendor_dict
from procurement_service.core.policy_client import require_policy
from procurement_service.core.runtime import get_container
from procurement_service.core.user_auth import check_user_authorization


router = APIRouter(tags=["vendors"])


@router.post("/vendors")
async def create_vendor(
    payload: VendorCreate,
    ctx=Depends(check_user_authorization("vendors.manage")),
    policy=Depends(require_policy("vendor.create")),
):
    container = get_container()
    with container.lock:
        vendor = container.platform.register_vendor(tenant_id=ctx.tenant_id, **payload.model_dump())
        return vendor_dict(vendor)


@router.get("/vendors/{vendor_id}/purchase-orders")
async def list_vendor_purchase_orders(
    vendor_id: str,
    ctx=Depends(check_user_authorization("vendors.portal.view")),
    policy=Depends(require_policy("vendor.read")),
):
    container = get_container()
    vendor = container.platform.store.vendors.get(vendor_id)
    if not vendor or vendor.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "vendor not found")
    items = [
        po_dict(container.platform, po)
        for po in container.platform.store.purchase_orders.values()
        if po.vendor_id == vendor_id and po.tenant_id == ctx.tenant_id
    ]
    return {"items": items}


@router.get("/vendors/{vendor_id}/shipments")
async def list_vendor_shipments(
    vendor_id: str,
    ctx=Depends(check_user_authorization("vendors.portal.view")),
    policy=Depends(require_policy("shipment.read")),
):
    container = get_container()
    vendor = container.platform.store.vendors.get(vendor_id)
    if not vendor or vendor.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "vendor not found")
    items = [
        shipment_dict(container.platform, shipment)
        for shipment in container.platform.store.shipments.values()
        if shipment.vendor_id == vendor_id and shipment.tenant_id == ctx.tenant_id
    ]
    return {"items": items}


@router.get("/vendors/{vendor_id}/disputes")
async def list_vendor_disputes(
    vendor_id: str,
    ctx=Depends(check_user_authorization("vendors.portal.view")),
    policy=Depends(require_policy("dispute.read")),
):
    container = get_container()
    vendor = container.platform.store.vendors.get(vendor_id)
    if not vendor or vendor.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "vendor not found")
    items = [
        dispute_dict(dispute)
        for dispute in container.platform.store.disputes.values()
        if dispute.vendor_id == vendor_id and dispute.tenant_id == ctx.tenant_id
    ]
    return {"items": items}
