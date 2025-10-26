import json
import time
import uuid
from typing import Dict

from fastapi import Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from services.orders.repositories.database_ops import get_orders_from_db, get_order_by_id, update_order_db, audit, \
    cancel_order_db
from services.orders.repositories.db_config import get_db
from services.orders.repositories.order_saga import OrderSaga
from services.orders.schemas import OrderRequest, OrderUpdateRequest
from services.orders.utils.metrics import orders_requests_total, orders_request_duration
from services.orders.utils.orders_logger import logger
from services.orders.utils.user_auth import get_user_context


async def create_order(
        req: OrderRequest,
        db: Session = Depends(get_db),
        uctx: Dict = Depends(get_user_context)
):
    """Create a new order"""
    start = time.time()
    try:
        orders_requests_total.labels(endpoint="create_order", status="start").inc()

        order_id = uuid.uuid4()
        tenant_id = uctx["tenant_id"]

        saga = OrderSaga(db)
        result = await saga.exec(order_id, tenant_id, req, uctx)

        orders_requests_total.labels(endpoint="create_order", status="ok").inc()
        orders_request_duration.labels(endpoint="create_order").observe(time.time() - start)

        return result

    except ValueError as e:
        orders_requests_total.labels(endpoint="create_order", status="fail").inc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        orders_requests_total.labels(endpoint="create_order", status="fail").inc()
        logger.error("Order creation failed", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


async def get_orders(tenant_id: str, limit: int, offset: int, db: Session = Depends(get_db)):
    """List orders for a tenant"""
    try:
        orders = get_orders_from_db(db, tenant_id, limit, offset)

        return [dict(order._mapping) for order in orders]

    except Exception as e:
        logger.error("Failed to list orders", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


async def get_order(
        order_id: str,
        db: Session = Depends(get_db)
):
    """Get order by ID"""
    try:
        return get_order_by_id(db, order_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get order", order_id=order_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


async def update_order(order_id: str, req: OrderUpdateRequest, db: Session, uctx: Dict = Depends(get_user_context)
):
    """Update order"""
    try:
        update_order_db(req, order_id, db)

        # Audit log
        audit(db, uctx["tenant_id"], uctx["user_id"], "UPDATE", "order", order_id, req.dict())

        return {"order_id": order_id, "updated": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update order", order_id=order_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


async def cancel_order(order_id: str, db: Session, uctx: Dict):
    """Cancel order"""
    try:
        cancel_order_db(order_id, db)
        # Audit log
        audit(db, uctx["tenant_id"], uctx["user_id"], "CANCEL", "order", order_id, {})

        return {"order_id": order_id, "cancelled": True}

    except Exception as e:
        logger.error("Failed to cancel order", order_id=order_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")