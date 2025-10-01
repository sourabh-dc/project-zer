# services/catalog/main.py
"""
Enhanced Catalog Service with V2 Multi-Tenant Marketplace Architecture

This service implements:
- V2 product management (product_master, product_variants, vendor_offers)
- Enhanced communication patterns (Service Bus, Saga, Circuit Breaker)
- Event sourcing and health monitoring
- RLS context handling
- UUID-based ID generation
- Production-ready error handling and logging
"""

import os
import sys
import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Body, Query, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy import text, UUID, String, Boolean, DateTime, func, JSON, BigInteger, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column

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
SERVICE_NAME = "catalog"
app = FastAPI(title="Enhanced ZeroQue Catalog Service", version="2.0.0")

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
add_idempotency_middleware(app, routes=[("POST", "/catalog/v2/products"), ("POST", "/catalog/v2/variants")])

# V2 SQLAlchemy Models for the new architecture
class ProductMasterV2(Base):
    __tablename__ = "product_master"
    product_id: Mapped[str] = mapped_column(UUID, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    brand: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    category_hierarchy: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    search_terms: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    attributes_schema: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class ProductVariantV2(Base):
    __tablename__ = "product_variants"
    variant_id: Mapped[str] = mapped_column(UUID, primary_key=True)
    product_id: Mapped[str] = mapped_column(UUID)
    sku: Mapped[str] = mapped_column(String(100), unique=True)
    gtin: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    mpn: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    uom: Mapped[str] = mapped_column(String(20), default="EA")
    package_quantity: Mapped[int] = mapped_column(Integer, default=1)
    weight_grams: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    dimensions: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    variant_attributes: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class VendorOfferV2(Base):
    __tablename__ = "vendor_offers"
    offer_id: Mapped[str] = mapped_column(UUID, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(UUID)
    variant_id: Mapped[str] = mapped_column(UUID)
    vendor_sku: Mapped[str] = mapped_column(String(100))
    vendor_product_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    base_price_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    cost_price_minor: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    min_order_quantity: Mapped[int] = mapped_column(Integer, default=1)
    lead_time_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    package_dimensions: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    tax_category: Mapped[str] = mapped_column(String(100), default="standard")
    status: Mapped[str] = mapped_column(String(20), default="active")
    offer_valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    offer_valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class ProductMediaV2(Base):
    __tablename__ = "product_media"
    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    product_id: Mapped[str] = mapped_column(UUID)
    variant_id: Mapped[Optional[str]] = mapped_column(UUID, nullable=True)
    media_type: Mapped[str] = mapped_column(String(20))  # image, video, document
    url: Mapped[str] = mapped_column(String(500))
    caption: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # alt_text -> caption
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)  # active -> is_primary
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ProductRelationshipV2(Base):
    __tablename__ = "product_relationships"
    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    from_product_id: Mapped[str] = mapped_column(UUID)
    to_product_id: Mapped[str] = mapped_column(UUID)
    relationship_type: Mapped[str] = mapped_column(String(50))  # bundle, accessory, replacement, etc.
    strength: Mapped[float] = mapped_column(Numeric(3, 2), default=1.0)
    is_bidirectional: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ProductTaxCategoryV2(Base):
    __tablename__ = "product_tax_categories"
    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    product_id: Mapped[str] = mapped_column(UUID)
    region_id: Mapped[str] = mapped_column(UUID)
    tax_category: Mapped[str] = mapped_column(String(100))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class StoreAssortmentV2(Base):
    __tablename__ = "store_assortments"
    assortment_id: Mapped[str] = mapped_column(UUID, primary_key=True)
    store_id: Mapped[str] = mapped_column(UUID)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class CustomerSegmentV2(Base):
    __tablename__ = "customer_segments"
    segment_id: Mapped[str] = mapped_column(UUID, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(UUID)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    criteria: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # Segment criteria rules
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class AssortmentSegmentV2(Base):
    __tablename__ = "assortment_segments"
    assortment_segment_id: Mapped[str] = mapped_column(UUID, primary_key=True)
    assortment_id: Mapped[str] = mapped_column(UUID)
    segment_id: Mapped[str] = mapped_column(UUID)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

# RLS Context Helper
def set_rls_context(db_session, tenant_id: str = None, user_id: str = None):
    """Set Row Level Security context for database session"""
    try:
        if tenant_id:
            db_session.execute(text("SET LOCAL row_security.tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        if user_id:
            db_session.execute(text("SET LOCAL row_security.user_id = :user_id"), {"user_id": user_id})
    except Exception as e:
        logger.warning(f"Failed to set RLS context: {str(e)}")

# Event handlers
async def handle_product_created(event: ServiceEvent):
    """Handle product created events"""
    logger.info(f"Received product created event: {event.data}")
    # Update local cache or trigger indexing

async def handle_product_updated(event: ServiceEvent):
    """Handle product updated events"""
    logger.info(f"Received product updated event: {event.data}")
    # Update local cache or trigger reindexing

async def handle_vendor_onboarded(event: ServiceEvent):
    """Handle vendor onboarded events"""
    logger.info(f"Received vendor onboarded event: {event.data}")
    # Trigger vendor offer synchronization

# Saga implementation
class CatalogSaga:
    def __init__(self):
        self.steps = [
            SagaStep("validate_product", self.validate_product),
            SagaStep("create_product_master", self.create_product_master),
            SagaStep("create_variant", self.create_variant),
            SagaStep("create_vendor_offer", self.create_vendor_offer),
            SagaStep("update_search_index", self.update_search_index)
        ]
        
        self.compensation_steps = [
            ("remove_vendor_offer", self.remove_vendor_offer),
            ("remove_variant", self.remove_variant),
            ("remove_product_master", self.remove_product_master)
        ]

    async def execute_product_creation_saga(self, product_data: Dict[str, Any]):
        """Execute product creation saga"""
        executed_steps = []
        saga_start_time = datetime.now()
        correlation_id = product_data.get('correlation_id', str(uuid.uuid4()))
        saga_id = str(uuid.uuid4())
        
        # Add saga_id to product_data for logging
        product_data['saga_id'] = saga_id
        
        # Saga metrics
        metrics.counter("saga.started").inc()
        
        try:
            for step in self.steps:
                step_start_time = datetime.now()
                logger.info(f"Saga: Starting step {step.name} for {product_data.get('product_id')} (saga_id: {saga_id})")
                
                result = await step.execute(product_data)
                executed_steps.append(step)
                
                step_duration = (datetime.now() - step_start_time).total_seconds()
                metrics.histogram("saga.step.duration").observe(step_duration)
                
                logger.info(f"Saga: Step {step.name} completed successfully in {step_duration:.2f}s (saga_id: {saga_id})")
            
            saga_duration = (datetime.now() - saga_start_time).total_seconds()
            metrics.histogram("saga.total.duration").observe(saga_duration)
            metrics.counter("saga.completed").inc()
            
            logger.info(f"Saga: Product creation saga completed successfully in {saga_duration:.2f}s for {product_data.get('product_id')}")
            return {"status": "completed", "product_id": product_data.get("product_id"), "duration": saga_duration}
            
        except Exception as e:
            saga_duration = (datetime.now() - saga_start_time).total_seconds()
            metrics.counter("saga.failed").inc()
            metrics.histogram("saga.failed.duration").observe(saga_duration)
            
            logger.error(f"Saga: Product creation saga failed after {saga_duration:.2f}s: {str(e)}")
            
            # Execute compensation steps in reverse order
            compensation_start_time = datetime.now()
            for step_name, compensation_func in reversed(self.compensation_steps):
                try:
                    await compensation_func(product_data)
                    logger.info(f"Saga: Compensation step {step_name} completed")
                except Exception as comp_error:
                    logger.error(f"Saga: Compensation failed for {step_name}: {comp_error}")
            
            compensation_duration = (datetime.now() - compensation_start_time).total_seconds()
            metrics.histogram("saga.compensation.duration").observe(compensation_duration)
            
            raise e

    async def validate_product(self, data: Dict[str, Any]):
        """Validate product data"""
        logger.info(f"Saga: Validating product data for {data.get('product_id')}")
        
        # Check if product name is unique
        with SessionLocal() as db:
            existing = db.query(ProductMasterV2).filter(
                ProductMasterV2.name == data.get('name')
            ).first()
            
            if existing:
                raise ValueError(f"Product with name '{data.get('name')}' already exists")
        
        # Validate required fields
        if not data.get('name'):
            raise ValueError("Product name is required")
        
        logger.info(f"Saga: Product validation successful for {data.get('product_id')}")
        return True

    async def create_product_master(self, data: Dict[str, Any]):
        """Create product master record"""
        logger.info(f"Saga: Creating product master for {data.get('product_id')}")
        
        with SessionLocal() as db:
            set_rls_context(db, user_id=data.get('correlation_id'))
            
            product = ProductMasterV2(
                product_id=data['product_id'],
                name=data['name'],
                description=data.get('description'),
                brand=data.get('brand'),
                category_hierarchy=data.get('category_hierarchy'),
                search_terms=data.get('search_terms'),
                attributes_schema=data.get('attributes_schema'),
                active=data.get('active', True)
            )
            db.add(product)
            db.commit()
            
            logger.info(f"Saga: Product master created successfully for {data.get('product_id')}")
            return True

    async def create_variant(self, data: Dict[str, Any]):
        """Create product variant"""
        variant_id = data.get('variant_id')
        if not variant_id:
            logger.info("Saga: Skipping variant creation - no variant_id provided")
            return True
            
        logger.info(f"Saga: Creating product variant for {variant_id}")
        
        with SessionLocal() as db:
            set_rls_context(db, user_id=data.get('correlation_id'))
            
            # Check if SKU is unique
            existing_sku = db.query(ProductVariantV2).filter(
                ProductVariantV2.sku == data.get('sku')
            ).first()
            
            if existing_sku:
                raise ValueError(f"Variant with SKU '{data.get('sku')}' already exists")
            
            variant = ProductVariantV2(
                variant_id=variant_id,
                product_id=data['product_id'],
                sku=data['sku'],
                gtin=data.get('gtin'),
                mpn=data.get('mpn'),
                uom=data.get('uom', 'EA'),
                package_quantity=data.get('package_quantity', 1),
                weight_grams=data.get('weight_grams'),
                dimensions=data.get('dimensions'),
                variant_attributes=data.get('variant_attributes'),
                active=data.get('active', True)
            )
            db.add(variant)
            db.commit()
            
            logger.info(f"Saga: Product variant created successfully for {variant_id}")
            return True

    async def create_vendor_offer(self, data: Dict[str, Any]):
        """Create vendor offer"""
        offer_id = data.get('offer_id')
        if not offer_id:
            logger.info("Saga: Skipping vendor offer creation - no offer_id provided")
            return True
            
        logger.info(f"Saga: Creating vendor offer for {offer_id}")
        
        with SessionLocal() as db:
            set_rls_context(db, user_id=data.get('correlation_id'))
            
            # Validate vendor exists
            vendor = db.execute(text("SELECT vendor_id FROM vendors WHERE vendor_id=:id"), 
                               {"id": data.get('vendor_id')}).first()
            if not vendor:
                raise ValueError(f"Vendor {data.get('vendor_id')} not found")
            
            # Validate currency exists
            currency = db.execute(text("SELECT iso_code FROM currencies WHERE iso_code=:code"), 
                               {"code": data.get('currency')}).first()
            if not currency:
                raise ValueError(f"Currency {data.get('currency')} not found")
            
            offer = VendorOfferV2(
                offer_id=offer_id,
                vendor_id=data['vendor_id'],
                variant_id=data['variant_id'],
                vendor_sku=data['vendor_sku'],
                vendor_product_name=data.get('vendor_product_name'),
                base_price_minor=data['base_price_minor'],
                currency=data['currency'],
                cost_price_minor=data.get('cost_price_minor'),
                min_order_quantity=data.get('min_order_quantity', 1),
                lead_time_days=data.get('lead_time_days'),
                package_dimensions=data.get('package_dimensions'),
                tax_category=data.get('tax_category', 'standard'),
                status=data.get('status', 'active'),
                offer_valid_from=data.get('offer_valid_from', datetime.now()),
                offer_valid_until=data.get('offer_valid_until')
            )
            db.add(offer)
            db.commit()
            
            logger.info(f"Saga: Vendor offer created successfully for {offer_id}")
            return True

    async def update_search_index(self, data: Dict[str, Any]):
        """Update search index"""
        logger.info(f"Saga: Updating search index for {data.get('product_id')}")
        
        # Publish event to search service
        await service_bus.publish_to_service(
            target_service="search",
            event_type=EventType.PRODUCT_CREATED,
            data={
                "product_id": data.get('product_id'),
                "variant_id": data.get('variant_id'),
                "offer_id": data.get('offer_id'),
                "action": "index"
            }
        )
        
        logger.info(f"Saga: Search index update initiated for {data.get('product_id')}")
        return True

    async def remove_vendor_offer(self, data: Dict[str, Any]):
        """Remove vendor offer"""
        logger.info(f"Saga: Removing vendor offer {data.get('offer_id')}")
        
        with SessionLocal() as db:
            offer = db.query(VendorOfferV2).filter(
                VendorOfferV2.offer_id == data.get('offer_id')
            ).first()
            if offer:
                db.delete(offer)
                db.commit()
                logger.info(f"Saga: Vendor offer removed {data.get('offer_id')}")
        return True

    async def remove_variant(self, data: Dict[str, Any]):
        """Remove variant"""
        logger.info(f"Saga: Removing variant {data.get('variant_id')}")
        
        with SessionLocal() as db:
            variant = db.query(ProductVariantV2).filter(
                ProductVariantV2.variant_id == data.get('variant_id')
            ).first()
            if variant:
                db.delete(variant)
                db.commit()
                logger.info(f"Saga: Variant removed {data.get('variant_id')}")
        return True

    async def remove_product_master(self, data: Dict[str, Any]):
        """Remove product master"""
        logger.info(f"Saga: Removing product master {data.get('product_id')}")
        
        with SessionLocal() as db:
            product = db.query(ProductMasterV2).filter(
                ProductMasterV2.product_id == data.get('product_id')
            ).first()
            if product:
                db.delete(product)
                db.commit()
                logger.info(f"Saga: Product master removed {data.get('product_id')}")
        return True

# Initialize saga
catalog_saga = CatalogSaga()

@app.on_event("startup")
async def startup():
    """Initialize enhanced service"""
    logger.info(f"Starting enhanced {SERVICE_NAME} service")
    
    # Initialize database
    get_engine()
    init_db()
    
    # Register service (simplified for now)
    try:
        await service_registry.register_service(
            service_name=SERVICE_NAME,
            instance_id=f"{SERVICE_NAME}-{os.getpid()}",
            host="localhost",
            port=8202,
            metadata={"version": "2.0.0", "enhanced": True}
        )
    except Exception as e:
        logger.warning(f"Service registration failed: {str(e)}")
    
    # Subscribe to events (simplified for now)
    try:
        service_bus.subscribe_to_event(EventType.PRODUCT_CREATED, handle_product_created)
        service_bus.subscribe_to_event(EventType.PRODUCT_UPDATED, handle_product_updated)
        service_bus.subscribe_to_event(EventType.TENANT_CREATED, handle_vendor_onboarded)
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
    
    # Publish service started event (simplified for now)
    try:
        await service_bus.publish_to_service(
            target_service="observability",
            event_type=EventType.SERVICE_STARTED,
            data={
                "service_name": SERVICE_NAME,
                "version": "2.0.0",
                "startup_time": datetime.now().isoformat(),
                "enhanced_features": ["saga", "circuit_breaker", "event_sourcing"]
            }
        )
    except Exception as e:
        logger.warning(f"Service started event publish failed: {str(e)}")

@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME, "version": "2.0.0", "enhanced": True}

@app.get("/readiness")
def readiness():
    return {"service": SERVICE_NAME, "db": check_db(), "redis": True, "version": "2.0.0"}

# ---------- V2 payloads ----------
class ProductMasterV2Payload(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    brand: Optional[str] = None
    category_hierarchy: Optional[dict] = None
    search_terms: Optional[str] = None
    attributes_schema: Optional[dict] = None
    active: bool = True

class ProductVariantV2Payload(BaseModel):
    product_id: str = Field(..., min_length=1)
    sku: str = Field(..., min_length=1)
    gtin: Optional[str] = None
    mpn: Optional[str] = None
    uom: str = Field("EA", min_length=1)
    package_quantity: int = Field(1, ge=1)
    weight_grams: Optional[int] = Field(None, ge=0)
    dimensions: Optional[dict] = None
    variant_attributes: Optional[dict] = None
    active: bool = True

class VendorOfferV2Payload(BaseModel):
    vendor_id: str = Field(..., min_length=1)
    variant_id: str = Field(..., min_length=1)
    vendor_sku: str = Field(..., min_length=1)
    vendor_product_name: Optional[str] = None
    base_price_minor: int = Field(..., ge=0)
    currency: str = Field("GBP", pattern=r"^[A-Z]{3}$")
    cost_price_minor: Optional[int] = Field(None, ge=0)
    min_order_quantity: int = Field(1, ge=1)
    lead_time_days: Optional[int] = Field(None, ge=0)
    package_dimensions: Optional[dict] = None
    tax_category: str = Field("standard", min_length=1)
    status: str = Field("active", min_length=1)
    offer_valid_from: Optional[datetime] = None
    offer_valid_until: Optional[datetime] = None

class ProductMediaV2Payload(BaseModel):
    product_id: str = Field(..., min_length=1)
    variant_id: Optional[str] = None
    media_type: str = Field(..., pattern=r"^(image|video|document)$")
    url: str = Field(..., min_length=1)
    caption: Optional[str] = None  # alt_text -> caption
    sort_order: int = Field(0, ge=0)
    is_primary: bool = False  # active -> is_primary

class ProductRelationshipV2Payload(BaseModel):
    from_product_id: str = Field(..., min_length=1)
    to_product_id: str = Field(..., min_length=1)
    relationship_type: str = Field(..., min_length=1)
    strength: float = Field(1.0, ge=0.0, le=1.0)
    is_bidirectional: bool = False

class ProductTaxCategoryV2Payload(BaseModel):
    product_id: str = Field(..., min_length=1)
    region_id: str = Field(..., min_length=1)
    tax_category: str = Field(..., min_length=1)
    effective_from: Optional[datetime] = None
    effective_until: Optional[datetime] = None

class StoreAssortmentV2Payload(BaseModel):
    store_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    active: bool = True

class CustomerSegmentV2Payload(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    criteria: Optional[dict] = None
    active: bool = True

class AssortmentSegmentV2Payload(BaseModel):
    assortment_id: str = Field(..., min_length=1)
    segment_id: str = Field(..., min_length=1)
    active: bool = True

# Legacy payloads for backward compatibility
class ProductUpsert(BaseModel):
    sku: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    active: bool = True

class PriceUpsert(BaseModel):
    sku: str = Field(..., min_length=1)
    currency: str = Field("GBP", pattern=r"^[A-Z]{3}$")
    unit_minor: float = Field(..., ge=0, description="price in pounds (e.g., 1.99)")
    active: bool = True

class RestockReq(BaseModel):
    store_id: str = Field(..., min_length=1)
    sku: str = Field(..., min_length=1)
    delta: int = Field(..., description="positive for inbound, negative for outbound; non-zero")
    reason: str = Field("restock", max_length=80)

# ---------- V2 endpoints ----------
@app.post("/catalog/v2/products", response_model=Dict[str, Any])
async def create_product_v2(payload: ProductMasterV2Payload = Body(...)):
    """Create product master with enhanced communication patterns"""
    
    correlation_id = str(uuid.uuid4())
    
    try:
        # Generate product ID using uuid.uuid4() (uuid7 not available in Python 3.11)
        product_id = str(uuid.uuid4())
        
        # Prepare product data
        product_data = {
            "product_id": product_id,
            "name": payload.name,
            "description": payload.description,
            "brand": payload.brand,
            "category_hierarchy": payload.category_hierarchy,
            "search_terms": payload.search_terms,
            "attributes_schema": payload.attributes_schema,
            "active": payload.active,
            "correlation_id": correlation_id
        }
        
        # Execute saga
        result = await catalog_saga.execute_product_creation_saga(product_data)
        
        # Store event in event store
        await event_store.append_event(ServiceEvent(
            event_type=EventType.PRODUCT_CREATED,
            service_name=SERVICE_NAME,
            correlation_id=correlation_id,
            data=result,
            metadata={"enhanced": True, "saga_completed": True},
            timestamp=datetime.now()
        ))
        
        return {
            "product_id": result["product_id"],
            "name": payload.name,
            "status": "created",
            "created_at": datetime.now(),
            "saga_id": correlation_id
        }
        
    except Exception as e:
        logger.error(f"Product creation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/catalog/v2/products/{product_id}")
async def upsert_product_master_v2(product_id: str = Path(...), payload: ProductMasterV2Payload = Body(...)):
    """Create or update a Product Master (V2 architecture)."""
    start_time = datetime.now()
    metrics.counter("endpoint.called").inc()
    
    try:
        # Use circuit breaker for external calls
        async with service_circuit_breaker:
            with SessionLocal() as db:
                # Set RLS context
                set_rls_context(db, tenant_id=None, user_id=str(uuid.uuid4()))  # Catalog is system-wide, add user_id for audited access
                
                # Validate product name uniqueness
                existing_name = db.query(ProductMasterV2).filter(
                    ProductMasterV2.name == payload.name,
                    ProductMasterV2.product_id != product_id
                ).first()
                if existing_name:
                    raise HTTPException(status_code=400, detail=f"Product with name '{payload.name}' already exists")
                
                pm = db.query(ProductMasterV2).filter(ProductMasterV2.product_id == product_id).one_or_none()
                if pm:
                    pm.name = payload.name
                    pm.description = payload.description
                    pm.brand = payload.brand
                    pm.category_hierarchy = payload.category_hierarchy
                    pm.search_terms = payload.search_terms
                    pm.attributes_schema = payload.attributes_schema
                    pm.active = payload.active
                    pm.updated_at = datetime.now()
                    db.commit()
                    logger.info("product_master_updated", extra={"product_id": product_id})
                    
                    # Publish event
                    await service_bus.publish_to_service(
                        target_service="search",
                        event_type=EventType.PRODUCT_UPDATED,
                        data={"product_id": product_id, "name": payload.name, "action": "updated"}
                    )
                    
                    metrics.histogram("endpoint.product_upsert.duration").observe((datetime.now() - start_time).total_seconds())
                    return {"product_id": pm.product_id, "name": pm.name, "updated": True}
                
                pm = ProductMasterV2(
                    product_id=product_id,
                    name=payload.name,
                    description=payload.description,
                    brand=payload.brand,
                    category_hierarchy=payload.category_hierarchy,
                    search_terms=payload.search_terms,
                    attributes_schema=payload.attributes_schema,
                    active=payload.active
                )
                db.add(pm)
                db.commit()
                logger.info("product_master_created", extra={"product_id": product_id})
                
                # Publish event
                await service_bus.publish_to_service(
                    target_service="search",
                    event_type=EventType.PRODUCT_CREATED,
                    data={"product_id": product_id, "name": payload.name, "action": "created"}
                )
                
                metrics.histogram("endpoint.product_upsert.duration").observe((datetime.now() - start_time).total_seconds())
                return {"product_id": pm.product_id, "name": pm.name, "created": True}
                
    except HTTPException:
        metrics.counter("endpoint.product_upsert.error").inc()
        raise
    except Exception as e:
        metrics.counter("endpoint.product_upsert.error").inc()
        logger.error(f"Product master upsert failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.put("/catalog/v2/variants/{variant_id}")
async def upsert_product_variant_v2(variant_id: str = Path(...), payload: ProductVariantV2Payload = Body(...)):
    """Create or update a Product Variant (V2 architecture)."""
    start_time = datetime.now()
    metrics.counter("endpoint.called").inc()
    
    with SessionLocal() as db:
        # Set RLS context
        set_rls_context(db, tenant_id=None, user_id=str(uuid.uuid4()))  # Catalog is system-wide, add user_id for audited access
        
        # Validate product exists
        if not db.query(ProductMasterV2).filter(ProductMasterV2.product_id == payload.product_id).one_or_none():
            raise HTTPException(status_code=400, detail="Product not found")
        
        pv = db.query(ProductVariantV2).filter(ProductVariantV2.variant_id == variant_id).one_or_none()
        if pv:
            pv.product_id = payload.product_id
            pv.sku = payload.sku
            pv.gtin = payload.gtin
            pv.mpn = payload.mpn
            pv.uom = payload.uom
            pv.package_quantity = payload.package_quantity
            pv.weight_grams = payload.weight_grams
            pv.dimensions = payload.dimensions
            pv.variant_attributes = payload.variant_attributes
            pv.active = payload.active
            pv.updated_at = datetime.now()
            db.commit()
            logger.info("product_variant_updated", extra={"variant_id": variant_id})
            return {"variant_id": pv.variant_id, "sku": pv.sku, "updated": True}
        
        pv = ProductVariantV2(
            variant_id=variant_id,
            product_id=payload.product_id,
            sku=payload.sku,
            gtin=payload.gtin,
            mpn=payload.mpn,
            uom=payload.uom,
            package_quantity=payload.package_quantity,
            weight_grams=payload.weight_grams,
            dimensions=payload.dimensions,
            variant_attributes=payload.variant_attributes,
            active=payload.active
        )
        db.add(pv)
        db.commit()
        logger.info("product_variant_created", extra={"variant_id": variant_id})
        metrics.histogram("endpoint.variant_upsert.duration").observe((datetime.now() - start_time).total_seconds())
        return {"variant_id": pv.variant_id, "sku": pv.sku, "created": True}

@app.put("/catalog/v2/vendor-offers/{offer_id}")
async def upsert_vendor_offer_v2(offer_id: str = Path(...), payload: VendorOfferV2Payload = Body(...)):
    """Create or update a Vendor Offer (V2 architecture)."""
    start_time = datetime.now()
    metrics.counter("endpoint.called").inc()
    
    with SessionLocal() as db:
        # Set RLS context
        set_rls_context(db, tenant_id=None, user_id=str(uuid.uuid4()))  # Catalog is system-wide, add user_id for audited access
        
        # Validate variant exists
        if not db.query(ProductVariantV2).filter(ProductVariantV2.variant_id == payload.variant_id).one_or_none():
            raise HTTPException(status_code=400, detail="Product variant not found")
        
        # Validate vendor exists
        vendor = db.execute(text("SELECT vendor_id FROM vendors WHERE vendor_id=:id"), 
                           {"id": payload.vendor_id}).first()
        if not vendor:
            raise HTTPException(status_code=400, detail="Vendor not found")
        
        # Validate currency exists
        currency = db.execute(text("SELECT iso_code FROM currencies WHERE iso_code=:code"), 
                             {"code": payload.currency}).first()
        if not currency:
            raise HTTPException(status_code=400, detail="Currency not found")
        
        vo = db.query(VendorOfferV2).filter(VendorOfferV2.offer_id == offer_id).one_or_none()
        if vo:
            vo.vendor_id = payload.vendor_id
            vo.variant_id = payload.variant_id
            vo.vendor_sku = payload.vendor_sku
            vo.vendor_product_name = payload.vendor_product_name
            vo.base_price_minor = payload.base_price_minor
            vo.currency = payload.currency
            vo.cost_price_minor = payload.cost_price_minor
            vo.min_order_quantity = payload.min_order_quantity
            vo.lead_time_days = payload.lead_time_days
            vo.package_dimensions = payload.package_dimensions
            vo.tax_category = payload.tax_category
            vo.status = payload.status
            vo.offer_valid_from = payload.offer_valid_from or datetime.now()
            vo.offer_valid_until = payload.offer_valid_until
            vo.updated_at = datetime.now()
            db.commit()
            logger.info("vendor_offer_updated", extra={"offer_id": offer_id})
            return {"offer_id": vo.offer_id, "vendor_sku": vo.vendor_sku, "updated": True}
        
        vo = VendorOfferV2(
            offer_id=offer_id,
            vendor_id=payload.vendor_id,
            variant_id=payload.variant_id,
            vendor_sku=payload.vendor_sku,
            vendor_product_name=payload.vendor_product_name,
            base_price_minor=payload.base_price_minor,
            currency=payload.currency,
            cost_price_minor=payload.cost_price_minor,
            min_order_quantity=payload.min_order_quantity,
            lead_time_days=payload.lead_time_days,
            package_dimensions=payload.package_dimensions,
            tax_category=payload.tax_category,
            status=payload.status,
            offer_valid_from=payload.offer_valid_from or datetime.now(),
            offer_valid_until=payload.offer_valid_until
        )
        db.add(vo)
        db.commit()
        logger.info("vendor_offer_created", extra={"offer_id": offer_id})
        metrics.histogram("endpoint.offer_upsert.duration").observe((datetime.now() - start_time).total_seconds())
        return {"offer_id": vo.offer_id, "vendor_sku": vo.vendor_sku, "created": True}

@app.get("/catalog/v2/products")
async def list_products_v2(active: Optional[bool] = Query(None), limit: int = Query(100, ge=1, le=1000)):
    """List products (V2 architecture)."""
    with SessionLocal() as db:
        # Set RLS context
        set_rls_context(db, tenant_id=None, user_id=str(uuid.uuid4()))  # Catalog is system-wide, add user_id for audited access
        
        query = db.query(ProductMasterV2)
        if active is not None:
            query = query.filter(ProductMasterV2.active == active)
        
        products = query.limit(limit).all()
        return [{"product_id": p.product_id, "name": p.name, "description": p.description, 
                "brand": p.brand, "active": p.active, "created_at": p.created_at} for p in products]

@app.get("/catalog/v2/variants")
async def list_variants_v2(product_id: Optional[str] = Query(None), limit: int = Query(100, ge=1, le=1000)):
    """List product variants (V2 architecture)."""
    with SessionLocal() as db:
        # Set RLS context
        set_rls_context(db, tenant_id=None, user_id=str(uuid.uuid4()))  # Catalog is system-wide, add user_id for audited access
        
        query = db.query(ProductVariantV2)
        if product_id:
            query = query.filter(ProductVariantV2.product_id == product_id)
        
        variants = query.limit(limit).all()
        return [{"variant_id": v.variant_id, "product_id": v.product_id, "sku": v.sku, 
                "gtin": v.gtin, "uom": v.uom, "active": v.active, "created_at": v.created_at} for v in variants]

@app.get("/catalog/v2/vendor-offers")
async def list_vendor_offers_v2(vendor_id: Optional[str] = Query(None), variant_id: Optional[str] = Query(None), 
                               limit: int = Query(100, ge=1, le=1000)):
    """List vendor offers (V2 architecture)."""
    with SessionLocal() as db:
        # Set RLS context
        set_rls_context(db, tenant_id=None, user_id=str(uuid.uuid4()))  # Catalog is system-wide, add user_id for audited access
        
        query = db.query(VendorOfferV2)
        if vendor_id:
            query = query.filter(VendorOfferV2.vendor_id == vendor_id)
        if variant_id:
            query = query.filter(VendorOfferV2.variant_id == variant_id)
        
        offers = query.limit(limit).all()
        return [{"offer_id": o.offer_id, "vendor_id": o.vendor_id, "variant_id": o.variant_id, 
                "vendor_sku": o.vendor_sku, "base_price_minor": o.base_price_minor, 
                "currency": o.currency, "status": o.status, "created_at": o.created_at} for o in offers]

# ---------- V2 additional endpoints ----------
@app.post("/catalog/v2/media", response_model=Dict[str, Any])
async def create_product_media(payload: ProductMediaV2Payload = Body(...)):
    """Create product media with enhanced communication patterns"""
    correlation_id = str(uuid.uuid4())
    
    try:
        media_id = str(uuid.uuid4())
        
        with SessionLocal() as db:
            set_rls_context(db, user_id=correlation_id)  # Add user_id for audited access
            
            # Validate product/variant exists
            if payload.variant_id:
                variant = db.query(ProductVariantV2).filter(ProductVariantV2.variant_id == payload.variant_id).first()
                if not variant:
                    raise HTTPException(status_code=400, detail="Product variant not found")
            else:
                product = db.query(ProductMasterV2).filter(ProductMasterV2.product_id == payload.product_id).first()
                if not product:
                    raise HTTPException(status_code=400, detail="Product not found")
            
            media = ProductMediaV2(
                id=media_id,
                product_id=payload.product_id,
                variant_id=payload.variant_id,
                media_type=payload.media_type,
                url=payload.url,
                caption=payload.caption,
                sort_order=payload.sort_order,
                is_primary=payload.is_primary
            )
            db.add(media)
            db.commit()
            
            logger.info("product_media_created", extra={"media_id": media_id, "product_id": payload.product_id})
            
            # Publish event
            await service_bus.publish_to_service(
                target_service="search",
                event_type=EventType.PRODUCT_CREATED,
                data={"media_id": media_id, "product_id": payload.product_id, "media_type": payload.media_type}
            )
            
            return {"media_id": media_id, "product_id": payload.product_id, "created": True}
            
    except Exception as e:
        logger.error(f"Product media creation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/catalog/v2/assortments/{assortment_id}")
async def upsert_store_assortment(assortment_id: str = Path(...), payload: StoreAssortmentV2Payload = Body(...)):
    """Create or update a Store Assortment (V2 architecture)."""
    with SessionLocal() as db:
        set_rls_context(db, user_id=str(uuid.uuid4()))  # Add user_id for audited access
        
        # Validate store exists
        store = db.execute(text("SELECT store_id FROM stores WHERE store_id=:id"), {"id": payload.store_id}).first()
        if not store:
            raise HTTPException(status_code=400, detail="Store not found")
        
        assortment = db.query(StoreAssortmentV2).filter(StoreAssortmentV2.assortment_id == assortment_id).one_or_none()
        if assortment:
            assortment.name = payload.name
            assortment.description = payload.description
            assortment.active = payload.active
            assortment.updated_at = datetime.now()
            db.commit()
            logger.info("store_assortment_updated", extra={"assortment_id": assortment_id})
            return {"assortment_id": assortment.assortment_id, "name": assortment.name, "updated": True}
        
        assortment = StoreAssortmentV2(
            assortment_id=assortment_id,
            store_id=payload.store_id,
            name=payload.name,
            description=payload.description,
            active=payload.active
        )
        db.add(assortment)
        db.commit()
        logger.info("store_assortment_created", extra={"assortment_id": assortment_id})
        return {"assortment_id": assortment.assortment_id, "name": assortment.name, "created": True}

@app.put("/catalog/v2/customer-segments/{segment_id}")
async def upsert_customer_segment(segment_id: str = Path(...), payload: CustomerSegmentV2Payload = Body(...)):
    """Create or update a Customer Segment (V2 architecture)."""
    with SessionLocal() as db:
        set_rls_context(db, tenant_id=payload.tenant_id, user_id=str(uuid.uuid4()))
        
        # Validate tenant exists
        tenant = db.execute(text("SELECT tenant_id FROM tenants WHERE tenant_id=:id"), {"id": payload.tenant_id}).first()
        if not tenant:
            raise HTTPException(status_code=400, detail="Tenant not found")
        
        segment = db.query(CustomerSegmentV2).filter(CustomerSegmentV2.segment_id == segment_id).one_or_none()
        if segment:
            segment.name = payload.name
            segment.description = payload.description
            segment.criteria = payload.criteria
            segment.active = payload.active
            segment.updated_at = datetime.now()
            db.commit()
            logger.info("customer_segment_updated", extra={"segment_id": segment_id})
            return {"segment_id": segment.segment_id, "name": segment.name, "updated": True}
        
        segment = CustomerSegmentV2(
            segment_id=segment_id,
            tenant_id=payload.tenant_id,
            name=payload.name,
            description=payload.description,
            criteria=payload.criteria,
            active=payload.active
        )
        db.add(segment)
        db.commit()
        logger.info("customer_segment_created", extra={"segment_id": segment_id})
        return {"segment_id": segment.segment_id, "name": segment.name, "created": True}

@app.put("/catalog/v2/assortment-segments/{assortment_segment_id}")
async def upsert_assortment_segment(assortment_segment_id: str = Path(...), payload: AssortmentSegmentV2Payload = Body(...)):
    """Create or update an Assortment Segment (V2 architecture)."""
    with SessionLocal() as db:
        set_rls_context(db, user_id=str(uuid.uuid4()))
        
        # Validate assortment and segment exist
        assortment = db.query(StoreAssortmentV2).filter(StoreAssortmentV2.assortment_id == payload.assortment_id).first()
        if not assortment:
            raise HTTPException(status_code=400, detail="Store assortment not found")
        
        segment = db.query(CustomerSegmentV2).filter(CustomerSegmentV2.segment_id == payload.segment_id).first()
        if not segment:
            raise HTTPException(status_code=400, detail="Customer segment not found")
        
        assortment_segment = db.query(AssortmentSegmentV2).filter(AssortmentSegmentV2.assortment_segment_id == assortment_segment_id).one_or_none()
        if assortment_segment:
            assortment_segment.active = payload.active
            assortment_segment.updated_at = datetime.now()
            db.commit()
            logger.info("assortment_segment_updated", extra={"assortment_segment_id": assortment_segment_id})
            return {"assortment_segment_id": assortment_segment.assortment_segment_id, "updated": True}
        
        assortment_segment = AssortmentSegmentV2(
            assortment_segment_id=assortment_segment_id,
            assortment_id=payload.assortment_id,
            segment_id=payload.segment_id,
            active=payload.active
        )
        db.add(assortment_segment)
        db.commit()
        logger.info("assortment_segment_created", extra={"assortment_segment_id": assortment_segment_id})
        return {"assortment_segment_id": assortment_segment.assortment_segment_id, "created": True}

@app.post("/catalog/v2/relationships", response_model=Dict[str, Any])
async def create_product_relationship(payload: ProductRelationshipV2Payload = Body(...)):
    """Create product relationship with enhanced communication patterns"""
    correlation_id = str(uuid.uuid4())
    
    try:
        relationship_id = str(uuid.uuid4())
        
        with SessionLocal() as db:
            set_rls_context(db, user_id=correlation_id)
            
            # Validate from and to products exist
            from_product = db.query(ProductMasterV2).filter(ProductMasterV2.product_id == payload.from_product_id).first()
            if not from_product:
                raise HTTPException(status_code=400, detail="From product not found")
            
            to_product = db.query(ProductMasterV2).filter(ProductMasterV2.product_id == payload.to_product_id).first()
            if not to_product:
                raise HTTPException(status_code=400, detail="To product not found")
            
            relationship = ProductRelationshipV2(
                id=relationship_id,
                from_product_id=payload.from_product_id,
                to_product_id=payload.to_product_id,
                relationship_type=payload.relationship_type,
                strength=payload.strength,
                is_bidirectional=payload.is_bidirectional
            )
            db.add(relationship)
            db.commit()
            
            logger.info("product_relationship_created", extra={"relationship_id": relationship_id, "from_product_id": payload.from_product_id})
            
            # Publish event
            await service_bus.publish_to_service(
                target_service="search",
                event_type=EventType.PRODUCT_CREATED,
                data={"relationship_id": relationship_id, "from_product_id": payload.from_product_id, "relationship_type": payload.relationship_type}
            )
            
            return {"relationship_id": relationship_id, "from_product_id": payload.from_product_id, "created": True}
            
    except Exception as e:
        logger.error(f"Product relationship creation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/catalog/v2/tax-categories/{tax_category_id}")
async def upsert_product_tax_category(tax_category_id: str = Path(...), payload: ProductTaxCategoryV2Payload = Body(...)):
    """Create or update a Product Tax Category (V2 architecture)."""
    with SessionLocal() as db:
        set_rls_context(db, user_id=str(uuid.uuid4()))
        
        # Validate product exists
        product = db.query(ProductMasterV2).filter(ProductMasterV2.product_id == payload.product_id).first()
        if not product:
            raise HTTPException(status_code=400, detail="Product not found")
        
        # Validate region exists
        region = db.execute(text("SELECT region_id FROM tax_regions WHERE region_id=:id"), 
                           {"id": payload.region_id}).first()
        if not region:
            raise HTTPException(status_code=400, detail="Tax region not found")
        
        tax_category = db.query(ProductTaxCategoryV2).filter(ProductTaxCategoryV2.id == tax_category_id).one_or_none()
        if tax_category:
            tax_category.tax_category = payload.tax_category
            tax_category.effective_from = payload.effective_from or datetime.now()
            tax_category.effective_until = payload.effective_until
            db.commit()
            logger.info("product_tax_category_updated", extra={"tax_category_id": tax_category_id})
            return {"tax_category_id": tax_category.id, "tax_category": tax_category.tax_category, "updated": True}
        
        tax_category = ProductTaxCategoryV2(
            id=tax_category_id,
            product_id=payload.product_id,
            region_id=payload.region_id,
            tax_category=payload.tax_category,
            effective_from=payload.effective_from or datetime.now(),
            effective_until=payload.effective_until
        )
        db.add(tax_category)
        db.commit()
        logger.info("product_tax_category_created", extra={"tax_category_id": tax_category_id})
        return {"tax_category_id": tax_category.id, "tax_category": tax_category.tax_category, "created": True}

# ---------- legacy products ----------
@app.put("/catalog/products")
def upsert_product(payload: ProductUpsert = Body(...)):
    """
    Create or update a product by SKU.
    """
    with SessionLocal() as db:
        exists = db.execute(
            text("SELECT sku FROM products WHERE sku=:s"),
            {"s": payload.sku}
        ).first()

        if exists:
            db.execute(text("""
                UPDATE products
                   SET name=:n, description=:d, active=:a, updated_at=NOW()
                 WHERE sku=:s
            """), {"n": payload.name, "d": payload.description, "a": payload.active, "s": payload.sku})
            db.commit()
            log.info("product_updated sku=%s active=%s", payload.sku, payload.active)
            
            # Publish product updated event
            try:
                product_event = Event(
                    event_type=EventType.PRODUCT_UPDATED,
                    tenant_id="system",  # Catalog events are system-wide
                    data={
                        "sku": payload.sku,
                        "name": payload.name,
                        "description": payload.description,
                        "active": payload.active,
                        "action": "updated"
                    },
                    metadata={"service": "catalog", "version": "0.8.0"}
                )
                
                celery_app.send_task(
                    "zeroque_common.events.catalog_tasks.process_product_event",
                    args=[product_event.__dict__],
                    queue="catalog"
                )
                log.info("product_event_published sku=%s event=updated", payload.sku)
            except Exception as e:
                log.warning("Failed to publish product updated event: %s", str(e))
            
            return {"sku": payload.sku, "updated": True}
        else:
            db.execute(text("""
                INSERT INTO products(sku, name, description, active)
                VALUES(:s, :n, :d, :a)
            """), {"s": payload.sku, "n": payload.name, "d": payload.description, "a": payload.active})
            db.commit()
            log.info("product_created sku=%s", payload.sku)
            
            # Publish product created event
            try:
                product_event = Event(
                    event_type=EventType.PRODUCT_CREATED,
                    tenant_id="system",  # Catalog events are system-wide
                    data={
                        "sku": payload.sku,
                        "name": payload.name,
                        "description": payload.description,
                        "active": payload.active,
                        "action": "created"
                    },
                    metadata={"service": "catalog", "version": "0.8.0"}
                )
                
                celery_app.send_task(
                    "zeroque_common.events.catalog_tasks.process_product_event",
                    args=[product_event.__dict__],
                    queue="catalog"
                )
                log.info("product_event_published sku=%s event=created", payload.sku)
            except Exception as e:
                log.warning("Failed to publish product created event: %s", str(e))
            
            return {"sku": payload.sku, "created": True}

@app.get("/catalog/products")
def list_products(active: Optional[bool] = Query(None), limit: int = Query(100, ge=1, le=1000)):
    """
    List products, optionally filtered by 'active'.
    """
    with SessionLocal() as db:
        if active is None:
            rows = db.execute(
                text("SELECT sku,name,description,active FROM products ORDER BY sku LIMIT :l"),
                {"l": limit}
            ).all()
        else:
            rows = db.execute(
                text("SELECT sku,name,description,active FROM products WHERE active=:a ORDER BY sku LIMIT :l"),
                {"a": active, "l": limit}
            ).all()
        out = [{"sku": r[0], "name": r[1], "description": r[2], "active": bool(r[3])} for r in rows]
        log.info("products_listed count=%d active=%s", len(out), active)
        return out

# ---------- prices ----------
@app.put("/catalog/prices")
def upsert_price(payload: PriceUpsert = Body(...)):
    """
    Create or update a price row (sku + currency). One row can be marked active.
    """
    with SessionLocal() as db:
        # verify product exists for better ergonomics
        prod = db.execute(text("SELECT 1 FROM products WHERE sku=:s"), {"s": payload.sku}).first()
        if not prod:
            raise HTTPException(status_code=400, detail="SKU not found; create product first")

        r = db.execute(text("""
            SELECT id FROM prices WHERE sku=:s AND currency=:c
        """), {"s": payload.sku, "c": payload.currency}).first()

        if r:
            db.execute(text("""
                UPDATE prices
                   SET unit_minor=:u, active=:a, updated_at=NOW()
                 WHERE id=:id
            """), {"u": payload.unit_minor, "a": payload.active, "id": int(r[0])})
            db.commit()
            log.info("price_updated sku=%s currency=%s unit_minor=%d active=%s",
                     payload.sku, payload.currency, payload.unit_minor, payload.active)
            return {"sku": payload.sku, "currency": payload.currency, "updated": True}

        db.execute(text("""
            INSERT INTO prices(sku, currency, unit_minor, active)
            VALUES(:s, :c, :u, :a)
        """), {"s": payload.sku, "c": payload.currency, "u": payload.unit_minor, "a": payload.active})
        db.commit()
        log.info("price_created sku=%s currency=%s unit_minor=%d active=%s",
                 payload.sku, payload.currency, payload.unit_minor, payload.active)
        return {"sku": payload.sku, "currency": payload.currency, "created": True}

@app.get("/catalog/prices")
def list_prices(sku: Optional[str] = Query(None), currency: str = Query("GBP", pattern=r"^[A-Z]{3}$")):
    """
    List prices. If 'sku' is passed, filter to that SKU + currency; else list all prices for a currency.
    """
    with SessionLocal() as db:
        if sku:
            rows = db.execute(text("""
                SELECT id, sku, currency, unit_minor, active
                  FROM prices
                 WHERE sku=:s AND currency=:c
            """), {"s": sku, "c": currency}).all()
        else:
            rows = db.execute(text("""
                SELECT id, sku, currency, unit_minor, active
                  FROM prices
                 WHERE currency=:c
            """), {"c": currency}).all()
        out = [{"id": int(r[0]), "sku": r[1], "currency": r[2], "unit_minor": int(r[3]), "active": bool(r[4])} for r in rows]
        log.info("prices_listed count=%d sku=%s currency=%s", len(out), sku, currency)
        return out

# ---------- inventory ----------
@app.post("/catalog/inventory/restock")
def restock(payload: RestockReq = Body(...)):
    """
    Adjust on-hand stock for a store/SKU and append a movement record.
    Positive delta = inbound; negative = outbound.
    """
    if payload.delta == 0:
        raise HTTPException(status_code=400, detail="delta must be non-zero")

    with SessionLocal() as db:
        # Optional safety: ensure SKU exists
        exists = db.execute(text("SELECT 1 FROM products WHERE sku=:s"), {"s": payload.sku}).first()
        if not exists:
            raise HTTPException(status_code=400, detail="SKU not found; create product first")

        # Update existing row (NO updated_at here)
        updated = db.execute(text("""
            UPDATE inventory
               SET qty = qty + :d
             WHERE store_id=:st AND sku=:s
        """), {"d": payload.delta, "st": payload.store_id, "s": payload.sku}).rowcount

        # If no row, insert a new one. Don’t start negative.
        if updated == 0:
            initial_qty = max(payload.delta, 0)
            db.execute(text("""
                INSERT INTO inventory(store_id, sku, qty)
                VALUES(:st, :s, :q)
            """), {"st": payload.store_id, "s": payload.sku, "q": initial_qty})

        # Always write a movement record
        db.execute(text("""
            INSERT INTO inventory_movements(store_id, sku, delta, reason)
            VALUES(:st, :s, :d, :r)
        """), {"st": payload.store_id, "s": payload.sku, "d": payload.delta, "r": payload.reason})

        db.commit()

        current = db.execute(text("""
            SELECT qty FROM inventory WHERE store_id=:st AND sku=:s
        """), {"st": payload.store_id, "s": payload.sku}).scalar() or 0

        log.info("inventory_adjusted store=%s sku=%s delta=%d qty=%d reason=%s",
                 payload.store_id, payload.sku, payload.delta, int(current), payload.reason)

        return {"store_id": payload.store_id, "sku": payload.sku, "delta": payload.delta, "qty": int(current)}
@app.get("/catalog/inventory")
def get_inventory(store_id: str = Query(...), limit: int = Query(500, ge=1, le=5000)):
    """
    Return current stock for a store.
    """
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT sku, qty
              FROM inventory
             WHERE store_id=:st
             ORDER BY sku
             LIMIT :l
        """), {"st": store_id, "l": limit}).all()
        out = [{"sku": r[0], "qty": int(r[1])} for r in rows]
        log.info("inventory_listed store=%s count=%d", store_id, len(out))
        return out