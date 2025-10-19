import uuid
from sqlalchemy import Column, String, Boolean, DateTime, Integer, JSON, ForeignKey, func, text, Text
from sqlalchemy.dialects.postgresql import UUID as SQLUUID
from sqlalchemy.orm import declarative_base


Base = declarative_base()

# Models
class TenantV2(Base):
    __tablename__ = "tenants_new"
    tenant_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True)
    type = Column(String(50), default="customer")
    active = Column(Boolean, default=True)
    tenant_metadata = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class SiteV2(Base):
    __tablename__ = "sites_new"
    site_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants_new.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    site_type = Column(String(50), default="retail")
    geo = Column(JSON)
    device_metadata = Column(JSON)  # Phase 2: Site Registry - tracks cameras, sensors, entry devices
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class StoreV2(Base):
    __tablename__ = "stores_new"
    store_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id = Column(SQLUUID(as_uuid=True), ForeignKey("sites_new.site_id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    store_type = Column(String(50), default="retail")
    geo = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class UserV2(Base):
    __tablename__ = "users_new"
    user_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants_new.tenant_id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False)
    display_name = Column(String(255), nullable=False)
    active = Column(Boolean, default=True)
    api_key = Column(String(255), unique=True, index=True)
    api_key_created_at = Column(DateTime(timezone=True))
    permissions = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class RoleV2(Base):
    __tablename__ = "roles_new"
    role_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(100), unique=True, nullable=False)
    name = Column(String(255))
    description = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class VendorV2(Base):
    __tablename__ = "vendors_new"
    vendor_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), ForeignKey("tenants_new.tenant_id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    contact_email = Column(String(255))
    description = Column(String(500))
    status = Column(String(50), default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class CostCentre(Base):
    __tablename__ = "cost_centres"
    cost_centre_id = Column(String(100), primary_key=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    budget_minor = Column(Integer, default=0)
    spent_minor = Column(Integer, default=0)
    currency_code = Column(String(3), default="GBP")
    status = Column(String(50), default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    event_id = Column(String(255), primary_key=True)
    event_type = Column(String(100), nullable=False, index=True)
    aggregate_id = Column(String(255), nullable=False)
    event_data = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    retry_count = Column(Integer, nullable=False, default=0)
    published_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AuditLog(Base):
    __tablename__ = "audit_logs"
    log_id = Column(String(255), primary_key=True)
    aggregate_id = Column(String(255), nullable=False, index=True)
    user_id = Column(String(255))
    action = Column(String(100), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(255), nullable=False)
    changes = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

