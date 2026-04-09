from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from supply_v2.auth import AuthContext
from supply_v2.dependencies import AppContainer
from supply_v2.idempotency import get_idempotency_key
from supply_v2.policy import require_policy
from supply_v2.rbac import require_permission
from supply_v2.schemas import ShipmentCreate
from supply_v2.serializers import shipment_dict


def build_fulfilment_router(container: AppContainer) -> APIRouter:
    router = APIRouter(tags=["fulfilment"])

    @router.post("/purchase-orders/{po_id}/shipments")
    def create_shipment(
        po_id: str,
        payload: ShipmentCreate,
        auth: AuthContext = Depends(require_permission(container, "shipments.create")),
        _policy: AuthContext = Depends(require_policy(container, "create", "shipment")),
        idempotency_key: Optional[str] = Depends(get_idempotency_key),
    ):
        with container.lock:
            container.reload()
            cached = container.get_idempotent_response(auth.tenant_id, f"POST:/purchase-orders/{po_id}/shipments", idempotency_key)
            if cached:
                return cached
            if po_id not in container.platform.store.purchase_orders:
                raise HTTPException(404, "purchase order not found")
            if container.platform.store.purchase_orders[po_id].tenant_id != auth.tenant_id:
                raise HTTPException(404, "purchase order not found")
            shipment = container.platform.vendor_create_shipment(
                po_id=po_id,
                tracking_number=payload.tracking_number,
                lines=[line.model_dump() for line in payload.lines],
            )
            response = shipment_dict(container.platform, shipment)
            container.save_idempotent_response(auth.tenant_id, f"POST:/purchase-orders/{po_id}/shipments", idempotency_key, response)
            container.commit()
            return response

    return router
