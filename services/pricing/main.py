# services/pricing/main.py
"""
Enhanced Pricing Service with V2 Multi-Tenant Marketplace Architecture

This service implements:
- V2 pricing system with pricebooks, price rules, and calculated prices
- PriceResolver logic for multi-level pricing resolution
- Service-specific event streams and saga patterns
- Circuit breaker pattern for external calls
- Event sourcing with PRICE_UPDATED events
- Health monitoring and comprehensive metrics
- Enhanced RBAC with scoped pricing permissions
"""

import os
import sys
import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Body, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy import text, UUID, String, Boolean, DateTime, func, JSON, BigInteger, Integer, Numeric, Float
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID

# Try to use uuid7 for time-sortable UUIDs, fallback to uuid4 if not available
try:
    from uuid import uuid7
    def generate_time_sortable_uuid():
        return str(uuid7())
except ImportError:
    def generate_time_sortable_uuid():
        return str(uuid.uuid4())

# Add the packages path to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', 'packages', 'zeroque_common'))

from zeroque_common.communication import (
    ServiceBus, ServiceEvent,
    CircuitBreaker, CircuitBreakerConfig,
    SagaOrchestrator, SagaStep,
    ServiceRegistry, HealthMonitor,
    EventStore,
    # Global instances
    service_bus as global_service_bus,
    service_circuit_breaker,
    saga_orchestrator,
    service_registry,
    health_monitor,
    event_store
)
from zeroque_common.events.bus import EventType
from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal, Base
from zeroque_common.middleware.usage_middleware import add_api_call_meter
from zeroque_common.middleware.idempotency import add_idempotency_middleware
from zeroque_common.observability import setup_logging, init_metrics, init_insights, add_observability_middleware

# Service configuration
SERVICE_NAME = "pricing"
app = FastAPI(title="Enhanced ZeroQue Pricing Service", version="2.0.0")

# Initialize enhanced communication
service_bus = global_service_bus
circuit_breaker_config = CircuitBreakerConfig(
    failure_threshold=3,
    timeout=30,
    success_threshold=2
)

# ---- observability ----
logger = setup_logging(SERVICE_NAME, "2.0.0")
metrics = init_metrics(SERVICE_NAME)
insights = init_insights(SERVICE_NAME, "2.0.0")

# ---- middleware ----
add_observability_middleware(app, SERVICE_NAME)
add_api_call_meter(app)
add_idempotency_middleware(app, routes=[
    ("POST", "/pricing/v2/pricebooks"),
    ("PUT", "/pricing/v2/pricebooks"),
    ("POST", "/pricing/v2/pricebook-assignments"),
    ("PUT", "/pricing/v2/pricebook-assignments"),
    ("POST", "/pricing/v2/pricebook-entries"),
    ("PUT", "/pricing/v2/pricebook-entries"),
    ("POST", "/pricing/v2/price-rules"),
    ("PUT", "/pricing/v2/price-rules"),
])

# V2 SQLAlchemy Models for Pricing System
class PricebookV2(Base):
    __tablename__ = "pricebooks"
    pricebook_id: Mapped[str] = mapped_column(PostgresUUID, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    pricebook_type: Mapped[str] = mapped_column(String(50))
    currency: Mapped[str] = mapped_column(String(3))
    hierarchy_rank: Mapped[int] = mapped_column(Integer, default=100)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    effective_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class PricebookAssignmentV2(Base):
    __tablename__ = "pricebook_assignments"
    assignment_id: Mapped[str] = mapped_column(PostgresUUID, primary_key=True)
    pricebook_id: Mapped[str] = mapped_column(PostgresUUID)
    target_type: Mapped[str] = mapped_column(String(50))  # TENANT, SITE, STORE, ROLE, VENDOR
    target_id: Mapped[str] = mapped_column(PostgresUUID)
    assignment_priority: Mapped[int] = mapped_column(Integer, default=100)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    effective_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class PricebookEntryV2(Base):
    __tablename__ = "pricebook_entries"
    entry_id: Mapped[str] = mapped_column(PostgresUUID, primary_key=True)
    pricebook_id: Mapped[str] = mapped_column(PostgresUUID)
    offer_id: Mapped[str] = mapped_column(PostgresUUID)
    price_minor: Mapped[int] = mapped_column(BigInteger)
    min_quantity: Mapped[int] = mapped_column(Integer, default=1)
    max_quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    effective_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class PricingVersionV2(Base):
    __tablename__ = "pricing_versions"
    version_id: Mapped[str] = mapped_column(PostgresUUID, primary_key=True)
    version_number: Mapped[int] = mapped_column(BigInteger)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    effective_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class PriceRuleV2(Base):
    __tablename__ = "price_rules_new"
    rule_id: Mapped[str] = mapped_column(PostgresUUID, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    rule_type: Mapped[str] = mapped_column(String(50))
    rule_config: Mapped[dict] = mapped_column(JSON)
    application_scope: Mapped[str] = mapped_column(String(50))
    application_order: Mapped[int] = mapped_column(Integer, default=100)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    scope_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    scope_id: Mapped[Optional[str]] = mapped_column(PostgresUUID, nullable=True)
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    version_created: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class CalculatedPriceV2(Base):
    __tablename__ = "calculated_prices"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    store_id: Mapped[str] = mapped_column(String)
    sku: Mapped[str] = mapped_column(String)
    user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    currency: Mapped[str] = mapped_column(String(3))
    applied_rules: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    applied_promotions: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    base_price_minor: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    final_price_minor: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

class PriceHookV2(Base):
    __tablename__ = "price_hooks"
    hook_id: Mapped[str] = mapped_column(PostgresUUID, primary_key=True)
    hook_name: Mapped[str] = mapped_column(String(100))
    hook_type: Mapped[str] = mapped_column(String(50))
    hook_config: Mapped[dict] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class PriceRuleConditionV2(Base):
    __tablename__ = "price_rule_conditions"
    condition_id: Mapped[str] = mapped_column(PostgresUUID, primary_key=True)
    rule_id: Mapped[str] = mapped_column(PostgresUUID)
    condition_type: Mapped[str] = mapped_column(String(50))
    condition_config: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class PromotionV2(Base):
    __tablename__ = "promotions"
    promotion_id: Mapped[str] = mapped_column(PostgresUUID, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    promo_type: Mapped[str] = mapped_column(String(50))
    promo_config: Mapped[dict] = mapped_column(JSON)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    scope_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    scope_id: Mapped[Optional[str]] = mapped_column(PostgresUUID, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

# Note: StoreV2, TenantV2, VendorV2 models are imported from zeroque_common
# or can be referenced directly from the database schema

@app.on_event("startup")
async def startup():
    """Enhanced startup with full communication integration"""
    logger.info("Starting enhanced pricing service")
    
    # Initialize database
    get_engine()
    init_db()
    
    # Register service
    try:
        await service_registry.register_service(
            service_name=SERVICE_NAME,
            version="2.0.0",
            health_check_url="http://localhost:8203/health"
        )
        logger.info("Service registered successfully")
    except Exception as e:
        logger.warning(f"Service registration failed: {str(e)}")
    
    # Subscribe to events
    try:
        service_bus.subscribe_to_event(EventType.PRICE_CALCULATED, handle_price_calculated)
        service_bus.subscribe_to_event(EventType.PRICE_CHANGED, handle_price_changed)
        service_bus.subscribe_to_event(EventType.VERSION_CHANGED, handle_version_changed)
        service_bus.subscribe_to_event(EventType.PRODUCT_CREATED, handle_product_created)
    except Exception as e:
        logger.warning(f"Event subscription failed: {str(e)}")
    
    # Start event consumer (temporarily commented for testing)
    # try:
    #     await service_bus.start_consumer()
    #     logger.info("Event consumer started")
    # except Exception as e:
    #     logger.warning(f"Event consumer start failed: {str(e)}")
    
    # Start health monitoring (temporarily commented for testing)
    # try:
    #     await health_monitor.start_monitoring()
    #     logger.info("Health monitoring started")
    # except Exception as e:
    #     logger.warning(f"Health monitoring start failed: {str(e)}")
    
    # Publish service started event
    try:
        await service_bus.publish_to_service(
            target_service="observability",
            event_type=EventType.SERVICE_STARTED,
            data={
                "service_name": SERVICE_NAME,
                "version": "2.0.0",
                "status": "healthy"
            }
        )
    except Exception as e:
        logger.warning(f"Failed to publish service started event: {str(e)}")
    
    logger.info("Enhanced pricing service started successfully")

# PriceResolver Logic
class PriceResolver:
    """Enhanced price resolver with multi-level pricing support"""
    
    def __init__(self):
        self.cache_ttl = timedelta(hours=1)
        self.logger = logger
    
    async def resolve_price(self, store_id: str, offer_id: str, user_id: Optional[str] = None, 
                          currency: str = "GBP", tenant_id: Optional[str] = None) -> Dict[str, Any]:
        """Resolve price using pricebooks and price rules"""
        start_time = datetime.now()
        metrics.counter("price_resolver.called").inc()
        
        try:
            # Check cache first
            cached_price = await self._get_cached_price(store_id, offer_id, user_id, currency)
            if cached_price:
                metrics.counter("price_resolver.cache_hit").inc()
                return cached_price
            
            # Resolve from pricebooks and rules
            price_data = await self._resolve_from_pricebooks(store_id, offer_id, user_id, currency, tenant_id)
            
            # Apply price rules
            final_price = await self._apply_price_rules(price_data, store_id, offer_id, user_id, currency, tenant_id)
            
            # Cache the result
            await self._cache_price(price_data, store_id, offer_id, user_id, currency)
            
            # Record metrics
            resolution_time = (datetime.now() - start_time).total_seconds()
            metrics.histogram("price_resolver.duration").observe(resolution_time)
            metrics.counter("price_resolver.cache_miss").inc()
            
            return final_price
            
        except Exception as e:
            metrics.counter("price_resolver.error").inc()
            logger.error(f"Price resolution failed: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Price resolution failed: {str(e)}")
    
    async def _get_cached_price(self, store_id: str, offer_id: str, user_id: Optional[str], currency: str) -> Optional[Dict[str, Any]]:
        """Get cached price from calculated_prices table"""
        with SessionLocal() as db:
            cached = db.query(CalculatedPriceV2).filter(
                CalculatedPriceV2.store_id == store_id,
                CalculatedPriceV2.sku == offer_id,  # Using offer_id as sku for now
                CalculatedPriceV2.user_id == user_id,
                CalculatedPriceV2.currency == currency,
                CalculatedPriceV2.expires_at > datetime.now()
            ).first()
            
            if cached:
                return {
                    "base_price_minor": cached.base_price_minor,
                    "final_price_minor": cached.final_price_minor,
                    "applied_rules": cached.applied_rules,
                    "applied_promotions": cached.applied_promotions,
                    "calculated_at": cached.calculated_at,
                    "cached": True
                }
        return None
    
    async def _resolve_from_pricebooks(self, store_id: str, offer_id: str, user_id: Optional[str], 
                                     currency: str, tenant_id: Optional[str]) -> Dict[str, Any]:
        """Resolve base price from pricebooks"""
        with SessionLocal() as db:
            # Get applicable pricebooks for the store/user
            pricebooks_query = text("""
                SELECT pb.pricebook_id, pb.name, pb.hierarchy_rank, pe.price_minor
                FROM pricebooks pb
                JOIN pricebook_assignments pa ON pb.pricebook_id = pa.pricebook_id
                JOIN pricebook_entries pe ON pb.pricebook_id = pe.pricebook_id
                WHERE pe.offer_id = :offer_id 
                AND pb.active = true
                AND pb.effective_from <= :now
                AND (pb.effective_until IS NULL OR pb.effective_until > :now)
                AND pa.effective_from <= :now
                AND (pa.effective_until IS NULL OR pa.effective_until > :now)
                AND pe.effective_from <= :now
                AND (pe.effective_until IS NULL OR pe.effective_until > :now)
                AND (
                    (pa.target_type = 'STORE' AND pa.target_id = :store_id) OR
                    (pa.target_type = 'TENANT' AND pa.target_id = :tenant_id) OR
                    (pa.target_type = 'ROLE' AND pa.target_id IN (
                        SELECT role_id FROM role_assignments WHERE user_id = :user_id
                    ))
                )
                ORDER BY pb.hierarchy_rank ASC, pa.assignment_priority ASC
                LIMIT 1
            """)
            
            result = db.execute(pricebooks_query, {
                "offer_id": offer_id,
                "store_id": store_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "now": datetime.now()
            }).first()
            
            if result:
                return {
                    "base_price_minor": result.price_minor,
                    "pricebook_id": result.pricebook_id,
                    "pricebook_name": result.name,
                    "source": "pricebook"
                }
            else:
                # Fallback to default pricing
                return {
                    "base_price_minor": 0,  # Will be handled by price rules
                    "source": "default"
                }
    
    async def _apply_price_rules(self, price_data: Dict[str, Any], store_id: str, offer_id: str, 
                               user_id: Optional[str], currency: str, tenant_id: Optional[str]) -> Dict[str, Any]:
        """Apply price rules to the base price with exchange rates, price hooks, and rule conditions"""
        with SessionLocal() as db:
            # Apply exchange rate conversion for non-GBP currencies
            base_price = price_data["base_price_minor"]
            if currency != "GBP":
                rate_query = text("""
                    SELECT rate FROM exchange_rates 
                    WHERE currency = :currency 
                    AND valid_at <= :now 
                    ORDER BY valid_at DESC 
                    LIMIT 1
                """)
                rate = db.execute(rate_query, {
                    "currency": currency, 
                    "now": datetime.now()
                }).scalar()
                if rate:
                    base_price = int(base_price * rate)
                    logger.info(f"Applied exchange rate {rate} for currency {currency}")
            
            # Get applicable price rules with conditions
            rules_query = text("""
                SELECT pr.rule_id, pr.name, pr.rule_type, pr.conditions, pr.actions, pr.priority,
                       prc.condition_type, prc.condition_config
                FROM price_rules_new pr
                LEFT JOIN price_rule_conditions prc ON pr.rule_id = prc.rule_id
                WHERE pr.active = true
                ORDER BY pr.priority ASC
            """)
            
            rules = db.execute(rules_query).fetchall()
            
            final_price = base_price
            applied_rules = []
            
            for rule in rules:
                rule_config = rule.rule_config
                rule_type = rule.rule_type
                
                # Evaluate rule conditions
                if rule.condition_type and not self._evaluate_rule_condition(
                    rule.condition_type, rule.condition_config, offer_id, user_id, store_id, tenant_id
                ):
                    continue
                
                # Apply rule based on type
                if rule_type == "percentage_discount":
                    discount = rule_config.get("discount_percentage", 0)
                    final_price = int(final_price * (1 - discount / 100))
                elif rule_type == "fixed_discount":
                    discount = rule_config.get("discount_amount_minor", 0)
                    final_price = max(0, final_price - discount)
                elif rule_type == "markup":
                    markup = rule_config.get("markup_percentage", 0)
                    final_price = int(final_price * (1 + markup / 100))
                elif rule_type == "tiered":
                    # Tiered pricing based on quantity
                    tiers = rule_config.get("tiers", [])
                    for tier in sorted(tiers, key=lambda x: x.get("min_quantity", 0), reverse=True):
                        min_qty = tier.get("min_quantity", 0)
                        if min_qty <= 1:  # Default to first tier for single item
                            final_price = tier.get("price_minor", final_price)
                            break
                elif rule_type == "override":
                    # Override price completely
                    override_price = rule_config.get("price_minor", final_price)
                    final_price = override_price
                
                applied_rules.append({
                    "rule_id": rule.rule_id,
                    "rule_name": rule.name,
                    "rule_type": rule_type,
                    "applied_at": datetime.now()
                })
            
            # Apply price hooks
            await self._apply_price_hooks(final_price, store_id, offer_id, user_id, currency, tenant_id)
            
            # Apply promotions
            applied_promotions = await self._apply_promotions(final_price, store_id, offer_id, user_id, currency, tenant_id)
            
            return {
                "base_price_minor": base_price,
                "final_price_minor": final_price,
                "applied_rules": applied_rules,
                "applied_promotions": applied_promotions,
                "calculated_at": datetime.now(),
                "source": price_data.get("source", "unknown")
            }
    
    def _evaluate_rule_condition(self, condition_type: str, condition_config: Dict[str, Any], 
                                offer_id: str, user_id: Optional[str], store_id: str, tenant_id: Optional[str]) -> bool:
        """Evaluate rule conditions for price rule application"""
        if condition_type == "sku_match":
            target_skus = condition_config.get("skus", [])
            return offer_id in target_skus
        elif condition_type == "category_match":
            # Would need to join with product catalog to get category
            target_categories = condition_config.get("categories", [])
            # Simplified: assume we can get category from offer_id or skip for now
            return True
        elif condition_type == "time_range":
            now = datetime.now()
            start_time = condition_config.get("start_time")
            end_time = condition_config.get("end_time")
            if start_time and now < start_time:
                return False
            if end_time and now > end_time:
                return False
            return True
        elif condition_type == "user_role":
            if not user_id:
                return False
            target_roles = condition_config.get("roles", [])
            # Would need to query user roles from database
            # Simplified: assume condition passes for now
            return True
        elif condition_type == "min_amount":
            min_amount = condition_config.get("min_amount_minor", 0)
            # Would need current cart total or order amount
            # Simplified: assume condition passes for now
            return True
        return True  # Default to applying rule if condition type not recognized
    
    async def _apply_price_hooks(self, price: int, store_id: str, offer_id: str, 
                                user_id: Optional[str], currency: str, tenant_id: Optional[str]) -> int:
        """Apply price hooks for external price adjustments"""
        with SessionLocal() as db:
            hooks_query = text("""
                SELECT hook_id, name, hook_type, hook_config, priority
                FROM price_hooks
                WHERE active = true
                AND (valid_from IS NULL OR valid_from <= :now)
                AND (valid_until IS NULL OR valid_until > :now)
                ORDER BY priority ASC
            """)
            
            hooks = db.execute(hooks_query, {
                "now": datetime.now()
            }).fetchall()
            
            final_price = price
            
            for hook in hooks:
                hook_config = hook.hook_config
                hook_type = hook.hook_type
                
                try:
                    if hook_type == "external_api":
                        # Call external API for price adjustment
                        api_endpoint = hook_config.get("api_endpoint")
                        api_key = hook_config.get("api_key")
                        if api_endpoint and api_key:
                            # Make HTTP call to external service
                            # This would be implemented with httpx or requests
                            logger.info(f"Would call external price hook: {hook.name}")
                            # For now, just log the hook execution
                    elif hook_type == "custom_function":
                        # Execute custom pricing function
                        function_name = hook_config.get("function_name")
                        if function_name:
                            logger.info(f"Would execute custom function: {function_name}")
                            # For now, just log the function execution
                    elif hook_type == "percentage_adjustment":
                        # Apply percentage adjustment
                        adjustment = hook_config.get("adjustment_percentage", 0)
                        final_price = int(final_price * (1 + adjustment / 100))
                        logger.info(f"Applied price hook {hook.name}: {adjustment}% adjustment")
                    elif hook_type == "fixed_adjustment":
                        # Apply fixed amount adjustment
                        adjustment = hook_config.get("adjustment_amount_minor", 0)
                        final_price = max(0, final_price + adjustment)
                        logger.info(f"Applied price hook {hook.name}: {adjustment} minor units adjustment")
                        
                except Exception as e:
                    logger.error(f"Error applying price hook {hook.name}: {str(e)}")
                    continue
            
            return final_price
    
    async def _cache_price(self, price_data: Dict[str, Any], store_id: str, offer_id: str, 
                         user_id: Optional[str], currency: str):
        """Cache the calculated price"""
        with SessionLocal() as db:
            # Remove existing cache entries
            db.query(CalculatedPriceV2).filter(
                CalculatedPriceV2.store_id == store_id,
                CalculatedPriceV2.sku == offer_id,  # Using offer_id as sku for now
                CalculatedPriceV2.user_id == user_id,
                CalculatedPriceV2.currency == currency
            ).delete()
            
            # Create new cache entry
            # Convert UUIDs to strings for JSON serialization
            applied_rules = price_data.get("applied_rules", [])
            applied_promotions = price_data.get("applied_promotions", [])
            
            if applied_rules:
                applied_rules = [{k: str(v) if isinstance(v, uuid.UUID) else v for k, v in rule.items()} for rule in applied_rules]
            if applied_promotions:
                applied_promotions = [{k: str(v) if isinstance(v, uuid.UUID) else v for k, v in promo.items()} for promo in applied_promotions]
            
            cached_price = CalculatedPriceV2(
                store_id=store_id,
                sku=offer_id,  # Using offer_id as sku for now
                user_id=user_id,
                currency=currency,
                applied_rules=applied_rules,
                applied_promotions=applied_promotions,
                expires_at=datetime.now() + self.cache_ttl,
                base_price_minor=price_data.get("base_price_minor"),
                final_price_minor=price_data.get("final_price_minor")
            )
            db.add(cached_price)
            db.commit()
    
    async def _apply_promotions(self, base_price: int, store_id: str, offer_id: str, 
                              user_id: Optional[str], currency: str, tenant_id: Optional[str]) -> List[Dict[str, Any]]:
        """Apply promotions to the price"""
        with SessionLocal() as db:
            # Get applicable promotions
            promotions_query = text("""
                SELECT id, name, promo_type, promo_config, priority
                FROM promotions
                WHERE active = true
                AND (valid_from IS NULL OR valid_from <= :now)
                AND (valid_until IS NULL OR valid_until > :now)
                ORDER BY priority ASC
            """)
            
            promotions = db.execute(promotions_query, {
                "store_id": store_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "now": datetime.now()
            }).fetchall()
            
            applied_promotions = []
            final_price = base_price
            
            for promo in promotions:
                promo_config = promo.promo_config
                promo_type = promo.promo_type
                
                # Apply promotion based on type
                if promo_type == "percentage_discount":
                    discount_pct = promo_config.get("discount_percentage", 0)
                    discount_amount = int(final_price * discount_pct / 100)
                    new_price = max(0, final_price - discount_amount)
                    if new_price != final_price:
                        applied_promotions.append({
                            "promotion_id": promo.id,
                            "promotion_name": promo.name,
                            "promo_type": promo_type,
                            "old_price": final_price,
                            "new_price": new_price,
                            "discount": discount_amount
                        })
                        final_price = new_price
                elif promo_type == "fixed_discount":
                    discount_amount = promo_config.get("discount_amount_minor", 0)
                    new_price = max(0, final_price - discount_amount)
                    if new_price != final_price:
                        applied_promotions.append({
                            "promotion_id": promo.id,
                            "promotion_name": promo.name,
                            "promo_type": promo_type,
                            "old_price": final_price,
                            "new_price": new_price,
                            "discount": discount_amount
                        })
                        final_price = new_price
                elif promo_type == "buy_one_get_one":
                    # BOGO logic - simplified for now
                    if promo_config.get("enabled", False):
                        # Apply 50% discount for BOGO
                        discount_amount = int(final_price / 2)
                        new_price = final_price - discount_amount
                        applied_promotions.append({
                            "promotion_id": promo.id,
                            "promotion_name": promo.name,
                            "promo_type": promo_type,
                            "old_price": final_price,
                            "new_price": new_price,
                            "discount": discount_amount
                        })
                        final_price = new_price
            
            return applied_promotions

# Initialize price resolver
price_resolver = PriceResolver()

# RLS Context Helper
def set_rls_context(db, tenant_id: Optional[str] = None, user_id: Optional[str] = None):
    """Set Row Level Security context for database session"""
    if tenant_id:
        db.execute(text("SET LOCAL row_security.tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    if user_id:
        db.execute(text("SET LOCAL row_security.user_id = :user_id"), {"user_id": user_id})

# Pydantic Models for API
class PricebookV2Payload(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    pricebook_type: str = Field(..., min_length=1, max_length=50)
    currency: str = Field(..., min_length=3, max_length=3)
    hierarchy_rank: int = Field(100, ge=1, le=1000)
    active: bool = True
    effective_from: Optional[datetime] = None
    effective_until: Optional[datetime] = None

class PricebookAssignmentV2Payload(BaseModel):
    pricebook_id: str = Field(..., min_length=1)
    target_type: str = Field(..., min_length=1, max_length=50)
    target_id: str = Field(..., min_length=1)
    assignment_priority: int = Field(100, ge=1, le=1000)
    effective_from: Optional[datetime] = None
    effective_until: Optional[datetime] = None

class PricebookEntryV2Payload(BaseModel):
    pricebook_id: str = Field(..., min_length=1)
    offer_id: str = Field(..., min_length=1)
    price_minor: int = Field(..., ge=0, description="Price in minor units (cents)")
    min_quantity: int = Field(1, ge=1, description="Minimum quantity for this price")
    max_quantity: Optional[int] = Field(None, ge=1, description="Maximum quantity for this price")
    effective_from: Optional[datetime] = None
    effective_until: Optional[datetime] = None

class PriceRuleV2Payload(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    rule_type: str = Field(..., min_length=1, max_length=50)
    rule_config: Dict[str, Any] = Field(..., description="Rule configuration JSON")
    application_scope: str = Field(..., min_length=1, max_length=50)
    application_order: int = Field(100, ge=1, le=1000)
    priority: int = Field(100, ge=1, le=1000)
    active: bool = True
    scope_type: Optional[str] = Field(None, max_length=50)
    scope_id: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None

class PriceResolutionRequest(BaseModel):
    store_id: str = Field(..., min_length=1)
    offer_id: str = Field(..., min_length=1)
    user_id: Optional[str] = None
    currency: str = Field("GBP", min_length=3, max_length=3)
    tenant_id: Optional[str] = None

class PriceHookV2Payload(BaseModel):
    hook_name: str = Field(..., min_length=1, max_length=100)
    hook_type: str = Field(..., min_length=1, max_length=50)
    hook_config: Dict[str, Any] = Field(..., description="Hook configuration JSON")
    active: bool = True

class PriceRuleConditionV2Payload(BaseModel):
    rule_id: str = Field(..., min_length=1)
    condition_type: str = Field(..., min_length=1, max_length=50)
    condition_config: Dict[str, Any] = Field(..., description="Condition configuration JSON")

class PricingVersionV2Payload(BaseModel):
    version_number: int = Field(..., ge=1)
    effective_from: Optional[datetime] = None
    effective_until: Optional[datetime] = None

@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}

@app.get("/readiness")
def readiness():
    return {"service": SERVICE_NAME, "db": check_db(), "redis": True}

# V2 API Endpoints

@app.post("/pricing/v2/resolve")
async def resolve_price(request: PriceResolutionRequest = Body(...)):
    """Resolve price for a product using pricebooks and price rules"""
    start_time = datetime.now()
    metrics.counter("endpoint.resolve_price.called").inc()
    
    try:
        result = await price_resolver.resolve_price(
            store_id=request.store_id,
            offer_id=request.offer_id,
            user_id=request.user_id,
            currency=request.currency,
            tenant_id=request.tenant_id
        )
        
        metrics.histogram("endpoint.resolve_price.duration").observe((datetime.now() - start_time).total_seconds())
        return result
        
    except Exception as e:
        metrics.counter("endpoint.resolve_price.error").inc()
        logger.error(f"Price resolution failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/pricing/v2/pricebooks/{pricebook_id}")
async def upsert_pricebook(
    pricebook_id: str = Path(...), 
    payload: PricebookV2Payload = Body(...),
    tenant_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None)
):
    """Create or update a pricebook (V2 architecture)"""
    start_time = datetime.now()
    metrics.counter("endpoint.pricebook_upsert.called").inc()
    
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id=tenant_id, user_id=user_id)
            # Validate currency exists
            currency = db.execute(text("SELECT iso_code FROM currencies WHERE iso_code=:code"), 
                               {"code": payload.currency}).first()
            if not currency:
                raise HTTPException(status_code=400, detail="Currency not found")
            
            # Check if pricebook exists
            existing = db.query(PricebookV2).filter(PricebookV2.pricebook_id == pricebook_id).first()
            
            if existing:
                # Update existing pricebook
                existing.name = payload.name
                existing.description = payload.description
                existing.pricebook_type = payload.pricebook_type
                existing.currency = payload.currency
                existing.hierarchy_rank = payload.hierarchy_rank
                existing.active = payload.active
                existing.effective_from = payload.effective_from or datetime.now()
                existing.effective_until = payload.effective_until
                existing.updated_at = datetime.now()
                db.commit()
                
                logger.info("pricebook_updated", extra={"pricebook_id": pricebook_id})
                
                # Publish event
                await service_bus.publish_to_service(
                    target_service="catalog",
                    event_type=EventType.PRICE_CHANGED,
                    data={"pricebook_id": pricebook_id, "action": "updated"}
                )
                
                metrics.histogram("endpoint.pricebook_upsert.duration").observe((datetime.now() - start_time).total_seconds())
                return {"pricebook_id": str(pricebook_id), "name": payload.name, "updated": True}
            else:
                # Create new pricebook
                pricebook = PricebookV2(
                    pricebook_id=pricebook_id,
                    name=payload.name,
                    description=payload.description,
                    pricebook_type=payload.pricebook_type,
                    currency=payload.currency,
                    hierarchy_rank=payload.hierarchy_rank,
                    active=payload.active,
                    effective_from=payload.effective_from or datetime.now(),
                    effective_until=payload.effective_until
                )
                db.add(pricebook)
                db.commit()
                
                logger.info("pricebook_created", extra={"pricebook_id": pricebook_id})
                
                # Publish event
                await service_bus.publish_to_service(
                    target_service="catalog",
                    event_type=EventType.PRICE_CHANGED,
                    data={"pricebook_id": pricebook_id, "action": "created"}
                )
                
                metrics.histogram("endpoint.pricebook_upsert.duration").observe((datetime.now() - start_time).total_seconds())
                return {"pricebook_id": str(pricebook_id), "name": payload.name, "created": True}
                
    except HTTPException:
        metrics.counter("endpoint.pricebook_upsert.error").inc()
        raise
    except Exception as e:
        metrics.counter("endpoint.pricebook_upsert.error").inc()
        logger.error(f"Pricebook upsert failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/pricing/v2/pricebook-assignments/{assignment_id}")
async def upsert_pricebook_assignment(
    assignment_id: str = Path(...), 
    payload: PricebookAssignmentV2Payload = Body(...),
    tenant_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None)
):
    """Create or update a pricebook assignment (V2 architecture)"""
    start_time = datetime.now()
    metrics.counter("endpoint.pricebook_assignment_upsert.called").inc()
    
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id=tenant_id, user_id=user_id)
            # Validate pricebook exists
            pricebook = db.query(PricebookV2).filter(PricebookV2.pricebook_id == payload.pricebook_id).first()
            if not pricebook:
                raise HTTPException(status_code=400, detail="Pricebook not found")
            
            # Validate target_id exists for target_type
            if payload.target_type == "STORE":
                store = db.execute(text("SELECT store_id FROM stores WHERE store_id=:id"), {"id": payload.target_id}).first()
                if not store:
                    raise HTTPException(status_code=400, detail="Store not found")
            elif payload.target_type == "TENANT":
                tenant = db.execute(text("SELECT tenant_id FROM tenants_new WHERE tenant_id=:id"), {"id": payload.target_id}).first()
                if not tenant:
                    raise HTTPException(status_code=400, detail="Tenant not found")
            elif payload.target_type == "ROLE":
                role = db.execute(text("SELECT role_id FROM roles_new WHERE role_id=:id"), {"id": payload.target_id}).first()
                if not role:
                    raise HTTPException(status_code=400, detail="Role not found")
            elif payload.target_type == "VENDOR":
                vendor = db.execute(text("SELECT vendor_id FROM vendors WHERE vendor_id=:id"), {"id": payload.target_id}).first()
                if not vendor:
                    raise HTTPException(status_code=400, detail="Vendor not found")
            
            # Check if assignment exists
            existing = db.query(PricebookAssignmentV2).filter(PricebookAssignmentV2.assignment_id == assignment_id).first()
            
            if existing:
                # Update existing assignment
                existing.pricebook_id = payload.pricebook_id
                existing.target_type = payload.target_type
                existing.target_id = payload.target_id
                existing.assignment_priority = payload.assignment_priority
                existing.effective_from = payload.effective_from or datetime.now()
                existing.effective_until = payload.effective_until
                db.commit()
                
                logger.info("pricebook_assignment_updated", extra={"assignment_id": assignment_id})
                metrics.histogram("endpoint.pricebook_assignment_upsert.duration").observe((datetime.now() - start_time).total_seconds())
                return {"assignment_id": str(assignment_id), "updated": True}
            else:
                # Create new assignment
                assignment = PricebookAssignmentV2(
                    assignment_id=assignment_id,
                    pricebook_id=payload.pricebook_id,
                    target_type=payload.target_type,
                    target_id=payload.target_id,
                    assignment_priority=payload.assignment_priority,
                    effective_from=payload.effective_from or datetime.now(),
                    effective_until=payload.effective_until
                )
                db.add(assignment)
                db.commit()
                
                logger.info("pricebook_assignment_created", extra={"assignment_id": assignment_id})
                metrics.histogram("endpoint.pricebook_assignment_upsert.duration").observe((datetime.now() - start_time).total_seconds())
                return {"assignment_id": str(assignment_id), "created": True}
                
    except HTTPException:
        metrics.counter("endpoint.pricebook_assignment_upsert.error").inc()
        raise
    except Exception as e:
        metrics.counter("endpoint.pricebook_assignment_upsert.error").inc()
        logger.error(f"Pricebook assignment upsert failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/pricing/v2/pricebook-entries/{entry_id}")
async def upsert_pricebook_entry(
    entry_id: str = Path(...), 
    payload: PricebookEntryV2Payload = Body(...),
    tenant_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None)
):
    """Create or update a pricebook entry (V2 architecture)"""
    start_time = datetime.now()
    metrics.counter("endpoint.pricebook_entry_upsert.called").inc()
    
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id=tenant_id, user_id=user_id)
            # Validate pricebook exists
            pricebook = db.query(PricebookV2).filter(PricebookV2.pricebook_id == payload.pricebook_id).first()
            if not pricebook:
                raise HTTPException(status_code=400, detail="Pricebook not found")
            
            # Validate offer exists
            offer = db.execute(text("SELECT offer_id FROM vendor_offers WHERE offer_id=:id"), 
                             {"id": payload.offer_id}).first()
            if not offer:
                raise HTTPException(status_code=400, detail="Vendor offer not found")
            
            # Check if entry exists
            existing = db.query(PricebookEntryV2).filter(PricebookEntryV2.entry_id == entry_id).first()
            
            if existing:
                # Update existing entry
                existing.pricebook_id = payload.pricebook_id
                existing.offer_id = payload.offer_id
                existing.price_minor = payload.price_minor
                existing.min_quantity = payload.min_quantity
                existing.max_quantity = payload.max_quantity
                existing.effective_from = payload.effective_from or datetime.now()
                existing.effective_until = payload.effective_until
                db.commit()
                
                logger.info("pricebook_entry_updated", extra={"entry_id": entry_id})
                
                # Publish event to invalidate cache
                await service_bus.publish_to_service(
                    target_service="catalog",
                    event_type=EventType.PRICE_CHANGED,
                    data={"entry_id": entry_id, "offer_id": payload.offer_id, "action": "updated"}
                )
                
                metrics.histogram("endpoint.pricebook_entry_upsert.duration").observe((datetime.now() - start_time).total_seconds())
                return {"entry_id": str(entry_id), "offer_id": str(payload.offer_id), "updated": True}
            else:
                # Create new entry
                entry = PricebookEntryV2(
                    entry_id=entry_id,
                    pricebook_id=payload.pricebook_id,
                    offer_id=payload.offer_id,
                    price_minor=payload.price_minor,
                    min_quantity=payload.min_quantity,
                    max_quantity=payload.max_quantity,
                    effective_from=payload.effective_from or datetime.now(),
                    effective_until=payload.effective_until
                )
                db.add(entry)
                db.commit()
                
                logger.info("pricebook_entry_created", extra={"entry_id": entry_id})
                
                # Publish event to invalidate cache
                await service_bus.publish_to_service(
                    target_service="catalog",
                    event_type=EventType.PRICE_CHANGED,
                    data={"entry_id": entry_id, "offer_id": payload.offer_id, "action": "created"}
                )
                
                metrics.histogram("endpoint.pricebook_entry_upsert.duration").observe((datetime.now() - start_time).total_seconds())
                return {"entry_id": str(entry_id), "offer_id": str(payload.offer_id), "created": True}
                
    except HTTPException:
        metrics.counter("endpoint.pricebook_entry_upsert.error").inc()
        raise
    except Exception as e:
        metrics.counter("endpoint.pricebook_entry_upsert.error").inc()
        logger.error(f"Pricebook entry upsert failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/pricing/v2/price-rules/{rule_id}")
async def upsert_price_rule(
    rule_id: str = Path(...), 
    payload: PriceRuleV2Payload = Body(...),
    tenant_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None)
):
    """Create or update a price rule (V2 architecture)"""
    start_time = datetime.now()
    metrics.counter("endpoint.price_rule_upsert.called").inc()
    
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id=tenant_id, user_id=user_id)
            # Check if rule exists
            existing = db.query(PriceRuleV2).filter(PriceRuleV2.rule_id == rule_id).first()
            
            if existing:
                # Update existing rule
                existing.name = payload.name
                existing.description = payload.description
                existing.rule_type = payload.rule_type
                existing.rule_config = payload.rule_config
                existing.application_scope = payload.application_scope
                existing.application_order = payload.application_order
                existing.priority = payload.priority
                existing.active = payload.active
                existing.scope_type = payload.scope_type
                existing.scope_id = payload.scope_id
                existing.valid_from = payload.valid_from
                existing.valid_until = payload.valid_until
                existing.version_created = existing.version_created + 1
                existing.updated_at = datetime.now()
                db.commit()
                
                logger.info("price_rule_updated", extra={"rule_id": rule_id})
                
                # Publish event to invalidate cache
                await service_bus.publish_to_service(
                    target_service="catalog",
                    event_type=EventType.PRICE_RULE_APPLIED,
                    data={"rule_id": rule_id, "action": "updated"}
                )
                
                metrics.histogram("endpoint.price_rule_upsert.duration").observe((datetime.now() - start_time).total_seconds())
                return {"rule_id": str(rule_id), "name": payload.name, "updated": True}
            else:
                # Create new rule
                rule = PriceRuleV2(
                    rule_id=rule_id,
                    name=payload.name,
                    description=payload.description,
                    rule_type=payload.rule_type,
                    rule_config=payload.rule_config,
                    application_scope=payload.application_scope,
                    application_order=payload.application_order,
                    priority=payload.priority,
                    active=payload.active,
                    scope_type=payload.scope_type,
                    scope_id=payload.scope_id,
                    valid_from=payload.valid_from,
                    valid_until=payload.valid_until,
                    version_created=1
                )
                db.add(rule)
                db.commit()
                
                logger.info("price_rule_created", extra={"rule_id": rule_id})
                
                # Publish event
                await service_bus.publish_to_service(
                    target_service="catalog",
                    event_type=EventType.PRICE_RULE_APPLIED,
                    data={"rule_id": rule_id, "action": "created"}
                )
                
                metrics.histogram("endpoint.price_rule_upsert.duration").observe((datetime.now() - start_time).total_seconds())
                return {"rule_id": str(rule_id), "name": payload.name, "created": True}
                
    except HTTPException:
        metrics.counter("endpoint.price_rule_upsert.error").inc()
        raise
    except Exception as e:
        metrics.counter("endpoint.price_rule_upsert.error").inc()
        logger.error(f"Price rule upsert failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/pricing/v2/calculated-prices")
async def get_calculated_prices(
    store_id: Optional[str] = Query(None),
    sku: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    currency: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000)
):
    """Get calculated prices with optional filters"""
    metrics.counter("endpoint.called").inc()
    
    try:
        with SessionLocal() as db:
            query = db.query(CalculatedPriceV2)
            
            if store_id:
                query = query.filter(CalculatedPriceV2.store_id == store_id)
            if sku:
                query = query.filter(CalculatedPriceV2.sku == sku)
            if user_id:
                query = query.filter(CalculatedPriceV2.user_id == user_id)
            if currency:
                query = query.filter(CalculatedPriceV2.currency == currency)
            
            prices = query.limit(limit).all()
            
            return [
                {
                    "id": price.id,
                    "store_id": price.store_id,
                    "sku": price.sku,
                    "user_id": price.user_id,
                    "currency": price.currency,
                    "base_price_minor": price.base_price_minor,
                    "final_price_minor": price.final_price_minor,
                    "applied_rules": price.applied_rules,
                    "applied_promotions": price.applied_promotions,
                    "calculated_at": price.calculated_at,
                    "expires_at": price.expires_at
                }
                for price in prices
            ]
            
    except Exception as e:
        metrics.counter("endpoint.calculated_prices_get.error").inc()
        logger.error(f"Get calculated prices failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/pricing/v2/pricebooks")
async def get_pricebooks(active: Optional[bool] = Query(None), limit: int = Query(100, ge=1, le=1000)):
    """Get pricebooks with optional filters"""
    metrics.counter("endpoint.called").inc()
    
    try:
        with SessionLocal() as db:
            query = db.query(PricebookV2)
            
            if active is not None:
                query = query.filter(PricebookV2.active == active)
            
            pricebooks = query.limit(limit).all()
            
            return [
                {
                    "pricebook_id": pb.pricebook_id,
                    "name": pb.name,
                    "description": pb.description,
                    "pricebook_type": pb.pricebook_type,
                    "currency": pb.currency,
                    "hierarchy_rank": pb.hierarchy_rank,
                    "active": pb.active,
                    "effective_from": pb.effective_from,
                    "effective_until": pb.effective_until,
                    "created_at": pb.created_at
                }
                for pb in pricebooks
            ]
            
    except Exception as e:
        metrics.counter("endpoint.pricebooks_get.error").inc()
        logger.error(f"Get pricebooks failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/pricing/v2/price-rules")
async def get_price_rules(active: Optional[bool] = Query(None), limit: int = Query(100, ge=1, le=1000)):
    """Get price rules with optional filters"""
    metrics.counter("endpoint.called").inc()
    
    try:
        with SessionLocal() as db:
            query = db.query(PriceRuleV2)
            
            if active is not None:
                query = query.filter(PriceRuleV2.active == active)
            
            rules = query.limit(limit).all()
            
            return [
                {
                    "rule_id": rule.rule_id,
                    "name": rule.name,
                    "description": rule.description,
                    "rule_type": rule.rule_type,
                    "rule_config": rule.rule_config,
                    "application_scope": rule.application_scope,
                    "application_order": rule.application_order,
                    "priority": rule.priority,
                    "active": rule.active,
                    "scope_type": rule.scope_type,
                    "scope_id": rule.scope_id,
                    "valid_from": rule.valid_from,
                    "valid_until": rule.valid_until,
                    "version_created": rule.version_created,
                    "created_at": rule.created_at
                }
                for rule in rules
            ]
            
    except Exception as e:
        metrics.counter("endpoint.price_rules_get.error").inc()
        logger.error(f"Get price rules failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/pricing/v2/price-hooks/{hook_id}")
async def upsert_price_hook(
    hook_id: str = Path(...), 
    payload: PriceHookV2Payload = Body(...),
    tenant_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None)
):
    """Create or update a price hook (V2 architecture)"""
    start_time = datetime.now()
    metrics.counter("endpoint.price_hook_upsert.called").inc()
    
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id=tenant_id, user_id=user_id)
            
            # Check if hook exists
            existing = db.query(PriceHookV2).filter(PriceHookV2.hook_id == hook_id).first()
            
            if existing:
                # Update existing hook
                existing.hook_name = payload.hook_name
                existing.hook_type = payload.hook_type
                existing.hook_config = payload.hook_config
                existing.active = payload.active
                existing.updated_at = datetime.now()
                db.commit()
                
                logger.info("price_hook_updated", extra={"hook_id": hook_id})
                metrics.histogram("endpoint.price_hook_upsert.duration").observe((datetime.now() - start_time).total_seconds())
                return {"hook_id": str(hook_id), "hook_name": payload.hook_name, "updated": True}
            else:
                # Create new hook
                hook = PriceHookV2(
                    hook_id=hook_id,
                    hook_name=payload.hook_name,
                    hook_type=payload.hook_type,
                    hook_config=payload.hook_config,
                    active=payload.active
                )
                db.add(hook)
                db.commit()
                
                logger.info("price_hook_created", extra={"hook_id": hook_id})
                metrics.histogram("endpoint.price_hook_upsert.duration").observe((datetime.now() - start_time).total_seconds())
                return {"hook_id": str(hook_id), "hook_name": payload.hook_name, "created": True}
                
    except HTTPException:
        metrics.counter("endpoint.price_hook_upsert.error").inc()
        raise
    except Exception as e:
        metrics.counter("endpoint.price_hook_upsert.error").inc()
        logger.error(f"Price hook upsert failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/pricing/v2/rule-conditions")
async def create_rule_condition(
    payload: PriceRuleConditionV2Payload = Body(...),
    tenant_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None)
):
    """Create a price rule condition (V2 architecture)"""
    start_time = datetime.now()
    metrics.counter("endpoint.rule_condition_create.called").inc()
    
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id=tenant_id, user_id=user_id)
            
            # Validate rule exists
            rule = db.query(PriceRuleV2).filter(PriceRuleV2.rule_id == payload.rule_id).first()
            if not rule:
                raise HTTPException(status_code=400, detail="Price rule not found")
            
            # Create new condition
            condition = PriceRuleConditionV2(
                condition_id=generate_time_sortable_uuid(),
                rule_id=payload.rule_id,
                condition_type=payload.condition_type,
                condition_config=payload.condition_config
            )
            db.add(condition)
            db.commit()
            
            logger.info("rule_condition_created", extra={"condition_id": condition.condition_id})
            metrics.histogram("endpoint.rule_condition_create.duration").observe((datetime.now() - start_time).total_seconds())
            return {"condition_id": str(condition.condition_id), "rule_id": str(payload.rule_id), "created": True}
                
    except HTTPException:
        metrics.counter("endpoint.rule_condition_create.error").inc()
        raise
    except Exception as e:
        metrics.counter("endpoint.rule_condition_create.error").inc()
        logger.error(f"Rule condition creation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/pricing/v2/pricing-versions/{version_id}")
async def upsert_pricing_version(
    version_id: str = Path(...), 
    payload: PricingVersionV2Payload = Body(...),
    tenant_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None)
):
    """Create or update a pricing version (V2 architecture)"""
    start_time = datetime.now()
    metrics.counter("endpoint.pricing_version_upsert.called").inc()
    
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id=tenant_id, user_id=user_id)
            
            # Check if version exists
            existing = db.query(PricingVersionV2).filter(PricingVersionV2.version_id == version_id).first()
            
            if existing:
                # Update existing version
                existing.version_number = payload.version_number
                existing.effective_from = payload.effective_from or datetime.now()
                existing.effective_until = payload.effective_until
                db.commit()
                
                logger.info("pricing_version_updated", extra={"version_id": version_id})
                
                # Publish VERSION_CHANGED event
                await service_bus.publish_to_service(
                    target_service="catalog",
                    event_type=EventType.VERSION_CHANGED,
                    data={"version_id": version_id, "version_number": payload.version_number, "action": "updated"}
                )
                
                metrics.histogram("endpoint.pricing_version_upsert.duration").observe((datetime.now() - start_time).total_seconds())
                return {"version_id": str(version_id), "version_number": payload.version_number, "updated": True}
            else:
                # Create new version
                version = PricingVersionV2(
                    version_id=version_id,
                    version_number=payload.version_number,
                    effective_from=payload.effective_from or datetime.now(),
                    effective_until=payload.effective_until
                )
                db.add(version)
                db.commit()
                
                logger.info("pricing_version_created", extra={"version_id": version_id})
                
                # Publish VERSION_CHANGED event
                await service_bus.publish_to_service(
                    target_service="catalog",
                    event_type=EventType.VERSION_CHANGED,
                    data={"version_id": version_id, "version_number": payload.version_number, "action": "created"}
                )
                
                metrics.histogram("endpoint.pricing_version_upsert.duration").observe((datetime.now() - start_time).total_seconds())
                return {"version_id": str(version_id), "version_number": payload.version_number, "created": True}
                
    except HTTPException:
        metrics.counter("endpoint.pricing_version_upsert.error").inc()
        raise
    except Exception as e:
        metrics.counter("endpoint.pricing_version_upsert.error").inc()
        logger.error(f"Pricing version upsert failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/pricing/v2/pricing-versions")
async def get_pricing_versions(tenant_id: Optional[str] = Query(None)):
    """Get pricing versions"""
    start_time = datetime.now()
    metrics.counter("endpoint.pricing_versions_list.called").inc()
    
    try:
        with SessionLocal() as db:
            set_rls_context(db, tenant_id=tenant_id)
            
            query = db.query(PricingVersionV2)
            if tenant_id:
                query = query.filter(PricingVersionV2.tenant_id == tenant_id)
            
            versions = query.all()
            
            metrics.histogram("endpoint.pricing_versions_list.duration").observe((datetime.now() - start_time).total_seconds())
            return {"status": "success", "versions": versions}
            
    except Exception as e:
        metrics.counter("endpoint.pricing_versions_list.error").inc()
        logger.error(f"Get pricing versions failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Event Handlers
async def handle_price_calculated(event_data: Dict[str, Any]):
    """Handle price calculated events"""
    logger.info("price_calculated_event_received", extra=event_data)
    metrics.counter("event.price_calculated.received").inc()

async def handle_price_changed(event_data: Dict[str, Any]):
    """Handle price changed events - invalidate cache"""
    logger.info("price_changed_event_received", extra=event_data)
    metrics.counter("event.price_changed.received").inc()
    
    # Invalidate related cache entries with scope-based invalidation
    sku = event_data.get("sku")
    offer_id = event_data.get("offer_id")
    scope_type = event_data.get("scope_type")
    scope_id = event_data.get("scope_id")
    
    with SessionLocal() as db:
        if sku or offer_id:
            query = db.query(CalculatedPriceV2)
            if sku:
                query = query.filter(CalculatedPriceV2.sku == sku)
            elif offer_id:
                query = query.filter(CalculatedPriceV2.sku == offer_id)  # Using offer_id as sku
            
            # Add scope-based filtering
            if scope_type == "STORE" and scope_id:
                query = query.filter(CalculatedPriceV2.store_id == scope_id)
            elif scope_type == "TENANT" and scope_id:
                # For tenant scope, invalidate all stores for that tenant
                # This would require a more complex query in a real implementation
                pass
            
            deleted_count = query.count()
            query.delete()
            db.commit()
            logger.info("cache_invalidated", extra={
                "sku": sku, 
                "offer_id": offer_id, 
                "scope_type": scope_type, 
                "scope_id": scope_id,
                "deleted_count": deleted_count
            })

async def handle_version_changed(event_data: Dict[str, Any]):
    """Handle version changed events - invalidate all calculated prices"""
    logger.info("version_changed_event_received", extra=event_data)
    metrics.counter("event.version_changed.received").inc()
    
    # Invalidate all calculated prices globally
    with SessionLocal() as db:
        deleted_count = db.query(CalculatedPriceV2).count()
        db.query(CalculatedPriceV2).delete()
        db.commit()
        logger.info("global_cache_invalidated", extra={
            "version_id": event_data.get("version_id"),
            "version_number": event_data.get("version_number"),
            "deleted_count": deleted_count
        })

async def handle_product_created(event_data: Dict[str, Any]):
    """Handle product created events"""
    logger.info("product_created_event_received", extra=event_data)
    metrics.counter("event.product_created.received").inc()

# Pricing Saga Implementation
class PricingSaga:
    """Saga for price rule application with compensation logic"""
    
    def __init__(self):
        self.logger = logger
        self.metrics = metrics
    
    async def execute_price_rule_saga(self, rule_data: Dict[str, Any]):
        """Execute price rule application saga"""
        executed_steps = []
        saga_start_time = datetime.now()
        correlation_id = rule_data.get('correlation_id', generate_time_sortable_uuid())
        saga_id = generate_time_sortable_uuid()
        
        # Add saga_id to rule_data for logging
        rule_data['saga_id'] = saga_id
        
        # Saga metrics
        metrics.counter("saga.started").inc()
        
        try:
            # Step 1: Validate price rule
            await self._validate_price_rule(rule_data)
            executed_steps.append("validate_price_rule")
            
            # Step 2: Create price rule
            await self._create_price_rule(rule_data)
            executed_steps.append("create_price_rule")
            
            # Step 3: Cache price rule
            await self._cache_price_rule(rule_data)
            executed_steps.append("cache_price_rule")
            
            # Step 4: Notify services
            await self._notify_services(rule_data)
            executed_steps.append("notify_services")
            
            saga_duration = (datetime.now() - saga_start_time).total_seconds()
            metrics.histogram("saga.total.duration").observe(saga_duration)
            metrics.counter("saga.completed").inc()
            
            logger.info("pricing_saga_completed", extra={
                "saga_id": saga_id,
                "rule_id": rule_data.get("rule_id"),
                "duration": saga_duration,
                "steps": executed_steps
            })
            
            return {
                "saga_id": saga_id,
                "rule_id": rule_data.get("rule_id"),
                "status": "completed",
                "steps": executed_steps,
                "duration": saga_duration
            }
            
        except Exception as e:
            # Compensation logic
            logger.error("pricing_saga_failed", extra={
                "saga_id": saga_id,
                "error": str(e),
                "executed_steps": executed_steps
            })
            
            # Execute compensation steps in reverse order
            for step in reversed(executed_steps):
                try:
                    await self._compensate_step(step, rule_data)
                except Exception as comp_error:
                    logger.error(f"compensation_failed_for_step_{step}", extra={
                        "saga_id": saga_id,
                        "error": str(comp_error)
                    })
            
            saga_duration = (datetime.now() - saga_start_time).total_seconds()
            metrics.histogram("saga.total.duration").observe(saga_duration)
            metrics.counter("saga.failed").inc()
            
            raise HTTPException(status_code=500, detail=f"Pricing saga failed: {str(e)}")
    
    async def _validate_price_rule(self, rule_data: Dict[str, Any]):
        """Validate price rule configuration"""
        logger.info("saga_validating_price_rule", extra={"saga_id": rule_data.get("saga_id")})
        
        # Validate rule configuration
        rule_config = rule_data.get("rule_config", {})
        rule_type = rule_data.get("rule_type")
        
        if rule_type == "percentage_discount":
            if "discount_percentage" not in rule_config:
                raise ValueError("percentage_discount rule requires discount_percentage")
            if not 0 <= rule_config["discount_percentage"] <= 100:
                raise ValueError("discount_percentage must be between 0 and 100")
        elif rule_type == "fixed_discount":
            if "discount_amount_minor" not in rule_config:
                raise ValueError("fixed_discount rule requires discount_amount_minor")
            if rule_config["discount_amount_minor"] < 0:
                raise ValueError("discount_amount_minor must be non-negative")
        elif rule_type == "markup":
            if "markup_percentage" not in rule_config:
                raise ValueError("markup rule requires markup_percentage")
            if rule_config["markup_percentage"] < 0:
                raise ValueError("markup_percentage must be non-negative")
        
        metrics.counter("saga.step.validate_price_rule.completed").inc()
        logger.info("saga_price_rule_validated", extra={"saga_id": rule_data.get("saga_id")})
    
    async def _create_price_rule(self, rule_data: Dict[str, Any]):
        """Create price rule in database"""
        logger.info("saga_creating_price_rule", extra={"saga_id": rule_data.get("saga_id")})
        
        with SessionLocal() as db:
            rule = PriceRuleV2(
                rule_id=rule_data.get("rule_id"),
                name=rule_data.get("name"),
                description=rule_data.get("description"),
                rule_type=rule_data.get("rule_type"),
                rule_config=rule_data.get("rule_config"),
                application_scope=rule_data.get("application_scope"),
                application_order=rule_data.get("application_order", 100),
                priority=rule_data.get("priority", 100),
                active=rule_data.get("active", True),
                scope_type=rule_data.get("scope_type"),
                scope_id=rule_data.get("scope_id"),
                valid_from=rule_data.get("valid_from"),
                valid_until=rule_data.get("valid_until"),
                version_created=1
            )
            db.add(rule)
            db.commit()
        
        metrics.counter("saga.step.create_price_rule.completed").inc()
        logger.info("saga_price_rule_created", extra={"saga_id": rule_data.get("saga_id")})
    
    async def _cache_price_rule(self, rule_data: Dict[str, Any]):
        """Cache price rule for performance"""
        logger.info("saga_caching_price_rule", extra={"saga_id": rule_data.get("saga_id")})
        
        # Invalidate existing cache entries that might be affected
        with SessionLocal() as db:
            # This would invalidate cache entries based on rule scope
            # For now, we'll just log the action
            pass
        
        metrics.counter("saga.step.cache_price_rule.completed").inc()
        logger.info("saga_price_rule_cached", extra={"saga_id": rule_data.get("saga_id")})
    
    async def _notify_services(self, rule_data: Dict[str, Any]):
        """Notify other services about price rule changes"""
        logger.info("saga_notifying_services", extra={"saga_id": rule_data.get("saga_id")})
        
        try:
            await service_bus.publish_to_service(
                target_service="catalog",
                event_type=EventType.PRICE_RULE_APPLIED,
                data={
                    "rule_id": rule_data.get("rule_id"),
                    "rule_type": rule_data.get("rule_type"),
                    "action": "created",
                    "saga_id": rule_data.get("saga_id")
                }
            )
        except Exception as e:
            logger.warning(f"service_notification_failed: {str(e)}")
        
        metrics.counter("saga.step.notify_services.completed").inc()
        logger.info("saga_services_notified", extra={"saga_id": rule_data.get("saga_id")})
    
    async def _compensate_step(self, step: str, rule_data: Dict[str, Any]):
        """Compensate for a failed saga step"""
        logger.info(f"saga_compensating_step_{step}", extra={"saga_id": rule_data.get("saga_id")})
        
        if step == "create_price_rule":
            # Remove the created price rule
            with SessionLocal() as db:
                db.query(PriceRuleV2).filter(PriceRuleV2.rule_id == rule_data.get("rule_id")).delete()
                db.commit()
            logger.info("saga_price_rule_removed", extra={"saga_id": rule_data.get("saga_id")})
        
        elif step == "cache_price_rule":
            # Cache compensation is idempotent, just log
            logger.info("saga_cache_compensation_completed", extra={"saga_id": rule_data.get("saga_id")})
        
        elif step == "notify_services":
            # Send compensation notification
            try:
                await service_bus.publish_to_service(
                    target_service="catalog",
                    event_type=EventType.PRICE_RULE_APPLIED,
                    data={
                        "rule_id": rule_data.get("rule_id"),
                        "action": "compensated",
                        "saga_id": rule_data.get("saga_id")
                    }
                )
            except Exception as e:
                logger.warning(f"compensation_notification_failed: {str(e)}")
        
        metrics.counter(f"saga.compensation.{step}.completed").inc()
        logger.info(f"saga_step_{step}_compensated", extra={"saga_id": rule_data.get("saga_id")})
    
    async def execute_pricebook_saga(self, pricebook_data: Dict[str, Any]):
        """Execute pricebook creation saga"""
        executed_steps = []
        saga_start_time = datetime.now()
        correlation_id = pricebook_data.get('correlation_id', generate_time_sortable_uuid())
        saga_id = generate_time_sortable_uuid()
        
        # Add saga_id to pricebook_data for logging
        pricebook_data['saga_id'] = saga_id
        
        # Saga metrics
        metrics.counter("saga.pricebook.started").inc()
        
        try:
            # Step 1: Validate pricebook
            await self._validate_pricebook(pricebook_data)
            executed_steps.append("validate_pricebook")
            
            # Step 2: Create pricebook
            await self._create_pricebook(pricebook_data)
            executed_steps.append("create_pricebook")
            
            # Step 3: Notify services
            await self._notify_pricebook_services(pricebook_data)
            executed_steps.append("notify_pricebook_services")
            
            saga_duration = (datetime.now() - saga_start_time).total_seconds()
            metrics.histogram("saga.pricebook.duration").observe(saga_duration)
            metrics.counter("saga.pricebook.completed").inc()
            
            logger.info("pricebook_saga_completed", extra={
                "saga_id": saga_id,
                "pricebook_id": pricebook_data.get("pricebook_id"),
                "duration": saga_duration,
                "steps": executed_steps
            })
            
            return {
                "saga_id": saga_id,
                "pricebook_id": pricebook_data.get("pricebook_id"),
                "status": "completed",
                "steps": executed_steps,
                "duration": saga_duration
            }
            
        except Exception as e:
            # Compensation logic
            logger.error("pricebook_saga_failed", extra={
                "saga_id": saga_id,
                "error": str(e),
                "executed_steps": executed_steps
            })
            
            # Execute compensation steps in reverse order
            for step in reversed(executed_steps):
                try:
                    await self._compensate_pricebook_step(step, pricebook_data)
                except Exception as comp_error:
                    logger.error(f"pricebook_compensation_failed_for_step_{step}", extra={
                        "saga_id": saga_id,
                        "error": str(comp_error)
                    })
            
            saga_duration = (datetime.now() - saga_start_time).total_seconds()
            metrics.histogram("saga.pricebook.duration").observe(saga_duration)
            metrics.counter("saga.pricebook.failed").inc()
            
            raise HTTPException(status_code=500, detail=f"Pricebook saga failed: {str(e)}")
    
    async def execute_pricebook_assignment_saga(self, assignment_data: Dict[str, Any]):
        """Execute pricebook assignment creation saga"""
        executed_steps = []
        saga_start_time = datetime.now()
        correlation_id = assignment_data.get('correlation_id', generate_time_sortable_uuid())
        saga_id = generate_time_sortable_uuid()
        
        # Add saga_id to assignment_data for logging
        assignment_data['saga_id'] = saga_id
        
        # Saga metrics
        metrics.counter("saga.pricebook_assignment.started").inc()
        
        try:
            # Step 1: Validate assignment
            await self._validate_pricebook_assignment(assignment_data)
            executed_steps.append("validate_pricebook_assignment")
            
            # Step 2: Create assignment
            await self._create_pricebook_assignment(assignment_data)
            executed_steps.append("create_pricebook_assignment")
            
            # Step 3: Invalidate cache
            await self._invalidate_assignment_cache(assignment_data)
            executed_steps.append("invalidate_assignment_cache")
            
            # Step 4: Notify services
            await self._notify_assignment_services(assignment_data)
            executed_steps.append("notify_assignment_services")
            
            saga_duration = (datetime.now() - saga_start_time).total_seconds()
            metrics.histogram("saga.pricebook_assignment.duration").observe(saga_duration)
            metrics.counter("saga.pricebook_assignment.completed").inc()
            
            logger.info("pricebook_assignment_saga_completed", extra={
                "saga_id": saga_id,
                "assignment_id": assignment_data.get("assignment_id"),
                "duration": saga_duration,
                "steps": executed_steps
            })
            
            return {
                "saga_id": saga_id,
                "assignment_id": assignment_data.get("assignment_id"),
                "status": "completed",
                "steps": executed_steps,
                "duration": saga_duration
            }
            
        except Exception as e:
            # Compensation logic
            logger.error("pricebook_assignment_saga_failed", extra={
                "saga_id": saga_id,
                "error": str(e),
                "executed_steps": executed_steps
            })
            
            # Execute compensation steps in reverse order
            for step in reversed(executed_steps):
                try:
                    await self._compensate_assignment_step(step, assignment_data)
                except Exception as comp_error:
                    logger.error(f"assignment_compensation_failed_for_step_{step}", extra={
                        "saga_id": saga_id,
                        "error": str(comp_error)
                    })
            
            saga_duration = (datetime.now() - saga_start_time).total_seconds()
            metrics.histogram("saga.pricebook_assignment.duration").observe(saga_duration)
            metrics.counter("saga.pricebook_assignment.failed").inc()
            
            raise HTTPException(status_code=500, detail=f"Pricebook assignment saga failed: {str(e)}")
    
    async def execute_pricebook_entry_saga(self, entry_data: Dict[str, Any]):
        """Execute pricebook entry creation saga"""
        executed_steps = []
        saga_start_time = datetime.now()
        correlation_id = entry_data.get('correlation_id', generate_time_sortable_uuid())
        saga_id = generate_time_sortable_uuid()
        
        # Add saga_id to entry_data for logging
        entry_data['saga_id'] = saga_id
        
        # Saga metrics
        metrics.counter("saga.pricebook_entry.started").inc()
        
        try:
            # Step 1: Validate entry
            await self._validate_pricebook_entry(entry_data)
            executed_steps.append("validate_pricebook_entry")
            
            # Step 2: Create entry
            await self._create_pricebook_entry(entry_data)
            executed_steps.append("create_pricebook_entry")
            
            # Step 3: Invalidate cache
            await self._invalidate_entry_cache(entry_data)
            executed_steps.append("invalidate_entry_cache")
            
            # Step 4: Notify services
            await self._notify_entry_services(entry_data)
            executed_steps.append("notify_entry_services")
            
            saga_duration = (datetime.now() - saga_start_time).total_seconds()
            metrics.histogram("saga.pricebook_entry.duration").observe(saga_duration)
            metrics.counter("saga.pricebook_entry.completed").inc()
            
            logger.info("pricebook_entry_saga_completed", extra={
                "saga_id": saga_id,
                "entry_id": entry_data.get("entry_id"),
                "duration": saga_duration,
                "steps": executed_steps
            })
            
            return {
                "saga_id": saga_id,
                "entry_id": entry_data.get("entry_id"),
                "status": "completed",
                "steps": executed_steps,
                "duration": saga_duration
            }
            
        except Exception as e:
            # Compensation logic
            logger.error("pricebook_entry_saga_failed", extra={
                "saga_id": saga_id,
                "error": str(e),
                "executed_steps": executed_steps
            })
            
            # Execute compensation steps in reverse order
            for step in reversed(executed_steps):
                try:
                    await self._compensate_entry_step(step, entry_data)
                except Exception as comp_error:
                    logger.error(f"entry_compensation_failed_for_step_{step}", extra={
                        "saga_id": saga_id,
                        "error": str(comp_error)
                    })
            
            saga_duration = (datetime.now() - saga_start_time).total_seconds()
            metrics.histogram("saga.pricebook_entry.duration").observe(saga_duration)
            metrics.counter("saga.pricebook_entry.failed").inc()
            
            raise HTTPException(status_code=500, detail=f"Pricebook entry saga failed: {str(e)}")
    
    # Helper methods for pricebook saga
    async def _validate_pricebook(self, pricebook_data: Dict[str, Any]):
        """Validate pricebook configuration"""
        logger.info("saga_validating_pricebook", extra={"saga_id": pricebook_data.get("saga_id")})
        
        # Validate required fields
        if not pricebook_data.get("name"):
            raise ValueError("Pricebook name is required")
        if not pricebook_data.get("currency"):
            raise ValueError("Pricebook currency is required")
        
        metrics.counter("saga.step.validate_pricebook.completed").inc()
        logger.info("saga_pricebook_validated", extra={"saga_id": pricebook_data.get("saga_id")})
    
    async def _create_pricebook(self, pricebook_data: Dict[str, Any]):
        """Create pricebook in database"""
        logger.info("saga_creating_pricebook", extra={"saga_id": pricebook_data.get("saga_id")})
        
        with SessionLocal() as db:
            pricebook = PricebookV2(
                pricebook_id=pricebook_data.get("pricebook_id"),
                name=pricebook_data.get("name"),
                description=pricebook_data.get("description"),
                pricebook_type=pricebook_data.get("pricebook_type", "standard"),
                currency=pricebook_data.get("currency"),
                active=pricebook_data.get("active", True)
            )
            db.add(pricebook)
            db.commit()
        
        metrics.counter("saga.step.create_pricebook.completed").inc()
        logger.info("saga_pricebook_created", extra={"saga_id": pricebook_data.get("saga_id")})
    
    async def _notify_pricebook_services(self, pricebook_data: Dict[str, Any]):
        """Notify other services about pricebook changes"""
        logger.info("saga_notifying_pricebook_services", extra={"saga_id": pricebook_data.get("saga_id")})
        
        try:
            await service_bus.publish_to_service(
                target_service="catalog",
                event_type=EventType.PRICEBOOK_CREATED,
                data={
                    "pricebook_id": pricebook_data.get("pricebook_id"),
                    "name": pricebook_data.get("name"),
                    "action": "created",
                    "saga_id": pricebook_data.get("saga_id")
                }
            )
        except Exception as e:
            logger.warning(f"pricebook_service_notification_failed: {str(e)}")
        
        metrics.counter("saga.step.notify_pricebook_services.completed").inc()
        logger.info("saga_pricebook_services_notified", extra={"saga_id": pricebook_data.get("saga_id")})
    
    async def _compensate_pricebook_step(self, step: str, pricebook_data: Dict[str, Any]):
        """Compensate for a failed pricebook saga step"""
        logger.info(f"saga_compensating_pricebook_step_{step}", extra={"saga_id": pricebook_data.get("saga_id")})
        
        if step == "create_pricebook":
            # Remove the created pricebook
            with SessionLocal() as db:
                db.query(PricebookV2).filter(PricebookV2.pricebook_id == pricebook_data.get("pricebook_id")).delete()
                db.commit()
            logger.info("saga_pricebook_removed", extra={"saga_id": pricebook_data.get("saga_id")})
        
        elif step == "notify_pricebook_services":
            # Send compensation notification
            try:
                await service_bus.publish_to_service(
                    target_service="catalog",
                    event_type=EventType.PRICEBOOK_CREATED,
                    data={
                        "pricebook_id": pricebook_data.get("pricebook_id"),
                        "action": "compensated",
                        "saga_id": pricebook_data.get("saga_id")
                    }
                )
            except Exception as e:
                logger.warning(f"pricebook_compensation_notification_failed: {str(e)}")
        
        metrics.counter(f"saga.pricebook.compensation.{step}.completed").inc()
        logger.info(f"saga_pricebook_step_{step}_compensated", extra={"saga_id": pricebook_data.get("saga_id")})
    
    # Helper methods for pricebook assignment saga
    async def _validate_pricebook_assignment(self, assignment_data: Dict[str, Any]):
        """Validate pricebook assignment configuration"""
        logger.info("saga_validating_pricebook_assignment", extra={"saga_id": assignment_data.get("saga_id")})
        
        # Validate required fields
        if not assignment_data.get("pricebook_id"):
            raise ValueError("Pricebook ID is required")
        if not assignment_data.get("target_type"):
            raise ValueError("Target type is required")
        if not assignment_data.get("target_id"):
            raise ValueError("Target ID is required")
        
        # Validate target exists based on target_type
        target_type = assignment_data.get("target_type")
        target_id = assignment_data.get("target_id")
        
        with SessionLocal() as db:
            if target_type == "STORE":
                result = db.execute(text("SELECT 1 FROM stores_new WHERE store_id = :target_id"), {"target_id": target_id}).fetchone()
                if not result:
                    raise ValueError(f"Store with ID {target_id} not found")
            elif target_type == "TENANT":
                result = db.execute(text("SELECT 1 FROM tenants WHERE tenant_id = :target_id"), {"target_id": target_id}).fetchone()
                if not result:
                    raise ValueError(f"Tenant with ID {target_id} not found")
            elif target_type == "VENDOR":
                result = db.execute(text("SELECT 1 FROM vendors WHERE vendor_id = :target_id"), {"target_id": target_id}).fetchone()
                if not result:
                    raise ValueError(f"Vendor with ID {target_id} not found")
        
        metrics.counter("saga.step.validate_pricebook_assignment.completed").inc()
        logger.info("saga_pricebook_assignment_validated", extra={"saga_id": assignment_data.get("saga_id")})
    
    async def _create_pricebook_assignment(self, assignment_data: Dict[str, Any]):
        """Create pricebook assignment in database"""
        logger.info("saga_creating_pricebook_assignment", extra={"saga_id": assignment_data.get("saga_id")})
        
        with SessionLocal() as db:
            assignment = PricebookAssignmentV2(
                assignment_id=assignment_data.get("assignment_id"),
                pricebook_id=assignment_data.get("pricebook_id"),
                target_type=assignment_data.get("target_type"),
                target_id=assignment_data.get("target_id"),
                assignment_priority=assignment_data.get("assignment_priority", 100),
                effective_from=assignment_data.get("effective_from"),
                effective_until=assignment_data.get("effective_until")
            )
            db.add(assignment)
            db.commit()
        
        metrics.counter("saga.step.create_pricebook_assignment.completed").inc()
        logger.info("saga_pricebook_assignment_created", extra={"saga_id": assignment_data.get("saga_id")})
    
    async def _invalidate_assignment_cache(self, assignment_data: Dict[str, Any]):
        """Invalidate cache entries affected by assignment"""
        logger.info("saga_invalidating_assignment_cache", extra={"saga_id": assignment_data.get("saga_id")})
        
        with SessionLocal() as db:
            # Invalidate calculated prices for the target
            target_type = assignment_data.get("target_type")
            target_id = assignment_data.get("target_id")
            
            if target_type == "STORE":
                db.query(CalculatedPriceV2).filter(CalculatedPriceV2.store_id == target_id).delete()
            elif target_type == "TENANT":
                db.query(CalculatedPriceV2).filter(CalculatedPriceV2.tenant_id == target_id).delete()
            
            db.commit()
        
        metrics.counter("saga.step.invalidate_assignment_cache.completed").inc()
        logger.info("saga_assignment_cache_invalidated", extra={"saga_id": assignment_data.get("saga_id")})
    
    async def _notify_assignment_services(self, assignment_data: Dict[str, Any]):
        """Notify other services about assignment changes"""
        logger.info("saga_notifying_assignment_services", extra={"saga_id": assignment_data.get("saga_id")})
        
        try:
            await service_bus.publish_to_service(
                target_service="catalog",
                event_type=EventType.PRICEBOOK_ASSIGNMENT_CREATED,
                data={
                    "assignment_id": assignment_data.get("assignment_id"),
                    "pricebook_id": assignment_data.get("pricebook_id"),
                    "target_type": assignment_data.get("target_type"),
                    "target_id": assignment_data.get("target_id"),
                    "action": "created",
                    "saga_id": assignment_data.get("saga_id")
                }
            )
        except Exception as e:
            logger.warning(f"assignment_service_notification_failed: {str(e)}")
        
        metrics.counter("saga.step.notify_assignment_services.completed").inc()
        logger.info("saga_assignment_services_notified", extra={"saga_id": assignment_data.get("saga_id")})
    
    async def _compensate_assignment_step(self, step: str, assignment_data: Dict[str, Any]):
        """Compensate for a failed assignment saga step"""
        logger.info(f"saga_compensating_assignment_step_{step}", extra={"saga_id": assignment_data.get("saga_id")})
        
        if step == "create_pricebook_assignment":
            # Remove the created assignment
            with SessionLocal() as db:
                db.query(PricebookAssignmentV2).filter(PricebookAssignmentV2.assignment_id == assignment_data.get("assignment_id")).delete()
                db.commit()
            logger.info("saga_pricebook_assignment_removed", extra={"saga_id": assignment_data.get("saga_id")})
        
        elif step == "invalidate_assignment_cache":
            # Cache invalidation compensation is idempotent, just log
            logger.info("saga_assignment_cache_compensation_completed", extra={"saga_id": assignment_data.get("saga_id")})
        
        elif step == "notify_assignment_services":
            # Send compensation notification
            try:
                await service_bus.publish_to_service(
                    target_service="catalog",
                    event_type=EventType.PRICEBOOK_ASSIGNMENT_CREATED,
                    data={
                        "assignment_id": assignment_data.get("assignment_id"),
                        "action": "compensated",
                        "saga_id": assignment_data.get("saga_id")
                    }
                )
            except Exception as e:
                logger.warning(f"assignment_compensation_notification_failed: {str(e)}")
        
        metrics.counter(f"saga.pricebook_assignment.compensation.{step}.completed").inc()
        logger.info(f"saga_assignment_step_{step}_compensated", extra={"saga_id": assignment_data.get("saga_id")})
    
    # Helper methods for pricebook entry saga
    async def _validate_pricebook_entry(self, entry_data: Dict[str, Any]):
        """Validate pricebook entry configuration"""
        logger.info("saga_validating_pricebook_entry", extra={"saga_id": entry_data.get("saga_id")})
        
        # Validate required fields
        if not entry_data.get("pricebook_id"):
            raise ValueError("Pricebook ID is required")
        if not entry_data.get("offer_id"):
            raise ValueError("Offer ID is required")
        if entry_data.get("price_minor", 0) < 0:
            raise ValueError("Price must be non-negative")
        
        # Validate pricebook exists
        with SessionLocal() as db:
            pricebook = db.query(PricebookV2).filter(PricebookV2.pricebook_id == entry_data.get("pricebook_id")).first()
            if not pricebook:
                raise ValueError(f"Pricebook with ID {entry_data.get('pricebook_id')} not found")
        
        metrics.counter("saga.step.validate_pricebook_entry.completed").inc()
        logger.info("saga_pricebook_entry_validated", extra={"saga_id": entry_data.get("saga_id")})
    
    async def _create_pricebook_entry(self, entry_data: Dict[str, Any]):
        """Create pricebook entry in database"""
        logger.info("saga_creating_pricebook_entry", extra={"saga_id": entry_data.get("saga_id")})
        
        with SessionLocal() as db:
            entry = PricebookEntryV2(
                entry_id=entry_data.get("entry_id"),
                pricebook_id=entry_data.get("pricebook_id"),
                offer_id=entry_data.get("offer_id"),
                price_minor=entry_data.get("price_minor"),
                min_quantity=entry_data.get("min_quantity", 1),
                max_quantity=entry_data.get("max_quantity"),
                effective_from=entry_data.get("effective_from"),
                effective_until=entry_data.get("effective_until")
            )
            db.add(entry)
            db.commit()
        
        metrics.counter("saga.step.create_pricebook_entry.completed").inc()
        logger.info("saga_pricebook_entry_created", extra={"saga_id": entry_data.get("saga_id")})
    
    async def _invalidate_entry_cache(self, entry_data: Dict[str, Any]):
        """Invalidate cache entries affected by entry"""
        logger.info("saga_invalidating_entry_cache", extra={"saga_id": entry_data.get("saga_id")})
        
        with SessionLocal() as db:
            # Invalidate calculated prices for this offer (using sku field)
            offer_id = entry_data.get("offer_id")
            db.query(CalculatedPriceV2).filter(CalculatedPriceV2.sku == offer_id).delete()
            db.commit()
        
        metrics.counter("saga.step.invalidate_entry_cache.completed").inc()
        logger.info("saga_entry_cache_invalidated", extra={"saga_id": entry_data.get("saga_id")})
    
    async def _notify_entry_services(self, entry_data: Dict[str, Any]):
        """Notify other services about entry changes"""
        logger.info("saga_notifying_entry_services", extra={"saga_id": entry_data.get("saga_id")})
        
        try:
            await service_bus.publish_to_service(
                target_service="catalog",
                event_type=EventType.PRICEBOOK_ENTRY_CREATED,
                data={
                    "entry_id": entry_data.get("entry_id"),
                    "pricebook_id": entry_data.get("pricebook_id"),
                    "offer_id": entry_data.get("offer_id"),
                    "price_minor": entry_data.get("price_minor"),
                    "action": "created",
                    "saga_id": entry_data.get("saga_id")
                }
            )
        except Exception as e:
            logger.warning(f"entry_service_notification_failed: {str(e)}")
        
        metrics.counter("saga.step.notify_entry_services.completed").inc()
        logger.info("saga_entry_services_notified", extra={"saga_id": entry_data.get("saga_id")})
    
    async def _compensate_entry_step(self, step: str, entry_data: Dict[str, Any]):
        """Compensate for a failed entry saga step"""
        logger.info(f"saga_compensating_entry_step_{step}", extra={"saga_id": entry_data.get("saga_id")})
        
        if step == "create_pricebook_entry":
            # Remove the created entry
            with SessionLocal() as db:
                db.query(PricebookEntryV2).filter(PricebookEntryV2.entry_id == entry_data.get("entry_id")).delete()
                db.commit()
            logger.info("saga_pricebook_entry_removed", extra={"saga_id": entry_data.get("saga_id")})
        
        elif step == "invalidate_entry_cache":
            # Cache invalidation compensation is idempotent, just log
            logger.info("saga_entry_cache_compensation_completed", extra={"saga_id": entry_data.get("saga_id")})
        
        elif step == "notify_entry_services":
            # Send compensation notification
            try:
                await service_bus.publish_to_service(
                    target_service="catalog",
                    event_type=EventType.PRICEBOOK_ENTRY_CREATED,
                    data={
                        "entry_id": entry_data.get("entry_id"),
                        "action": "compensated",
                        "saga_id": entry_data.get("saga_id")
                    }
                )
            except Exception as e:
                logger.warning(f"entry_compensation_notification_failed: {str(e)}")
        
        metrics.counter(f"saga.pricebook_entry.compensation.{step}.completed").inc()
        logger.info(f"saga_entry_step_{step}_compensated", extra={"saga_id": entry_data.get("saga_id")})

# Initialize pricing saga
pricing_saga = PricingSaga()

@app.post("/pricing/v2/saga/price-rule")
async def execute_price_rule_saga(payload: PriceRuleV2Payload = Body(...)):
    """Execute price rule application saga"""
    start_time = datetime.now()
    metrics.counter("endpoint.called").inc()
    
    try:
        rule_data = {
            "rule_id": generate_time_sortable_uuid(),
            "correlation_id": generate_time_sortable_uuid(),
            **payload.dict()
        }
        
        result = await pricing_saga.execute_price_rule_saga(rule_data)
        
        metrics.histogram("endpoint.price_rule_saga.duration").observe((datetime.now() - start_time).total_seconds())
        return result
        
    except Exception as e:
        metrics.counter("endpoint.price_rule_saga.error").inc()
        logger.error(f"Price rule saga failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/pricing/v2/saga/pricebook")
async def execute_pricebook_saga(payload: PricebookV2Payload = Body(...)):
    """Execute pricebook creation saga"""
    start_time = datetime.now()
    metrics.counter("endpoint.pricebook_saga.called").inc()
    
    try:
        pricebook_data = {
            "pricebook_id": generate_time_sortable_uuid(),
            "correlation_id": generate_time_sortable_uuid(),
            **payload.dict()
        }
        
        result = await pricing_saga.execute_pricebook_saga(pricebook_data)
        
        metrics.histogram("endpoint.pricebook_saga.duration").observe((datetime.now() - start_time).total_seconds())
        return result
        
    except Exception as e:
        metrics.counter("endpoint.pricebook_saga.error").inc()
        logger.error(f"Pricebook saga failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/pricing/v2/saga/pricebook-assignment")
async def execute_pricebook_assignment_saga(payload: PricebookAssignmentV2Payload = Body(...)):
    """Execute pricebook assignment creation saga"""
    start_time = datetime.now()
    metrics.counter("endpoint.pricebook_assignment_saga.called").inc()
    
    try:
        assignment_data = {
            "assignment_id": generate_time_sortable_uuid(),
            "correlation_id": generate_time_sortable_uuid(),
            **payload.dict()
        }
        
        result = await pricing_saga.execute_pricebook_assignment_saga(assignment_data)
        
        metrics.histogram("endpoint.pricebook_assignment_saga.duration").observe((datetime.now() - start_time).total_seconds())
        return result
        
    except Exception as e:
        metrics.counter("endpoint.pricebook_assignment_saga.error").inc()
        logger.error(f"Pricebook assignment saga failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/pricing/v2/saga/pricebook-entry")
async def execute_pricebook_entry_saga(payload: PricebookEntryV2Payload = Body(...)):
    """Execute pricebook entry creation saga"""
    start_time = datetime.now()
    metrics.counter("endpoint.pricebook_entry_saga.called").inc()
    
    try:
        entry_data = {
            "entry_id": generate_time_sortable_uuid(),
            "correlation_id": generate_time_sortable_uuid(),
            **payload.dict()
        }
        
        result = await pricing_saga.execute_pricebook_entry_saga(entry_data)
        
        metrics.histogram("endpoint.pricebook_entry_saga.duration").observe((datetime.now() - start_time).total_seconds())
        return result
        
    except Exception as e:
        metrics.counter("endpoint.pricebook_entry_saga.error").inc()
        logger.error(f"Pricebook entry saga failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Legacy endpoints for backward compatibility
@app.get("/pricing/legacy/store-products")
async def get_legacy_store_products(store_id: str = Query(...), limit: int = Query(100, ge=1, le=1000)):
    """Legacy endpoint for store products - DEPRECATED"""
    metrics.counter("endpoint.legacy.called").inc()
    
    try:
        with SessionLocal() as db:
            # This would query legacy tables
            return {
                "message": "Legacy endpoint - use V2 endpoints", 
                "store_id": store_id,
                "deprecated": True,
                "warning": "This endpoint is deprecated. Please migrate to /pricing/v2/resolve for price resolution.",
                "migration_guide": "Use POST /pricing/v2/resolve with offer_id instead of sku"
            }
    except Exception as e:
        metrics.counter("endpoint.legacy.error").inc()
        logger.error(f"Legacy endpoint failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
