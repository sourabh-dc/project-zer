from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, String, Integer, DateTime, BigInteger, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
import uuid
# =============================================================================
# DATABASE MODELS
# =============================================================================

Base = declarative_base()


class LedgerEntryNew(Base):
    """Enhanced ledger entry with v4.1 features"""
    __tablename__ = "ledger_entries_new"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    vendor_id = Column(UUID(as_uuid=True), nullable=True)
    account = Column(String(100), nullable=False)
    entry_type = Column(String(20), nullable=False)  # debit/credit
    amount_minor = Column(BigInteger, nullable=False)
    currency = Column(String(3), nullable=False)
    cost_centre_id = Column(UUID(as_uuid=True), nullable=True)
    site_id = Column(UUID(as_uuid=True), nullable=True)
    store_id = Column(UUID(as_uuid=True), nullable=True)
    reference_type = Column(String(50), nullable=True)  # order, invoice, approval
    reference_id = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    entry_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)


class AccountBalanceNew(Base):
    """Precomputed account balances for performance"""
    __tablename__ = "account_balances_new"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    account = Column(String(100), nullable=False)
    currency = Column(String(3), nullable=False)
    balance_minor = Column(BigInteger, nullable=False, server_default='0')
    last_updated = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OutboxEvent(Base):
    """Outbox pattern for reliable event publishing"""
    __tablename__ = "outbox_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True)
    event_type = Column(String(100), nullable=False)
    event_data = Column(JSONB, nullable=False)
    status = Column(String(20), nullable=False, default='pending')  # pending, published, failed
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    """Audit trail for all operations - Phase 7: Enhanced for compliance"""
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(String(255), nullable=True)
    details = Column(JSONB, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Phase 7: Enhanced audit fields for compliance
    session_id = Column(String(100), nullable=True)
    correlation_id = Column(String(100), nullable=True)
    severity = Column(String(20), nullable=False, default="info")  # info, warning, error, critical
    category = Column(String(50), nullable=False, default="system")  # system, security, business, compliance
    retention_until = Column(DateTime(timezone=True), nullable=True)  # For data retention policies


class IdempotencyRecord(Base):
    """Idempotency records to prevent duplicate operations"""
    __tablename__ = "idempotency_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    idempotency_key = Column(String(255), nullable=False, unique=True, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    request_hash = Column(String(255), nullable=False)  # Hash of request body
    response_data = Column(JSONB, nullable=False)  # Cached response
    status_code = Column(Integer, nullable=False)  # HTTP status code
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)  # Auto-expire after 24 hours