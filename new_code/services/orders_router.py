import uuid
from datetime import datetime, timezone
from fastapi import HTTPException, Depends, Query, APIRouter
from sqlalchemy.orm import Session

from Models import Order, OrderItem
from Schemas import OrderRequest, OrderUpdateRequest
from core.db_config import get_db

app = APIRouter()

# =============================================================================
# ORDER ENDPOINTS
# =============================================================================

@app.post("/orders")
async def create_order(
        req: OrderRequest,
        db: Session = Depends(get_db)
):
    """Create a new order"""
    try:
        order_id = uuid.uuid4()
        tenant_id = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")  # Demo tenant

        # Validate and convert UUIDs
        try:
            customer_uuid = uuid.UUID(req.customer_id) if req.customer_id and req.customer_id.strip() else uuid.uuid4()
        except (ValueError, AttributeError):
            customer_uuid = uuid.uuid4()

        try:
            site_uuid = uuid.UUID(req.site_id) if req.site_id and req.site_id.strip() else None
        except (ValueError, AttributeError):
            site_uuid = None

        try:
            store_uuid = uuid.UUID(req.store_id) if req.store_id and req.store_id.strip() else None
        except (ValueError, AttributeError):
            store_uuid = None

        # Create order
        order = Order(
            order_id=order_id,
            tenant_id=tenant_id,
            site_id=site_uuid,
            store_id=store_uuid,
            customer_id=customer_uuid,
            order_number=f"ORD-{int(datetime.now(timezone.utc).timestamp())}",
            order_type=req.order_type,
            shipping_address=req.shipping_address,
            billing_address=req.billing_address,
            order_metadata=req.metadata
        )
        db.add(order)
        db.flush()

        # Calculate total amount and add items
        total_amount = 0
        for item_data in req.items:
            try:
                product_uuid = uuid.UUID(item_data['product_id'])
            except (ValueError, KeyError):
                product_uuid = uuid.uuid4()

            try:
                variant_uuid = uuid.UUID(item_data.get('variant_id')) if item_data.get('variant_id') else None
            except (ValueError, TypeError):
                variant_uuid = None

            item = OrderItem(
                order_id=order_id,
                product_id=product_uuid,
                variant_id=variant_uuid,
                quantity=item_data['quantity'],
                unit_price_minor=item_data['unit_price_minor'],
                total_price_minor=item_data['quantity'] * item_data['unit_price_minor']
            )
            db.add(item)
            total_amount += item.total_price_minor

        order.total_amount_minor = total_amount
        db.commit()
        db.refresh(order)

        return {
            "order_id": str(order_id),
            "order_number": order.order_number,
            "total_amount_minor": total_amount,
            "created": True
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/orders")
async def list_orders(
        tenant_id: str = Query(...),
        limit: int = Query(100, le=1000),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db)
):
    """List orders for a tenant"""
    try:
        orders = db.query(Order).filter(
            Order.tenant_id == uuid.UUID(tenant_id)
        ).order_by(Order.created_at.desc()).offset(offset).limit(limit).all()

        return {
            "orders": [
                {
                    "order_id": str(o.order_id),
                    "order_number": o.order_number,
                    "order_status": o.order_status,
                    "total_amount_minor": o.total_amount_minor,
                    "currency": o.currency,
                    "payment_status": o.payment_status,
                    "fulfillment_status": o.fulfillment_status,
                    "created_at": o.created_at.isoformat(),
                    "updated_at": o.updated_at.isoformat() if o.updated_at else None
                }
                for o in orders
            ],
            "total": len(orders),
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/orders/{order_id}")
async def get_order(
        order_id: str,
        db: Session = Depends(get_db)
):
    """Get order by ID"""
    try:
        order = db.query(Order).filter(
            Order.order_id == uuid.UUID(order_id)
        ).first()

        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        # Get order items
        items = db.query(OrderItem).filter(
            OrderItem.order_id == uuid.UUID(order_id)
        ).all()

        return {
            "order_id": str(order.order_id),
            "order_number": order.order_number,
            "order_status": order.order_status,
            "order_type": order.order_type,
            "total_amount_minor": order.total_amount_minor,
            "currency": order.currency,
            "payment_status": order.payment_status,
            "fulfillment_status": order.fulfillment_status,
            "shipping_address": order.shipping_address,
            "billing_address": order.billing_address,
            "items": [
                {
                    "item_id": str(i.item_id),
                    "product_id": str(i.product_id),
                    "variant_id": str(i.variant_id) if i.variant_id else None,
                    "quantity": i.quantity,
                    "unit_price_minor": i.unit_price_minor,
                    "total_price_minor": i.total_price_minor
                }
                for i in items
            ],
            "created_at": order.created_at.isoformat(),
            "updated_at": order.updated_at.isoformat() if order.updated_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/orders/{order_id}")
async def update_order(
        order_id: str,
        req: OrderUpdateRequest,
        db: Session = Depends(get_db)
):
    """Update order"""
    try:
        order = db.query(Order).filter(
            Order.order_id == uuid.UUID(order_id)
        ).first()

        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        if req.order_status:
            order.order_status = req.order_status

        if req.payment_status:
            order.payment_status = req.payment_status

        if req.fulfillment_status:
            order.fulfillment_status = req.fulfillment_status

        if req.metadata:
            order.order_metadata = req.metadata

        db.commit()
        db.refresh(order)

        return {
            "order_id": str(order.order_id),
            "order_status": order.order_status,
            "payment_status": order.payment_status,
            "fulfillment_status": order.fulfillment_status,
            "updated": True
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/orders/{order_id}")
async def cancel_order(
        order_id: str,
        db: Session = Depends(get_db)
):
    """Cancel order"""
    try:
        order = db.query(Order).filter(
            Order.order_id == uuid.UUID(order_id)
        ).first()

        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        order.order_status = "cancelled"
        db.commit()

        return {
            "order_id": str(order.order_id),
            "order_status": "cancelled",
            "cancelled": True
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ORDER ITEMS ENDPOINTS
# =============================================================================

@app.get("/orders/{order_id}/items")
async def get_order_items(
        order_id: str,
        db: Session = Depends(get_db)
):
    """Get items for an order"""
    try:
        items = db.query(OrderItem).filter(
            OrderItem.order_id == uuid.UUID(order_id)
        ).all()

        return {
            "order_id": order_id,
            "items": [
                {
                    "item_id": str(i.item_id),
                    "product_id": str(i.product_id),
                    "variant_id": str(i.variant_id) if i.variant_id else None,
                    "quantity": i.quantity,
                    "unit_price_minor": i.unit_price_minor,
                    "total_price_minor": i.total_price_minor,
                    "created_at": i.created_at.isoformat()
                }
                for i in items
            ],
            "total": len(items)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# QUERY ENDPOINTS
# =============================================================================

@app.get("/orders/status/{status}")
async def get_orders_by_status(
        status: str,
        tenant_id: str = Query(...),
        limit: int = Query(100, le=1000),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db)
):
    """Get orders by status"""
    try:
        orders = db.query(Order).filter(
            Order.tenant_id == uuid.UUID(tenant_id),
            Order.order_status == status
        ).order_by(Order.created_at.desc()).offset(offset).limit(limit).all()

        return {
            "status": status,
            "orders": [
                {
                    "order_id": str(o.order_id),
                    "order_number": o.order_number,
                    "total_amount_minor": o.total_amount_minor,
                    "payment_status": o.payment_status,
                    "fulfillment_status": o.fulfillment_status,
                    "created_at": o.created_at.isoformat()
                }
                for o in orders
            ],
            "total": len(orders),
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/orders/customer/{customer_id}")
async def get_customer_orders(
        customer_id: str,
        tenant_id: str = Query(...),
        limit: int = Query(100, le=1000),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db)
):
    """Get orders for a customer"""
    try:
        orders = db.query(Order).filter(
            Order.tenant_id == uuid.UUID(tenant_id),
            Order.customer_id == uuid.UUID(customer_id)
        ).order_by(Order.created_at.desc()).offset(offset).limit(limit).all()

        return {
            "customer_id": customer_id,
            "orders": [
                {
                    "order_id": str(o.order_id),
                    "order_number": o.order_number,
                    "order_status": o.order_status,
                    "total_amount_minor": o.total_amount_minor,
                    "created_at": o.created_at.isoformat()
                }
                for o in orders
            ],
            "total": len(orders),
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
