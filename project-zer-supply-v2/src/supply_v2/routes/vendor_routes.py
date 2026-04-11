from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from supply_v2.auth import AuthContext, get_auth_context
from supply_v2.dependencies import AppContainer
from supply_v2.policy import require_policy
from supply_v2.rbac import require_permission
from supply_v2.schemas import VendorCreate
from supply_v2.serializers import dispute_dict, po_dict, shipment_dict, vendor_dict


def build_vendor_router(container: AppContainer) -> APIRouter:
    router = APIRouter(tags=["vendors"])

    @router.post("/vendors")
    def create_vendor(
        payload: VendorCreate,
        auth: AuthContext = Depends(require_permission(container, "vendors.manage")),
        _policy: AuthContext = Depends(require_policy(container, "create", "vendor")),
    ):
        with container.lock:
            container.reload()
            vendor = container.platform.register_vendor(tenant_id=auth.tenant_id, **payload.model_dump())
            container.commit()
            return vendor_dict(vendor)

    @router.get("/vendors/{vendor_id}/purchase-orders")
    def list_vendor_purchase_orders(
        vendor_id: str,
        auth: AuthContext = Depends(require_permission(container, "vendors.portal.view")),
        _policy: AuthContext = Depends(require_policy(container, "read", "vendor")),
    ):
        container.reload()
        vendor = container.platform.store.vendors.get(vendor_id)
        if not vendor or vendor.tenant_id != auth.tenant_id:
            raise HTTPException(404, "vendor not found")
        items = [
            po_dict(container.platform, po)
            for po in container.platform.store.purchase_orders.values()
            if po.vendor_id == vendor_id and po.tenant_id == auth.tenant_id
        ]
        return {"items": items}

    @router.get("/vendors/{vendor_id}/shipments")
    def list_vendor_shipments(
        vendor_id: str,
        auth: AuthContext = Depends(require_permission(container, "vendors.portal.view")),
        _policy: AuthContext = Depends(require_policy(container, "read", "shipment")),
    ):
        container.reload()
        vendor = container.platform.store.vendors.get(vendor_id)
        if not vendor or vendor.tenant_id != auth.tenant_id:
            raise HTTPException(404, "vendor not found")
        items = [
            shipment_dict(container.platform, shipment)
            for shipment in container.platform.store.shipments.values()
            if shipment.vendor_id == vendor_id and shipment.tenant_id == auth.tenant_id
        ]
        return {"items": items}

    @router.get("/vendors/{vendor_id}/disputes")
    def list_vendor_disputes(
        vendor_id: str,
        auth: AuthContext = Depends(require_permission(container, "vendors.portal.view")),
        _policy: AuthContext = Depends(require_policy(container, "read", "dispute")),
    ):
        container.reload()
        vendor = container.platform.store.vendors.get(vendor_id)
        if not vendor or vendor.tenant_id != auth.tenant_id:
            raise HTTPException(404, "vendor not found")
        items = [
            dispute_dict(dispute)
            for dispute in container.platform.store.disputes.values()
            if dispute.vendor_id == vendor_id and dispute.tenant_id == auth.tenant_id
        ]
        return {"items": items}

    return router
