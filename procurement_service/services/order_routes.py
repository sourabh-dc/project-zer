from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from procurement_service.Schemas import OrderCreate, ReceiptCreate
from procurement_service.core.db_config import ProcurementOrder, ProcurementOrderDetail, SessionLocal
from procurement_service.core.helpers.serializers import order_dict, receipt_dict
from procurement_service.core.notification_dispatcher import dispatch_queued_notifications
from procurement_service.core.policy_client import require_policy
from procurement_service.core.runtime import get_container
from procurement_service.core.user_auth import check_user_authorization


router = APIRouter(tags=["orders"])


def _persist_order_snapshot(response: dict, tenant_id: str, customer_email: str) -> None:
    total_cost_minor = sum(line["ordered_quantity"] * line["unit_price_minor"] for line in response["lines"])
    db = SessionLocal()
    try:
        order_row = ProcurementOrder(
            order_id=response["order_id"],
            tenant_id=tenant_id,
            order_number=response["order_number"],
            customer_id=response["customer_id"],
            customer_email=customer_email,
            status=response["status"],
            total_cost_minor=total_cost_minor,
            created_at=datetime.utcnow(),
        )
        db.merge(order_row)
        for line in response["lines"]:
            db.merge(
                ProcurementOrderDetail(
                    order_line_id=line["order_line_id"],
                    order_id=response["order_id"],
                    tenant_id=tenant_id,
                    vendor_id=line["vendor_id"],
                    sku=line["sku"],
                    description=line["description"],
                    quantity=line["ordered_quantity"],
                    unit_price_minor=line["unit_price_minor"],
                    line_total_minor=line["ordered_quantity"] * line["unit_price_minor"],
                    status=line["status"],
                    created_at=datetime.utcnow(),
                )
            )
        db.commit()
    finally:
        db.close()


@router.post("/orders")
async def create_order(
    payload: OrderCreate,
    x_idempotency_key: Optional[str] = Header(default=None),
    ctx=Depends(check_user_authorization("orders.create")),
    policy=Depends(require_policy("order.create")),
):
    container = get_container()
    with container.lock:
        cached = container.get_idempotent_response(ctx.tenant_id, "POST:/orders", x_idempotency_key)
        if cached:
            return cached
        order = container.platform.place_customer_order(
            tenant_id=ctx.tenant_id,
            customer_id=payload.customer_id,
            customer_email=payload.customer_email,
            ship_to=payload.ship_to,
            items=[item.model_dump() for item in payload.items],
        )
        response = order_dict(container.platform, order)
        _persist_order_snapshot(response, ctx.tenant_id, payload.customer_email)
        dispatch_queued_notifications(container, order_id=order.order_id)
        container.save_idempotent_response(ctx.tenant_id, "POST:/orders", x_idempotency_key, response)
        return response


@router.get("/orders")
async def list_orders(
    customer_id: Optional[str] = None,
    ctx=Depends(check_user_authorization("orders.view")),
    policy=Depends(require_policy("order.read")),
):
    container = get_container()
    items = []
    for order in container.platform.store.orders.values():
        if order.tenant_id != ctx.tenant_id:
            continue
        if customer_id and order.customer_id != customer_id:
            continue
        items.append(order_dict(container.platform, order))
    return {"items": items}


@router.get("/orders/{order_id}")
async def get_order(
    order_id: str,
    ctx=Depends(check_user_authorization("orders.view")),
    policy=Depends(require_policy("order.read")),
):
    container = get_container()
    order = container.platform.store.orders.get(order_id)
    if not order or order.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "order not found")
    return order_dict(container.platform, order)


@router.post("/orders/{order_id}/receipts")
async def create_receipt(
    order_id: str,
    payload: ReceiptCreate,
    x_idempotency_key: Optional[str] = Header(default=None),
    ctx=Depends(check_user_authorization("receipts.create")),
    policy=Depends(require_policy("shipment.create")),
):
    container = get_container()
    with container.lock:
        cached = container.get_idempotent_response(ctx.tenant_id, f"POST:/orders/{order_id}/receipts", x_idempotency_key)
        if cached:
            return cached

        order = container.platform.store.orders.get(order_id)
        if not order or order.tenant_id != ctx.tenant_id:
            raise HTTPException(404, "order not found")
        if payload.shipment_id not in container.platform.store.shipments:
            raise HTTPException(404, "shipment not found")

        receipt = container.platform.record_receipt(
            order_id=order_id,
            shipment_id=payload.shipment_id,
            lines=[line.model_dump() for line in payload.lines],
        )
        response = receipt_dict(container.platform, receipt)
        container.save_idempotent_response(ctx.tenant_id, f"POST:/orders/{order_id}/receipts", x_idempotency_key, response)
        return response


@router.post("/orders/{order_id}/finalize")
async def finalize_order(
    order_id: str,
    ctx=Depends(check_user_authorization("orders.finalize")),
    policy=Depends(require_policy("order.update")),
):
    container = get_container()
    with container.lock:
        order = container.platform.store.orders.get(order_id)
        if not order or order.tenant_id != ctx.tenant_id:
            raise HTTPException(404, "order not found")
        updated = container.platform.finalize_order(order_id)
        return order_dict(container.platform, updated)
