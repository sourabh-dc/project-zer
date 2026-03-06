"""
Policy Engine — Database Models

Tables:
  policies, policy_versions, policy_rules, policy_assignments,
  policy_action_types, policy_decisions
"""
import uuid

from sqlalchemy import (
    Column, String, Boolean, DateTime, Integer, Text, ForeignKey,
    func, Index
)
from sqlalchemy.dialects.postgresql import UUID as SQLUUID, JSONB
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------
class Policy(Base):
    __tablename__ = "policies"

    policy_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=True, index=True)  # NULL = global
    code = Column(String(150), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String(1000), nullable=True)
    policy_type = Column(String(50), nullable=False, index=True)  # entitlement / budget / approval / product / access / vendor
    priority = Column(Integer, nullable=False, default=100)  # lower = evaluated first
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    status = Column(String(20), nullable=False, default="active")  # draft / active / archived

    created_by = Column(SQLUUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    versions = relationship("PolicyVersion", back_populates="policy", cascade="all, delete-orphan",
                            order_by="PolicyVersion.version_number.desc()")
    assignments = relationship("PolicyAssignment", back_populates="policy", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_policies_tenant_code_unique", "tenant_id", "code", unique=True),
    )


# ---------------------------------------------------------------------------
# PolicyVersion  (immutable snapshot of rules)
# ---------------------------------------------------------------------------
class PolicyVersion(Base):
    __tablename__ = "policy_versions"

    version_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    policy_id = Column(SQLUUID(as_uuid=True), ForeignKey("policies.policy_id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False, default=1)
    rules_json = Column(JSONB, nullable=True)  # denormalised copy of rules for fast read
    effective_from = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    effective_until = Column(DateTime(timezone=True), nullable=True)  # NULL = current version
    change_reason = Column(String(500), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    policy = relationship("Policy", back_populates="versions")
    rules = relationship("PolicyRule", back_populates="version", cascade="all, delete-orphan",
                         order_by="PolicyRule.rule_order")


# ---------------------------------------------------------------------------
# PolicyRule
# ---------------------------------------------------------------------------
class PolicyRule(Base):
    __tablename__ = "policy_rules"

    rule_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_id = Column(SQLUUID(as_uuid=True), ForeignKey("policy_versions.version_id", ondelete="CASCADE"), nullable=False, index=True)
    rule_order = Column(Integer, nullable=False, default=0)
    name = Column(String(255), nullable=False)
    condition_expression = Column(Text, nullable=False)
    effect = Column(String(30), nullable=False, default="deny")  # allow / deny / require_approval
    denial_reason = Column(Text, nullable=True)
    approval_chain_id = Column(SQLUUID(as_uuid=True), nullable=True)
    actions = Column(JSONB, nullable=True)  # optional structured actions
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    version = relationship("PolicyVersion", back_populates="rules")


# ---------------------------------------------------------------------------
# PolicyAssignment  (scoping: where/when a policy applies)
# ---------------------------------------------------------------------------
class PolicyAssignment(Base):
    __tablename__ = "policy_assignments"

    assignment_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    policy_id = Column(SQLUUID(as_uuid=True), ForeignKey("policies.policy_id", ondelete="CASCADE"), nullable=False, index=True)
    scope_type = Column(String(30), nullable=False, default="global")  # global / tenant / site / store / org_unit / user
    scope_id = Column(SQLUUID(as_uuid=True), nullable=True)  # NULL for global scope
    action_pattern = Column(String(200), nullable=False, index=True)  # e.g. "order.create", "order.*", "*"
    priority_override = Column(Integer, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_until = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    policy = relationship("Policy", back_populates="assignments")


# ---------------------------------------------------------------------------
# PolicyActionType  (catalog of known actions with schemas)
# ---------------------------------------------------------------------------
class PolicyActionType(Base):
    __tablename__ = "policy_action_types"

    action_type_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    subject_schema = Column(JSONB, nullable=True)
    resource_schema = Column(JSONB, nullable=True)
    category = Column(String(50), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# PolicyDecisionLog  (immutable audit trail)
# ---------------------------------------------------------------------------
class PolicyDecisionLog(Base):
    __tablename__ = "policy_decisions"

    decision_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(SQLUUID(as_uuid=True), nullable=True, index=True)
    action = Column(String(200), nullable=False, index=True)
    subject = Column(JSONB, nullable=False)
    resource = Column(JSONB, nullable=False)
    decision = Column(String(30), nullable=False)  # allow / deny / require_approval
    matched_policies = Column(JSONB, nullable=True)
    reason = Column(Text, nullable=True)
    evaluation_ms = Column(Integer, nullable=True)
    correlation_id = Column(String(100), nullable=True, index=True)
    evaluated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_policy_decisions_tenant_action", "tenant_id", "action"),
    )

