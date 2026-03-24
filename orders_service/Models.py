from datetime import datetime
from typing import Any, Dict, Optional
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UUID,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    email = Column(String, nullable=False)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)


class Role(Base):
    __tablename__ = "roles"
    role_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(100), unique=True, nullable=False, index=True)


class UserRole(Base):
    __tablename__ = "user_roles"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.role_id", ondelete="CASCADE"), nullable=False, index=True)


class Permission(Base):
    __tablename__ = "permissions"
    permission_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(150), unique=True, nullable=False, index=True)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_code = Column(String, ForeignKey("roles.code", ondelete="CASCADE"), nullable=False, index=True)
    permission_code = Column(String, ForeignKey("permissions.code", ondelete="CASCADE"), nullable=False, index=True)


class CostCentre(Base):
    __tablename__ = "cost_centres"
    cost_centre_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    code = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, index=True)


class Vendor(Base):
    __tablename__ = "vendors"
    vendor_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Category(Base):
    __tablename__ = "categories"
    category_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class OrgUnit(Base):
    __tablename__ = "org_units"
    org_unit_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parent_org_unit_id = Column(UUID(as_uuid=True), ForeignKey("org_units.org_unit_id"), nullable=True, index=True)
    manager_user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=True)


class UserOrgAssignment(Base):
    __tablename__ = "user_org_assignments"
    assignment_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    org_unit_id = Column(UUID(as_uuid=True), ForeignKey("org_units.org_unit_id", ondelete="CASCADE"), nullable=False, index=True)


class FinancialCalendar(Base):
    __tablename__ = "financial_calendars"
    calendar_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    is_default = Column(Boolean, nullable=False, default=False)


class FinancialYear(Base):
    __tablename__ = "financial_years"
    year_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calendar_id = Column(UUID(as_uuid=True), ForeignKey("financial_calendars.calendar_id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="draft")


class FinancialPeriod(Base):
    __tablename__ = "financial_periods"
    period_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    year_id = Column(UUID(as_uuid=True), ForeignKey("financial_years.year_id", ondelete="CASCADE"), nullable=False, index=True)
    calendar_id = Column(UUID(as_uuid=True), ForeignKey("financial_calendars.calendar_id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    period_number = Column(Integer, nullable=False)
    label = Column(String(50), nullable=False)
    period_type = Column(String(20), nullable=False, default="month")
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)


class CompanyBudgetCap(Base):
    __tablename__ = "company_budget_caps"
    cap_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    year_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    total_budget_minor = Column(BigInteger, nullable=False)
    committed_minor = Column(BigInteger, nullable=False, default=0)
    spent_minor = Column(BigInteger, nullable=False, default=0)
    hard_cap = Column(Boolean, nullable=False, default=False)


class CostCentreBudgetVersion(Base):
    __tablename__ = "cc_budget_versions"
    version_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cost_centre_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    year_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    period_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    budget_minor = Column(BigInteger, nullable=False)
    carry_forward_minor = Column(BigInteger, nullable=False, default=0)
    committed_minor = Column(BigInteger, nullable=False, default=0)
    spent_minor = Column(BigInteger, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="draft", index=True)


class UserBudgetLimit(Base):
    __tablename__ = "user_budget_limits"
    limit_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    cost_centre_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    year_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    period_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    limit_type = Column(String(20), nullable=False, index=True)
    window_type = Column(String(20), nullable=False, index=True)
    limit_amount_minor = Column(BigInteger, nullable=False)
    committed_minor = Column(BigInteger, nullable=False, default=0)
    spent_minor = Column(BigInteger, nullable=False, default=0)
    carry_forward_minor = Column(BigInteger, nullable=False, default=0)
    carry_forward_enabled = Column(Boolean, nullable=False, default=False)
    window_start = Column(Date, nullable=True)
    window_end = Column(Date, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)


class ApprovalPolicy(Base):
    __tablename__ = "approval_policies"
    policy_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    cost_centre_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    routing_mode = Column(String(20), nullable=False, default="hierarchical")
    broadcast_n = Column(Integer, nullable=False, default=3)
    sox_sod_enforced = Column(Boolean, nullable=False, default=True)
    partial_approval_mode = Column(String(20), nullable=False, default="block")
    zero_value_mode = Column(String(20), nullable=False, default="auto")
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    stages = relationship("ApprovalStage", back_populates="policy", order_by="ApprovalStage.stage_order")


class ApprovalStage(Base):
    __tablename__ = "approval_stages"
    stage_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    policy_id = Column(UUID(as_uuid=True), ForeignKey("approval_policies.policy_id", ondelete="CASCADE"), nullable=False, index=True)
    stage_order = Column(Integer, nullable=False)
    name = Column(String(255), nullable=True)
    parallel_allowed = Column(Boolean, nullable=False, default=False)
    min_approvers = Column(Integer, nullable=False, default=1)
    escalation_timeout_hours = Column(Integer, nullable=True)

    policy = relationship("ApprovalPolicy", back_populates="stages")
    conditions = relationship("ApprovalStageCondition", back_populates="stage")
    approvers = relationship("ApprovalStageApprover", back_populates="stage")


class ApprovalStageCondition(Base):
    __tablename__ = "approval_stage_conditions"
    condition_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stage_id = Column(UUID(as_uuid=True), ForeignKey("approval_stages.stage_id", ondelete="CASCADE"), nullable=False, index=True)
    field = Column(String(50), nullable=False)
    operator = Column(String(10), nullable=False)
    value = Column(JSONB, nullable=False)
    logic = Column(String(5), nullable=False, default="AND")

    stage = relationship("ApprovalStage", back_populates="conditions")


class ApprovalStageApprover(Base):
    __tablename__ = "approval_stage_approvers"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stage_id = Column(UUID(as_uuid=True), ForeignKey("approval_stages.stage_id", ondelete="CASCADE"), nullable=False, index=True)
    approver_type = Column(String(30), nullable=False)
    approver_user_id = Column(UUID(as_uuid=True), nullable=True)
    org_unit_id = Column(UUID(as_uuid=True), nullable=True)
    role_code = Column(String(100), nullable=True)

    stage = relationship("ApprovalStage", back_populates="approvers")


class PurchaseRequest(Base):
    __tablename__ = "purchase_requests"
    request_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    requester_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    cost_centre_id = Column(UUID(as_uuid=True), ForeignKey("cost_centres.cost_centre_id", ondelete="CASCADE"), nullable=False, index=True)
    vendor_id = Column(UUID(as_uuid=True), ForeignKey("vendors.vendor_id", ondelete="SET NULL"), nullable=True, index=True)
    category_id = Column(UUID(as_uuid=True), ForeignKey("categories.category_id", ondelete="SET NULL"), nullable=True, index=True)
    year_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    period_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    reference_number = Column(String(50), nullable=True, index=True)
    description = Column(Text, nullable=True)
    line_items = Column(JSONB, nullable=True)
    amount_minor = Column(BigInteger, nullable=False)
    currency = Column(String(3), nullable=False, default="GBP")
    status = Column(String(30), nullable=False, default="draft", index=True)
    approval_mode = Column(String(20), nullable=True)
    notes = Column(Text, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    approved_by = Column(UUID(as_uuid=True), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    po_issued_at = Column(DateTime(timezone=True), nullable=True)
    po_reference = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    workflow = relationship("ApprovalWorkflow", back_populates="request", uselist=False)


class ApprovalWorkflow(Base):
    __tablename__ = "approval_workflows"
    workflow_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("purchase_requests.request_id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    policy_id = Column(UUID(as_uuid=True), ForeignKey("approval_policies.policy_id", ondelete="SET NULL"), nullable=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    current_stage_order = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default="active", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    request = relationship("PurchaseRequest", back_populates="workflow")
    tasks = relationship("ApprovalTask", back_populates="workflow")


class ApprovalTask(Base):
    __tablename__ = "approval_tasks"
    task_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("approval_workflows.workflow_id", ondelete="CASCADE"), nullable=False, index=True)
    stage_id = Column(UUID(as_uuid=True), ForeignKey("approval_stages.stage_id", ondelete="SET NULL"), nullable=True, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    assignee_user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    stage_order = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    decided_by = Column(UUID(as_uuid=True), nullable=True)
    note = Column(Text, nullable=True)
    escalated_to_task_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    workflow = relationship("ApprovalWorkflow", back_populates="tasks")


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    aggregate_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    aggregate_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    event_type: Mapped[str] = mapped_column(nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(default="pending")
    retry_count: Mapped[int] = mapped_column(default=0)
    max_retries: Mapped[int] = mapped_column(default=3)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


class OutboxEventDelivery(Base):
    __tablename__ = "outbox_event_delivery"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("outbox_events.id"), nullable=False)
    consumer: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    retry_count: Mapped[int] = mapped_column(default=0)
    max_retries: Mapped[int] = mapped_column(default=3)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("event_id", "consumer", name="uq_delivery_event_consumer"),
        Index("idx_delivery_consumer_status", "consumer", "status"),
        Index("idx_delivery_consumer_status_created", "consumer", "status", "created_at"),
    )

