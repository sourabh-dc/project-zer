"""
AiFi Order Integration Service - With Policy Engine Integration

Handles orders coming from AiFi webhooks.
Uses Policy Engine for budget validation.
"""
import uuid
import os
import httpx
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional, List

from sqlalchemy.orm import Session

from operations_service.Models import (
    Order,
    OrderItem,
    User,
    Product,
    Store,
    AifiStoreMap,
    UserCostCentre,
    CostCentre,
    SpendingEvent,
)
from operations_service.core.db_config import SessionLocal
from operations_service.utils.logger import logger
from operations_service.operations.ledger import record_order_ledger


POLICY_ENGINE_URL = os.getenv("POLICY_ENGINE_URL", "http://localhost:8004")


def _to_minor(amount: Optional[str | float | int]) -> int:
    """Convert a string/float amount to minor units (int cents)."""
    if amount is None:
        return 0
    try:
        return int(Decimal(str(amount)) * 100)
    except (InvalidOperation, ValueError):
        return 0


def _find_user_and_tenant(db: Session, aifi_customer_id: str):
    user = db.query(User).filter(User.aifi_customer_id == str(aifi_customer_id)).first()
    if not user:
        return None, None
    return user, user.tenant_id


def _find_product_id(db: Session, product_hint: str, barcode: str = None, sku: str = None):
    """Try to resolve a product using AiFi identifiers or barcode/sku."""
    if not product_hint and not barcode and not sku:
        return None
    # Prefer aifi_product_id match
    if product_hint:
        prod = db.query(Product).filter(Product.aifi_product_id == str(product_hint)).first()
        if prod:
            return prod.product_id
    # Fallback to barcode
    if barcode:
        prod = db.query(Product).filter(Product.barcode == str(barcode)).first()
        if prod:
            return prod.product_id
    # Fallback to sku
    if sku:
        prod = db.query(Product).filter(Product.sku == str(sku)).first()
        if prod:
            return prod.product_id
    return None


def _price_for_product(db: Session, product_id, store_id=None) -> int:
    """
    Resolve price in minor units for a product, preferring store price when store_id is known.
    """
    if store_id:
        from operations_service.Models import StoreProduct

        sp = (
            db.query(StoreProduct)
            .filter(StoreProduct.store_id == store_id, StoreProduct.product_id == product_id)
            .first()
        )
        if sp and sp.price_minor is not None:
            return int(sp.price_minor)
    prod = db.query(Product).filter(Product.product_id == product_id).first()
    return int(getattr(prod, "base_price_minor", 0) or 0) if prod else 0


def _resolve_store(db: Session, aifi_store_id) -> Optional[uuid.UUID]:
    """
    Map AiFi storeId to our Store.store_id.
    - Check explicit mapping table (AifiStoreMap).
    - If exactly one store exists, fallback to it.
    """
    if aifi_store_id:
        mapping = db.query(AifiStoreMap).filter(AifiStoreMap.aifi_store_id == str(aifi_store_id)).first()
        if mapping:
            return mapping.store_id
    stores = db.query(Store).all()
    if not stores:
        return None
    if len(stores) == 1:
        return stores[0].store_id
    return None


def evaluate_policy_sync(action: str, subject: dict, resource: dict, context: dict = None) -> dict:
    """
    Synchronous policy evaluation for use in non-async contexts.
    
    Returns:
        dict with keys: allowed, decision, reason
    """
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
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
                # Fail open with warning
                return {"allowed": True, "decision": "allowed", "reason": "Policy Engine unavailable"}
    except Exception as e:
        logger.error(f"Policy Engine connection error: {e}")
        return {"allowed": True, "decision": "allowed", "reason": f"Policy Engine unavailable: {e}"}


def upsert_aifi_order(order_data: Dict, db: Optional[Session] = None) -> Dict:
    """
    Upsert an AiFi order into our orders/order_items tables.
    - Uses Policy Engine for budget validation.
    - Requires mapping AiFi customer -> local user via User.aifi_customer_id.
    - Attempts to map products via Product.aifi_product_id.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        aifi_order_id = str(order_data.get("id") or order_data.get("orderId"))
        if not aifi_order_id:
            return {"status": "error", "reason": "missing_aifi_order_id"}

        user, tenant_id = _find_user_and_tenant(db, order_data.get("customerId"))
        if not user or not tenant_id:
            return {"status": "error", "reason": "missing_local_user_for_aifi_customer", "aifi_customer_id": order_data.get("customerId")}

        # Upsert order by aifi_order_id
        order = db.query(Order).filter(Order.aifi_order_id == aifi_order_id).first()
        is_new = order is None
        if not order:
            order = Order(
                order_id=uuid.uuid4(),
                aifi_order_id=aifi_order_id,
                tenant_id=tenant_id,
                customer_id=user.user_id,
                order_number=f"AIFI-{aifi_order_id}",
            )

        # Map basic fields
        order.order_status = order_data.get("status") or order.order_status or "pending"
        order.payment_status = "paid" if (order_data.get("status") == "paid") else order.payment_status or "pending"
        order.fulfillment_status = order.fulfillment_status or "pending"
        order.order_type = "aifi"
        order.currency = order.currency or "GBP"
        store_mapped = _resolve_store(db, order_data.get("storeId"))
        if store_mapped:
            order.store_id = store_mapped

        # Persist AiFi metadata including storeId, transactionId, sessionId, etc.
        meta = order.order_metadata or {}
        meta.update(
            {
                "aifi_order_id": aifi_order_id,
                "aifi_store_id": order_data.get("storeId"),
                "aifi_customer_id": order_data.get("customerId"),
                "aifi_transaction_id": order_data.get("transactionId"),
                "aifi_customer_session_id": order_data.get("customerShoppingSessionId"),
                "aifi_external_status": order_data.get("externalStatus"),
                "aifi_raw": order_data,
            }
        )
        order.order_metadata = meta

        db.add(order)
        db.flush()

        # Refresh items: delete existing and re-add if items are present
        items_payload: List[Dict] = order_data.get("items") or order_data.get("products") or []
        if not items_payload:
            db.commit()
            return {"status": "ok", "created": is_new, "order_id": str(order.order_id), "note": "no_items_in_payload"}

        db.query(OrderItem).filter(OrderItem.order_id == order.order_id).delete()

        skipped_items = []
        computed_total = 0
        for item in items_payload:
            product_id = _find_product_id(
                db,
                item.get("productId") or item.get("id"),
                barcode=item.get("barcode"),
                sku=item.get("sku"),
            )
            if not product_id:
                skipped_items.append(
                    {
                        "productId": item.get("productId") or item.get("id"),
                        "barcode": item.get("barcode"),
                        "sku": item.get("sku"),
                        "reason": "unmapped_product",
                    }
                )
                continue
            quantity = int(item.get("quantity") or 0)
            unit_price_minor = _price_for_product(db, product_id, store_id=order.store_id)
            if not unit_price_minor:
                unit_price_minor = _to_minor(item.get("price") or item.get("unitPrice") or item.get("unit_price"))
            total_price_minor = unit_price_minor * quantity if quantity else _to_minor(item.get("totalPrice"))
            computed_total += total_price_minor
            db.add(
                OrderItem(
                    order_id=order.order_id,
                    product_id=product_id,
                    variant_id=None,
                    quantity=quantity,
                    unit_price_minor=unit_price_minor,
                    total_price_minor=total_price_minor,
                    item_metadata={"aifi_raw": item},
                )
            )

        if computed_total:
            order.total_amount_minor = computed_total

        # =====================================================================
        # POLICY ENGINE VALIDATION
        # =====================================================================
        budget_delta = 0
        try:
            user_cc = db.query(UserCostCentre).filter(UserCostCentre.user_id == user.user_id).first()
            
            if user_cc:
                # Build subject context for policy evaluation
                budget_remaining = (user_cc.allocated_budget_minor or 0) - (user_cc.spent_minor or 0)
                
                subject = {
                    "user_id": str(user.user_id),
                    "tenant_id": str(tenant_id),
                    "cost_centre_id": str(user_cc.cost_centre_id) if user_cc.cost_centre_id else None,
                    "budget_remaining": budget_remaining,
                    "max_order_limit_minor": getattr(user, 'max_order_limit_minor', 10000000) or 10000000
                }
                
                resource = {
                    "order_total": computed_total,
                    "item_count": len(items_payload) - len(skipped_items),
                    "source": "aifi"
                }
                
                # Evaluate policy
                policy_result = evaluate_policy_sync(
                    action="order.create",
                    subject=subject,
                    resource=resource,
                    context={"channel": "aifi_webhook"}
                )
                
                logger.info(f"Policy evaluation for AiFi order: {policy_result}")
                
                if not policy_result.get("allowed", True):
                    decision = policy_result.get("decision", "denied")
                    reason = policy_result.get("reason", "Policy evaluation failed")
                    
                    # For AiFi orders, we can't require approval - just deny
                    if decision in ["denied", "approval_required"]:
                        db.rollback()
                        return {
                            "status": "error",
                            "reason": "policy_denied",
                            "policy_reason": reason,
                            "decision": decision,
                            "order_total": computed_total,
                            "budget_remaining": budget_remaining
                        }
                
                # Policy allowed - deduct budget
                budget_delta = computed_total
                user_cc.spent_minor = (user_cc.spent_minor or 0) + budget_delta
                
                cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == user_cc.cost_centre_id).first()
                if cc:
                    cc.spent_minor = (cc.spent_minor or 0) + budget_delta
                
                db.add(
                    SpendingEvent(
                        event_id=uuid.uuid4(),
                        event_type="budget_spent",
                        user_id=user.user_id,
                        cost_centre_id=user_cc.cost_centre_id,
                        order_id=order.order_id,
                        approval_request_id=None,
                        amount_minor=budget_delta,
                        currency_code=getattr(user_cc, "currency_code", "GBP"),
                        event_metadata={"order_number": order.order_number, "source": "aifi"},
                    )
                )
        except Exception as exc:
            logger.warning(f"Budget/policy check skipped: {exc}")

        # Record ledger (best-effort, idempotent)
        try:
            record_order_ledger(order, db.query(OrderItem).filter(OrderItem.order_id == order.order_id).all(), source="aifi", db=db)
        except Exception as exc:
            logger.warning(f"Ledger posting skipped: {exc}")

        db.commit()
        return {
            "status": "ok",
            "created": is_new,
            "order_id": str(order.order_id),
            "skipped_items": skipped_items,
            "budget_debited_minor": budget_delta,
        }
    except Exception as exc:
        db.rollback()
        logger.error(f"Failed to upsert AiFi order: {exc}")
        return {"status": "error", "reason": str(exc)}
    finally:
        if close_db:
            db.close()
