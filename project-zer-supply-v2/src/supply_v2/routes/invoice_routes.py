from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from supply_v2.auth import AuthContext
from supply_v2.dependencies import AppContainer
from supply_v2.idempotency import get_idempotency_key
from supply_v2.policy import require_policy
from supply_v2.rbac import require_permission
from supply_v2.schemas import InvoiceCreate
from supply_v2.serializers import invoice_dict, sla_dict


def build_invoice_router(container: AppContainer) -> APIRouter:
    router = APIRouter(tags=["invoices"])

    @router.post("/purchase-orders/{po_id}/invoices")
    def create_invoice(
        po_id: str,
        payload: InvoiceCreate,
        auth: AuthContext = Depends(require_permission(container, "invoices.create")),
        _policy: AuthContext = Depends(require_policy(container, "create", "invoice")),
        idempotency_key: Optional[str] = Depends(get_idempotency_key),
    ):
        with container.lock:
            container.reload()
            cached = container.get_idempotent_response(auth.tenant_id, f"POST:/purchase-orders/{po_id}/invoices", idempotency_key)
            if cached:
                return cached
            po = container.platform.store.purchase_orders.get(po_id)
            if not po or po.tenant_id != auth.tenant_id:
                raise HTTPException(404, "purchase order not found")
            invoice = container.platform.create_invoice(
                tenant_id=auth.tenant_id,
                po_id=po_id,
                invoice_number=payload.invoice_number,
                lines=[line.model_dump() for line in payload.lines],
            )
            response = invoice_dict(container.platform, invoice)
            container.save_idempotent_response(auth.tenant_id, f"POST:/purchase-orders/{po_id}/invoices", idempotency_key, response)
            container.commit()
            return response

    @router.get("/purchase-orders/{po_id}/slas")
    def list_po_slas(
        po_id: str,
        auth: AuthContext = Depends(require_permission(container, "slas.view")),
        _policy: AuthContext = Depends(require_policy(container, "read", "purchase_order")),
    ):
        container.reload()
        po = container.platform.store.purchase_orders.get(po_id)
        if not po or po.tenant_id != auth.tenant_id:
            raise HTTPException(404, "purchase order not found")
        slas = [
            sla_dict(item)
            for item in container.platform.store.sla_records.values()
            if item.entity_id == po_id and item.tenant_id == auth.tenant_id
        ]
        return {"items": slas}

    return router
