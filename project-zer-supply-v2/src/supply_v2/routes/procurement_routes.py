from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException

from supply_v2.auth import AuthContext
from supply_v2.dependencies import AppContainer
from supply_v2.policy import require_policy
from supply_v2.rbac import require_permission
from supply_v2.schemas import AckDecisionIn, CancelLineIn, ReallocateLineIn, VendorDisputeRaiseIn
from supply_v2.serializers import po_dict
from supply_v2.vendor_access import verify_vendor_token


def build_procurement_router(container: AppContainer) -> APIRouter:
    router = APIRouter(tags=["procurement"])

    @router.get("/purchase-orders/{po_id}")
    def get_po(
        po_id: str,
        auth: AuthContext = Depends(require_permission(container, "purchase_orders.view")),
        _policy: AuthContext = Depends(require_policy(container, "read", "purchase_order")),
    ):
        container.reload()
        po = container.platform.store.purchase_orders.get(po_id)
        if not po or po.tenant_id != auth.tenant_id:
            raise HTTPException(404, "purchase order not found")
        return po_dict(container.platform, po)

    @router.post("/purchase-orders/{po_id}/acknowledge")
    def acknowledge_po(
        po_id: str,
        decisions: list[AckDecisionIn],
        auth: AuthContext = Depends(require_permission(container, "purchase_orders.acknowledge")),
        _policy: AuthContext = Depends(require_policy(container, "acknowledge", "purchase_order")),
    ):
        with container.lock:
            container.reload()
            if po_id not in container.platform.store.purchase_orders:
                raise HTTPException(404, "purchase order not found")
            if container.platform.store.purchase_orders[po_id].tenant_id != auth.tenant_id:
                raise HTTPException(404, "purchase order not found")
            po = container.platform.vendor_acknowledge(po_id, [item.model_dump() for item in decisions])
            container.commit()
            return po_dict(container.platform, po)

    @router.post("/purchase-orders/{po_id}/vendor-disputes")
    def raise_vendor_dispute(
        po_id: str,
        payload: VendorDisputeRaiseIn,
        x_vendor_access_token: str = Header(default=""),
    ):
        token = verify_vendor_token(x_vendor_access_token)
        if token["po_id"] != po_id:
            raise HTTPException(403, "vendor token po mismatch")
        with container.lock:
            container.reload()
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
            container.commit()
            return po_dict(container.platform, updated)

    @router.post("/orders/{order_id}/cancel-line")
    def cancel_order_line(
        order_id: str,
        payload: CancelLineIn,
        auth: AuthContext = Depends(require_permission(container, "orders.cancel")),
        _policy: AuthContext = Depends(require_policy(container, "cancel", "order")),
    ):
        with container.lock:
            container.reload()
            order = container.platform.store.orders.get(order_id)
            if not order or order.tenant_id != auth.tenant_id:
                raise HTTPException(404, "order not found")
            try:
                line = container.platform.cancel_order_line(order_id=order_id, order_line_id=payload.order_line_id, reason=payload.reason)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            container.commit()
            return {"order_line_id": line.order_line_id, "status": line.status}

    @router.post("/orders/{order_id}/reallocate-line")
    def reallocate_order_line(
        order_id: str,
        payload: ReallocateLineIn,
        auth: AuthContext = Depends(require_permission(container, "orders.reallocate")),
        _policy: AuthContext = Depends(require_policy(container, "reallocate", "order")),
    ):
        with container.lock:
            container.reload()
            order = container.platform.store.orders.get(order_id)
            if not order or order.tenant_id != auth.tenant_id:
                raise HTTPException(404, "order not found")
            if payload.new_vendor_id not in container.platform.store.vendors:
                raise HTTPException(404, "vendor not found")
            try:
                po = container.platform.reallocate_order_line(
                    order_id=order_id,
                    order_line_id=payload.order_line_id,
                    new_vendor_id=payload.new_vendor_id,
                    reason=payload.reason,
                )
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            container.commit()
            return po_dict(container.platform, po)

    return router
