from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, ForeignKey, BigInteger, func
from sqlalchemy.dialects.postgresql import UUID
import uuid


Base = declarative_base()
# SQLAlchemy Models - Matching actual database schema
class ApprovalChain(Base):
    """Approval Chain: Workflow templates for approval processes"""
    __tablename__ = "approval_chains"

    chain_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    chain_type = Column(String(50), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True)


class ApprovalChainStep(Base):
    """Approval Chain Step: Individual steps in an approval chain"""
    __tablename__ = "approval_chain_steps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    approval_chain_id = Column(UUID(as_uuid=True), nullable=False)
    step_number = Column(Integer, nullable=False)
    approver_role = Column(Text, nullable=False)
    approver_scope = Column(String(50), nullable=False)
    escalation_after_hours = Column(Integer, nullable=True)
    is_required = Column(Boolean, nullable=False, default=True)


class ApprovalRequest(Base):
    """Approval Request: Individual approval requests"""
    __tablename__ = "approval_requests_new"

    request_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_number = Column(String(50), nullable=False, unique=True)
    chain_id = Column(UUID(as_uuid=True), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)  # Added for tenant isolation
    request_type = Column(String(50), nullable=False)
    request_data = Column(Text, nullable=False)  # JSONB stored as text
    requested_by = Column(UUID(as_uuid=True), nullable=False)
    request_status = Column(String(20), nullable=False, default='pending')
    current_step_id = Column(UUID(as_uuid=True), nullable=True)
    current_step_number = Column(Integer, nullable=False, default=1)  # Added for workflow tracking
    total_amount_minor = Column(BigInteger, nullable=True)
    currency = Column(String(3), nullable=True)
    due_date = Column(DateTime(timezone=True), nullable=True)
    completed_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    approvers = relationship("ApprovalRequestApprover", back_populates="request")


class ApprovalRequestApprover(Base):
    """Approval Request Approver: Tracks individual approver responses"""
    __tablename__ = "approval_request_approvers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey('approval_requests_new.request_id'), nullable=False)
    approver_user_id = Column(UUID(as_uuid=True), nullable=False)
    approver_role = Column(String(100), nullable=False)
    step_number = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default='pending')  # pending, approved, denied, skipped
    notes = Column(Text, nullable=True)
    responded_at = Column(DateTime(timezone=True), nullable=True)
    escalation_sent = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    request = relationship("ApprovalRequest", back_populates="approvers")


class OutboxEvent(Base):
    """Outbox Event: For reliable event publishing"""
    __tablename__ = "outbox_events"

    event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(String(100), nullable=False)
    aggregate_id = Column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    event_data = Column(Text, nullable=False)  # JSONB stored as text
    event_version = Column(Integer, nullable=False, default=1)
    event_timestamp = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    status = Column(String(20), nullable=False, default='pending')
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    """Audit Log: Security and access logging"""
    __tablename__ = "audit_logs"

    log_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    table_name = Column(String(100), nullable=False)
    record_id = Column(UUID(as_uuid=True), nullable=False)
    operation = Column(String(20), nullable=False)
    old_values = Column(Text, nullable=True)  # JSONB stored as text
    new_values = Column(Text, nullable=True)  # JSONB stored as text
    changed_by = Column(UUID(as_uuid=True), nullable=True)
    changed_at = Column(DateTime(timezone=True), server_default=func.now())
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)