from sqlalchemy import Column, String, Integer, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.types import DateTime, Text
import uuid

# =============================================================================
# DATABASE MODELS
# =============================================================================
Base = declarative_base()
class Device(Base):
    """Phase 2: Device registry for hardware monitoring"""
    __tablename__ = "devices"

    device_id = Column(String(100), primary_key=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    site_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    device_type = Column(String(50), nullable=False)  # camera, sensor, entry_device
    device_name = Column(String(255), nullable=False)
    zone = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default='online')  # online, offline, error, maintenance
    health_score = Column(Integer, nullable=True)  # 0-100
    last_heartbeat = Column(DateTime(timezone=True), nullable=True)
    device_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class DeviceStatusLog(Base):
    """Phase 2: Device status change logs"""
    __tablename__ = "device_status_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(String(100), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    status = Column(String(20), nullable=False)
    health_score = Column(Integer, nullable=True)
    details = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DeviceAlert(Base):
    """Phase 2: Device alerts for offline/error states"""
    __tablename__ = "device_alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(String(100), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    alert_type = Column(String(50), nullable=False)  # offline, error, low_health
    severity = Column(String(20), nullable=False, default='warning')  # info, warning, critical
    message = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default='open')  # open, acknowledged, resolved
    acknowledged_by = Column(String(255), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


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