from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from supply_v2.auth import AuthContext, get_auth_context
from supply_v2.dependencies import AppContainer
from supply_v2.idempotency import get_idempotency_key
from supply_v2.policy import require_policy
from supply_v2.rbac import require_permission
from supply_v2.schemas import OrderCreate, ReceiptCreate
from supply_v2.serializers import order_dict, receipt_dict


def build_order_router(container: AppContainer) -> APIRouter:
    router = APIRouter(tags=["orders"])

    @router.post("/orders")
    def create_order(
        payload: OrderCreate,
        auth: AuthContext = Depends(require_permission(container, "orders.create")),
        _policy: AuthContext = Depends(require_policy(container, "create", "order")),
        idempotency_key: Optional[str] = Depends(get_idempotency_key),
    ):
        with container.lock:
            container.reload()
            cached = container.get_idempotent_response(auth.tenant_id, "POST:/orders", idempotency_key)
            if cached:
                return cached
            order = container.platform.place_customer_order(
                tenant_id=auth.tenant_id,
                customer_id=payload.customer_id,
                ship_to=payload.ship_to,
                items=[item.model_dump() for item in payload.items],
            )
            response = order_dict(container.platform, container.platform.store.orders[order.order_id])
            container.save_idempotent_response(auth.tenant_id, "POST:/orders", idempotency_key, response)
            container.commit()
            return response

    @router.get("/orders/{order_id}")
    def get_order(
        order_id: str,
        auth: AuthContext = Depends(require_permission(container, "orders.view")),
        _policy: AuthContext = Depends(require_policy(container, "read", "order")),
    ):
        container.reload()
        order = container.platform.store.orders.get(order_id)
        if not order or order.tenant_id != auth.tenant_id:
            raise HTTPException(404, "order not found")
        return order_dict(container.platform, order)

    @router.post("/orders/{order_id}/receipts")
    def create_receipt(
        order_id: str,
        payload: ReceiptCreate,
        auth: AuthContext = Depends(require_permission(container, "receipts.create")),
        _policy: AuthContext = Depends(require_policy(container, "create", "shipment")),
        idempotency_key: Optional[str] = Depends(get_idempotency_key),
    ):
        with container.lock:
            container.reload()
            cached = container.get_idempotent_response(auth.tenant_id, f"POST:/orders/{order_id}/receipts", idempotency_key)
            if cached:
                return cached
            if order_id not in container.platform.store.orders:
                raise HTTPException(404, "order not found")
            if container.platform.store.orders[order_id].tenant_id != auth.tenant_id:
                raise HTTPException(404, "order not found")
            if payload.shipment_id not in container.platform.store.shipments:
                raise HTTPException(404, "shipment not found")
            receipt = container.platform.customer_record_receipt(
                order_id=order_id,
                shipment_id=payload.shipment_id,
                lines=[line.model_dump() for line in payload.lines],
            )
            response = receipt_dict(container.platform, receipt)
            container.save_idempotent_response(auth.tenant_id, f"POST:/orders/{order_id}/receipts", idempotency_key, response)
            container.commit()
            return response

    @router.post("/orders/{order_id}/finalize")
    def finalize_order(
        order_id: str,
        auth: AuthContext = Depends(require_permission(container, "orders.finalize")),
        _policy: AuthContext = Depends(require_policy(container, "update", "order")),
    ):
        with container.lock:
            container.reload()
            if order_id not in container.platform.store.orders:
                raise HTTPException(404, "order not found")
            if container.platform.store.orders[order_id].tenant_id != auth.tenant_id:
                raise HTTPException(404, "order not found")
            container.platform.finalize_order(order_id)
            container.commit()
            return order_dict(container.platform, container.platform.store.orders[order_id])

    return router
