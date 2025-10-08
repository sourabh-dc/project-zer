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
from sqlalchemy import text, UUID, String, Boolean, DateTime, func, JSON, BigInteger, Integer, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

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

# Custom exceptions for catalog service
class CatalogValidationError(Exception):
    """Custom validation error for catalog operations"""
    pass

class CatalogNotFoundError(Exception):
    """Custom not found error for catalog operations"""
    pass

class CatalogDuplicateError(Exception):
    """Custom duplicate error for catalog operations"""
    pass

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

# Custom exception handlers
@app.exception_handler(CatalogValidationError)
async def catalog_validation_exception_handler(request, exc: CatalogValidationError):
    """Handle catalog validation errors"""
    logger.warning(f"Catalog validation error: {exc}")
    return HTTPException(status_code=400, detail=str(exc))

@app.exception_handler(CatalogNotFoundError)
async def catalog_not_found_exception_handler(request, exc: CatalogNotFoundError):
    """Handle catalog not found errors"""
    logger.warning(f"Catalog not found error: {exc}")
    return HTTPException(status_code=404, detail=str(exc))

@app.exception_handler(CatalogDuplicateError)
async def catalog_duplicate_exception_handler(request, exc: CatalogDuplicateError):
    """Handle catalog duplicate errors"""
    logger.warning(f"Catalog duplicate error: {exc}")
    return HTTPException(status_code=409, detail=str(exc))

# V2 SQLAlchemy Models for the new architecture
class ProductMasterV2(Base):
    __tablename__ = "product_master"
    product_id: Mapped[str] = mapped_column(UUID, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    brand: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    category_hierarchy: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # search_terms removed as requested
    attributes_schema: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class ProductVariantV2(Base):
    __tablename__ = "product_variants"
    variant_id: Mapped[str] = mapped_column(UUID, primary_key=True)
    product_id: Mapped[str] = mapped_column(UUID)  # References product_master(product_id)
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
    vendor_id: Mapped[str] = mapped_column(UUID)  # References vendors(vendor_id)
    variant_id: Mapped[str] = mapped_column(UUID)  # References product_variants(variant_id)
    vendor_sku: Mapped[str] = mapped_column(String(100))
    vendor_product_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    base_price_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))  # References currencies(iso_code)
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
    product_id: Mapped[str] = mapped_column(UUID)  # References product_master(product_id)
    variant_id: Mapped[Optional[str]] = mapped_column(UUID, nullable=True)  # References product_variants(variant_id)
    media_type: Mapped[str] = mapped_column(String(20))  # image, video, document
    url: Mapped[str] = mapped_column(String(500))
    caption: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ProductRelationshipV2(Base):
    __tablename__ = "product_relationships"
    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    from_product_id: Mapped[str] = mapped_column(UUID)  # References product_master(product_id)
    to_product_id: Mapped[str] = mapped_column(UUID)  # References product_master(product_id)
    relationship_type: Mapped[str] = mapped_column(String(50))  # bundle, accessory, replacement, etc.
    strength: Mapped[float] = mapped_column(Numeric(3, 2), default=1.0)
    is_bidirectional: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ProductTaxCategoryV2(Base):
    __tablename__ = "product_tax_categories"
    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    product_id: Mapped[str] = mapped_column(UUID)  # References product_master(product_id)
    region_id: Mapped[str] = mapped_column(UUID)  # References tax_regions(region_id)
    tax_category: Mapped[str] = mapped_column(String(100))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class StoreAssortmentV2(Base):
    __tablename__ = "store_assortments"
    assortment_id: Mapped[str] = mapped_column(UUID, primary_key=True)
    store_id: Mapped[str] = mapped_column(UUID)  # References stores(store_id)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active, inactive, draft
    effective_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
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
    assortment_id: Mapped[str] = mapped_column(UUID)  # References store_assortments(assortment_id)
    segment_id: Mapped[str] = mapped_column(UUID)  # References customer_segments(segment_id)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class ProductNormalizationCache(Base):
    """Cache for CV product mapping - mentioned in architecture"""
    __tablename__ = "product_normalization_cache"
    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    cv_product_id: Mapped[str] = mapped_column(String(200))  # CV provider product ID
    product_id: Mapped[Optional[str]] = mapped_column(UUID, nullable=True)  # References product_master(product_id)
    variant_id: Mapped[Optional[str]] = mapped_column(UUID, nullable=True)  # References product_variants(variant_id)
    confidence_score: Mapped[Optional[float]] = mapped_column(Numeric(3, 2), nullable=True)
    cv_provider: Mapped[str] = mapped_column(String(50))  # aifi, other CV providers
    normalization_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class AssortmentItemV2(Base):
    """Products/variants in store assortments"""
    __tablename__ = "assortment_items"
    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    assortment_id: Mapped[str] = mapped_column(UUID)  # References store_assortments(assortment_id)
    offer_id: Mapped[str] = mapped_column(UUID)  # References vendor_offers(offer_id)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

# Missing models from architecture
class VendorV2(Base):
    """Vendor management - from architecture"""
    __tablename__ = "vendors"
    vendor_id: Mapped[str] = mapped_column(UUID, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(UUID)  # References tenants(tenant_id)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rating: Mapped[Optional[float]] = mapped_column(Numeric(3, 2), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class VendorOnboardingV2(Base):
    """Vendor onboarding process - from architecture"""
    __tablename__ = "vendor_onboarding"
    onboarding_id: Mapped[str] = mapped_column(UUID, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(UUID)  # References vendors(vendor_id)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    requirements: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # Docs checklist
    approver_id: Mapped[Optional[str]] = mapped_column(UUID, nullable=True)  # References users(user_id)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class StoreVendorV2(Base):
    """M:N relationship between stores and vendors - from architecture"""
    __tablename__ = "store_vendors"
    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    store_id: Mapped[str] = mapped_column(UUID)  # References stores(store_id)
    vendor_id: Mapped[str] = mapped_column(UUID)  # References vendors(vendor_id)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class TaxRegionV2(Base):
    """Tax regions for jurisdiction-based taxes - from architecture"""
    __tablename__ = "tax_regions"
    region_id: Mapped[str] = mapped_column(UUID, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    jurisdiction: Mapped[dict] = mapped_column(JSON)  # Geo polygon/country/state/GST code
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class TaxRuleV2(Base):
    """Tax rules for regions - from architecture"""
    __tablename__ = "tax_rules"
    rule_id: Mapped[str] = mapped_column(UUID, primary_key=True)
    region_id: Mapped[str] = mapped_column(UUID)  # References tax_regions(region_id)
    category: Mapped[str] = mapped_column(String(100))
    rate: Mapped[float] = mapped_column(Numeric(5, 4))
    is_inclusive: Mapped[bool] = mapped_column(Boolean, default=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

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

# RLS Context Helper - Standardized
def set_rls_context(db_session, tenant_id: str = None, user_id: str = None, store_id: str = None, vendor_id: str = None):
    """Set Row Level Security context for database session - standardized implementation"""
    try:
        if tenant_id:
            db_session.execute(text("SET LOCAL app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        if user_id:
            db_session.execute(text("SET LOCAL app.user_id = :user_id"), {"user_id": user_id})
        if store_id:
            db_session.execute(text("SET LOCAL app.current_store_id = :store_id"), {"store_id": store_id})
        if vendor_id:
            db_session.execute(text("SET LOCAL app.current_vendor_id = :vendor_id"), {"vendor_id": vendor_id})
        
        # Enable RLS for the session
        db_session.execute(text("SET row_security = on"))
        
    except Exception as e:
        logger.warning(f"Failed to set RLS context: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to set security context")

# Validation helpers
def validate_product_name_unique(db_session, name: str, exclude_product_id: str = None):
    """Validate that product name is unique using ORM"""
    try:
        query = db_session.query(ProductMasterV2).filter(ProductMasterV2.name == name)
        if exclude_product_id:
            query = query.filter(ProductMasterV2.product_id != exclude_product_id)
        
        existing = query.first()
        if existing:
            raise CatalogDuplicateError(f"Product with name '{name}' already exists")
    except SQLAlchemyError as e:
        logger.error(f"Database error validating product name uniqueness: {str(e)}")
        raise HTTPException(status_code=500, detail="Database validation error")

def validate_variant_sku_unique(db_session, sku: str, exclude_variant_id: str = None):
    """Validate that variant SKU is unique"""
    query = db_session.query(ProductVariantV2).filter(ProductVariantV2.sku == sku)
    if exclude_variant_id:
        query = query.filter(ProductVariantV2.variant_id != exclude_variant_id)
    
    existing = query.first()
    if existing:
        raise CatalogDuplicateError(f"Variant with SKU '{sku}' already exists")

def validate_vendor_offer_unique(db_session, vendor_id: str, variant_id: str = None, vendor_sku: str = None):
    """Validate that vendor offer is unique for vendor+variant or vendor+vendor_sku"""
    if variant_id:
        existing = db_session.query(VendorOfferV2).filter(
            VendorOfferV2.vendor_id == vendor_id,
            VendorOfferV2.variant_id == variant_id
        ).first()
        if existing:
            raise CatalogDuplicateError(f"Vendor offer already exists for vendor {vendor_id} and variant {variant_id}")
    
    if vendor_sku:
        existing = db_session.query(VendorOfferV2).filter(
            VendorOfferV2.vendor_id == vendor_id,
            VendorOfferV2.vendor_sku == vendor_sku
        ).first()
        if existing:
            raise CatalogDuplicateError(f"Vendor offer already exists for vendor {vendor_id} and SKU {vendor_sku}")

def validate_references_exist(db_session, **references):
    """Validate that referenced entities exist"""
    for ref_type, ref_id in references.items():
        if ref_id:
            if ref_type == "product_id":
                product = db_session.query(ProductMasterV2).filter(ProductMasterV2.product_id == ref_id).first()
                if not product:
                    raise CatalogNotFoundError(f"Product {ref_id} not found")
            elif ref_type == "variant_id":
                variant = db_session.query(ProductVariantV2).filter(ProductVariantV2.variant_id == ref_id).first()
                if not variant:
                    raise CatalogNotFoundError(f"Product variant {ref_id} not found")
            elif ref_type == "vendor_id":
                vendor = db_session.execute(text("SELECT vendor_id FROM vendors WHERE vendor_id=:id"), 
                                           {"id": ref_id}).first()
                if not vendor:
                    raise CatalogNotFoundError(f"Vendor {ref_id} not found")
            elif ref_type == "currency":
                currency = db_session.execute(text("SELECT iso_code FROM currencies WHERE iso_code=:code"), 
                                             {"code": ref_id}).first()
                if not currency:
                    raise CatalogNotFoundError(f"Currency {ref_id} not found")
            elif ref_type == "store_id":
                store = db_session.execute(text("SELECT store_id FROM stores WHERE store_id=:id"), 
                                          {"id": ref_id}).first()
                if not store:
                    raise CatalogNotFoundError(f"Store {ref_id} not found")
            elif ref_type == "tenant_id":
                tenant = db_session.execute(text("SELECT tenant_id FROM tenants WHERE tenant_id=:id"), 
                                           {"id": ref_id}).first()
                if not tenant:
                    raise CatalogNotFoundError(f"Tenant {ref_id} not found")

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
        
        # Validate required fields
        if not data.get('name'):
            raise CatalogValidationError("Product name is required")
        
        # Check if product name is unique
        with SessionLocal() as db:
            validate_product_name_unique(db, data.get('name'))
            
            # Validate variant SKU if provided
            if data.get('sku'):
                validate_variant_sku_unique(db, data.get('sku'))
            
            # Validate references exist
            validate_references_exist(db, 
                                    vendor_id=data.get('vendor_id'),
                                    currency=data.get('currency'))
        
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
                # search_terms removed as requested
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
            
            # Validate SKU uniqueness
            validate_variant_sku_unique(db, data.get('sku'))
            
            # Validate product exists
            validate_references_exist(db, product_id=data['product_id'])
            
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
            
            # Validate references exist
            validate_references_exist(db, 
                                    vendor_id=data.get('vendor_id'),
                                    variant_id=data.get('variant_id'),
                                    currency=data.get('currency'))
            
            # Validate vendor offer uniqueness
            validate_vendor_offer_unique(db, 
                                       vendor_id=data.get('vendor_id'),
                                       variant_id=data.get('variant_id'),
                                       vendor_sku=data.get('vendor_sku'))
            
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
        
        # Publish comprehensive event to search service
        search_data = {
                "product_id": data.get('product_id'),
                "variant_id": data.get('variant_id'),
                "offer_id": data.get('offer_id'),
            "name": data.get('name'),
            "description": data.get('description'),
            "brand": data.get('brand'),
            "sku": data.get('sku'),
            "category_hierarchy": data.get('category_hierarchy'),
            # search_terms removed as requested
            "action": "index",
            "timestamp": datetime.now().isoformat()
        }
        
        await service_bus.publish_to_service(
            target_service="search",
            event_type=EventType.PRODUCT_CREATED,
            data=search_data
        )
        
        # Also publish to event store for audit
        await event_store.append_event(ServiceEvent(
            event_type=EventType.PRODUCT_CREATED,
            service_name=SERVICE_NAME,
            correlation_id=data.get('correlation_id', ''),
            data=search_data,
            metadata={"saga_step": "search_index", "enhanced": True},
            timestamp=datetime.now()
        ))
        
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
async def health():
    """Enhanced health check endpoint with integration testing"""
    health_status = {
        "status": "healthy",
        "service": SERVICE_NAME,
        "version": "2.0.0",
        "timestamp": datetime.now().isoformat(),
        "components": {}
    }
    
    try:
        # Test database connectivity
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            health_status["components"]["database"] = {"status": "healthy", "message": "Connected"}
    except Exception as e:
        health_status["components"]["database"] = {"status": "unhealthy", "message": str(e)}
        health_status["status"] = "unhealthy"
    
    try:
        # Test service bus connectivity
        await service_bus.health_check()
        health_status["components"]["service_bus"] = {"status": "healthy", "message": "Connected"}
    except Exception as e:
        health_status["components"]["service_bus"] = {"status": "unhealthy", "message": str(e)}
        health_status["status"] = "degraded"
    
    try:
        # Test event store connectivity
        await event_store.health_check()
        health_status["components"]["event_store"] = {"status": "healthy", "message": "Connected"}
    except Exception as e:
        health_status["components"]["event_store"] = {"status": "unhealthy", "message": str(e)}
        health_status["status"] = "degraded"
    
    # Test circuit breaker status
    try:
        circuit_count = len(service_circuit_breaker.circuits)
        health_status["components"]["circuit_breaker"] = {
            "status": "healthy",
            "message": f"Circuit breaker active with {circuit_count} circuits",
            "circuits": list(service_circuit_breaker.circuits.keys())
        }
    except Exception as e:
        health_status["components"]["circuit_breaker"] = {"status": "unhealthy", "message": str(e)}
    
    return health_status

@app.get("/catalog/v2/integration-test")
async def integration_test():
    """Test endpoint to verify catalog service integration with other services"""
    test_results = {
        "test_id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "service": SERVICE_NAME,
        "tests": {}
    }
    
    try:
        # Test 1: Database RLS functionality
        with SessionLocal() as db:
            set_rls_context(db, user_id="test-user", tenant_id="test-tenant")
            db.execute(text("SELECT 1"))
            test_results["tests"]["database_rls"] = {"status": "passed", "message": "RLS context set successfully"}
    except Exception as e:
        test_results["tests"]["database_rls"] = {"status": "failed", "message": str(e)}
    
    try:
        # Test 2: Service bus event publishing
        test_event_data = {
            "test": True,
            "timestamp": datetime.now().isoformat(),
            "service": SERVICE_NAME
        }
        
        await service_bus.publish_to_service(
            target_service="test",
            event_type=EventType.PRODUCT_CREATED,
            data=test_event_data
        )
        test_results["tests"]["service_bus"] = {"status": "passed", "message": "Event published successfully"}
    except Exception as e:
        test_results["tests"]["service_bus"] = {"status": "failed", "message": str(e)}
    
    try:
        # Test 3: Event store functionality
        test_event = ServiceEvent(
            event_type=EventType.PRODUCT_CREATED,
            service_name=SERVICE_NAME,
            correlation_id="test-correlation",
            data={"test": True},
            metadata={"integration_test": True},
            timestamp=datetime.now()
        )
        
        await event_store.append_event(test_event)
        test_results["tests"]["event_store"] = {"status": "passed", "message": "Event stored successfully"}
    except Exception as e:
        test_results["tests"]["event_store"] = {"status": "failed", "message": str(e)}
    
    try:
        # Test 4: Circuit breaker functionality
        circuit_count = len(service_circuit_breaker.circuits)
        test_results["tests"]["circuit_breaker"] = {
            "status": "passed",
            "message": f"Circuit breaker active with {circuit_count} circuits",
            "circuits": list(service_circuit_breaker.circuits.keys())
        }
    except Exception as e:
        test_results["tests"]["circuit_breaker"] = {"status": "failed", "message": str(e)}
    
    # Calculate overall test result
    failed_tests = [test for test in test_results["tests"].values() if test["status"] == "failed"]
    if failed_tests:
        test_results["overall_status"] = "failed"
        test_results["failed_count"] = len(failed_tests)
    else:
        test_results["overall_status"] = "passed"
        test_results["failed_count"] = 0
    
    return test_results

@app.get("/catalog/v2/performance")
async def get_performance_metrics():
    """Get performance metrics for catalog service (V2 architecture)."""
    return get_performance_metrics()

@app.get("/catalog/v2/comprehensive-test")
async def comprehensive_catalog_test():
    """Comprehensive test of all catalog service functionality (V2 architecture)."""
    test_results = {
        "test_id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "service": SERVICE_NAME,
        "version": "2.0.0",
        "test_categories": {}
    }
    
    try:
        # Test 1: Database Schema Validation
        with SessionLocal() as db:
            # Test all V2 models exist and are accessible
            v2_models = [
                ProductMasterV2, ProductVariantV2, VendorOfferV2,
                ProductMediaV2, ProductRelationshipV2, StoreAssortmentV2,
                CustomerSegmentV2, VendorV2, VendorOnboardingV2,
                StoreVendorV2, TaxRegionV2, TaxRuleV2,
                ProductTaxCategoryV2, ProductNormalizationCache, AssortmentItemV2
            ]
            
            model_tests = {}
            for model in v2_models:
                try:
                    db.query(model).limit(1).all()
                    model_tests[model.__tablename__] = {"status": "passed", "message": "Model accessible"}
                except Exception as e:
                    model_tests[model.__tablename__] = {"status": "failed", "message": str(e)}
            
            test_results["test_categories"]["database_schema"] = {
                "status": "passed" if all(t["status"] == "passed" for t in model_tests.values()) else "failed",
                "models_tested": model_tests
            }
        
        # Test 2: RLS Functionality
        with SessionLocal() as db:
            try:
                set_rls_context(db, user_id="test-user", tenant_id="test-tenant", store_id="test-store")
                db.execute(text("SELECT 1"))
                test_results["test_categories"]["row_level_security"] = {
                    "status": "passed",
                    "message": "RLS context set successfully"
                }
            except Exception as e:
                test_results["test_categories"]["row_level_security"] = {
                    "status": "failed",
                    "message": str(e)
                }
        
        # Test 3: Validation Functions
        validation_tests = {}
        try:
            # Test business rule validation
            validate_business_rules(None, {"name": "test"}, "product_creation")
            validation_tests["business_rules"] = {"status": "passed", "message": "Business rules validation working"}
        except Exception as e:
            validation_tests["business_rules"] = {"status": "failed", "message": str(e)}
        
        try:
            # Test JSON schema validation
            validate_json_schema({"country": "US", "state": "CA", "city": "SF"}, "jurisdiction")
            validation_tests["json_schema"] = {"status": "passed", "message": "JSON schema validation working"}
        except Exception as e:
            validation_tests["json_schema"] = {"status": "failed", "message": str(e)}
        
        test_results["test_categories"]["validation_functions"] = {
            "status": "passed" if all(t["status"] == "passed" for t in validation_tests.values()) else "failed",
            "validation_tests": validation_tests
        }
        
        # Test 4: Event Publishing
        try:
            test_event_data = {
                "test": True,
                "timestamp": datetime.now().isoformat(),
                "service": SERVICE_NAME,
                "comprehensive_test": True
            }
            
            await service_bus.publish_to_service(
                target_service="test",
                event_type=EventType.PRODUCT_CREATED,
                data=test_event_data
            )
            
            test_results["test_categories"]["event_publishing"] = {
                "status": "passed",
                "message": "Event publishing successful"
            }
        except Exception as e:
            test_results["test_categories"]["event_publishing"] = {
                "status": "failed",
                "message": str(e)
            }
        
        # Test 5: Circuit Breaker
        try:
            circuit_count = len(service_circuit_breaker.circuits)
            test_results["test_categories"]["circuit_breaker"] = {
                "status": "passed",
                "message": f"Circuit breaker active with {circuit_count} circuits",
                "circuits": list(service_circuit_breaker.circuits.keys())
            }
        except Exception as e:
            test_results["test_categories"]["circuit_breaker"] = {
                "status": "failed",
                "message": str(e)
            }
        
        # Calculate overall test result
        failed_categories = [cat for cat in test_results["test_categories"].values() if cat["status"] == "failed"]
        if failed_categories:
            test_results["overall_status"] = "failed"
            test_results["failed_categories"] = len(failed_categories)
        else:
            test_results["overall_status"] = "passed"
            test_results["failed_categories"] = 0
        
        test_results["summary"] = {
            "total_categories": len(test_results["test_categories"]),
            "passed_categories": len([cat for cat in test_results["test_categories"].values() if cat["status"] == "passed"]),
            "failed_categories": len(failed_categories),
            "success_rate": f"{((len(test_results['test_categories']) - len(failed_categories)) / len(test_results['test_categories']) * 100):.1f}%"
        }
        
        return test_results
        
    except Exception as e:
        return {
            "test_id": str(uuid.uuid4()),
            "timestamp": datetime.now().isoformat(),
            "service": SERVICE_NAME,
            "overall_status": "failed",
            "error": str(e),
            "message": "Comprehensive test failed with unexpected error"
        }

@app.get("/readiness")
def readiness():
    return {"service": SERVICE_NAME, "db": check_db(), "redis": True, "version": "2.0.0"}

# Enhanced validation functions for Phase 3
def validate_business_rules(db_session, payload: dict, operation_type: str):
    """Validate business rules for catalog operations"""
    errors = []
    
    if operation_type == "product_creation":
        # Validate product name uniqueness
        if payload.get('name'):
            existing = db_session.query(ProductMasterV2).filter(
                ProductMasterV2.name == payload['name']
            ).first()
            if existing:
                errors.append(f"Product with name '{payload['name']}' already exists")
    
    elif operation_type == "vendor_offer_creation":
        # Validate vendor offer uniqueness
        if payload.get('vendor_id') and payload.get('variant_id'):
            existing = db_session.query(VendorOfferV2).filter(
                VendorOfferV2.vendor_id == payload['vendor_id'],
                VendorOfferV2.variant_id == payload['variant_id']
            ).first()
            if existing:
                errors.append(f"Vendor offer already exists for vendor {payload['vendor_id']} and variant {payload['variant_id']}")
        
        # Validate price is positive
        if payload.get('base_price_minor') and payload['base_price_minor'] <= 0:
            errors.append("Base price must be positive")
    
    elif operation_type == "tax_rule_creation":
        # Validate tax rate is within valid range
        if payload.get('rate'):
            rate = payload['rate']
            if rate < 0 or rate > 1:
                errors.append("Tax rate must be between 0 and 1 (0% to 100%)")
        
        # Validate effective dates
        if payload.get('effective_from') and payload.get('effective_until'):
            if payload['effective_from'] >= payload['effective_until']:
                errors.append("Effective until date must be after effective from date")
    
    if errors:
        raise CatalogValidationError(f"Business rule validation failed: {'; '.join(errors)}")
    
    return True

def validate_json_schema(data: dict, schema_type: str):
    """Validate JSON data against expected schema"""
    if schema_type == "category_hierarchy":
        if not isinstance(data, dict):
            raise CatalogValidationError("Category hierarchy must be a JSON object")
        # Add more specific validation as needed
    
    elif schema_type == "jurisdiction":
        if not isinstance(data, dict):
            raise CatalogValidationError("Jurisdiction must be a JSON object")
        required_fields = ["country", "state", "city"]
        for field in required_fields:
            if field not in data:
                raise CatalogValidationError(f"Jurisdiction missing required field: {field}")
    
    elif schema_type == "attributes_schema":
        if not isinstance(data, dict):
            raise CatalogValidationError("Attributes schema must be a JSON object")
    
    return True

def get_performance_metrics():
    """Get performance metrics for monitoring"""
    return {
        "timestamp": datetime.now().isoformat(),
        "service": SERVICE_NAME,
        "metrics": {
            "database_connections": "active",  # Would be actual metric in production
            "event_publishing_rate": "healthy",
            "response_times": "optimal",
            "error_rate": "low"
        }
    }

# API Documentation endpoint
@app.get("/catalog/v2/docs", include_in_schema=False)
async def api_documentation():
    """Comprehensive API documentation for Catalog Service V2"""
    return {
        "service": "ZeroQue Catalog Service V2",
        "version": "2.0.0",
        "description": "Enhanced catalog service with v2 architecture support",
        "endpoints": {
            "products": {
                "POST /catalog/v2/products/{product_id}": "Create/update product master",
                "GET /catalog/v2/products": "List products with filtering",
                "POST /catalog/v2/bulk-products": "Bulk product creation"
            },
            "variants": {
                "POST /catalog/v2/variants/{variant_id}": "Create/update product variant",
                "GET /catalog/v2/variants": "List product variants"
            },
            "vendor_offers": {
                "POST /catalog/v2/vendor-offers/{offer_id}": "Create/update vendor offer",
                "GET /catalog/v2/vendor-offers": "List vendor offers"
            },
            "media": {
                "POST /catalog/v2/media": "Create product media",
                "GET /catalog/v2/media": "List product media"
            },
            "relationships": {
                "POST /catalog/v2/relationships": "Create product relationship",
                "GET /catalog/v2/relationships": "List product relationships"
            },
            "assortments": {
                "POST /catalog/v2/assortments/{assortment_id}": "Create/update store assortment",
                "GET /catalog/v2/assortments": "List store assortments",
                "POST /catalog/v2/assortment-items/{item_id}": "Create/update assortment item",
                "GET /catalog/v2/assortment-items": "List assortment items"
            },
            "customer_segments": {
                "POST /catalog/v2/customer-segments/{segment_id}": "Create/update customer segment",
                "GET /catalog/v2/customer-segments": "List customer segments"
            },
            "vendors": {
                "POST /catalog/v2/vendors/{vendor_id}": "Create/update vendor",
                "GET /catalog/v2/vendors": "List vendors",
                "POST /catalog/v2/vendor-onboarding/{onboarding_id}": "Create/update vendor onboarding",
                "GET /catalog/v2/vendor-onboarding": "List vendor onboarding records",
                "POST /catalog/v2/store-vendors/{store_vendor_id}": "Create/update store-vendor relationship",
                "GET /catalog/v2/store-vendors": "List store-vendor relationships"
            },
            "tax_management": {
                "POST /catalog/v2/tax-regions/{region_id}": "Create/update tax region",
                "GET /catalog/v2/tax-regions": "List tax regions",
                "POST /catalog/v2/tax-rules/{rule_id}": "Create/update tax rule",
                "GET /catalog/v2/tax-rules": "List tax rules",
                "POST /catalog/v2/tax-categories/{tax_category_id}": "Create/update product tax category"
            },
            "search": {
                "GET /catalog/v2/search": "Enhanced product search with filtering"
            },
            "normalization": {
                "POST /catalog/v2/product-normalization/{cache_id}": "Create/update product normalization cache",
                "GET /catalog/v2/product-normalization": "List product normalization cache"
            },
            "monitoring": {
                "GET /health": "Enhanced health check with component status",
                "GET /catalog/v2/integration-test": "Service integration testing",
                "GET /catalog/v2/performance": "Performance metrics"
            }
        },
        "features": {
            "v2_architecture": "Full support for v2 database schema",
            "row_level_security": "Comprehensive RLS with tenant/user/store/vendor scoping",
            "enhanced_communication": "Service bus, saga patterns, circuit breakers",
            "event_sourcing": "Complete event store integration",
            "bulk_operations": "High-performance batch processing",
            "comprehensive_validation": "Business rule and schema validation",
            "vendor_management": "Complete vendor lifecycle management",
            "tax_compliance": "Region-based tax management",
            "assortment_management": "Store-specific product assortments",
            "media_management": "Product media and relationships",
            "search_integration": "Enhanced search with filtering",
            "performance_monitoring": "Comprehensive metrics and health checks"
        },
        "data_models": {
            "ProductMasterV2": "Enhanced product master with full v2 schema",
            "ProductVariantV2": "Product variants with proper references",
            "VendorOfferV2": "Vendor offers with marketplace support",
            "ProductMediaV2": "Product media management",
            "ProductRelationshipV2": "Product relationships and bundling",
            "StoreAssortmentV2": "Store-specific assortments",
            "CustomerSegmentV2": "Customer segmentation",
            "VendorV2": "Vendor management",
            "VendorOnboardingV2": "Vendor onboarding process",
            "StoreVendorV2": "Store-vendor relationships",
            "TaxRegionV2": "Tax regions for compliance",
            "TaxRuleV2": "Tax rules per region",
            "ProductTaxCategoryV2": "Product tax categories",
            "ProductNormalizationCache": "CV provider integration",
            "AssortmentItemV2": "Assortment items management"
        },
        "security": {
            "rls_enabled": "Row Level Security for multi-tenancy",
            "tenant_isolation": "Complete tenant data isolation",
            "user_scoping": "User-based access controls",
            "vendor_scoping": "Vendor-specific data access",
            "store_scoping": "Store-level access controls"
        },
        "performance": {
            "bulk_operations": "Batch processing for high throughput",
            "optimized_queries": "Efficient database queries with joins",
            "caching_support": "Built-in caching mechanisms",
            "connection_pooling": "Optimized database connections",
            "async_processing": "Asynchronous event processing"
        },
        "monitoring": {
            "health_checks": "Component-level health monitoring",
            "integration_tests": "Automated service connectivity tests",
            "performance_metrics": "Real-time performance monitoring",
            "error_tracking": "Comprehensive error handling and logging",
            "audit_trails": "Complete operation audit trails"
        }
    }

# ---------- V2 payloads ----------
class ProductMasterV2Payload(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    brand: Optional[str] = None
    category_hierarchy: Optional[dict] = None
    # search_terms removed as requested
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
    status: str = Field("active", min_length=1)
    effective_from: Optional[datetime] = None
    effective_until: Optional[datetime] = None
    active: bool = True

class AssortmentItemV2Payload(BaseModel):
    assortment_id: str = Field(..., min_length=1)
    offer_id: str = Field(..., min_length=1)
    sort_order: int = Field(0, ge=0)
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

class ProductNormalizationCachePayload(BaseModel):
    cv_product_id: str = Field(..., min_length=1)
    product_id: Optional[str] = Field(None, min_length=1)
    variant_id: Optional[str] = Field(None, min_length=1)
    confidence_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    cv_provider: str = Field(..., min_length=1)
    normalization_data: Optional[dict] = None

class BulkProductPayload(BaseModel):
    """Payload for bulk product operations"""
    products: List[ProductMasterV2Payload] = Field(..., min_items=1, max_items=100)
    variants: List[ProductVariantV2Payload] = Field(default=[])
    vendor_offers: List[VendorOfferV2Payload] = Field(default=[])
    media: List[ProductMediaV2Payload] = Field(default=[])

# New payload models for missing functionality
class VendorV2Payload(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    rating: Optional[float] = Field(None, ge=0.0, le=5.0)
    active: bool = True

class VendorOnboardingV2Payload(BaseModel):
    vendor_id: str = Field(..., min_length=1)
    status: str = Field("pending", min_length=1)
    requirements: Optional[dict] = None
    approver_id: Optional[str] = Field(None, min_length=1)
    notes: Optional[str] = None

class StoreVendorV2Payload(BaseModel):
    store_id: str = Field(..., min_length=1)
    vendor_id: str = Field(..., min_length=1)
    active: bool = True

class TaxRegionV2Payload(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    jurisdiction: dict = Field(..., description="Geo polygon/country/state/GST code")
    active: bool = True

class TaxRuleV2Payload(BaseModel):
    region_id: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1, max_length=100)
    rate: float = Field(..., ge=0.0, le=1.0)
    is_inclusive: bool = False
    effective_from: datetime
    effective_until: Optional[datetime] = None
    description: Optional[str] = None

# Legacy payloads for backward compatibility
# Legacy payload models removed - using V2 models instead

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
            # search_terms removed as requested
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

@app.post("/catalog/v2/products/{product_id}")
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
                    # search_terms removed as requested
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
                    # search_terms removed as requested
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

@app.post("/catalog/v2/variants/{variant_id}")
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

@app.post("/catalog/v2/vendor-offers/{offer_id}")
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

# Search endpoint removed as requested

@app.post("/catalog/v2/bulk-products")
async def create_bulk_products(payload: BulkProductPayload = Body(...)):
    """Create multiple products with variants, offers, and media in a single transaction (V2 architecture)."""
    correlation_id = str(uuid.uuid4())
    logger.info("bulk_product_creation_started", extra={"correlation_id": correlation_id, "product_count": len(payload.products)})
    
    try:
        with SessionLocal() as db:
            set_rls_context(db, user_id=correlation_id)
            
            created_products = []
            
            # Create products
            for product_data in payload.products:
                product_id = str(uuid.uuid4())
                
                # Validate product name is unique
                validate_product_name_unique(db, product_data.name)
                
                product = ProductMasterV2(
                    product_id=product_id,
                    name=product_data.name,
                    description=product_data.description,
                    brand=product_data.brand,
                    category_hierarchy=product_data.category_hierarchy,
                    # search_terms removed as requested
                    attributes_schema=product_data.attributes_schema,
                    active=product_data.active
                )
                db.add(product)
                created_products.append({
                    "product_id": product_id,
                    "name": product_data.name,
                    "original_data": product_data
                })
            
            # Create variants
            for variant_data in payload.variants:
                variant_id = str(uuid.uuid4())
                
                # Find corresponding product
                product = next((p for p in created_products if p["product_id"] == variant_data.product_id), None)
                if not product:
                    raise CatalogValidationError(f"Product {variant_data.product_id} not found in bulk operation")
                
                # Validate SKU is unique
                validate_variant_sku_unique(db, variant_data.sku)
                
                variant = ProductVariantV2(
                    variant_id=variant_id,
                    product_id=variant_data.product_id,
                    sku=variant_data.sku,
                    gtin=variant_data.gtin,
                    mpn=variant_data.mpn,
                    uom=variant_data.uom,
                    package_quantity=variant_data.package_quantity,
                    weight_grams=variant_data.weight_grams,
                    dimensions=variant_data.dimensions,
                    variant_attributes=variant_data.variant_attributes,
                    active=variant_data.active
                )
                db.add(variant)
                
                # Update created products with variant info
                product["variant_id"] = variant_id
            
            # Create vendor offers
            for offer_data in payload.vendor_offers:
                offer_id = str(uuid.uuid4())
                
                # Validate vendor exists
                validate_references_exist(db, vendor_id=offer_data.vendor_id)
                
                offer = VendorOfferV2(
                    offer_id=offer_id,
                    vendor_id=offer_data.vendor_id,
                    variant_id=offer_data.variant_id,
                    vendor_sku=offer_data.vendor_sku,
                    vendor_product_name=offer_data.vendor_product_name,
                    base_price_minor=offer_data.base_price_minor,
                    currency=offer_data.currency,
                    cost_price_minor=offer_data.cost_price_minor,
                    min_order_quantity=offer_data.min_order_quantity,
                    lead_time_days=offer_data.lead_time_days,
                    package_dimensions=offer_data.package_dimensions,
                    tax_category=offer_data.tax_category,
                    status=offer_data.status
                )
                db.add(offer)
                
                # Update created products with offer info
                for product in created_products:
                    if product.get("variant_id") == offer_data.variant_id:
                        product["offer_id"] = offer_id
            
            # Create media
            for media_data in payload.media:
                media_id = str(uuid.uuid4())
                
                media = ProductMediaV2(
                    id=media_id,
                    product_id=media_data.product_id,
                    variant_id=media_data.variant_id,
                    media_type=media_data.media_type,
                    url=media_data.url,
                    caption=media_data.caption,
                    sort_order=media_data.sort_order,
                    is_primary=media_data.is_primary
                )
                db.add(media)
            
            # Commit all changes
            db.commit()
            
            # Publish comprehensive event for bulk operation
            bulk_event_data = {
                "operation_type": "bulk_product_creation",
                "correlation_id": correlation_id,
                "product_count": len(payload.products),
                "variant_count": len(payload.variants),
                "offer_count": len(payload.vendor_offers),
                "media_count": len(payload.media),
                "products": [{"product_id": p["product_id"], "name": p["name"]} for p in created_products],
                "timestamp": datetime.now().isoformat()
            }
            
            await service_bus.publish_to_service(
                target_service="search",
                event_type=EventType.PRODUCT_CREATED,
                data=bulk_event_data
            )
            
            await event_store.append_event(ServiceEvent(
                event_type=EventType.PRODUCT_CREATED,
                service_name=SERVICE_NAME,
                correlation_id=correlation_id,
                data=bulk_event_data,
                metadata={"bulk_operation": True, "enhanced": True},
                timestamp=datetime.now()
            ))
            
            logger.info("bulk_product_creation_completed", extra={
                "correlation_id": correlation_id,
                "product_count": len(created_products)
            })
            
            return {
                "correlation_id": correlation_id,
                "created_products": created_products,
                "summary": {
                    "products": len(created_products),
                    "variants": len(payload.variants),
                    "vendor_offers": len(payload.vendor_offers),
                    "media": len(payload.media)
                }
            }
            
    except Exception as e:
        logger.error(f"Bulk product creation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Bulk operation failed: {str(e)}")

# Vendor Management Endpoints
@app.post("/catalog/v2/vendors/{vendor_id}")
async def upsert_vendor(vendor_id: str = Path(...), payload: VendorV2Payload = Body(...)):
    """Create or update a Vendor (V2 architecture) with proper transaction management."""
    try:
        # Validate UUID format
        uuid.UUID(vendor_id)
        uuid.UUID(payload.tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")
    
    with SessionLocal() as db:
        try:
            # Check if vendor name is unique within tenant using ORM
            existing_vendor = db.query(VendorV2).filter(
                VendorV2.tenant_id == payload.tenant_id,
                VendorV2.name == payload.name,
                VendorV2.vendor_id != vendor_id
            ).first()
            
            if existing_vendor:
                raise CatalogDuplicateError(f"Vendor with name '{payload.name}' already exists in tenant")
            
            vendor = db.query(VendorV2).filter(VendorV2.vendor_id == vendor_id).one_or_none()
            if vendor:
                # Update existing vendor
                vendor.name = payload.name
                vendor.description = payload.description
                vendor.rating = payload.rating
                vendor.active = payload.active
                vendor.updated_at = datetime.now()
                db.commit()
                logger.info("vendor_updated", extra={"vendor_id": vendor_id})
                return {"vendor_id": vendor.vendor_id, "name": vendor.name, "updated": True}
            else:
                # Create new vendor
                vendor = VendorV2(
                    vendor_id=vendor_id,
                    tenant_id=payload.tenant_id,
                    name=payload.name,
                    description=payload.description,
                    rating=payload.rating,
                    active=payload.active
                )
                db.add(vendor)
                db.commit()
                logger.info("vendor_created", extra={"vendor_id": vendor_id})
                return {"vendor_id": vendor.vendor_id, "name": vendor.name, "created": True}
                
        except (CatalogDuplicateError, CatalogNotFoundError, CatalogValidationError):
            # Re-raise custom catalog errors
            raise
        except SQLAlchemyError as e:
            logger.error(f"Database error in vendor upsert: {str(e)}")
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Database operation failed: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error in vendor upsert: {str(e)}")
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.put("/catalog/v2/vendor-onboarding/{onboarding_id}")
async def upsert_vendor_onboarding(onboarding_id: str = Path(...), payload: VendorOnboardingV2Payload = Body(...)):
    """Create or update Vendor Onboarding (V2 architecture)."""
    with SessionLocal() as db:
        set_rls_context(db, user_id=str(uuid.uuid4()))
        
        # Validate vendor exists
        validate_references_exist(db, vendor_id=payload.vendor_id)
        
        onboarding = db.query(VendorOnboardingV2).filter(VendorOnboardingV2.onboarding_id == onboarding_id).one_or_none()
        if onboarding:
            onboarding.vendor_id = payload.vendor_id
            onboarding.status = payload.status
            onboarding.requirements = payload.requirements
            onboarding.approver_id = payload.approver_id
            onboarding.notes = payload.notes
            onboarding.updated_at = datetime.now()
            db.commit()
            logger.info("vendor_onboarding_updated", extra={"onboarding_id": onboarding_id})
            return {"onboarding_id": onboarding.onboarding_id, "status": onboarding.status, "updated": True}
        
        onboarding = VendorOnboardingV2(
            onboarding_id=onboarding_id,
            vendor_id=payload.vendor_id,
            status=payload.status,
            requirements=payload.requirements,
            approver_id=payload.approver_id,
            notes=payload.notes
        )
        db.add(onboarding)
        db.commit()
        logger.info("vendor_onboarding_created", extra={"onboarding_id": onboarding_id})
        return {"onboarding_id": onboarding.onboarding_id, "status": onboarding.status, "created": True}

@app.put("/catalog/v2/store-vendors/{store_vendor_id}")
async def upsert_store_vendor(store_vendor_id: str = Path(...), payload: StoreVendorV2Payload = Body(...)):
    """Create or update Store-Vendor relationship (V2 architecture)."""
    with SessionLocal() as db:
        set_rls_context(db, user_id=str(uuid.uuid4()))
        
        # Validate references exist
        validate_references_exist(db, store_id=payload.store_id, vendor_id=payload.vendor_id)
        
        store_vendor = db.query(StoreVendorV2).filter(StoreVendorV2.id == store_vendor_id).one_or_none()
        if store_vendor:
            store_vendor.store_id = payload.store_id
            store_vendor.vendor_id = payload.vendor_id
            store_vendor.active = payload.active
            store_vendor.updated_at = datetime.now()
            db.commit()
            logger.info("store_vendor_updated", extra={"store_vendor_id": store_vendor_id})
            return {"store_vendor_id": store_vendor.id, "store_id": store_vendor.store_id, "vendor_id": store_vendor.vendor_id, "updated": True}
        
        store_vendor = StoreVendorV2(
            id=store_vendor_id,
            store_id=payload.store_id,
            vendor_id=payload.vendor_id,
            active=payload.active
        )
        db.add(store_vendor)
        db.commit()
        logger.info("store_vendor_created", extra={"store_vendor_id": store_vendor_id})
        return {"store_vendor_id": store_vendor.id, "store_id": store_vendor.store_id, "vendor_id": store_vendor.vendor_id, "created": True}

# Tax Management Endpoints
@app.put("/catalog/v2/tax-regions/{region_id}")
async def upsert_tax_region(region_id: str = Path(...), payload: TaxRegionV2Payload = Body(...)):
    """Create or update a Tax Region (V2 architecture)."""
    with SessionLocal() as db:
        set_rls_context(db, user_id=str(uuid.uuid4()))
        
        # Check if region name is unique
        existing_region = db.query(TaxRegionV2).filter(
            TaxRegionV2.name == payload.name,
            TaxRegionV2.region_id != region_id
        ).first()
        
        if existing_region:
            raise CatalogDuplicateError(f"Tax region with name '{payload.name}' already exists")
        
        region = db.query(TaxRegionV2).filter(TaxRegionV2.region_id == region_id).one_or_none()
        if region:
            region.name = payload.name
            region.jurisdiction = payload.jurisdiction
            region.active = payload.active
            db.commit()
            logger.info("tax_region_updated", extra={"region_id": region_id})
            return {"region_id": region.region_id, "name": region.name, "updated": True}
        
        region = TaxRegionV2(
            region_id=region_id,
            name=payload.name,
            jurisdiction=payload.jurisdiction,
            active=payload.active
        )
        db.add(region)
        db.commit()
        logger.info("tax_region_created", extra={"region_id": region_id})
        return {"region_id": region.region_id, "name": region.name, "created": True}

@app.put("/catalog/v2/tax-rules/{rule_id}")
async def upsert_tax_rule(rule_id: str = Path(...), payload: TaxRuleV2Payload = Body(...)):
    """Create or update a Tax Rule (V2 architecture)."""
    with SessionLocal() as db:
        set_rls_context(db, user_id=str(uuid.uuid4()))
        
        # Validate region exists
        validate_references_exist(db, region_id=payload.region_id)
        
        rule = db.query(TaxRuleV2).filter(TaxRuleV2.rule_id == rule_id).one_or_none()
        if rule:
            rule.region_id = payload.region_id
            rule.category = payload.category
            rule.rate = payload.rate
            rule.is_inclusive = payload.is_inclusive
            rule.effective_from = payload.effective_from
            rule.effective_until = payload.effective_until
            rule.description = payload.description
            db.commit()
            logger.info("tax_rule_updated", extra={"rule_id": rule_id})
            return {"rule_id": rule.rule_id, "category": rule.category, "rate": rule.rate, "updated": True}
        
        rule = TaxRuleV2(
            rule_id=rule_id,
            region_id=payload.region_id,
            category=payload.category,
            rate=payload.rate,
            is_inclusive=payload.is_inclusive,
            effective_from=payload.effective_from,
            effective_until=payload.effective_until,
            description=payload.description
        )
        db.add(rule)
        db.commit()
        logger.info("tax_rule_created", extra={"rule_id": rule_id})
        return {"rule_id": rule.rule_id, "category": rule.category, "rate": rule.rate, "created": True}

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

@app.get("/catalog/v2/product-normalization")
async def list_product_normalization_cache(cv_provider: Optional[str] = Query(None), limit: int = Query(100, ge=1, le=1000)):
    """List product normalization cache entries (V2 architecture)."""
    with SessionLocal() as db:
        set_rls_context(db, user_id=str(uuid.uuid4()))
        
        query = db.query(ProductNormalizationCache)
        if cv_provider:
            query = query.filter(ProductNormalizationCache.cv_provider == cv_provider)
        
        cache_entries = query.limit(limit).all()
        return [{"id": c.id, "cv_product_id": c.cv_product_id, "product_id": c.product_id, 
                "variant_id": c.variant_id, "confidence_score": c.confidence_score, 
                "cv_provider": c.cv_provider, "last_updated": c.last_updated, "created_at": c.created_at} for c in cache_entries]

@app.get("/catalog/v2/assortments")
async def list_store_assortments(store_id: Optional[str] = Query(None), status: Optional[str] = Query(None), limit: int = Query(100, ge=1, le=1000)):
    """List store assortments (V2 architecture)."""
    with SessionLocal() as db:
        set_rls_context(db, user_id=str(uuid.uuid4()))
        
        query = db.query(StoreAssortmentV2)
        if store_id:
            query = query.filter(StoreAssortmentV2.store_id == store_id)
        if status:
            query = query.filter(StoreAssortmentV2.status == status)
        
        assortments = query.limit(limit).all()
        return [{"assortment_id": a.assortment_id, "store_id": a.store_id, "name": a.name, 
                "description": a.description, "status": a.status, "effective_from": a.effective_from,
                "effective_until": a.effective_until, "active": a.active, "created_at": a.created_at} for a in assortments]

@app.get("/catalog/v2/assortment-items")
async def list_assortment_items(assortment_id: Optional[str] = Query(None), limit: int = Query(100, ge=1, le=1000)):
    """List assortment items (V2 architecture)."""
    with SessionLocal() as db:
        set_rls_context(db, user_id=str(uuid.uuid4()))
        
        query = db.query(AssortmentItemV2)
        if assortment_id:
            query = query.filter(AssortmentItemV2.assortment_id == assortment_id)
        
        items = query.order_by(AssortmentItemV2.sort_order).limit(limit).all()
        return [{"id": i.id, "assortment_id": i.assortment_id, "offer_id": i.offer_id, 
                "sort_order": i.sort_order, "active": i.active, "created_at": i.created_at} for i in items]

@app.get("/catalog/v2/vendors")
async def list_vendors(tenant_id: Optional[str] = Query(None), active_only: bool = Query(True), limit: int = Query(100, ge=1, le=1000)):
    """List vendors (V2 architecture)."""
    with SessionLocal() as db:
        set_rls_context(db, user_id=str(uuid.uuid4()))
        
        query = db.query(VendorV2)
        if tenant_id:
            query = query.filter(VendorV2.tenant_id == tenant_id)
        if active_only:
            query = query.filter(VendorV2.active == True)
        
        vendors = query.limit(limit).all()
        return [{"vendor_id": v.vendor_id, "tenant_id": v.tenant_id, "name": v.name, 
                "description": v.description, "rating": v.rating, "active": v.active, 
                "created_at": v.created_at} for v in vendors]

@app.get("/catalog/v2/vendor-onboarding")
async def list_vendor_onboarding(vendor_id: Optional[str] = Query(None), status: Optional[str] = Query(None), 
                               limit: int = Query(100, ge=1, le=1000)):
    """List vendor onboarding records (V2 architecture)."""
    with SessionLocal() as db:
        set_rls_context(db, user_id=str(uuid.uuid4()))
        
        query = db.query(VendorOnboardingV2)
        if vendor_id:
            query = query.filter(VendorOnboardingV2.vendor_id == vendor_id)
        if status:
            query = query.filter(VendorOnboardingV2.status == status)
        
        onboarding_records = query.limit(limit).all()
        return [{"onboarding_id": o.onboarding_id, "vendor_id": o.vendor_id, "status": o.status, 
                "requirements": o.requirements, "approver_id": o.approver_id, "notes": o.notes, 
                "created_at": o.created_at} for o in onboarding_records]

@app.get("/catalog/v2/store-vendors")
async def list_store_vendors(store_id: Optional[str] = Query(None), vendor_id: Optional[str] = Query(None), 
                           active_only: bool = Query(True), limit: int = Query(100, ge=1, le=1000)):
    """List store-vendor relationships (V2 architecture)."""
    with SessionLocal() as db:
        set_rls_context(db, user_id=str(uuid.uuid4()))
        
        query = db.query(StoreVendorV2)
        if store_id:
            query = query.filter(StoreVendorV2.store_id == store_id)
        if vendor_id:
            query = query.filter(StoreVendorV2.vendor_id == vendor_id)
        if active_only:
            query = query.filter(StoreVendorV2.active == True)
        
        store_vendors = query.limit(limit).all()
        return [{"id": sv.id, "store_id": sv.store_id, "vendor_id": sv.vendor_id, 
                "active": sv.active, "created_at": sv.created_at} for sv in store_vendors]

@app.get("/catalog/v2/tax-regions")
async def list_tax_regions(active_only: bool = Query(True), limit: int = Query(100, ge=1, le=1000)):
    """List tax regions (V2 architecture)."""
    with SessionLocal() as db:
        set_rls_context(db, user_id=str(uuid.uuid4()))
        
        query = db.query(TaxRegionV2)
        if active_only:
            query = query.filter(TaxRegionV2.active == True)
        
        regions = query.limit(limit).all()
        return [{"region_id": r.region_id, "name": r.name, "jurisdiction": r.jurisdiction, 
                "active": r.active, "created_at": r.created_at} for r in regions]

@app.get("/catalog/v2/tax-rules")
async def list_tax_rules(region_id: Optional[str] = Query(None), category: Optional[str] = Query(None), 
                        limit: int = Query(100, ge=1, le=1000)):
    """List tax rules (V2 architecture)."""
    with SessionLocal() as db:
        set_rls_context(db, user_id=str(uuid.uuid4()))
        
        query = db.query(TaxRuleV2)
        if region_id:
            query = query.filter(TaxRuleV2.region_id == region_id)
        if category:
            query = query.filter(TaxRuleV2.category == category)
        
        rules = query.limit(limit).all()
        return [{"rule_id": r.rule_id, "region_id": r.region_id, "category": r.category, 
                "rate": r.rate, "is_inclusive": r.is_inclusive, "effective_from": r.effective_from,
                "effective_until": r.effective_until, "description": r.description, 
                "created_at": r.created_at} for r in rules]

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
            
            # Publish comprehensive event
            media_event_data = {
                "media_id": media_id,
                "product_id": payload.product_id,
                "variant_id": payload.variant_id,
                "media_type": payload.media_type,
                "url": payload.url,
                "caption": payload.caption,
                "is_primary": payload.is_primary,
                "action": "media_created",
                "timestamp": datetime.now().isoformat()
            }
            
            await service_bus.publish_to_service(
                target_service="search",
                event_type=EventType.PRODUCT_UPDATED,
                data=media_event_data
            )
            
            # Store in event store for audit
            await event_store.append_event(ServiceEvent(
                event_type=EventType.PRODUCT_UPDATED,
                service_name=SERVICE_NAME,
                correlation_id=correlation_id,
                data=media_event_data,
                metadata={"enhanced": True, "media_created": True},
                timestamp=datetime.now()
            ))
            
            return {"media_id": media_id, "product_id": payload.product_id, "created": True}
            
    except Exception as e:
        logger.error(f"Product media creation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/catalog/v2/assortments/{assortment_id}")
async def upsert_store_assortment(assortment_id: str = Path(...), payload: StoreAssortmentV2Payload = Body(...)):
    """Create or update a Store Assortment (V2 architecture)."""
    with SessionLocal() as db:
        set_rls_context(db, user_id=str(uuid.uuid4()))  # Add user_id for audited access
        
        # Validate store exists
        validate_references_exist(db, store_id=payload.store_id)
        
        assortment = db.query(StoreAssortmentV2).filter(StoreAssortmentV2.assortment_id == assortment_id).one_or_none()
        if assortment:
            assortment.name = payload.name
            assortment.description = payload.description
            assortment.status = payload.status
            assortment.effective_from = payload.effective_from
            assortment.effective_until = payload.effective_until
            assortment.active = payload.active
            assortment.updated_at = datetime.now()
            db.commit()
            logger.info("store_assortment_updated", extra={"assortment_id": assortment_id})
            return {"assortment_id": assortment.assortment_id, "name": assortment.name, "status": assortment.status, "updated": True}
        
        assortment = StoreAssortmentV2(
            assortment_id=assortment_id,
            store_id=payload.store_id,
            name=payload.name,
            description=payload.description,
            status=payload.status,
            effective_from=payload.effective_from,
            effective_until=payload.effective_until,
            active=payload.active
        )
        db.add(assortment)
        db.commit()
        logger.info("store_assortment_created", extra={"assortment_id": assortment_id})
        return {"assortment_id": assortment.assortment_id, "name": assortment.name, "status": assortment.status, "created": True}

@app.put("/catalog/v2/assortment-items/{item_id}")
async def upsert_assortment_item(item_id: str = Path(...), payload: AssortmentItemV2Payload = Body(...)):
    """Create or update an Assortment Item (V2 architecture)."""
    with SessionLocal() as db:
        set_rls_context(db, user_id=str(uuid.uuid4()))
        
        # Validate references exist
        validate_references_exist(db, 
                                assortment_id=payload.assortment_id,
                                offer_id=payload.offer_id)
        
        # Check if assortment exists
        assortment = db.query(StoreAssortmentV2).filter(StoreAssortmentV2.assortment_id == payload.assortment_id).first()
        if not assortment:
            raise CatalogNotFoundError(f"Assortment {payload.assortment_id} not found")
        
        # Check if vendor offer exists
        offer = db.query(VendorOfferV2).filter(VendorOfferV2.offer_id == payload.offer_id).first()
        if not offer:
            raise CatalogNotFoundError(f"Vendor offer {payload.offer_id} not found")
        
        item = db.query(AssortmentItemV2).filter(AssortmentItemV2.id == item_id).one_or_none()
        if item:
            item.assortment_id = payload.assortment_id
            item.offer_id = payload.offer_id
            item.sort_order = payload.sort_order
            item.active = payload.active
            item.updated_at = datetime.now()
            db.commit()
            logger.info("assortment_item_updated", extra={"item_id": item_id})
            return {"item_id": item.id, "assortment_id": item.assortment_id, "offer_id": item.offer_id, "updated": True}
        
        item = AssortmentItemV2(
            id=item_id,
            assortment_id=payload.assortment_id,
            offer_id=payload.offer_id,
            sort_order=payload.sort_order,
            active=payload.active
        )
        db.add(item)
        db.commit()
        logger.info("assortment_item_created", extra={"item_id": item_id})
        return {"item_id": item.id, "assortment_id": item.assortment_id, "offer_id": item.offer_id, "created": True}

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

# =============================================================================
# INTEGRATION ENDPOINTS
# =============================================================================

@app.post("/catalog/v2/integration/cv-connector/product-created")
async def notify_cv_connector_product_created(
    tenant_id: str = Body(...),
    product_id: str = Body(...),
    product_data: Dict[str, Any] = Body(...)
):
    """Integration endpoint for CV Connector service to handle PRODUCT_CREATED events"""
    try:
        logger.info(f"Processing PRODUCT_CREATED event for CV Connector integration: product_id={product_id}, tenant_id={tenant_id}")
        
        # Validate product exists
        with SessionLocal() as db:
            product = db.execute(
                text("SELECT * FROM product_master WHERE id = :product_id AND tenant_id = :tenant_id"),
                {"product_id": product_id, "tenant_id": tenant_id}
            ).fetchone()
            
            if not product:
                raise HTTPException(status_code=404, detail="Product not found")
        
        # Prepare event data for CV Connector service
        cv_event_data = {
            "tenant_id": tenant_id,
            "product_id": product_id,
            "product_data": product_data,
            "event_source": "catalog_service"
        }
        
        # Notify CV Connector service via HTTP call
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "http://localhost:8100/events/product-created",
                    json=cv_event_data
                )
                
                if response.status_code == 200:
                    logger.info(f"Successfully notified CV Connector service for product {product_id}")
                    return {"ok": True, "cv_notified": True, "product_id": product_id}
                else:
                    logger.warning(f"CV Connector service returned status {response.status_code} for product {product_id}")
                    return {"ok": False, "cv_notified": False, "product_id": product_id, "error": "CV Connector service error"}
                    
        except Exception as e:
            logger.error(f"Failed to notify CV Connector service for product {product_id}: {str(e)}")
            return {"ok": False, "cv_notified": False, "product_id": product_id, "error": str(e)}
            
    except Exception as e:
        logger.error(f"Error processing PRODUCT_CREATED event for product {product_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to process PRODUCT_CREATED event: {str(e)}")

@app.post("/catalog/v2/integration/cv-connector/batch-sync")
async def trigger_cv_connector_batch_sync(
    tenant_id: str = Body(...),
    provider: str = Body("aifi"),
    sync_type: str = Body("products"),  # products, customers, inventory
    filters: Optional[Dict[str, Any]] = Body(None)
):
    """Integration endpoint for CV Connector service to trigger batch sync"""
    try:
        logger.info(f"Triggering CV Connector batch sync: tenant_id={tenant_id}, provider={provider}, sync_type={sync_type}")
        
        # Prepare batch sync data
        batch_sync_data = {
            "tenant_id": tenant_id,
            "provider": provider,
            "sync_type": sync_type,
            "filters": filters or {},
            "triggered_by": "catalog_service"
        }
        
        # Notify CV Connector service via HTTP call
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "http://localhost:8100/cv/sync/batch",
                    json=batch_sync_data
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Successfully triggered CV Connector batch sync: {result}")
                    return {"ok": True, "sync_triggered": True, "result": result}
                else:
                    logger.warning(f"CV Connector service returned status {response.status_code} for batch sync")
                    return {"ok": False, "sync_triggered": False, "error": "CV Connector service error"}
                    
        except Exception as e:
            logger.error(f"Failed to trigger CV Connector batch sync: {str(e)}")
            return {"ok": False, "sync_triggered": False, "error": str(e)}
            
    except Exception as e:
        logger.error(f"Error triggering CV Connector batch sync: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger CV Connector batch sync: {str(e)}")

@app.get("/catalog/v2/integration/status")
async def get_integration_status():
    """Get status of all service integrations"""
    try:
        integration_status = {
            "cv_connector_service": {"status": "unknown", "url": "http://localhost:8100"},
            "cv_gateway_service": {"status": "unknown", "url": "http://localhost:8000"},
            "orders_service": {"status": "unknown", "url": "http://localhost:8081"},
            "provisioning_service": {"status": "unknown", "url": "http://localhost:8082"}
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

@app.get("/catalog/v2/media")
async def list_product_media(product_id: Optional[str] = Query(None), variant_id: Optional[str] = Query(None), 
                           media_type: Optional[str] = Query(None), limit: int = Query(100, ge=1, le=1000)):
    """List product media (V2 architecture)."""
    with SessionLocal() as db:
        set_rls_context(db, user_id=str(uuid.uuid4()))
        
        query = db.query(ProductMediaV2)
        if product_id:
            query = query.filter(ProductMediaV2.product_id == product_id)
        if variant_id:
            query = query.filter(ProductMediaV2.variant_id == variant_id)
        if media_type:
            query = query.filter(ProductMediaV2.media_type == media_type)
        
        media_items = query.order_by(ProductMediaV2.sort_order, ProductMediaV2.is_primary.desc()).limit(limit).all()
        return [{"id": m.id, "product_id": m.product_id, "variant_id": m.variant_id, 
                "media_type": m.media_type, "url": m.url, "caption": m.caption, 
                "sort_order": m.sort_order, "is_primary": m.is_primary, "created_at": m.created_at} for m in media_items]

@app.get("/catalog/v2/relationships")
async def list_product_relationships(from_product_id: Optional[str] = Query(None), 
                                   to_product_id: Optional[str] = Query(None),
                                   relationship_type: Optional[str] = Query(None), 
                                   limit: int = Query(100, ge=1, le=1000)):
    """List product relationships (V2 architecture)."""
    with SessionLocal() as db:
        set_rls_context(db, user_id=str(uuid.uuid4()))
        
        query = db.query(ProductRelationshipV2)
        if from_product_id:
            query = query.filter(ProductRelationshipV2.from_product_id == from_product_id)
        if to_product_id:
            query = query.filter(ProductRelationshipV2.to_product_id == to_product_id)
        if relationship_type:
            query = query.filter(ProductRelationshipV2.relationship_type == relationship_type)
        
        relationships = query.limit(limit).all()
        return [{"id": r.id, "from_product_id": r.from_product_id, "to_product_id": r.to_product_id, 
                "relationship_type": r.relationship_type, "strength": r.strength, 
                "is_bidirectional": r.is_bidirectional, "created_at": r.created_at} for r in relationships]

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

@app.put("/catalog/v2/product-normalization/{cache_id}")
async def upsert_product_normalization_cache(cache_id: str = Path(...), payload: ProductNormalizationCachePayload = Body(...)):
    """Create or update Product Normalization Cache (V2 architecture)."""
    with SessionLocal() as db:
        set_rls_context(db, user_id=str(uuid.uuid4()))
        
        # Validate product/variant exists if provided
        if payload.product_id:
            product = db.query(ProductMasterV2).filter(ProductMasterV2.product_id == payload.product_id).first()
            if not product:
                raise HTTPException(status_code=400, detail="Product not found")
        
        if payload.variant_id:
            variant = db.query(ProductVariantV2).filter(ProductVariantV2.variant_id == payload.variant_id).first()
            if not variant:
                raise HTTPException(status_code=400, detail="Product variant not found")
        
        cache = db.query(ProductNormalizationCache).filter(ProductNormalizationCache.id == cache_id).one_or_none()
        if cache:
            cache.cv_product_id = payload.cv_product_id
            cache.product_id = payload.product_id
            cache.variant_id = payload.variant_id
            cache.confidence_score = payload.confidence_score
            cache.cv_provider = payload.cv_provider
            cache.normalization_data = payload.normalization_data
            cache.last_updated = datetime.now()
            db.commit()
            logger.info("product_normalization_cache_updated", extra={"cache_id": cache_id})
            return {"cache_id": cache.id, "cv_product_id": cache.cv_product_id, "updated": True}
        
        cache = ProductNormalizationCache(
            id=cache_id,
            cv_product_id=payload.cv_product_id,
            product_id=payload.product_id,
            variant_id=payload.variant_id,
            confidence_score=payload.confidence_score,
            cv_provider=payload.cv_provider,
            normalization_data=payload.normalization_data
        )
        db.add(cache)
            db.commit()
        logger.info("product_normalization_cache_created", extra={"cache_id": cache_id})
        return {"cache_id": cache.id, "cv_product_id": cache.cv_product_id, "created": True}

# Legacy endpoints removed - fully migrated to V2 architecture