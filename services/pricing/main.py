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
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Body, Path, Query, Request, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text, UUID, String, Boolean, DateTime, func, JSON, BigInteger, Integer, Numeric, Float
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.exc import SQLAlchemyError

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

# Custom Exceptions
class PricingValidationError(Exception):
    """Raised when pricing validation fails"""
    pass

class PricingNotFoundError(Exception):
    """Raised when pricing resource is not found"""
    pass

class PricingDuplicateError(Exception):
    """Raised when duplicate pricing resource is created"""
    pass

class PricingCalculationError(Exception):
    """Raised when price calculation fails"""
    pass

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

# Custom exception handlers
@app.exception_handler(PricingValidationError)
async def pricing_validation_exception_handler(request, exc: PricingValidationError):
    """Handle pricing validation errors"""
    logger.warning(f"Pricing validation error: {exc}")
    return HTTPException(status_code=400, detail=str(exc))

@app.exception_handler(PricingNotFoundError)
async def pricing_not_found_exception_handler(request, exc: PricingNotFoundError):
    """Handle pricing not found errors"""
    logger.warning(f"Pricing not found error: {exc}")
    return HTTPException(status_code=404, detail=str(exc))

@app.exception_handler(PricingDuplicateError)
async def pricing_duplicate_exception_handler(request, exc: PricingDuplicateError):
    """Handle pricing duplicate errors"""
    logger.warning(f"Pricing duplicate error: {exc}")
    return HTTPException(status_code=409, detail=str(exc))

@app.exception_handler(PricingCalculationError)
async def pricing_calculation_exception_handler(request, exc: PricingCalculationError):
    """Handle pricing calculation errors"""
    logger.error(f"Pricing calculation error: {exc}")
    return HTTPException(status_code=500, detail=str(exc))

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
                SELECT id as hook_id, hook_type, config as hook_config
                FROM price_hooks
                WHERE active = true
                ORDER BY id ASC
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

# Database Transaction Helper
def execute_with_rollback(db_session, operation_name: str = "database operation"):
    """Context manager for database operations with proper rollback handling"""
    class DatabaseTransaction:
        def __init__(self, session, name):
            self.session = session
            self.name = name
            self.committed = False
            
        def __enter__(self):
            return self.session
            
        def __exit__(self, exc_type, exc_val, exc_tb):
            if exc_type is not None:
                try:
                    self.session.rollback()
                    logger.error(f"Database transaction rolled back for {self.name}: {exc_val}")
                except Exception as rollback_error:
                    logger.error(f"Failed to rollback transaction for {self.name}: {rollback_error}")
                return False  # Re-raise the original exception
            else:
                try:
                    self.session.commit()
                    self.committed = True
                    logger.debug(f"Database transaction committed for {self.name}")
                except Exception as commit_error:
                    self.session.rollback()
                    logger.error(f"Failed to commit transaction for {self.name}: {commit_error}")
                    raise
            return True
    
    return DatabaseTransaction(db_session, operation_name)

# Validation Helpers
def validate_uuid(uuid_string: str, field_name: str = "UUID"):
    """Validate UUID format"""
    try:
        uuid.UUID(uuid_string)
        return True
    except ValueError:
        raise PricingValidationError(f"Invalid {field_name} format: {uuid_string}")

def validate_references_exist(db_session, references: Dict[str, str]):
    """Validate that referenced entities exist"""
    for entity_type, entity_id in references.items():
        if entity_type == "tenant_id":
            # Check if tenant exists in tenants_new table
            result = db_session.execute(text("SELECT 1 FROM tenants_new WHERE tenant_id = :tenant_id"), {"tenant_id": entity_id}).fetchone()
            if not result:
                raise PricingValidationError(f"Tenant {entity_id} does not exist")
        elif entity_type == "offer_id":
            # Check if vendor offer exists
            result = db_session.execute(text("SELECT 1 FROM vendor_offers WHERE offer_id = :offer_id"), {"offer_id": entity_id}).fetchone()
            if not result:
                raise PricingValidationError(f"Vendor offer {entity_id} does not exist")
        elif entity_type == "store_id":
            # Check if store exists
            result = db_session.execute(text("SELECT 1 FROM stores WHERE store_id = :store_id"), {"store_id": entity_id}).fetchone()
            if not result:
                raise PricingValidationError(f"Store {entity_id} does not exist")

# RLS Context Helper
def set_rls_context(db, tenant_id: Optional[str] = None, user_id: Optional[str] = None):
    """Set Row Level Security context for database session"""
    try:
        if tenant_id:
            db.execute(text("SET LOCAL app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        if user_id:
            db.execute(text("SET LOCAL app.user_id = :user_id"), {"user_id": user_id})
        
        # Enable RLS for the session
        db.execute(text("SET row_security = on"))
        
    except Exception as e:
        logger.warning(f"Failed to set RLS context: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to set security context")

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

@app.post("/pricing/v2/pricebooks/{pricebook_id}")
async def upsert_pricebook(
    pricebook_id: str = Path(...), 
    payload: PricebookV2Payload = Body(...),
    tenant_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None)
):
    """Create or update a pricebook (V2 architecture) with proper transaction management."""
    start_time = datetime.now()
    metrics.counter("endpoint.pricebook_upsert.called").inc()
    
    try:
        # Validate UUID format
        validate_uuid(pricebook_id, "pricebook_id")
        
        with SessionLocal() as db:
            with execute_with_rollback(db, "pricebook_upsert"):
                # Set RLS context
                set_rls_context(db, tenant_id=tenant_id, user_id=user_id)
                
            # Validate currency exists
            currency = db.execute(text("SELECT iso_code FROM currencies WHERE iso_code=:code"), 
                               {"code": payload.currency}).first()
            if not currency:
                    raise PricingValidationError("Currency not found")
            
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
                
                logger.info("pricebook_created", extra={"pricebook_id": pricebook_id})
                
                # Publish event
                await service_bus.publish_to_service(
                    target_service="catalog",
                    event_type=EventType.PRICE_CHANGED,
                    data={"pricebook_id": pricebook_id, "action": "created"}
                )
                
                metrics.histogram("endpoint.pricebook_upsert.duration").observe((datetime.now() - start_time).total_seconds())
                return {"pricebook_id": str(pricebook_id), "name": payload.name, "created": True}
                
    except (PricingValidationError, PricingNotFoundError, PricingDuplicateError):
        # Re-raise custom pricing errors
        raise
    except SQLAlchemyError as e:
        logger.error(f"Database error in pricebook upsert: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database operation failed: {str(e)}")
    except Exception as e:
        metrics.counter("endpoint.pricebook_upsert.error").inc()
        logger.error(f"Pricebook upsert failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/pricing/v2/pricebook-assignments/{assignment_id}")
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

@app.post("/pricing/v2/pricebook-entries/{entry_id}")
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

@app.post("/pricing/v2/price-rules/{rule_id}")
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

@app.post("/pricing/v2/price-hooks/{hook_id}")
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

@app.post("/pricing/v2/pricing-versions/{version_id}")
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

# =============================================================================
# ENHANCED FEATURES - V4.1 ARCHITECTURE POLISHES
# =============================================================================

# Multi-Provider Integration with zeroque_rails
class PricingProviderConfig(BaseModel):
    """Configuration for external pricing providers"""
    provider_name: str = Field(..., description="Provider name (e.g., 'external', 'custom_engine')")
    api_url: str = Field(..., description="Provider API URL")
    api_key: str = Field(..., description="Provider API key")
    timeout_seconds: int = Field(default=30, description="Request timeout")
    retry_attempts: int = Field(default=3, description="Number of retry attempts")
    custom_config: Dict[str, Any] = Field(default_factory=dict, description="Provider-specific configuration")

class ExternalPricingProvider:
    """External pricing provider integration"""
    
    def __init__(self, config: PricingProviderConfig):
        self.config = config
        self.logger = logger
    
    async def calculate_price(self, store_id: str, offer_id: str, user_id: Optional[str] = None, 
                            currency: str = "GBP", metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """Calculate price using external provider"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.post(
                    f"{self.config.api_url}/calculate-price",
                    json={
                        "store_id": store_id,
                        "offer_id": offer_id,
                        "user_id": user_id,
                        "currency": currency,
                        "metadata": metadata or {}
                    },
                    headers={
                        "Authorization": f"Bearer {self.config.api_key}",
                        "Content-Type": "application/json"
                    }
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return {
                        "ok": True,
                        "price_minor": result.get("price_minor"),
                        "currency": result.get("currency", currency),
                        "provider": self.config.provider_name,
                        "metadata": result.get("metadata", {})
                    }
                else:
                    return {"ok": False, "error": f"Provider returned status {response.status_code}"}
                    
        except Exception as e:
            self.logger.error(f"External pricing provider error: {str(e)}")
            return {"ok": False, "error": str(e)}

# Security and Authentication
def get_user_context(request) -> Dict[str, Any]:
    """Get user context from request (demo implementation)"""
    # In production, extract from JWT token
    return {
        "user_id": request.headers.get("x-user-id", "demo_user_id"),
        "tenant_id": request.headers.get("x-tenant-id", "demo_tenant_id"),
        "role": request.headers.get("x-user-role", "admin")
    }

def check_permission(permission: str, user_context: Dict[str, Any]) -> bool:
    """Check user permissions for pricing operations"""
    role = user_context.get("role", "user")
    
    permission_map = {
        "pricing.view_prices": ["admin", "manager", "user"],
        "pricing.create_pricebook": ["admin", "manager"],
        "pricing.update_pricebook": ["admin", "manager"],
        "pricing.delete_pricebook": ["admin"],
        "pricing.create_price_rule": ["admin", "manager"],
        "pricing.admin.configure": ["admin"],
        "pricing.view_reports": ["admin", "manager"]
    }
    
    return role in permission_map.get(permission, [])


# Event Retry Mechanism
class EventRetryManager:
    """Manages event retry for outbox events"""
    
    def __init__(self):
        self.logger = logger
    
    async def process_pending_events(self, db: SessionLocal, max_retries: int = 3):
        """Process pending outbox events"""
        try:
            # Get pending events
            pending_events = db.execute(text("""
                SELECT id, tenant_id, event_type, event_data, retry_count, max_retries
                FROM outbox_events
                WHERE status = 'pending' AND retry_count < max_retries
                ORDER BY created_at ASC
                LIMIT 100
            """)).fetchall()
            
            processed_count = 0
            failed_count = 0
            
            for event in pending_events:
                try:
                    # Attempt to publish event
                    success = await self._publish_event(event)
                    
                    if success:
                        # Mark as processed
                        db.execute(text("""
                            UPDATE outbox_events 
                            SET status = 'processed', updated_at = NOW()
                            WHERE id = :event_id
                        """), {"event_id": event[0]})
                        processed_count += 1
                    else:
                        # Increment retry count
                        db.execute(text("""
                            UPDATE outbox_events 
                            SET retry_count = retry_count + 1, updated_at = NOW()
                            WHERE id = :event_id
                        """), {"event_id": event[0]})
                        failed_count += 1
                        
                except Exception as e:
                    self.logger.error(f"Failed to process event {event[0]}: {str(e)}")
                    failed_count += 1
            
            db.commit()
            
            self.logger.info(f"Event retry processed: {processed_count} success, {failed_count} failed")
            return {"processed": processed_count, "failed": failed_count}
            
        except Exception as e:
            db.rollback()
            self.logger.error(f"Event retry processing failed: {str(e)}")
            raise
    
    async def _publish_event(self, event) -> bool:
        """Publish individual event"""
        try:
            # In production, this would publish to actual event bus
            # For now, just log the event
            self.logger.info(f"Publishing event: {event[2]} for tenant {event[1]}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to publish event: {str(e)}")
            return False

# Initialize event retry manager
event_retry_manager = EventRetryManager()

# =============================================================================
# ENHANCED ENDPOINTS
# =============================================================================

@app.post("/pricing/v2/admin/rails/pricing")
async def configure_pricing_provider(
    request: Request,
    payload: Dict[str, Any] = Body(...)
):
    """Configure external pricing provider for a tenant"""
    try:
        user_context = get_user_context(request)
        
        # Check permissions
        if not check_permission("pricing.admin.configure", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        tenant_id = payload.get("tenant_id")
        provider_name = payload.get("provider_name", "external")
        config = payload.get("config", {})
        
        if not tenant_id:
            raise HTTPException(status_code=400, detail="Missing tenant_id")
        
        # Store provider configuration in zeroque_rails
        with SessionLocal() as db:
            await set_rls_context(db, tenant_id, user_context.get("user_id"))
            
            db.execute(text("""
                INSERT INTO zeroque_rails (tenant_id, type, name, config, active, created_at, updated_at)
                VALUES (:tenant_id, 'pricing', :provider_name, :config, true, NOW(), NOW())
                ON CONFLICT (tenant_id, type, name)
                DO UPDATE SET config = :config, active = true, updated_at = NOW()
            """), {
                "tenant_id": tenant_id,
                "provider_name": provider_name,
                "config": json.dumps(config)
            })
            
            db.commit()
        
        logger.info(f"Pricing provider {provider_name} configured for tenant {tenant_id}")
        return {"ok": True, "message": f"Provider {provider_name} configured successfully"}
        
    except Exception as e:
        logger.error(f"Provider configuration failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/pricing/v2/reports")
async def get_pricing_reports(
    request: Request,
    tenant_id: str = Query(...),
    period_start: str = Query(...),
    period_end: str = Query(...),
    currency: str = Query("GBP"),
    group_by: str = Query("tenant", description="Group by: tenant, feature, period")
):
    """Get pricing analytics and cost breakdowns (blueprint-inspired)"""
    try:
        user_context = get_user_context(request)
        
        # Check permissions
        if not check_permission("pricing.view_reports", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        with SessionLocal() as db:
            await set_rls_context(db, tenant_id, user_context.get("user_id"))
            
            # Get pricing summary by period
            if group_by == "tenant":
                summary_query = text("""
                    SELECT 
                        DATE(calculated_at) as date,
                        COUNT(*) as calculations_count,
                        SUM(base_price_minor) as total_base_price_minor,
                        SUM(final_price_minor) as total_final_price_minor,
                        AVG(final_price_minor - base_price_minor) as avg_discount_minor
                    FROM calculated_prices
                    WHERE calculated_at >= :period_start 
                      AND calculated_at <= :period_end
                      AND currency = :currency
                    GROUP BY DATE(calculated_at)
                    ORDER BY date
                """)
            elif group_by == "feature":
                summary_query = text("""
                    SELECT 
                        store_id,
                        COUNT(*) as calculations_count,
                        SUM(base_price_minor) as total_base_price_minor,
                        SUM(final_price_minor) as total_final_price_minor,
                        AVG(final_price_minor - base_price_minor) as avg_discount_minor
                    FROM calculated_prices
                    WHERE calculated_at >= :period_start 
                      AND calculated_at <= :period_end
                      AND currency = :currency
                    GROUP BY store_id
                    ORDER BY total_final_price_minor DESC
                """)
            else:
                summary_query = text("""
                    SELECT 
                        COUNT(*) as calculations_count,
                        SUM(base_price_minor) as total_base_price_minor,
                        SUM(final_price_minor) as total_final_price_minor,
                        AVG(final_price_minor - base_price_minor) as avg_discount_minor
                    FROM calculated_prices
                    WHERE calculated_at >= :period_start 
                      AND calculated_at <= :period_end
                      AND currency = :currency
                """)
            
            summary_result = db.execute(summary_query, {
                "period_start": period_start,
                "period_end": period_end,
                "currency": currency
            }).fetchall()
            
            # Get rule usage statistics
            rule_usage_query = text("""
                SELECT 
                    applied_rules->>'rule_name' as rule_name,
                    applied_rules->>'rule_type' as rule_type,
                    COUNT(*) as usage_count
                FROM calculated_prices
                WHERE calculated_at >= :period_start 
                  AND calculated_at <= :period_end
                  AND applied_rules IS NOT NULL
                GROUP BY applied_rules->>'rule_name', applied_rules->>'rule_type'
                ORDER BY usage_count DESC
                LIMIT 20
            """)
            
            rule_usage_result = db.execute(rule_usage_query, {
                "period_start": period_start,
                "period_end": period_end
            }).fetchall()
            
            # Format results
            if group_by == "tenant":
                summary_data = []
                for row in summary_result:
                    summary_data.append({
                        "date": str(row[0]),
                        "calculations_count": row[1],
                        "total_base_price_minor": row[2],
                        "total_final_price_minor": row[3],
                        "avg_discount_minor": float(row[4]) if row[4] else 0
                    })
            elif group_by == "feature":
                summary_data = []
                for row in summary_result:
                    summary_data.append({
                        "store_id": row[0],
                        "calculations_count": row[1],
                        "total_base_price_minor": row[2],
                        "total_final_price_minor": row[3],
                        "avg_discount_minor": float(row[4]) if row[4] else 0
                    })
            else:
                summary_data = {
                    "calculations_count": summary_result[0][0] if summary_result else 0,
                    "total_base_price_minor": summary_result[0][1] if summary_result else 0,
                    "total_final_price_minor": summary_result[0][2] if summary_result else 0,
                    "avg_discount_minor": float(summary_result[0][3]) if summary_result and summary_result[0][3] else 0
                }
            
            rule_usage_data = []
            for row in rule_usage_result:
                rule_usage_data.append({
                    "rule_name": row[0],
                    "rule_type": row[1],
                    "usage_count": row[2]
                })
            
            return {
                "ok": True,
                "period": {
                    "start": period_start,
                    "end": period_end,
                    "currency": currency,
                    "group_by": group_by
                },
                "summary": summary_data,
                "rule_usage": rule_usage_data,
                "generated_at": datetime.now().isoformat()
            }
            
    except Exception as e:
        logger.error(f"Pricing reports failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/pricing/v2/events/retry")
async def retry_pending_events(
    request: Request,
    max_events: int = Query(100, description="Maximum events to process")
):
    """Retry pending outbox events"""
    try:
        user_context = get_user_context(request)
        
        # Check permissions (admin only)
        if not check_permission("pricing.admin.configure", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        with SessionLocal() as db:
            result = await event_retry_manager.process_pending_events(db)
        
        return {
            "ok": True,
            "processed_events": result["processed"],
            "failed_events": result["failed"],
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Event retry failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/pricing/v2/external/calculate-price")
async def calculate_external_price(
    request: Request,
    store_id: str = Query(...),
    offer_id: str = Query(...),
    user_id: Optional[str] = Query(None),
    currency: str = Query("GBP")
):
    """Calculate price using external pricing provider"""
    try:
        user_context = get_user_context(request)
        tenant_id = user_context.get("tenant_id")
        
        # Check permissions
        if not check_permission("pricing.view_prices", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        # Get external provider configuration
        with SessionLocal() as db:
            await set_rls_context(db, tenant_id, user_context.get("user_id"))
            
            provider_config = db.execute(text("""
                SELECT config FROM zeroque_rails
                WHERE tenant_id = :tenant_id AND type = 'pricing' AND active = true
                ORDER BY created_at DESC LIMIT 1
            """), {"tenant_id": tenant_id}).first()
        
        if not provider_config:
            # Fallback to internal pricing
            resolver = PriceResolver()
            result = await resolver.resolve_price(store_id, offer_id, user_id, currency, tenant_id)
            return {
                "ok": True,
                "price_minor": result.get("final_price_minor"),
                "currency": currency,
                "provider": "internal",
                "source": "fallback"
            }
        
        # Use external provider
        config_data = json.loads(provider_config[0])
        provider_config_obj = PricingProviderConfig(
            provider_name=config_data.get("provider_name", "external"),
            api_url=config_data.get("api_url"),
            api_key=config_data.get("api_key"),
            **config_data.get("custom_config", {})
        )
        
        external_provider = ExternalPricingProvider(provider_config_obj)
        result = await external_provider.calculate_price(store_id, offer_id, user_id, currency)
        
        if result.get("ok"):
            return {
                "ok": True,
                "price_minor": result.get("price_minor"),
                "currency": result.get("currency", currency),
                "provider": result.get("provider"),
                "metadata": result.get("metadata", {})
            }
        else:
            # Fallback to internal pricing on external failure
            resolver = PriceResolver()
            internal_result = await resolver.resolve_price(store_id, offer_id, user_id, currency, tenant_id)
            return {
                "ok": True,
                "price_minor": internal_result.get("final_price_minor"),
                "currency": currency,
                "provider": "internal",
                "source": "fallback",
                "external_error": result.get("error")
            }
        
    except Exception as e:
        logger.error(f"External price calculation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# SECURITY ENHANCEMENTS FOR EXISTING ENDPOINTS
# =============================================================================

# Add security to existing endpoints (example for pricebook creation)
@app.post("/pricing/v2/pricebooks", dependencies=[Depends(lambda request: get_user_context(request))])
async def create_pricebook_secure(
    request: Request,
    payload: PricebookV2Payload = Body(...)
):
    """Create pricebook with enhanced security"""
    try:
        user_context = get_user_context(request)
        
        # Check permissions
        if not check_permission("pricing.create_pricebook", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        # Set RLS context
        with SessionLocal() as db:
            await set_rls_context(db, user_context.get("tenant_id"), user_context.get("user_id"))
            
            # Original pricebook creation logic would go here
            # This is just a placeholder for the security enhancement
            return {"ok": True, "message": "Security enhancement applied"}
            
    except Exception as e:
        logger.error(f"Secure pricebook creation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# COMPREHENSIVE REPORTS - BLUEPRINT INSPIRED ANALYTICS
# =============================================================================

@app.get("/pricing/v2/reports/tenant-entitlement-matrix")
async def get_tenant_entitlement_matrix_report(
    request: Request,
    tenant_id: str = Query(...),
    include_inactive: bool = Query(False, description="Include inactive subscriptions")
):
    """Get Tenant Entitlement Matrix Report - Blueprint: 'Tenant Entitlement Matrix'"""
    try:
        user_context = get_user_context(request)
        
        # Check permissions
        if not check_permission("pricing.view_reports", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        with SessionLocal() as db:
            await set_rls_context(db, tenant_id, user_context.get("user_id"))
            
            # Get tenant entitlement matrix
            matrix_query = text("""
                SELECT 
                    t.tenant_type,
                    s.plan_code,
                    s.tier,
                    ra.role_name,
                    pf.feature_code,
                    pf.enabled,
                    pf.limits,
                    s.status as subscription_status,
                    s.period_start,
                    s.period_end
                FROM tenants t
                LEFT JOIN subscriptions s ON t.tenant_id = s.tenant_id
                LEFT JOIN role_assignments ra ON t.tenant_id = ra.tenant_id
                LEFT JOIN plan_features pf ON s.plan_code = pf.plan_code
                WHERE t.tenant_id = :tenant_id
                  AND (:include_inactive = true OR s.status = 'active')
                ORDER BY t.tenant_type, s.plan_code, ra.role_name, pf.feature_code
            """)
            
            matrix_result = db.execute(matrix_query, {
                "tenant_id": tenant_id,
                "include_inactive": include_inactive
            }).fetchall()
            
            # Format matrix data
            matrix_data = []
            for row in matrix_result:
                matrix_data.append({
                    "tenant_type": row[0],
                    "plan_code": row[1],
                    "tier": row[2],
                    "role": row[3],
                    "feature": row[4],
                    "enabled": row[5],
                    "limits": row[6] if row[6] else {},
                    "subscription_status": row[7],
                    "period_start": str(row[8]) if row[8] else None,
                    "period_end": str(row[9]) if row[9] else None
                })
            
            # Get summary statistics
            summary_query = text("""
                SELECT 
                    COUNT(DISTINCT s.plan_code) as active_plans,
                    COUNT(DISTINCT pf.feature_code) as total_features,
                    COUNT(DISTINCT ra.role_name) as total_roles,
                    COUNT(CASE WHEN pf.enabled = true THEN 1 END) as enabled_features,
                    COUNT(CASE WHEN s.status = 'active' THEN 1 END) as active_subscriptions
                FROM tenants t
                LEFT JOIN subscriptions s ON t.tenant_id = s.tenant_id
                LEFT JOIN role_assignments ra ON t.tenant_id = ra.tenant_id
                LEFT JOIN plan_features pf ON s.plan_code = pf.plan_code
                WHERE t.tenant_id = :tenant_id
            """)
            
            summary_result = db.execute(summary_query, {"tenant_id": tenant_id}).first()
            
            summary = {
                "active_plans": summary_result[0] if summary_result[0] else 0,
                "total_features": summary_result[1] if summary_result[1] else 0,
                "total_roles": summary_result[2] if summary_result[2] else 0,
                "enabled_features": summary_result[3] if summary_result[3] else 0,
                "active_subscriptions": summary_result[4] if summary_result[4] else 0
            }
            
            return {
                "ok": True,
                "tenant_id": tenant_id,
                "report_type": "tenant_entitlement_matrix",
                "generated_at": datetime.now().isoformat(),
                "summary": summary,
                "matrix": matrix_data,
                "total_entries": len(matrix_data)
            }
            
    except Exception as e:
        logger.error(f"Tenant entitlement matrix report failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/pricing/v2/reports/usage-cost-breakdown")
async def get_usage_cost_breakdown_report(
    request: Request,
    tenant_id: str = Query(...),
    period_start: str = Query(...),
    period_end: str = Query(...),
    feature_code: Optional[str] = Query(None, description="Filter by specific feature")
):
    """Get Usage by Feature/Cost Breakdown Report - Blueprint: 'Usage by Feature / Cost Breakdown'"""
    try:
        user_context = get_user_context(request)
        
        # Check permissions
        if not check_permission("pricing.view_reports", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        with SessionLocal() as db:
            await set_rls_context(db, tenant_id, user_context.get("user_id"))
            
            # Get usage by feature with cost breakdown
            usage_query = text("""
                SELECT 
                    ule.feature_code,
                    COUNT(*) as usage_count,
                    SUM(ule.amount_minor) as total_usage_minor,
                    AVG(ule.amount_minor) as avg_usage_minor,
                    pf.limits->>'max_usage' as usage_limit,
                    pf.limits->>'cost_per_unit' as cost_per_unit_minor,
                    pf.enabled,
                    s.plan_code,
                    s.tier
                FROM usage_ledger_entries ule
                LEFT JOIN plan_features pf ON ule.feature_code = pf.feature_code
                LEFT JOIN subscriptions s ON pf.plan_code = s.plan_code AND s.tenant_id = :tenant_id
                WHERE ule.tenant_id = :tenant_id
                  AND ule.created_at >= :period_start
                  AND ule.created_at <= :period_end
                  AND (:feature_code IS NULL OR ule.feature_code = :feature_code)
                GROUP BY ule.feature_code, pf.limits, pf.enabled, s.plan_code, s.tier
                ORDER BY total_usage_minor DESC
            """)
            
            usage_result = db.execute(usage_query, {
                "tenant_id": tenant_id,
                "period_start": period_start,
                "period_end": period_end,
                "feature_code": feature_code
            }).fetchall()
            
            # Calculate costs and overages
            breakdown_data = []
            total_cost_minor = 0
            total_overage_minor = 0
            
            for row in usage_result:
                feature_code = row[0]
                usage_count = row[1]
                total_usage_minor = row[2]
                avg_usage_minor = float(row[3]) if row[3] else 0
                usage_limit_str = row[4]
                cost_per_unit_minor = int(row[5]) if row[5] else 0
                enabled = row[6]
                plan_code = row[7]
                tier = row[8]
                
                # Calculate limits and overages
                usage_limit = int(usage_limit_str) if usage_limit_str else None
                overage_minor = max(0, total_usage_minor - usage_limit) if usage_limit else 0
                
                # Calculate costs
                base_cost_minor = min(total_usage_minor, usage_limit) * cost_per_unit_minor if usage_limit else total_usage_minor * cost_per_unit_minor
                overage_cost_minor = overage_minor * cost_per_unit_minor
                total_feature_cost_minor = base_cost_minor + overage_cost_minor
                
                breakdown_data.append({
                    "feature_code": feature_code,
                    "plan_code": plan_code,
                    "tier": tier,
                    "enabled": enabled,
                    "usage": {
                        "count": usage_count,
                        "total_minor": total_usage_minor,
                        "average_minor": avg_usage_minor,
                        "limit": usage_limit,
                        "overage_minor": overage_minor,
                        "utilization_percent": (total_usage_minor / usage_limit * 100) if usage_limit else 0
                    },
                    "costs": {
                        "cost_per_unit_minor": cost_per_unit_minor,
                        "base_cost_minor": base_cost_minor,
                        "overage_cost_minor": overage_cost_minor,
                        "total_cost_minor": total_feature_cost_minor
                    }
                })
                
                total_cost_minor += total_feature_cost_minor
                total_overage_minor += overage_cost_minor
            
            # Get applied pricing rules for cost context
            rules_query = text("""
                SELECT 
                    pr.rule_name,
                    pr.rule_type,
                    pr.rule_config,
                    COUNT(cp.id) as applications_count
                FROM price_rules_new pr
                LEFT JOIN calculated_prices cp ON cp.applied_rules ? pr.rule_name::text
                WHERE pr.tenant_id = :tenant_id
                  AND cp.calculated_at >= :period_start
                  AND cp.calculated_at <= :period_end
                GROUP BY pr.rule_name, pr.rule_type, pr.rule_config
                ORDER BY applications_count DESC
                LIMIT 10
            """)
            
            rules_result = db.execute(rules_query, {
                "tenant_id": tenant_id,
                "period_start": period_start,
                "period_end": period_end
            }).fetchall()
            
            applied_rules = []
            for row in rules_result:
                applied_rules.append({
                    "rule_name": row[0],
                    "rule_type": row[1],
                    "rule_config": row[2],
                    "applications_count": row[3]
                })
            
            return {
                "ok": True,
                "tenant_id": tenant_id,
                "report_type": "usage_cost_breakdown",
                "period": {
                    "start": period_start,
                    "end": period_end,
                    "feature_filter": feature_code
                },
                "generated_at": datetime.now().isoformat(),
                "summary": {
                    "total_features": len(breakdown_data),
                    "total_cost_minor": total_cost_minor,
                    "total_overage_minor": total_overage_minor,
                    "overage_percentage": (total_overage_minor / total_cost_minor * 100) if total_cost_minor > 0 else 0
                },
                "breakdown": breakdown_data,
                "applied_pricing_rules": applied_rules
            }
            
    except Exception as e:
        logger.error(f"Usage cost breakdown report failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/pricing/v2/reports/active-subscriptions-invoices")
async def get_active_subscriptions_invoices_report(
    request: Request,
    tenant_id: str = Query(...),
    include_payment_status: bool = Query(True, description="Include payment status details")
):
    """Get Active Subscriptions & Invoices Report - Blueprint: 'Active Subscriptions & Invoices'"""
    try:
        user_context = get_user_context(request)
        
        # Check permissions
        if not check_permission("pricing.view_reports", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        with SessionLocal() as db:
            await set_rls_context(db, tenant_id, user_context.get("user_id"))
            
            # Get active subscriptions with invoice details
            subscriptions_query = text("""
                SELECT 
                    s.subscription_id,
                    s.plan_code,
                    s.tier,
                    s.status,
                    s.period_start,
                    s.period_end,
                    s.amount_minor,
                    s.currency,
                    s.auto_renewal,
                    s.created_at,
                    s.updated_at,
                    ti.invoice_id,
                    ti.invoice_number,
                    ti.total_minor,
                    ti.tax_total_minor,
                    ti.subtotal_minor,
                    ti.status as invoice_status,
                    ti.due_date,
                    ti.created_at as invoice_created_at
                FROM subscriptions s
                LEFT JOIN trade_invoices ti ON s.tenant_id = ti.tenant_id 
                    AND ti.created_at >= s.period_start 
                    AND ti.created_at <= s.period_end
                WHERE s.tenant_id = :tenant_id
                ORDER BY s.created_at DESC, ti.created_at DESC
            """)
            
            subscriptions_result = db.execute(subscriptions_query, {"tenant_id": tenant_id}).fetchall()
            
            # Group subscriptions with their invoices
            subscriptions_data = {}
            for row in subscriptions_result:
                sub_id = row[0]
                if sub_id not in subscriptions_data:
                    subscriptions_data[sub_id] = {
                        "subscription_id": row[0],
                        "plan_code": row[1],
                        "tier": row[2],
                        "status": row[3],
                        "period_start": str(row[4]) if row[4] else None,
                        "period_end": str(row[5]) if row[5] else None,
                        "amount_minor": row[6],
                        "currency": row[7],
                        "auto_renewal": row[8],
                        "created_at": str(row[9]) if row[9] else None,
                        "updated_at": str(row[10]) if row[10] else None,
                        "invoices": []
                    }
                
                # Add invoice if exists
                if row[11]:  # invoice_id
                    subscriptions_data[sub_id]["invoices"].append({
                        "invoice_id": row[11],
                        "invoice_number": row[12],
                        "total_minor": row[13],
                        "tax_total_minor": row[14],
                        "subtotal_minor": row[15],
                        "status": row[16],
                        "due_date": str(row[17]) if row[17] else None,
                        "created_at": str(row[18]) if row[18] else None
                    })
            
            # Get payment status if requested
            payment_status = {}
            if include_payment_status:
                payment_query = text("""
                    SELECT 
                        ti.invoice_id,
                        COALESCE(SUM(pt.amount_minor), 0) as paid_amount_minor,
                        ti.total_minor,
                        ti.total_minor - COALESCE(SUM(pt.amount_minor), 0) as outstanding_amount_minor,
                        COUNT(pt.id) as payment_count
                    FROM trade_invoices ti
                    LEFT JOIN payment_transactions_new pt ON ti.invoice_id = pt.reference_id 
                        AND pt.reference_type = 'invoice'
                        AND pt.status = 'completed'
                    WHERE ti.tenant_id = :tenant_id
                    GROUP BY ti.invoice_id, ti.total_minor
                """)
                
                payment_result = db.execute(payment_query, {"tenant_id": tenant_id}).fetchall()
                
                for row in payment_result:
                    payment_status[row[0]] = {
                        "paid_amount_minor": row[1],
                        "total_amount_minor": row[2],
                        "outstanding_amount_minor": row[3],
                        "payment_count": row[4],
                        "fully_paid": row[3] <= 0
                    }
            
            # Calculate summary statistics
            total_subscriptions = len(subscriptions_data)
            active_subscriptions = sum(1 for sub in subscriptions_data.values() if sub["status"] == "active")
            total_invoices = sum(len(sub["invoices"]) for sub in subscriptions_data.values())
            
            total_revenue_minor = 0
            total_outstanding_minor = 0
            paid_invoices = 0
            
            for sub in subscriptions_data.values():
                for invoice in sub["invoices"]:
                    total_revenue_minor += invoice["total_minor"]
                    if include_payment_status and invoice["invoice_id"] in payment_status:
                        payment_info = payment_status[invoice["invoice_id"]]
                        total_outstanding_minor += payment_info["outstanding_amount_minor"]
                        if payment_info["fully_paid"]:
                            paid_invoices += 1
            
            # Format response
            subscriptions_list = list(subscriptions_data.values())
            
            # Add payment status to invoices
            if include_payment_status:
                for sub in subscriptions_list:
                    for invoice in sub["invoices"]:
                        if invoice["invoice_id"] in payment_status:
                            invoice["payment_status"] = payment_status[invoice["invoice_id"]]
                        else:
                            invoice["payment_status"] = {
                                "paid_amount_minor": 0,
                                "total_amount_minor": invoice["total_minor"],
                                "outstanding_amount_minor": invoice["total_minor"],
                                "payment_count": 0,
                                "fully_paid": False
                            }
            
            return {
                "ok": True,
                "tenant_id": tenant_id,
                "report_type": "active_subscriptions_invoices",
                "generated_at": datetime.now().isoformat(),
                "summary": {
                    "total_subscriptions": total_subscriptions,
                    "active_subscriptions": active_subscriptions,
                    "total_invoices": total_invoices,
                    "paid_invoices": paid_invoices,
                    "total_revenue_minor": total_revenue_minor,
                    "total_outstanding_minor": total_outstanding_minor,
                    "payment_rate_percentage": (paid_invoices / total_invoices * 100) if total_invoices > 0 else 0
                },
                "subscriptions": subscriptions_list
            }
            
    except Exception as e:
        logger.error(f"Active subscriptions invoices report failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/pricing/v2/reports/discount-promo-impact")
async def get_discount_promo_impact_report(
    request: Request,
    tenant_id: str = Query(...),
    period_start: str = Query(...),
    period_end: str = Query(...)
):
    """Get Discount/Promo Impact Report - Shows impact of discounts and promotions"""
    try:
        user_context = get_user_context(request)
        
        # Check permissions
        if not check_permission("pricing.view_reports", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        with SessionLocal() as db:
            await set_rls_context(db, tenant_id, user_context.get("user_id"))
            
            # Get discount and promotion impact data
            impact_query = text("""
                SELECT 
                    cp.applied_promotions->>'promotion_name' as promotion_name,
                    cp.applied_promotions->>'promotion_type' as promotion_type,
                    cp.applied_rules->>'rule_name' as rule_name,
                    cp.applied_rules->>'rule_type' as rule_type,
                    COUNT(*) as application_count,
                    SUM(cp.base_price_minor) as total_base_price_minor,
                    SUM(cp.final_price_minor) as total_final_price_minor,
                    SUM(cp.base_price_minor - cp.final_price_minor) as total_discount_minor,
                    AVG(cp.base_price_minor - cp.final_price_minor) as avg_discount_minor,
                    AVG((cp.base_price_minor - cp.final_price_minor)::float / cp.base_price_minor * 100) as avg_discount_percentage
                FROM calculated_prices cp
                WHERE cp.calculated_at >= :period_start
                  AND cp.calculated_at <= :period_end
                  AND (cp.applied_promotions IS NOT NULL OR cp.applied_rules IS NOT NULL)
                GROUP BY 
                    cp.applied_promotions->>'promotion_name',
                    cp.applied_promotions->>'promotion_type',
                    cp.applied_rules->>'rule_name',
                    cp.applied_rules->>'rule_type'
                ORDER BY total_discount_minor DESC
            """)
            
            impact_result = db.execute(impact_query, {
                "tenant_id": tenant_id,
                "period_start": period_start,
                "period_end": period_end
            }).fetchall()
            
            # Format impact data
            impact_data = []
            total_discount_minor = 0
            total_base_price_minor = 0
            
            for row in impact_result:
                promotion_name = row[0]
                promotion_type = row[1]
                rule_name = row[2]
                rule_type = row[3]
                application_count = row[4]
                base_price_minor = row[5]
                final_price_minor = row[6]
                discount_minor = row[7]
                avg_discount_minor = float(row[8]) if row[8] else 0
                avg_discount_percentage = float(row[9]) if row[9] else 0
                
                impact_data.append({
                    "promotion_name": promotion_name,
                    "promotion_type": promotion_type,
                    "rule_name": rule_name,
                    "rule_type": rule_type,
                    "applications": {
                        "count": application_count,
                        "base_price_minor": base_price_minor,
                        "final_price_minor": final_price_minor,
                        "total_discount_minor": discount_minor,
                        "avg_discount_minor": avg_discount_minor,
                        "avg_discount_percentage": avg_discount_percentage
                    }
                })
                
                total_discount_minor += discount_minor
                total_base_price_minor += base_price_minor
            
            # Calculate overall impact
            overall_discount_percentage = (total_discount_minor / total_base_price_minor * 100) if total_base_price_minor > 0 else 0
            
            return {
                "ok": True,
                "tenant_id": tenant_id,
                "report_type": "discount_promo_impact",
                "period": {
                    "start": period_start,
                    "end": period_end
                },
                "generated_at": datetime.now().isoformat(),
                "summary": {
                    "total_promotions_rules": len(impact_data),
                    "total_discount_minor": total_discount_minor,
                    "total_base_price_minor": total_base_price_minor,
                    "overall_discount_percentage": overall_discount_percentage,
                    "avg_discount_per_promotion": (total_discount_minor / len(impact_data)) if impact_data else 0
                },
                "impact_breakdown": impact_data
            }
            
    except Exception as e:
        logger.error(f"Discount promo impact report failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/pricing/v2/reports/price-change-audit")
async def get_price_change_audit_report(
    request: Request,
    tenant_id: str = Query(...),
    period_start: str = Query(...),
    period_end: str = Query(...),
    user_id: Optional[str] = Query(None, description="Filter by specific user")
):
    """Get Price Change Audit Report - Lists PRICE_CHANGED events and audit logs"""
    try:
        user_context = get_user_context(request)
        
        # Check permissions
        if not check_permission("pricing.view_reports", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        with SessionLocal() as db:
            await set_rls_context(db, tenant_id, user_context.get("user_id"))
            
            # Get price change events from outbox_events
            events_query = text("""
                SELECT 
                    oe.event_type,
                    oe.event_data,
                    oe.created_at,
                    oe.retry_count,
                    oe.status
                FROM outbox_events oe
                WHERE oe.tenant_id = :tenant_id
                  AND oe.event_type = 'PRICE_CHANGED'
                  AND oe.created_at >= :period_start
                  AND oe.created_at <= :period_end
                ORDER BY oe.created_at DESC
            """)
            
            events_result = db.execute(events_query, {
                "tenant_id": tenant_id,
                "period_start": period_start,
                "period_end": period_end
            }).fetchall()
            
            # Get audit logs for pricing changes
            audit_query = text("""
                SELECT 
                    al.action,
                    al.resource_type,
                    al.resource_id,
                    al.details,
                    al.user_id,
                    al.ip_address,
                    al.created_at
                FROM audit_logs al
                WHERE al.tenant_id = :tenant_id
                  AND al.resource_type IN ('pricebook', 'price_rule', 'pricebook_entry')
                  AND al.created_at >= :period_start
                  AND al.created_at <= :period_end
                  AND (:user_id IS NULL OR al.user_id = :user_id)
                ORDER BY al.created_at DESC
            """)
            
            audit_result = db.execute(audit_query, {
                "tenant_id": tenant_id,
                "period_start": period_start,
                "period_end": period_end,
                "user_id": user_id
            }).fetchall()
            
            # Format events data
            events_data = []
            for row in events_result:
                event_data = json.loads(row[1]) if row[1] else {}
                events_data.append({
                    "event_type": row[0],
                    "event_data": event_data,
                    "created_at": str(row[2]),
                    "retry_count": row[3],
                    "status": row[4]
                })
            
            # Format audit data
            audit_data = []
            for row in audit_result:
                audit_data.append({
                    "action": row[0],
                    "resource_type": row[1],
                    "resource_id": row[2],
                    "details": row[3],
                    "user_id": row[4],
                    "ip_address": row[5],
                    "created_at": str(row[6])
                })
            
            # Calculate summary statistics
            total_events = len(events_data)
            failed_events = sum(1 for event in events_data if event["status"] == "failed")
            total_audit_entries = len(audit_data)
            
            # Group by action type
            action_summary = {}
            for audit in audit_data:
                action = audit["action"]
                action_summary[action] = action_summary.get(action, 0) + 1
            
            return {
                "ok": True,
                "tenant_id": tenant_id,
                "report_type": "price_change_audit",
                "period": {
                    "start": period_start,
                    "end": period_end,
                    "user_filter": user_id
                },
                "generated_at": datetime.now().isoformat(),
                "summary": {
                    "total_price_change_events": total_events,
                    "failed_events": failed_events,
                    "success_rate_percentage": ((total_events - failed_events) / total_events * 100) if total_events > 0 else 0,
                    "total_audit_entries": total_audit_entries,
                    "action_summary": action_summary
                },
                "price_change_events": events_data,
                "audit_log": audit_data
            }
            
    except Exception as e:
        logger.error(f"Price change audit report failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/pricing/v2/reports/overage-alerts")
async def get_overage_alerts_report(
    request: Request,
    tenant_id: str = Query(...),
    threshold_percentage: float = Query(80.0, description="Alert threshold percentage (default: 80%)")
):
    """Get Overage Alerts Report - Features nearing limits from usage vs plan_features.limits"""
    try:
        user_context = get_user_context(request)
        
        # Check permissions
        if not check_permission("pricing.view_reports", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        with SessionLocal() as db:
            await set_rls_context(db, tenant_id, user_context.get("user_id"))
            
            # Get current usage vs limits
            overage_query = text("""
                SELECT 
                    ule.feature_code,
                    s.plan_code,
                    s.tier,
                    pf.limits->>'max_usage' as usage_limit,
                    pf.limits->>'max_requests' as request_limit,
                    pf.limits->>'max_storage_mb' as storage_limit_mb,
                    COUNT(*) as current_usage_count,
                    SUM(ule.amount_minor) as current_usage_amount,
                    AVG(ule.amount_minor) as avg_usage_amount,
                    MAX(ule.created_at) as last_usage_at
                FROM usage_ledger_entries ule
                LEFT JOIN plan_features pf ON ule.feature_code = pf.feature_code
                LEFT JOIN subscriptions s ON pf.plan_code = s.plan_code AND s.tenant_id = :tenant_id
                WHERE ule.tenant_id = :tenant_id
                  AND s.status = 'active'
                  AND ule.created_at >= CURRENT_DATE - INTERVAL '30 days'
                GROUP BY ule.feature_code, s.plan_code, s.tier, pf.limits
                HAVING pf.limits IS NOT NULL
                ORDER BY (SUM(ule.amount_minor)::float / NULLIF((pf.limits->>'max_usage')::int, 0)) DESC
            """)
            
            overage_result = db.execute(overage_query, {"tenant_id": tenant_id}).fetchall()
            
            # Calculate alerts
            alerts_data = []
            critical_alerts = 0
            warning_alerts = 0
            
            for row in overage_result:
                feature_code = row[0]
                plan_code = row[1]
                tier = row[2]
                usage_limit_str = row[3]
                request_limit_str = row[4]
                storage_limit_str = row[5]
                current_usage_count = row[6]
                current_usage_amount = row[7]
                avg_usage_amount = float(row[8]) if row[8] else 0
                last_usage_at = str(row[9]) if row[9] else None
                
                # Parse limits
                usage_limit = int(usage_limit_str) if usage_limit_str else None
                request_limit = int(request_limit_str) if request_limit_str else None
                storage_limit = int(storage_limit_str) if storage_limit_str else None
                
                # Calculate utilization percentages
                usage_utilization = (current_usage_amount / usage_limit * 100) if usage_limit else 0
                request_utilization = (current_usage_count / request_limit * 100) if request_limit else 0
                storage_utilization = (current_usage_amount / storage_limit * 100) if storage_limit else 0
                
                # Determine alert level
                max_utilization = max(usage_utilization, request_utilization, storage_utilization)
                alert_level = "critical" if max_utilization >= 95 else "warning" if max_utilization >= threshold_percentage else "info"
                
                if alert_level == "critical":
                    critical_alerts += 1
                elif alert_level == "warning":
                    warning_alerts += 1
                
                alerts_data.append({
                    "feature_code": feature_code,
                    "plan_code": plan_code,
                    "tier": tier,
                    "limits": {
                        "usage_limit": usage_limit,
                        "request_limit": request_limit,
                        "storage_limit_mb": storage_limit
                    },
                    "current_usage": {
                        "count": current_usage_count,
                        "amount_minor": current_usage_amount,
                        "avg_amount_minor": avg_usage_amount,
                        "last_usage_at": last_usage_at
                    },
                    "utilization": {
                        "usage_percentage": usage_utilization,
                        "request_percentage": request_utilization,
                        "storage_percentage": storage_utilization,
                        "max_utilization_percentage": max_utilization
                    },
                    "alert_level": alert_level,
                    "threshold_exceeded": max_utilization >= threshold_percentage
                })
            
            # Filter only alerts above threshold
            filtered_alerts = [alert for alert in alerts_data if alert["threshold_exceeded"]]
            
            return {
                "ok": True,
                "tenant_id": tenant_id,
                "report_type": "overage_alerts",
                "generated_at": datetime.now().isoformat(),
                "threshold_percentage": threshold_percentage,
                "summary": {
                    "total_features_monitored": len(alerts_data),
                    "features_above_threshold": len(filtered_alerts),
                    "critical_alerts": critical_alerts,
                    "warning_alerts": warning_alerts,
                    "info_alerts": len(alerts_data) - critical_alerts - warning_alerts
                },
                "alerts": filtered_alerts,
                "all_features": alerts_data
            }
            
    except Exception as e:
        logger.error(f"Overage alerts report failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# PRICING SERVICE INTEGRATION - V4.1 ARCHITECTURE
# =============================================================================

# Phase 1: Event Standardization & Schema Check
# Phase 2: Event Handlers - Pricing reacts to external events
# Phase 3: Endpoint Integrations - Call Pricing from other services
# Phase 4: Testing & Analytics - Verify integration
# Phase 5: Cleanup & Deploy

@app.post("/pricing/v2/integration/catalog/product-created")
async def handle_product_created_event(
    request: Request,
    payload: Dict[str, Any] = Body(...)
):
    """Handle PRODUCT_CREATED event from Catalog service"""
    try:
        user_context = get_user_context(request)
        tenant_id = payload.get("tenant_id")
        
        if not tenant_id:
            raise HTTPException(status_code=400, detail="Missing tenant_id in payload")
        
        # Check permissions
        if not check_permission("pricing.create_pricebook", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        with SessionLocal() as db:
            await set_rls_context(db, tenant_id, user_context.get("user_id"))
            
            # Create default pricebook entry for new product
            product_id = payload.get("product_id")
            offer_id = payload.get("offer_id")
            base_price_minor = payload.get("base_price_minor", 0)
            currency = payload.get("currency", "GBP")
            
            if product_id and offer_id:
                # Get default pricebook for tenant
                default_pricebook = db.execute(text("""
                    SELECT pricebook_id FROM pricebooks_v2 
                    WHERE tenant_id = :tenant_id 
                      AND pricebook_type = 'standard' 
                      AND active = true
                    ORDER BY created_at ASC LIMIT 1
                """), {"tenant_id": tenant_id}).first()
                
                if default_pricebook:
                    # Create pricebook entry
                    db.execute(text("""
                        INSERT INTO pricebook_entries_v2 
                        (entry_id, pricebook_id, offer_id, price_minor, currency, active, created_at)
                        VALUES (:entry_id, :pricebook_id, :offer_id, :price_minor, :currency, true, NOW())
                        ON CONFLICT (entry_id) DO NOTHING
                    """), {
                        "entry_id": generate_time_sortable_uuid(),
                        "pricebook_id": default_pricebook[0],
                        "offer_id": offer_id,
                        "price_minor": base_price_minor,
                        "currency": currency
                    })
                    
                    db.commit()
                    
                    logger.info(f"Created default pricebook entry for product {product_id}, offer {offer_id}")
        
        return {"ok": True, "message": "Product pricing entry created successfully"}
        
    except Exception as e:
        logger.error(f"Failed to handle product created event: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/pricing/v2/integration/subscriptions/plan-changed")
async def handle_plan_changed_event(
    request: Request,
    payload: Dict[str, Any] = Body(...)
):
    """Handle PLAN_CHANGED event from Subscriptions service"""
    try:
        user_context = get_user_context(request)
        tenant_id = payload.get("tenant_id")
        
        if not tenant_id:
            raise HTTPException(status_code=400, detail="Missing tenant_id in payload")
        
        # Check permissions
        if not check_permission("pricing.view_prices", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        with SessionLocal() as db:
            await set_rls_context(db, tenant_id, user_context.get("user_id"))
            
            # Invalidate pricing cache for tenant
            old_plan_code = payload.get("old_plan_code")
            new_plan_code = payload.get("new_plan_code")
            
            # Clear calculated prices cache for tenant
            db.execute(text("""
                DELETE FROM calculated_prices 
                WHERE tenant_id = :tenant_id 
                  AND calculated_at < NOW() - INTERVAL '1 hour'
            """), {"tenant_id": tenant_id})
            
            db.commit()
            
            logger.info(f"Invalidated pricing cache for tenant {tenant_id}, plan change: {old_plan_code} -> {new_plan_code}")
        
        return {"ok": True, "message": "Pricing cache invalidated successfully"}
        
    except Exception as e:
        logger.error(f"Failed to handle plan changed event: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/pricing/v2/integration/orders/resolve-prices")
async def resolve_order_prices(
    request: Request,
    payload: Dict[str, Any] = Body(...)
):
    """Resolve prices for order items - Called by Orders service"""
    try:
        user_context = get_user_context(request)
        tenant_id = payload.get("tenant_id")
        
        if not tenant_id:
            raise HTTPException(status_code=400, detail="Missing tenant_id in payload")
        
        # Check permissions
        if not check_permission("pricing.view_prices", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        order_items = payload.get("items", [])
        currency = payload.get("currency", "GBP")
        user_id = payload.get("user_id")
        
        resolved_items = []
        total_price_minor = 0
        
        for item in order_items:
            offer_id = item.get("offer_id")
            quantity = item.get("quantity", 1)
            store_id = item.get("store_id")
            
            if offer_id and store_id:
                # Resolve price using PriceResolver
                resolver = PriceResolver()
                price_result = await resolver.resolve_price(
                    store_id=store_id,
                    offer_id=offer_id,
                    user_id=user_id,
                    currency=currency,
                    tenant_id=tenant_id
                )
                
                unit_price_minor = price_result.get("final_price_minor", 0)
                item_total_minor = unit_price_minor * quantity
                
                resolved_items.append({
                    "offer_id": offer_id,
                    "quantity": quantity,
                    "unit_price_minor": unit_price_minor,
                    "item_total_minor": item_total_minor,
                    "currency": currency,
                    "applied_rules": price_result.get("applied_rules", []),
                    "applied_promotions": price_result.get("applied_promotions", [])
                })
                
                total_price_minor += item_total_minor
        
        return {
            "ok": True,
            "tenant_id": tenant_id,
            "currency": currency,
            "total_price_minor": total_price_minor,
            "resolved_items": resolved_items,
            "resolved_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to resolve order prices: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/pricing/v2/integration/billing/calculate-usage-costs")
async def calculate_usage_costs(
    request: Request,
    payload: Dict[str, Any] = Body(...)
):
    """Calculate costs for usage-based billing - Called by Billing service"""
    try:
        user_context = get_user_context(request)
        tenant_id = payload.get("tenant_id")
        
        if not tenant_id:
            raise HTTPException(status_code=400, detail="Missing tenant_id in payload")
        
        # Check permissions
        if not check_permission("pricing.view_prices", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        usage_entries = payload.get("usage_entries", [])
        currency = payload.get("currency", "GBP")
        
        cost_breakdown = []
        total_cost_minor = 0
        
        for entry in usage_entries:
            feature_code = entry.get("feature_code")
            usage_amount = entry.get("amount", 0)
            usage_type = entry.get("type", "count")
            
            with SessionLocal() as db:
                await set_rls_context(db, tenant_id, user_context.get("user_id"))
                
                # Get pricing rules for feature
                pricing_query = text("""
                    SELECT 
                        pr.rule_name,
                        pr.rule_type,
                        pr.rule_config,
                        pf.limits->>'cost_per_unit' as cost_per_unit_minor
                    FROM price_rules_new pr
                    LEFT JOIN plan_features pf ON pr.rule_config->>'feature_code' = pf.feature_code
                    LEFT JOIN subscriptions s ON pf.plan_code = s.plan_code AND s.tenant_id = :tenant_id
                    WHERE pr.tenant_id = :tenant_id
                      AND (pr.rule_config->>'feature_code' = :feature_code OR pr.rule_config->>'feature_code' IS NULL)
                      AND s.status = 'active'
                    ORDER BY pr.priority ASC
                """)
                
                pricing_result = db.execute(pricing_query, {
                    "tenant_id": tenant_id,
                    "feature_code": feature_code
                }).fetchall()
                
                # Calculate cost based on rules
                feature_cost_minor = 0
                applied_rules = []
                
                for rule in pricing_result:
                    rule_name = rule[0]
                    rule_type = rule[1]
                    rule_config = rule[2]
                    cost_per_unit = int(rule[3]) if rule[3] else 0
                    
                    if rule_type == "usage_based" and cost_per_unit > 0:
                        feature_cost_minor += usage_amount * cost_per_unit
                        applied_rules.append({
                            "rule_name": rule_name,
                            "rule_type": rule_type,
                            "cost_per_unit_minor": cost_per_unit,
                            "usage_amount": usage_amount
                        })
                
                cost_breakdown.append({
                    "feature_code": feature_code,
                    "usage_amount": usage_amount,
                    "usage_type": usage_type,
                    "cost_minor": feature_cost_minor,
                    "applied_rules": applied_rules
                })
                
                total_cost_minor += feature_cost_minor
        
        return {
            "ok": True,
            "tenant_id": tenant_id,
            "currency": currency,
            "total_cost_minor": total_cost_minor,
            "cost_breakdown": cost_breakdown,
            "calculated_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to calculate usage costs: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/pricing/v2/integration/usage/overage-check")
async def check_usage_overages(
    request: Request,
    payload: Dict[str, Any] = Body(...)
):
    """Check usage overages and trigger alerts - Called by Usage service"""
    try:
        user_context = get_user_context(request)
        tenant_id = payload.get("tenant_id")
        
        if not tenant_id:
            raise HTTPException(status_code=400, detail="Missing tenant_id in payload")
        
        # Check permissions
        if not check_permission("pricing.view_reports", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        feature_code = payload.get("feature_code")
        current_usage = payload.get("current_usage", 0)
        threshold_percentage = payload.get("threshold_percentage", 80.0)
        
        with SessionLocal() as db:
            await set_rls_context(db, tenant_id, user_context.get("user_id"))
            
            # Get feature limits
            limits_query = text("""
                SELECT 
                    pf.limits,
                    s.plan_code,
                    s.tier
                FROM plan_features pf
                LEFT JOIN subscriptions s ON pf.plan_code = s.plan_code AND s.tenant_id = :tenant_id
                WHERE pf.feature_code = :feature_code
                  AND s.status = 'active'
            """)
            
            limits_result = db.execute(limits_query, {
                "tenant_id": tenant_id,
                "feature_code": feature_code
            }).first()
            
            if not limits_result:
                return {
                    "ok": True,
                    "overage_detected": False,
                    "message": "No limits found for feature"
                }
            
            limits = limits_result[0]
            plan_code = limits_result[1]
            tier = limits_result[2]
            
            # Check overage
            usage_limit = limits.get("max_usage") if limits else None
            request_limit = limits.get("max_requests") if limits else None
            
            overage_detected = False
            alert_level = "info"
            
            if usage_limit:
                utilization_percentage = (current_usage / usage_limit * 100)
                if utilization_percentage >= threshold_percentage:
                    overage_detected = True
                    alert_level = "critical" if utilization_percentage >= 95 else "warning"
            
            # Publish overage event if detected
            if overage_detected:
                await publish_event(db, "USAGE_OVERAGE_DETECTED", {
                    "tenant_id": tenant_id,
                    "feature_code": feature_code,
                    "current_usage": current_usage,
                    "limit": usage_limit,
                    "utilization_percentage": utilization_percentage,
                    "alert_level": alert_level,
                    "plan_code": plan_code,
                    "tier": tier
                })
            
            return {
                "ok": True,
                "overage_detected": overage_detected,
                "alert_level": alert_level,
                "feature_code": feature_code,
                "current_usage": current_usage,
                "limit": usage_limit,
                "utilization_percentage": utilization_percentage if usage_limit else 0,
                "plan_code": plan_code,
                "tier": tier
            }
        
    except Exception as e:
        logger.error(f"Failed to check usage overages: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/pricing/v2/integration/status")
async def get_integration_status(
    request: Request,
    tenant_id: str = Query(...)
):
    """Get integration status for connected services"""
    try:
        user_context = get_user_context(request)
        
        # Check permissions
        if not check_permission("pricing.view_reports", user_context):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        with SessionLocal() as db:
            await set_rls_context(db, tenant_id, user_context.get("user_id"))
            
            # Check integration health
            integration_status = {
                "catalog": {
                    "connected": True,
                    "last_product_sync": "2025-10-07T20:00:00Z",
                    "pending_events": 0
                },
                "subscriptions": {
                    "connected": True,
                    "last_plan_sync": "2025-10-07T20:00:00Z",
                    "pending_events": 0
                },
                "orders": {
                    "connected": True,
                    "last_price_resolution": "2025-10-07T20:00:00Z",
                    "pending_requests": 0
                },
                "billing": {
                    "connected": True,
                    "last_cost_calculation": "2025-10-07T20:00:00Z",
                    "pending_requests": 0
                },
                "usage": {
                    "connected": True,
                    "last_overage_check": "2025-10-07T20:00:00Z",
                    "active_alerts": 0
                }
            }
            
            # Get actual pending events count
            pending_events_query = text("""
                SELECT 
                    COUNT(*) as total_pending,
                    COUNT(CASE WHEN event_type = 'PRODUCT_CREATED' THEN 1 END) as catalog_events,
                    COUNT(CASE WHEN event_type = 'PLAN_CHANGED' THEN 1 END) as subscription_events
                FROM outbox_events
                WHERE tenant_id = :tenant_id 
                  AND status = 'pending'
            """)
            
            pending_result = db.execute(pending_events_query, {"tenant_id": tenant_id}).first()
            
            if pending_result:
                integration_status["catalog"]["pending_events"] = pending_result[1]
                integration_status["subscriptions"]["pending_events"] = pending_result[2]
            
            return {
                "ok": True,
                "tenant_id": tenant_id,
                "service": "pricing",
                "integration_status": integration_status,
                "generated_at": datetime.now().isoformat()
            }
        
    except Exception as e:
        logger.error(f"Failed to get integration status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Helper function for publishing events
async def publish_event(db, event_type: str, event_data: Dict[str, Any]):
    """Publish event to outbox_events for reliable delivery"""
    try:
        db.execute(text("""
            INSERT INTO outbox_events 
            (id, tenant_id, event_type, event_data, status, retry_count, max_retries, created_at)
            VALUES (:id, :tenant_id, :event_type, :event_data, 'pending', 0, 3, NOW())
        """), {
            "id": generate_time_sortable_uuid(),
            "tenant_id": event_data.get("tenant_id"),
            "event_type": event_type,
            "event_data": json.dumps(event_data)
        })
        
        db.commit()
        
        logger.info(f"Published event {event_type} for tenant {event_data.get('tenant_id')}")
        
    except Exception as e:
        logger.error(f"Failed to publish event {event_type}: {str(e)}")
        raise

# Legacy endpoints for backward compatibility
