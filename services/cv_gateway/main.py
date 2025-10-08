# CV Gateway Service - Enhanced V4.1 Architecture
# Multi-provider CV order processing with sagas, events, and RLS

import os
import uuid
import json
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI, Body, HTTPException, Query, Path, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text, create_engine, Column, String, Integer, Boolean, DateTime, Text, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.sql import func

# Prometheus metrics
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

# Common imports
from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal
from zeroque_common.middleware.usage_middleware import add_api_call_meter
from zeroque_common.billing.helpers import create_trade_invoice_if_applicable
from zeroque_common.middleware.idempotency import add_idempotency_middleware

# =============================================================================
# PROMETHEUS METRICS
# =============================================================================

# Metrics for CV Gateway
cv_gateway_requests_total = Counter(
    'cv_gateway_requests_total', 
    'Total CV gateway requests',
    ['method', 'endpoint', 'provider', 'status']
)

cv_gateway_request_duration = Histogram(
    'cv_gateway_request_duration_seconds',
    'CV gateway request duration',
    ['method', 'endpoint', 'provider']
)

cv_order_processing_total = Counter(
    'cv_order_processing_total',
    'Total CV order processing',
    ['provider', 'status', 'reason']
)

cv_order_processing_duration = Histogram(
    'cv_order_processing_duration_seconds',
    'CV order processing duration',
    ['provider']
)

cv_saga_steps_total = Counter(
    'cv_saga_steps_total',
    'Total CV saga steps',
    ['step', 'provider', 'status']
)

cv_unknown_items_total = Counter(
    'cv_unknown_items_total',
    'Total unknown items',
    ['provider', 'tenant_id']
)

# =============================================================================
# CONFIGURATION
# =============================================================================

SERVICE_NAME = "cv_gateway_v4"

# =============================================================================
# DATABASE MODELS
# =============================================================================

Base = declarative_base()

class CvUnknownItemReview(Base):
    """Unknown item reviews for reconciliation"""
    __tablename__ = "cv_unknown_item_reviews"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=False)
    site_id = Column(UUID(as_uuid=True), ForeignKey('sites.site_id'), nullable=True)
    store_id = Column(UUID(as_uuid=True), ForeignKey('stores.store_id'), nullable=True)
    provider = Column(String(50), nullable=False)
    external_sku = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    qty = Column(Integer, nullable=False)
    price_minor = Column(Integer, nullable=False)
    payload_json = Column(JSONB, nullable=False)
    status = Column(String(20), nullable=False, default='pending')
    mapped_sku = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    resolved_by = Column(String(255), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class OutboxEvent(Base):
    """Reliable event publishing"""
    __tablename__ = "outbox_events"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=True)
    event_type = Column(String(100), nullable=False)
    event_data = Column(JSONB, nullable=False)
    status = Column(String(20), nullable=False, default='pending')
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class AuditLog(Base):
    """Audit trail for operations"""
    __tablename__ = "audit_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.tenant_id'), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.user_id'), nullable=True)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(String(255), nullable=True)
    details = Column(JSONB, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

# =============================================================================
# PYDANTIC SCHEMAS
# =============================================================================

class AiFiItem(BaseModel):
    """CV order item"""
    sku: str = Field(..., description="Product SKU")
    name: str = Field(..., description="Product name")
    qty: int = Field(..., description="Quantity")
    price_minor: int = Field(..., description="Price in minor units")

class AiFiOrder(BaseModel):
    """CV order from provider"""
    provider: str = Field(..., description="Provider name")
    provider_order_id: str = Field(..., description="Provider order ID")
    
    # External IDs (optional if local IDs are provided)
    tenant_ext_id: Optional[str] = Field(None, description="External tenant ID")
    site_ext_id: Optional[str] = Field(None, description="External site ID")
    store_ext_id: Optional[str] = Field(None, description="External store ID")
    user_ext_id: Optional[str] = Field(None, description="External user ID")
    
    # Local IDs (preferred)
    tenant_id: Optional[str] = Field(None, description="Local tenant ID")
    site_id: Optional[str] = Field(None, description="Local site ID")
    store_id: Optional[str] = Field(None, description="Local store ID")
    shopper_id: Optional[str] = Field(None, description="Local shopper ID")
    
    currency: str = Field("GBP", description="Currency")
    items: List[AiFiItem] = Field(..., description="Order items")
    occurred_at: Optional[datetime] = Field(None, description="Order timestamp")
    
    @field_validator('tenant_id', 'site_id', 'store_id', 'shopper_id')
    @classmethod
    def validate_uuids(cls, v):
        if v is not None:
            try:
                uuid.UUID(v)
                return v
            except ValueError:
                raise ValueError('Invalid UUID format')
        return v

class ReviewResolvePayload(BaseModel):
    """Review resolution payload"""
    mapped_sku: Optional[str] = Field(None, description="Mapped SKU")
    status: str = Field("resolved", description="Resolution status")
    notes: Optional[str] = Field(None, description="Resolution notes")
    
    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        if v not in ("resolved", "ignored"):
            raise ValueError("Status must be 'resolved' or 'ignored'")
        return v

class OrderResponse(BaseModel):
    """Order processing response"""
    ok: bool = Field(..., description="Success status")
    order_id: Optional[int] = Field(None, description="Created order ID")
    total_minor: Optional[int] = Field(None, description="Total amount in minor units")
    currency: Optional[str] = Field(None, description="Currency")
    unknown_items: Optional[List[dict]] = Field(None, description="Unknown items requiring review")

# =============================================================================
# UTILITIES
# =============================================================================

def set_rls_context(db: Session, tenant_id: str):
    """Set RLS context for database session"""
    db.execute(text("SET LOCAL app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})

async def _map_provider(db: Session, provider: str, entity_type: str, external_id: str) -> Optional[str]:
    """Map external provider ID to local ID"""
    row = db.execute(text("""
        SELECT local_id
          FROM provider_mappings
         WHERE provider=:p AND entity_type=:et AND external_id=:eid
         LIMIT 1
    """), {"p": provider, "et": entity_type, "eid": external_id}).first()
    return row[0] if row else None

async def _update_daily(db: Session, when: datetime, tenant_id: str, site_id: Optional[str], 
                       store_id: Optional[str], meter_code: str, delta: int):
    """Update daily usage aggregates"""
    day = when.date()
    upd = db.execute(text("""
        UPDATE usage_aggregates_daily
           SET value = value + :delta
         WHERE day=:d AND tenant_id=:t
           AND COALESCE(site_id,'')=COALESCE(:s,'')
           AND COALESCE(store_id,'')=COALESCE(:st,'')
           AND meter_code=:m
    """), {"delta": delta, "d": day, "t": tenant_id, "s": site_id, "st": store_id, "m": meter_code}).rowcount
    
    if upd == 0:
        try:
            db.execute(text("""
                INSERT INTO usage_aggregates_daily(day, tenant_id, site_id, store_id, meter_code, value)
                VALUES(:d,:t,:s,:st,:m,:v)
            """), {"d": day, "t": tenant_id, "s": site_id, "st": store_id, "m": meter_code, "v": delta})
        except Exception:
            # Race condition - try update again
            db.execute(text("""
                UPDATE usage_aggregates_daily
                   SET value = value + :delta
                 WHERE day=:d AND tenant_id=:t
                   AND COALESCE(site_id,'')=COALESCE(:s,'')
                   AND COALESCE(store_id,'')=COALESCE(:st,'')
                   AND meter_code=:m
            """), {"delta": delta, "d": day, "t": tenant_id, "s": site_id, "st": store_id, "m": meter_code})

async def _approval_cover_and_consume(db: Session, cost_centre_id: str, user_id: str, amount: int) -> bool:
    """Check and consume approval coverage for budget overspend"""
    need = amount
    for scoped in (True, False):
        rows = db.execute(text("""
            SELECT id, remaining_minor FROM approval_requests_new
             WHERE cost_centre_id=:cc AND status='approved'
               AND (:u IS NULL OR (user_scope_id = :u))
               AND (:scoped = TRUE AND user_scope_id IS NOT NULL OR :scoped = FALSE AND user_scope_id IS NULL)
             ORDER BY approved_at DESC NULLS LAST, id DESC
        """), {"cc": cost_centre_id, "u": user_id, "scoped": scoped}).all()
        
        for r in rows:
            if need <= 0: 
                break
            ar_id, rem = int(r[0]), int(r[1] or 0)
            if rem <= 0: 
                continue
            take = min(rem, need)
            db.execute(text("UPDATE approval_requests_new SET remaining_minor = remaining_minor - :take WHERE id=:id"),
                       {"take": take, "id": ar_id})
            need -= take
    return need == 0

async def _review_unknown_item(db: Session, provider: str, tenant_id: str, site_id: str, store_id: str,
                         external_sku: str, name: str, qty: int, price_minor: int, payload_fragment: dict):
    """Record unknown item for review"""
    db.execute(text("""
        INSERT INTO cv_unknown_item_reviews(tenant_id, site_id, store_id, provider,
                                            external_sku, name, qty, price_minor, payload_json, status)
        VALUES(:t,:si,:st,:p,:esk,:n,:q,:pm,:pl,'pending')
    """), {"t": tenant_id, "si": site_id, "st": store_id, "p": provider,
           "esk": external_sku, "n": name, "q": qty, "pm": price_minor,
           "pl": json.dumps(payload_fragment)})

async def _apply_inventory_decrements(db: Session, store_id: str, items: list[dict]):
    """Apply inventory decrements for sold items"""
    for item in items:
        sku = item["sku"]
        qty = int(item["qty"])
        
        # Update inventory_new table
        upd = db.execute(text("UPDATE inventory_new SET qty = qty - :q WHERE store_id=:st AND sku=:s"),
                         {"q": qty, "st": store_id, "s": sku}).rowcount
        if upd == 0:
            db.execute(text("INSERT INTO inventory_new(store_id, sku, qty) VALUES(:st, :s, :q)"),
                       {"st": store_id, "s": sku, "q": -qty})
        
        # Record inventory movement
        db.execute(text("""
            INSERT INTO inventory_movements(store_id, sku, delta, reason, created_at)
            VALUES(:st, :s, :d, 'cv_sale', NOW())
        """), {"st": store_id, "s": sku, "d": -qty})

async def publish_event(db: Session, event_type: str, event_data: dict, tenant_id: Optional[str] = None):
    """Publish event to outbox for reliable delivery"""
    event = OutboxEvent(
        tenant_id=tenant_id,
        event_type=event_type,
        event_data=event_data,
        status="pending"
    )
    db.add(event)
    db.commit()

async def log_audit(db: Session, action: str, resource_type: str, resource_id: Optional[str] = None,
                   details: Optional[dict] = None, user_id: Optional[str] = None, tenant_id: Optional[str] = None):
    """Log audit trail"""
    audit = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details
    )
    db.add(audit)
    db.commit()

# =============================================================================
# SAGA PATTERN IMPLEMENTATION
# =============================================================================

class CvOrderSaga:
    """Saga for CV order processing with compensation"""
    
    def __init__(self, db: Session, order_data: dict):
        self.db = db
        self.order_data = order_data
        self.compensation_steps = []
    
    async def execute(self) -> dict:
        """Execute the saga steps"""
        try:
            # Step 1: Resolve IDs
            cv_saga_steps_total.labels(step="resolve_ids", provider=self.order_data["provider"], status="started").inc()
            resolved_ids = await self._resolve_ids()
            cv_saga_steps_total.labels(step="resolve_ids", provider=self.order_data["provider"], status="success").inc()
            
            # Step 2: Validate items
            validation_result = await self._validate_items(resolved_ids)
            if not validation_result["valid"]:
                # Update metrics for unknown items
                cv_unknown_items_total.labels(
                    provider=self.order_data["provider"],
                    tenant_id=resolved_ids["tenant_id"]
                ).inc(len(validation_result.get("unknown_items", [])))
                return validation_result
            
            # Step 3: Check budgets/approvals
            budget_result = await self._check_budget_approvals(resolved_ids)
            if not budget_result["approved"]:
                return budget_result
            
            # Step 4: Create order
            order_result = await self._create_order(resolved_ids, validation_result["validated_items"])
            
            # Step 5: Update inventory
            await self._update_inventory(resolved_ids, validation_result["validated_items"])
            
            # Step 6: Create ledger entries
            await self._create_ledger_entries(resolved_ids, order_result["total_minor"])
            
            # Step 7: Update budget
            await self._update_budget(resolved_ids, order_result["total_minor"])
            
            # Step 8: Record usage metrics
            await self._record_usage_metrics(resolved_ids)
            
            # Step 9: Create trade invoice
            await self._create_trade_invoice(resolved_ids, order_result)
            
            # Step 10: Send notifications
            await self._send_notifications(resolved_ids, order_result)
            
            # Step 11: Publish events
            await self._publish_events(resolved_ids, order_result)
            
            # Commit transaction
            self.db.commit()
            
            return {
                "ok": True,
                "order_id": order_result["order_id"],
                "total_minor": order_result["total_minor"],
                "currency": self.order_data["currency"]
            }
            
        except Exception as e:
            # Execute compensation steps
            await self._compensate()
            raise e
    
    async def _resolve_ids(self) -> dict:
        """Resolve external IDs to local IDs"""
        provider = self.order_data["provider"]
        
        tenant_id = (self.order_data.get("tenant_id") or 
                    (self.order_data.get("tenant_ext_id") and 
                     await _map_provider(self.db, provider, "tenant", self.order_data["tenant_ext_id"])))
        
        site_id = (self.order_data.get("site_id") or 
                  (self.order_data.get("site_ext_id") and 
                   await _map_provider(self.db, provider, "site", self.order_data["site_ext_id"])))
        
        store_id = (self.order_data.get("store_id") or 
                   (self.order_data.get("store_ext_id") and 
                    await _map_provider(self.db, provider, "store", self.order_data["store_ext_id"])))
        
        shopper_id = (self.order_data.get("shopper_id") or 
                     (self.order_data.get("user_ext_id") and 
                      await _map_provider(self.db, provider, "user", self.order_data["user_ext_id"])))

        if not all([tenant_id, site_id, store_id, shopper_id]):
            raise HTTPException(
                status_code=400,
                detail="Mapping failed (tenant/site/store/user). Provide local IDs or external IDs + provider_mappings."
            )
        
        return {
            "tenant_id": tenant_id,
            "site_id": site_id,
            "store_id": store_id,
            "shopper_id": shopper_id
        }
    
    async def _validate_items(self, resolved_ids: dict) -> dict:
        """Validate items and check for unknowns"""
        unknown_items = []
        validated_items = []
        
        for item in self.order_data["items"]:
            # Check if product exists
            prod = self.db.execute(text("SELECT 1 FROM product_master WHERE sku=:s AND active=TRUE"), 
                                  {"s": item.sku}).first()
            
            # Check if price exists
            price = self.db.execute(text("""
                SELECT unit_minor FROM prices WHERE sku=:s AND currency=:c AND active=TRUE
            """), {"s": item.sku, "c": self.order_data["currency"]}).first()
            
            if not prod or not price:
                unknown_items.append({
                    "sku": item.sku,
                    "name": item.name,
                    "qty": item.qty,
                    "price_minor": item.price_minor
                })
                
                # Record for review
                await _review_unknown_item(
                    self.db, self.order_data["provider"], resolved_ids["tenant_id"],
                    resolved_ids["site_id"], resolved_ids["store_id"],
                    item.sku, item.name, item.qty, item.price_minor,
                    {"sku": item.sku, "name": item.name, "qty": item.qty, "price_minor": item.price_minor}
                )
                continue
            
            validated_items.append({
                "sku": item.sku,
                "qty": int(item.qty),
                "unit_minor": int(price[0])
            })
        
        if unknown_items:
            return {
                "valid": False,
                "status": 202,
                "reason": "reconciliation_required",
                "unknown_count": len(unknown_items),
                "items": unknown_items
            }
        
        return {
            "valid": True,
            "validated_items": validated_items
        }
    
    async def _check_budget_approvals(self, resolved_ids: dict) -> dict:
        """Check budget and approval coverage"""
        # Get shopper cost centre
        cc_row = self.db.execute(text("""
            SELECT cost_centre_id FROM user_cost_centres
             WHERE user_id=:u ORDER BY id ASC LIMIT 1
        """), {"u": resolved_ids["shopper_id"]}).first()
        
        cost_centre_id = cc_row[0] if cc_row else None

        if not cost_centre_id:
            return {"approved": True}  # No budget constraints
        
        # Check budget
        budget = self.db.execute(text("""
            SELECT limit_minor, spent_minor FROM budgets_new
                 WHERE cost_centre_id=:cc ORDER BY budget_id DESC LIMIT 1
            """), {"cc": cost_centre_id}).first()
        
        if budget:
            remaining = int(budget[0]) - int(budget[1])
            total_minor = sum(item["qty"] * item["unit_minor"] for item in self.order_data["items"])
            
            if remaining < total_minor:
                need = total_minor - max(0, remaining)
                if not await _approval_cover_and_consume(self.db, cost_centre_id, resolved_ids["shopper_id"], need):
                    return {
                        "approved": False,
                        "status": 403,
                        "detail": "Budget would overspend (hard block); no approval cover"
                    }
        
        return {"approved": True, "cost_centre_id": cost_centre_id}
    
    async def _create_order(self, resolved_ids: dict, validated_items: list) -> dict:
        """Create order and line items"""
        total_minor = sum(item["qty"] * item["unit_minor"] for item in validated_items)
        
        # Create order
        self.db.execute(text("""
            INSERT INTO orders_new(tenant_id, site_id, store_id, shopper_id, cost_centre_id,
                               provider, provider_order_id, total_minor, currency, status, occurred_at)
            VALUES(:t,:si,:st,:u,:cc,:p,:po,:tot,:cur,'completed',:occ)
        """), {"t": resolved_ids["tenant_id"], "si": resolved_ids["site_id"], 
               "st": resolved_ids["store_id"], "u": resolved_ids["shopper_id"],
               "cc": resolved_ids.get("cost_centre_id"), "p": self.order_data["provider"],
               "po": self.order_data["provider_order_id"], "tot": total_minor,
               "cur": self.order_data["currency"], "occ": self.order_data.get("occurred_at", datetime.now(timezone.utc))})
        
        order_id = self.db.execute(text("SELECT currval(pg_get_serial_sequence('orders_new','order_id'))")).scalar()
        
        # Create order items
        for item in validated_items:
            self.db.execute(text("""
                INSERT INTO order_items_new(order_id, sku, name, qty, price_minor)
                VALUES(:oid,:sku,:name,:qty,:price)
            """), {"oid": order_id, "sku": item["sku"], "name": item["sku"], 
                   "qty": item["qty"], "price": item["unit_minor"]})
        
        # Add compensation step
        self.compensation_steps.append(("delete_order", {"order_id": order_id}))
        
        return {"order_id": order_id, "total_minor": total_minor}
    
    async def _update_inventory(self, resolved_ids: dict, validated_items: list):
        """Update inventory levels"""
        await _apply_inventory_decrements(resolved_ids["store_id"], validated_items)
        
        # Add compensation step
        self.compensation_steps.append(("restore_inventory", {
            "store_id": resolved_ids["store_id"],
            "items": validated_items
        }))
    
    async def _create_ledger_entries(self, resolved_ids: dict, total_minor: int):
        """Create ledger entries"""
        # Debit cost centre spend
        self.db.execute(text("""
            INSERT INTO ledger_entries_new(tenant_id, account, entry_type, amount_minor, currency,
                                       cost_centre_id, site_id, store_id,
                                       reference_type, reference_id, description)
            VALUES(:t,'CostCentreSpend','debit',:amt,:cur,:cc,:si,:st,'cv_order',:ref,'CV order')
        """), {"t": resolved_ids["tenant_id"], "amt": total_minor, "cur": self.order_data["currency"],
               "cc": resolved_ids.get("cost_centre_id"), "si": resolved_ids["site_id"],
               "st": resolved_ids["store_id"], "ref": str(resolved_ids.get("order_id"))})
        
        # Credit tenant clearing
        self.db.execute(text("""
            INSERT INTO ledger_entries_new(tenant_id, account, entry_type, amount_minor, currency,
                                       cost_centre_id, site_id, store_id,
                                       reference_type, reference_id, description)
            VALUES(:t,'TenantClearing','credit',:amt,:cur,:cc,:si,:st,'cv_order',:ref,'CV order')
        """), {"t": resolved_ids["tenant_id"], "amt": total_minor, "cur": self.order_data["currency"],
               "cc": resolved_ids.get("cost_centre_id"), "si": resolved_ids["site_id"],
               "st": resolved_ids["store_id"], "ref": str(resolved_ids.get("order_id"))})
    
    async def _update_budget(self, resolved_ids: dict, total_minor: int):
        """Update budget spent amount"""
        if resolved_ids.get("cost_centre_id"):
            self.db.execute(text("""
                UPDATE budgets_new SET spent_minor = spent_minor + :amt 
                WHERE cost_centre_id=:cc
            """), {"amt": total_minor, "cc": resolved_ids["cost_centre_id"]})
    
    async def _record_usage_metrics(self, resolved_ids: dict):
        """Record usage metrics"""
        when = self.order_data.get("occurred_at", datetime.now(timezone.utc))
        
        # Record order event
        self.db.execute(text("""
            INSERT INTO usage_events(tenant_id, site_id, store_id, meter_code, subject_id, value, occurred_at)
            VALUES(:t,:si,:st,'orders',:u,1,:occ)
        """), {"t": resolved_ids["tenant_id"], "si": resolved_ids["site_id"],
               "st": resolved_ids["store_id"], "u": resolved_ids["shopper_id"], "occ": when})
        
        await _update_daily(self.db, when, resolved_ids["tenant_id"], resolved_ids["site_id"],
                           resolved_ids["store_id"], "orders", 1)
        
        # Check for unique shoppers
        exist = self.db.execute(text("""
            SELECT 1 FROM usage_events
             WHERE meter_code='unique_shoppers' AND tenant_id=:t
               AND COALESCE(site_id,'')=COALESCE(:si,'')
               AND COALESCE(store_id,'')=COALESCE(:st,'')
               AND subject_id=:u AND occurred_at::date = :d
             LIMIT 1
        """), {"t": resolved_ids["tenant_id"], "si": resolved_ids["site_id"],
               "st": resolved_ids["store_id"], "u": resolved_ids["shopper_id"], "d": when.date()}).first()
        
        if not exist:
            self.db.execute(text("""
                INSERT INTO usage_events(tenant_id, site_id, store_id, meter_code, subject_id, value, occurred_at)
                VALUES(:t,:si,:st,'unique_shoppers',:u,1,:occ)
            """), {"t": resolved_ids["tenant_id"], "si": resolved_ids["site_id"],
                   "st": resolved_ids["store_id"], "u": resolved_ids["shopper_id"], "occ": when})
            
            await _update_daily(self.db, when, resolved_ids["tenant_id"], resolved_ids["site_id"],
                               resolved_ids["store_id"], "unique_shoppers", 1)
    
    async def _create_trade_invoice(self, resolved_ids: dict, order_result: dict):
        """Create trade invoice if applicable"""
        create_trade_invoice_if_applicable(
            self.db, resolved_ids["tenant_id"], int(order_result["order_id"]),
            order_result["total_minor"], self.order_data["currency"],
            resolved_ids["site_id"], resolved_ids["store_id"]
        )
    
    async def _send_notifications(self, resolved_ids: dict, order_result: dict):
        """Send order notifications"""
        self.db.execute(text("""
            INSERT INTO notifications(tenant_id, target_user_id, channel, subject, body)
            VALUES(:t,:u,'dev','CV Order Receipt', :body)
        """), {"t": resolved_ids["tenant_id"], "u": resolved_ids["shopper_id"],
               "body": f"CV Order {order_result['order_id']} total {order_result['total_minor']} {self.order_data['currency']}"})
    
    async def _publish_events(self, resolved_ids: dict, order_result: dict):
        """Publish events for integration"""
        # Publish ORDER_CREATED event
        await publish_event(self.db, "ORDER_CREATED", {
            "order_id": order_result["order_id"],
            "tenant_id": resolved_ids["tenant_id"],
            "provider": self.order_data["provider"],
            "total_minor": order_result["total_minor"],
            "currency": self.order_data["currency"]
        }, resolved_ids["tenant_id"])
    
    async def _compensate(self):
        """Execute compensation steps in reverse order"""
        for step_name, step_data in reversed(self.compensation_steps):
            try:
                if step_name == "delete_order":
                    self.db.execute(text("DELETE FROM order_items_new WHERE order_id=:oid"), 
                                   {"oid": step_data["order_id"]})
                    self.db.execute(text("DELETE FROM orders_new WHERE order_id=:oid"), 
                                   {"oid": step_data["order_id"]})
                
                elif step_name == "restore_inventory":
                    for item in step_data["items"]:
                        self.db.execute(text("""
                            UPDATE inventory_new SET qty = qty + :q WHERE store_id=:st AND sku=:s
                        """), {"q": item["qty"], "st": step_data["store_id"], "s": item["sku"]})
                
            except Exception as e:
                # Log compensation failure but continue
                print(f"Compensation step {step_name} failed: {e}")

# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Startup
    get_engine()
    init_db()
    yield
    # Shutdown

app = FastAPI(
    title="ZeroQue CV Gateway V4.1",
    version="2.0.0",
    lifespan=lifespan
)

# Add middleware
add_api_call_meter(app)
add_idempotency_middleware(app, routes=[
    ("POST", "/cv/webhook/order"),
])

# =============================================================================
# DEPENDENCY INJECTION
# =============================================================================

def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# =============================================================================
# HEALTH AND ROOT ENDPOINTS
# =============================================================================

@app.get("/")
def root():
    return {"service": SERVICE_NAME, "version": "2.0.0"}

@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}

@app.get("/readiness")
def readiness():
    return {"service": SERVICE_NAME, "db": check_db(), "redis": True}

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    from fastapi.responses import Response
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# =============================================================================
# WEBHOOK ENDPOINTS
# =============================================================================

@app.post("/cv/webhook/order", response_model=OrderResponse)
async def cv_order_webhook(order: AiFiOrder, db: Session = Depends(get_db)):
    """Process CV order webhook with saga pattern"""
    # Update metrics
    cv_gateway_requests_total.labels(
        method="POST", endpoint="/cv/webhook/order", provider=order.provider, status="started"
    ).inc()
    
    start_time = datetime.now()
    
    try:
        set_rls_context(db, order.tenant_id or order.tenant_ext_id or "default")
        
        # Create and execute saga
        saga = CvOrderSaga(db, order.model_dump())
        result = await saga.execute()
        
        # Log audit
        await log_audit(
            db, "cv_order_processed", "order",
            details={"provider": order.provider, "order_id": result.get("order_id")},
            tenant_id=order.tenant_id
        )
        
        # Update metrics
        duration = (datetime.now() - start_time).total_seconds()
        cv_gateway_request_duration.labels(
            method="POST", endpoint="/cv/webhook/order", provider=order.provider
        ).observe(duration)
        
        cv_order_processing_total.labels(
            provider=order.provider, status="success", reason="completed"
        ).inc()
        
        cv_gateway_requests_total.labels(
            method="POST", endpoint="/cv/webhook/order", provider=order.provider, status="success"
        ).inc()
        
        return OrderResponse(**result)
        
    except HTTPException as e:
        # Update metrics for HTTP exceptions
        duration = (datetime.now() - start_time).total_seconds()
        cv_gateway_request_duration.labels(
            method="POST", endpoint="/cv/webhook/order", provider=order.provider
        ).observe(duration)
        
        cv_order_processing_total.labels(
            provider=order.provider, status="failure", reason=f"http_{e.status_code}"
        ).inc()
        
        cv_gateway_requests_total.labels(
            method="POST", endpoint="/cv/webhook/order", provider=order.provider, status="error"
        ).inc()
        raise
    except Exception as e:
        db.rollback()
        
        # Update metrics for other exceptions
        duration = (datetime.now() - start_time).total_seconds()
        cv_gateway_request_duration.labels(
            method="POST", endpoint="/cv/webhook/order", provider=order.provider
        ).observe(duration)
        
        cv_order_processing_total.labels(
            provider=order.provider, status="failure", reason="exception"
        ).inc()
        
        cv_gateway_requests_total.labels(
            method="POST", endpoint="/cv/webhook/order", provider=order.provider, status="error"
        ).inc()
        
        raise HTTPException(status_code=500, detail=f"Order processing failed: {str(e)}")

# =============================================================================
# REVIEW MANAGEMENT ENDPOINTS
# =============================================================================

@app.get("/cv/reviews")
async def list_reviews(
    tenant_id: str = Query(...),
    status: str = Query("pending"),
    limit: int = Query(50),
    db: Session = Depends(get_db)
):
    """List unknown item reviews for reconciliation"""
    try:
        set_rls_context(db, tenant_id)
        
        rows = db.execute(text("""
            SELECT id, provider, external_sku, name, qty, price_minor, status, created_at
              FROM cv_unknown_item_reviews
             WHERE tenant_id=:t AND status=:s
             ORDER BY id DESC
             LIMIT :l
        """), {"t": tenant_id, "s": status, "l": limit}).all()
        
        return [{
            "id": str(r[0]), "provider": r[1], "external_sku": r[2], "name": r[3],
            "qty": int(r[4]), "price_minor": int(r[5] or 0), "status": r[6], "created_at": str(r[7])
        } for r in rows]

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list reviews: {str(e)}")

@app.post("/cv/reviews/{review_id}/resolve")
async def resolve_review(
    review_id: str = Path(...),
    payload: ReviewResolvePayload = Body(...),
    db: Session = Depends(get_db)
):
    """Resolve an unknown item review"""
    try:
        # Get review to find tenant_id
        review = db.execute(text("""
            SELECT tenant_id FROM cv_unknown_item_reviews WHERE id=:id
        """), {"id": review_id}).first()
        
        if not review:
            raise HTTPException(status_code=404, detail="Review not found")
        
        set_rls_context(db, str(review[0]))
        
        # Update review
        db.execute(text("""
            UPDATE cv_unknown_item_reviews
               SET status=:st, mapped_sku=:ms, notes=:n, resolved_at=NOW()
             WHERE id=:id
        """), {"st": payload.status, "ms": payload.mapped_sku, "n": payload.notes, "id": review_id})
        
        db.commit()
        
        # Log audit
        await log_audit(
            db, "review_resolved", "cv_unknown_item_review",
            details={"review_id": review_id, "status": payload.status},
            tenant_id=str(review[0])
        )
        
        return {"id": review_id, "status": payload.status}

# =============================================================================
# INTEGRATION ENDPOINTS
# =============================================================================

@app.post("/cv/v4/integration/orders/create-order")
async def create_order_in_orders_service(
    tenant_id: str = Body(...),
    order_data: Dict[str, Any] = Body(...)
):
    """Integration endpoint to create order in Orders service"""
    try:
        logger.info(f"Creating order in Orders service for CV Gateway: tenant_id={tenant_id}")
        
        # Prepare order data for Orders service
        orders_data = {
            "tenant_id": tenant_id,
            "site_id": order_data.get("site_id"),
            "store_id": order_data.get("store_id"),
            "user_id": order_data.get("shopper_id"),
            "currency": order_data.get("currency", "GBP"),
            "total_minor": order_data.get("total_minor", 0),
            "items": order_data.get("items", []),
            "provider": order_data.get("provider"),
            "provider_order_id": order_data.get("provider_order_id"),
            "event_source": "cv_gateway"
        }
        
        # Notify Orders service via HTTP call
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    "http://localhost:8081/orders/v2",
                    json=orders_data
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Successfully created order in Orders service: {result}")
                    return {"ok": True, "order_created": True, "order_id": result.get("order_id")}
                else:
                    logger.warning(f"Orders service returned status {response.status_code}")
                    return {"ok": False, "order_created": False, "error": "Orders service error"}
                    
        except Exception as e:
            logger.error(f"Failed to create order in Orders service: {str(e)}")
            return {"ok": False, "order_created": False, "error": str(e)}
            
    except Exception as e:
        logger.error(f"Error creating order in Orders service: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create order: {str(e)}")

@app.post("/cv/v4/integration/approvals/budget-check")
async def check_budget_with_approvals_service(
    tenant_id: str = Body(...),
    amount_minor: int = Body(...),
    currency: str = Body("GBP"),
    cost_centre_id: str = Body(None),
    site_id: str = Body(None),
    store_id: str = Body(None)
):
    """Integration endpoint to check budget with Approvals service"""
    try:
        logger.info(f"Checking budget with Approvals service: tenant_id={tenant_id}, amount={amount_minor}")
        
        # Prepare budget check data
        budget_check_data = {
            "tenant_id": tenant_id,
            "amount_minor": amount_minor,
            "currency": currency,
            "cost_centre_id": cost_centre_id,
            "site_id": site_id,
            "store_id": store_id
        }
        
        # Notify Approvals service via HTTP call
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "http://localhost:8084/approvals/v2/integration/cv-gateway/budget-check",
                    json=budget_check_data
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Successfully checked budget with Approvals service: {result}")
                    return result
                else:
                    logger.warning(f"Approvals service returned status {response.status_code}")
                    return {"ok": False, "error": "Approvals service error"}
                    
        except Exception as e:
            logger.error(f"Failed to check budget with Approvals service: {str(e)}")
            return {"ok": False, "error": str(e)}
            
    except Exception as e:
        logger.error(f"Error checking budget with Approvals service: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to check budget: {str(e)}")

@app.post("/cv/v4/integration/billing/create-invoice")
async def create_invoice_with_billing_service(
    tenant_id: str = Body(...),
    order_id: str = Body(...),
    total_amount_minor: int = Body(...),
    currency: str = Body("GBP"),
    customer_id: str = Body(None),
    items: List[Dict[str, Any]] = Body(...)
):
    """Integration endpoint to create invoice with Billing service"""
    try:
        logger.info(f"Creating invoice with Billing service: tenant_id={tenant_id}, order_id={order_id}")
        
        # Prepare invoice data
        invoice_data = {
            "tenant_id": tenant_id,
            "order_id": order_id,
            "total_amount_minor": total_amount_minor,
            "currency": currency,
            "customer_id": customer_id,
            "items": items
        }
        
        # Notify Billing service via HTTP call
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    "http://localhost:8083/billing/v2/integration/cv-gateway/invoice-creation",
                    json=invoice_data
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Successfully created invoice with Billing service: {result}")
                    return result
                else:
                    logger.warning(f"Billing service returned status {response.status_code}")
                    return {"ok": False, "error": "Billing service error"}
                    
        except Exception as e:
            logger.error(f"Failed to create invoice with Billing service: {str(e)}")
            return {"ok": False, "error": str(e)}
            
    except Exception as e:
        logger.error(f"Error creating invoice with Billing service: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create invoice: {str(e)}")

@app.get("/cv/v4/integration/status")
async def get_integration_status():
    """Get status of all service integrations"""
    try:
        integration_status = {
            "orders_service": {"status": "unknown", "url": "http://localhost:8081"},
            "approvals_service": {"status": "unknown", "url": "http://localhost:8084"},
            "billing_service": {"status": "unknown", "url": "http://localhost:8083"},
            "ledger_service": {"status": "unknown", "url": "http://localhost:8086"},
            "cv_connector_service": {"status": "unknown", "url": "http://localhost:8100"}
        }
        
        # Test each service connectivity
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            for service_name, config in integration_status.items():
                try:
                    response = await client.get(f"{config['url']}/health")
                    if response.status_code == 200:
                        config["status"] = "healthy"
                        config["response_time_ms"] = response.elapsed.total_seconds() * 1000
                    else:
                        config["status"] = "unhealthy"
                except Exception as e:
                    config["status"] = "unreachable"
                    config["error"] = str(e)
        
        return {
            "integration_status": integration_status,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting integration status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get integration status: {str(e)}")
            tenant_id=str(review[0])
        )
        
        return {"id": review_id, "status": payload.status}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to resolve review: {str(e)}")

# =============================================================================
# STATISTICS ENDPOINTS
# =============================================================================

@app.get("/cv/orders")
async def list_cv_orders(
    tenant_id: str = Query(...),
    limit: int = Query(50),
    db: Session = Depends(get_db)
):
    """List CV orders for a tenant"""
    try:
        set_rls_context(db, tenant_id)
        
        rows = db.execute(text("""
            SELECT order_id, provider, provider_order_id, total_minor, currency, status, occurred_at
              FROM orders_new
             WHERE tenant_id=:t AND provider IS NOT NULL
             ORDER BY occurred_at DESC
             LIMIT :l
        """), {"t": tenant_id, "l": limit}).all()
        
        return [{
            "order_id": int(r[0]), "provider": r[1], "provider_order_id": r[2],
            "total_minor": int(r[3]), "currency": r[4], "status": r[5], "occurred_at": str(r[6])
        } for r in rows]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list CV orders: {str(e)}")

@app.get("/cv/stats/{tenant_id}")
async def get_cv_stats(tenant_id: str = Path(...), db: Session = Depends(get_db)):
    """Get CV statistics for a tenant"""
    try:
        set_rls_context(db, tenant_id)
        
        # Total orders
        total_orders = db.execute(text("""
            SELECT COUNT(*) FROM orders_new WHERE tenant_id=:t AND provider IS NOT NULL
        """), {"t": tenant_id}).scalar()
        
        # Total revenue
        total_revenue = db.execute(text("""
            SELECT COALESCE(SUM(total_minor), 0) FROM orders_new 
            WHERE tenant_id=:t AND provider IS NOT NULL AND status='completed'
        """), {"t": tenant_id}).scalar()
        
        # Pending reviews
        pending_reviews = db.execute(text("""
            SELECT COUNT(*) FROM cv_unknown_item_reviews 
            WHERE tenant_id=:t AND status='pending'
        """), {"t": tenant_id}).scalar()
        
        return {
            "tenant_id": tenant_id,
            "total_orders": int(total_orders),
            "total_revenue_minor": int(total_revenue),
            "pending_reviews": int(pending_reviews)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get CV stats: {str(e)}")

# =============================================================================
# LEGACY ENDPOINTS (DEPRECATED)
# =============================================================================

@app.post("/cv/aifi/webhook/order")
async def aifi_order_legacy(payload: dict = Body(...)):
    """Legacy AiFi order webhook - DEPRECATED"""
    return {
        "deprecated": True,
        "migrate_to": "/cv/webhook/order",
        "message": "This endpoint is deprecated. Please use /cv/webhook/order with provider parameter."
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)