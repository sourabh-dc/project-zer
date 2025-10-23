import uuid
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, JSON, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import UUID


Base = declarative_base()

# =============================================================================
# MODELS (SQLAlchemy)
# =============================================================================

class OrderV2(Base):
    """Order entity for V2 architecture"""
    __tablename__ = "orders_v2"

    order_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    site_id = Column(UUID(as_uuid=True), nullable=True)
    store_id = Column(UUID(as_uuid=True), nullable=True)
    customer_id = Column(UUID(as_uuid=True), nullable=False)
    order_number = Column(String(50), nullable=False, unique=True)
    order_status = Column(String(20), nullable=False, default='pending')
    order_type = Column(String(20), nullable=False, default='purchase')
    total_amount_minor = Column(Integer, nullable=False, default=0)
    currency = Column(String(3), nullable=False, default='GBP')
    payment_status = Column(String(20), nullable=False, default='pending')
    fulfillment_status = Column(String(20), nullable=False, default='pending')
    shipping_address = Column(JSON, nullable=True)
    billing_address = Column(JSON, nullable=True)
    order_metadata = Column(JSON, nullable=True)  # Renamed from metadata to avoid SQLAlchemy conflict
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class OrderItemV2(Base):
    """Order item entity"""
    __tablename__ = "order_items_v2"

    item_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey('orders_v2.order_id'), nullable=False)
    product_id = Column(UUID(as_uuid=True), nullable=False)
    variant_id = Column(UUID(as_uuid=True), nullable=True)
    quantity = Column(Integer, nullable=False)
    unit_price_minor = Column(Integer, nullable=False)
    total_price_minor = Column(Integer, nullable=False)
    item_metadata = Column(JSON, nullable=True)  # Renamed from metadata to avoid SQLAlchemy conflict
    created_at = Column(DateTime(timezone=True), server_default=func.now())


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
    event_version = Column(Integer, nullable=False, default=1)
    max_retries = Column(Integer, nullable=False, default=3)
    last_error = Column(Text, nullable=True)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)


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