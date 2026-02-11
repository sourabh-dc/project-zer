"""
Order Service - Refactored with Policy Engine Integration

Policies enforced:
1. order.cost_centre_assignment - User must be assigned to a cost centre
2. order.budget.check - User must have sufficient budget
3. order.large_order_approval - Orders exceeding user's limit require approval
"""

import uuid
import json
from datetime import datetime, timezone
from fastapi import HTTPException, Depends, Query, APIRouter
from sqlalchemy.orm import Session
from typing import Optional

from Models import Order, OrderItem, Tenant, UserCostCentre, CostCentre, User, SpendingEvent
from Schemas import OrderRequest, OrderUpdateRequest, UserContext
from core.db_config import get_db
from core.user_auth import get_user_context
from utils.logger import logger
from utils.metrics import req_total, req_duration
from utils.service_bus import publish_spending_event, publish_order_event
from utils.redis_client import redis_client

# Policy Engine Client
import httpx
import os

POLICY_ENGINE_URL = os.getenv("POLICY_ENGINE_URL", "http://localhost:8004")

app = APIRouter()


async def evaluate_policy(action: str, subject: dict, resource: dict, context: dict = None) -> dict:
    """
    Evaluate a policy against the Policy Engine.
    
    Returns:
        dict with keys: allowed, effect, reason, requires_approval, approval_chain_id
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{POLICY_ENGINE_URL}/v1/policy-engine/evaluate",
                json={
                    "action": action,
                    "subject": subject,
                    "resource": resource,
                    "context": context or {}
                }
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Policy Engine error: {response.status_code} - {response.text}")
                # Fail open with warning in case of Policy Engine issues
                return {
                    "allowed": True,
                    "effect": "allow",
                    "reason": "Policy Engine unavailable - allowing with warning",
                    "requires_approval": False
                }
    except Exception as e:
        logger.error(f"Policy Engine connection error: {e}")
        # Fail open with warning
        return {
            "allowed": True,
            "effect": "allow", 
            "reason": f"Policy Engine unavailable: {e}",
            "requires_approval": False
        }


# =============================================================================
# ORDER ENDPOINTS
# =============================================================================

@app.post("/orders")
async def create_order(
        req: OrderRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(get_user_context)
):
    """
    Create a new order with Policy Engine validation.
    
    Policies evaluated:
    1. order.cost_centre_assignment - User must be assigned to a cost centre
    2. order.budget.check - User must have sufficient budget
    3. order.large_order_approval - Large orders require approval
    """
    start = datetime.now()
    try:
        req_total.labels(operation="create_order", status="start").inc()
        
        # 1. Get tenant
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(ctx.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # 2. Calculate total amount first (needed for policy evaluation)
        total_amount = 0
        items = []
        
        for item_data in req.items:
            try:
                product_uuid = uuid.UUID(item_data['product_id'])
            except (ValueError, KeyError):
                raise HTTPException(status_code=400, detail=f"Invalid product_id: {item_data.get('product_id')}")
            
            variant_uuid = None
            if item_data.get('variant_id'):
                try:
                    variant_uuid = uuid.UUID(item_data['variant_id'])
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"Invalid variant_id: {item_data.get('variant_id')}")
            
            quantity = item_data['quantity']
            unit_price = item_data['unit_price_minor']
            item_total = quantity * unit_price
            total_amount += item_total
            
            items.append({
                "product_id": product_uuid,
                "variant_id": variant_uuid,
                "quantity": quantity,
                "unit_price_minor": unit_price,
                "total_price_minor": item_total
            })
        
        # 3. For customer tenants, evaluate policies via Policy Engine
        user_cc = None
        cc = None
        approval_request_id = None
        
        if tenant.tenant_type == "customer":
            # Get user data for policy context
            user = db.query(User).filter(User.user_id == uuid.UUID(ctx.user_id)).first()
            user_cc = db.query(UserCostCentre).filter(
                UserCostCentre.user_id == uuid.UUID(ctx.user_id)
            ).first()
            
            # Build subject context for policy evaluation
            subject = {
                "user_id": ctx.user_id,
                "tenant_id": ctx.tenant_id,
                "roles": ctx.roles if hasattr(ctx, 'roles') else [],
                "cost_centre_id": str(user_cc.cost_centre_id) if user_cc else None,
                "budget_remaining": (user_cc.allocated_budget_minor - user_cc.spent_minor) if user_cc else 0,
                "max_order_limit_minor": user.max_order_limit_minor if user else 10000000
            }
            
            # Build resource context
            resource = {
                "order_total": total_amount,
                "item_count": len(items),
                "tenant_id": ctx.tenant_id
            }
            
            # Evaluate order.create policy (handles all 3 policies)
            policy_result = await evaluate_policy(
                action="order.create",
                subject=subject,
                resource=resource,
                context={"timestamp": datetime.now(timezone.utc).isoformat()}
            )
            
            logger.info(f"Policy evaluation result: {policy_result}")
            
            # Handle policy decision
            if not policy_result.get("allowed", True):
                effect = policy_result.get("effect", "deny")
                reason = policy_result.get("reason", "Policy evaluation failed")
                
                if effect == "require_approval":
                    # Check if approval was provided
                    if hasattr(req, 'approval_request_id') and req.approval_request_id:
                        # Validate the approval request
                        from Models import ApprovalRequest
                        appr = db.query(ApprovalRequest).filter(
                            ApprovalRequest.request_id == uuid.UUID(req.approval_request_id),
                            ApprovalRequest.request_status == "approved",
                            ApprovalRequest.requested_by == uuid.UUID(ctx.user_id)
                        ).first()
                        
                        if not appr:
                            raise HTTPException(
                                status_code=403,
                                detail="Valid approved request required for this order amount"
                            )
                        approval_request_id = uuid.UUID(req.approval_request_id)
                    else:
                        raise HTTPException(
                            status_code=403,
                            detail={
                                "message": reason,
                                "requires_approval": True,
                                "order_total": total_amount,
                                "user_limit": subject.get("max_order_limit_minor")
                            }
                        )
                else:
                    # Deny
                    raise HTTPException(status_code=403, detail=reason)
            
            # Get cost centre for budget deduction
            if user_cc:
                cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == user_cc.cost_centre_id).first()
        
        # 4. Create order
        site_uuid = uuid.UUID(req.site_id) if req.site_id else None
        store_uuid = uuid.UUID(req.store_id) if req.store_id else None
        
        order = Order(
            order_id=uuid.uuid4(),
            tenant_id=uuid.UUID(ctx.tenant_id),
            customer_id=uuid.UUID(ctx.user_id),
            site_id=site_uuid,
            store_id=store_uuid,
            order_number=f"ORD-{int(datetime.now(timezone.utc).timestamp())}-{uuid.uuid4().hex[:6]}",
            order_type=req.order_type or ("employee_purchase" if tenant.tenant_type == "customer" else "purchase"),
            total_amount_minor=total_amount,
            currency=user_cc.currency_code if user_cc else "GBP",
            approval_request_id=approval_request_id,
            order_status="confirmed",
            payment_status="budget_deducted" if tenant.tenant_type == "customer" else "pending",
            fulfillment_status="pending",
            shipping_address=req.shipping_address,
            billing_address=req.billing_address,
            order_metadata=req.metadata
        )
        db.add(order)
        db.flush()
        
        # 5. Add order items
        for item in items:
            db.add(OrderItem(
                order_id=order.order_id,
                product_id=item['product_id'],
                variant_id=item['variant_id'],
                quantity=item['quantity'],
                unit_price_minor=item['unit_price_minor'],
                total_price_minor=item['total_price_minor']
            ))
        
        # 6. Deduct budgets for customer tenants
        if tenant.tenant_type == "customer" and user_cc and cc:
            user_cc.spent_minor += total_amount
            cc.spent_minor += total_amount
            
            # Create spending event record
            spending_event = SpendingEvent(
                event_id=uuid.uuid4(),
                event_type="budget_spent",
                user_id=uuid.UUID(ctx.user_id),
                cost_centre_id=user_cc.cost_centre_id,
                order_id=order.order_id,
                approval_request_id=approval_request_id,
                amount_minor=total_amount,
                currency_code=user_cc.currency_code,
                metadata={
                    "order_number": order.order_number,
                    "item_count": len(items)
                }
            )
            db.add(spending_event)
        
        db.commit()
        db.refresh(order)
        
        # 7. Publish events (non-critical)
        try:
            if tenant.tenant_type == "customer" and user_cc:
                publish_spending_event(
                    event_type="budget_spent",
                    user_id=ctx.user_id,
                    cost_centre_id=str(user_cc.cost_centre_id),
                    amount_minor=total_amount,
                    order_id=str(order.order_id),
                    approval_request_id=str(approval_request_id) if approval_request_id else None,
                    metadata={
                        "tenant_id": ctx.tenant_id,
                        "order_number": order.order_number,
                        "manager_id": str(cc.manager_user_id) if cc and cc.manager_user_id else None
                    }
                )
            
            publish_order_event(
                event_type="order_created",
                order_id=str(order.order_id),
                tenant_id=ctx.tenant_id,
                customer_id=ctx.user_id,
                total_amount_minor=total_amount,
                currency=order.currency,
                metadata={"order_type": order.order_type}
            )
            
            # Publish to Redis for real-time notifications
            if redis_client:
                redis_client.publish("order.created", json.dumps({
                    "order_id": str(order.order_id),
                    "user_id": ctx.user_id,
                    "total_amount_minor": total_amount,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }))
        except Exception as e:
            logger.warning(f"Event publishing failed (non-critical): {e}")
        
        req_total.labels(operation="create_order", status="success").inc()
        req_duration.labels(operation="create_order").observe(
            (datetime.now() - start).total_seconds()
        )
        
        logger.info(f"✅ Order created: {order.order_id} for user {ctx.user_id}, amount: {total_amount}")
        
        return {
            "order_id": str(order.order_id),
            "order_number": order.order_number,
            "total_amount_minor": total_amount,
            "currency": order.currency,
            "status": order.order_status,
            "payment_status": order.payment_status,
            "created_at": order.created_at.isoformat()
        }
        
    except HTTPException:
        req_total.labels(operation="create_order", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_order", status="error").inc()
        logger.error(f"❌ Order creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


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
