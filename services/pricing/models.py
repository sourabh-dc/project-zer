import uuid
from sqlalchemy import Column, String, Integer, Numeric, DateTime, Boolean, Text, ForeignKey, JSON, \
    func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base

# =============================================================================
# MODELS (SQLAlchemy)
# =============================================================================

Base = declarative_base()

class PricebookV2(Base):
    """Pricebook entity for V2 architecture"""
    __tablename__ = "pricebooks_v2"

    pricebook_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    currency = Column(String(3), nullable=False, default='GBP')
    is_active = Column(Boolean, nullable=False, default=True)
    custom_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PriceRuleV2(Base):
    """Price rule entity"""
    __tablename__ = "price_rules_v2"

    rule_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pricebook_id = Column(UUID(as_uuid=True), ForeignKey('pricebooks_v2.pricebook_id'), nullable=False)
    product_id = Column(UUID(as_uuid=True), nullable=True)
    variant_id = Column(UUID(as_uuid=True), nullable=True)
    rule_type = Column(String(20), nullable=False)  # fixed, percentage, formula
    rule_value = Column(Numeric(10, 2), nullable=False)
    min_quantity = Column(Integer, nullable=True)
    max_quantity = Column(Integer, nullable=True)
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_until = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    custom_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class CalculatedPriceV2(Base):
    """Calculated price cache"""
    __tablename__ = "calculated_prices_v2"

    price_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    product_id = Column(UUID(as_uuid=True), nullable=False)
    variant_id = Column(UUID(as_uuid=True), nullable=True)
    pricebook_id = Column(UUID(as_uuid=True), nullable=False)
    base_price_minor = Column(Integer, nullable=False)
    calculated_price_minor = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    calculated_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)

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