import uuid

from sqlalchemy import create_engine, text, Column, String, Integer, Numeric, DateTime, Boolean, Text, ForeignKey, JSON, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base

# =============================================================================
# MODELS (SQLAlchemy)
# =============================================================================

Base = declarative_base()

class ProductV2(Base):
    """Product entity for V2 architecture - Phase 3 Enhanced"""
    __tablename__ = "products_v2"

    product_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    vendor_id = Column(UUID(as_uuid=True), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    sku = Column(String(100), nullable=False)
    barcode = Column(String(100), nullable=True)  # Phase 3: Barcode for CV linkage
    category_id = Column(UUID(as_uuid=True), nullable=True)
    brand = Column(String(100), nullable=True)
    base_price_minor = Column(Integer, nullable=False, default=0)
    currency = Column(String(3), nullable=False, default='GBP')
    weight_grams = Column(Integer, nullable=True)
    dimensions_cm = Column(JSON, nullable=True)  # {"length": 10, "width": 5, "height": 3}
    is_active = Column(Boolean, nullable=False, default=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ProductVariantV2(Base):
    """Product variant entity"""
    __tablename__ = "product_variants_v2"

    variant_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey('products_v2.product_id'), nullable=False)
    name = Column(String(200), nullable=False)
    sku = Column(String(100), nullable=False)
    price_adjustment_minor = Column(Integer, nullable=False, default=0)
    attributes = Column(JSON, nullable=True)  # {"color": "red", "size": "L"}
    is_active = Column(Boolean, nullable=False, default=True)


# Phase 3: Bundle/Kit Models
class ProductBundleV2(Base):
    """Product bundle/kit entity - Phase 3"""
    __tablename__ = "product_bundles_v2"

    bundle_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    bundle_sku = Column(String(100), nullable=False)
    bundle_type = Column(String(50), nullable=False)  # "kit", "bundle", "package"
    base_price_minor = Column(Integer, nullable=False, default=0)
    currency = Column(String(3), nullable=False, default='GBP')
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class BundleComponentV2(Base):
    """Bundle component mapping - Phase 3"""
    __tablename__ = "bundle_components_v2"

    component_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bundle_id = Column(UUID(as_uuid=True), ForeignKey('product_bundles_v2.bundle_id'), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey('products_v2.product_id'), nullable=False)
    variant_id = Column(UUID(as_uuid=True), ForeignKey('product_variants_v2.variant_id'), nullable=True)
    quantity = Column(Integer, nullable=False, default=1)
    price_override_minor = Column(Integer, nullable=True)  # Override price for this component
    is_required = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class CategoryV2(Base):
    """Product category entity"""
    __tablename__ = "categories_v2"

    category_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    parent_category_id = Column(UUID(as_uuid=True), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class OutboxEvent(Base):
    """Outbox pattern for event publishing"""
    __tablename__ = "outbox_events"

    event_id = Column(String(50), primary_key=True)
    event_type = Column(String(50), nullable=False)
    aggregate_id = Column(UUID(as_uuid=True), nullable=False)
    event_data = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default='pending')
    retry_count = Column(Integer, nullable=False, default=0)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    """Audit logging"""
    __tablename__ = "audit_logs"

    log_id = Column(String(50), primary_key=True)
    aggregate_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(String(50), nullable=False)
    action = Column(String(20), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    changes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())