"""
Policy Engine Database Models
SQLAlchemy models for policy management and decision logging
"""
from datetime import datetime
from sqlalchemy import (
    Column, String, Boolean, DateTime, Integer, ForeignKey, 
    func, Text, Index, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID as SQLUUID, JSONB
from sqlalchemy.orm import declarative_base, relationship
import uuid

Base = declarative_base()


class Policy(Base):
    """
    Policy definition - a named collection of rules.
    Policies can be global (tenant_id=NULL) or tenant-specific.
    """
    __tablename__ = "policies"

    policy_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=True, index=True)  # NULL = global policy
    
    code = Column(String(100), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Policy categorization
    policy_type = Column(String(50), nullable=False, index=True)  # budget, access, entitlement, approval, product
    
    # Evaluation order - lower priority = evaluated first
    priority = Column(Integer, nullable=False, default=100)
    
    # Status
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    
    # Audit fields
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    created_by = Column(SQLUUID(as_uuid=True), nullable=True)
    
    # Relationships
    versions = relationship("PolicyVersion", back_populates="policy", cascade="all, delete-orphan")
    assignments = relationship("PolicyAssignment", back_populates="policy", cascade="all, delete-orphan")
    
    __table_args__ = (
        UniqueConstraint('tenant_id', 'code', name='uq_policy_tenant_code'),
        Index('ix_policy_type_active', 'policy_type', 'is_active'),
    )


class PolicyVersion(Base):
    """
    Immutable version of a policy's rules.
    Each change creates a new version for audit trail.
    """
    __tablename__ = "policy_versions"

    version_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    policy_id = Column(SQLUUID(as_uuid=True), ForeignKey("policies.policy_id", ondelete="CASCADE"), nullable=False, index=True)
    
    version_number = Column(Integer, nullable=False)
    
    # The rules as JSON (denormalized for quick loading)
    rules_json = Column(JSONB, nullable=False)
    
    # Validity period
    effective_from = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    effective_until = Column(DateTime(timezone=True), nullable=True)  # NULL = current version
    
    # Audit
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by = Column(SQLUUID(as_uuid=True), nullable=True)
    change_reason = Column(Text, nullable=True)
    
    # Relationships
    policy = relationship("Policy", back_populates="versions")
    rules = relationship("PolicyRule", back_populates="version", cascade="all, delete-orphan")
    
    __table_args__ = (
        UniqueConstraint('policy_id', 'version_number', name='uq_policy_version'),
        Index('ix_policy_version_effective', 'policy_id', 'effective_from', 'effective_until'),
    )


class PolicyRule(Base):
    """
    Individual rule within a policy version.
    Rules are evaluated in order and can allow, deny, or require approval.
    """
    __tablename__ = "policy_rules"

    rule_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_id = Column(SQLUUID(as_uuid=True), ForeignKey("policy_versions.version_id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Rule ordering within the policy
    rule_order = Column(Integer, nullable=False, default=0)
    
    # Rule identification
    name = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    
    # The condition expression (evaluated against context)
    # e.g., "subject.budget_remaining < resource.order_total"
    condition_expression = Column(Text, nullable=False)
    
    # What happens when condition matches
    effect = Column(String(20), nullable=False)  # 'allow', 'deny', 'require_approval'
    
    # Human-readable reason (supports template variables)
    # e.g., "Budget exceeded. Available: {subject.budget_remaining}"
    denial_reason = Column(Text, nullable=True)
    
    # If effect is 'require_approval', which approval chain to use
    approval_chain_id = Column(SQLUUID(as_uuid=True), nullable=True)
    
    # Additional actions to trigger (e.g., notifications)
    actions = Column(JSONB, nullable=True)
    
    # Rule can be individually disabled
    is_active = Column(Boolean, nullable=False, default=True)
    
    # Audit
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationships
    version = relationship("PolicyVersion", back_populates="rules")
    
    __table_args__ = (
        Index('ix_rule_version_order', 'version_id', 'rule_order'),
    )


class PolicyAssignment(Base):
    """
    Assigns a policy to a specific scope.
    Determines where/when a policy applies.
    """
    __tablename__ = "policy_assignments"

    assignment_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    policy_id = Column(SQLUUID(as_uuid=True), ForeignKey("policies.policy_id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Scope: where does this policy apply?
    scope_type = Column(String(50), nullable=False, index=True)  # 'global', 'tenant', 'site', 'store', 'org_unit', 'user'
    scope_id = Column(SQLUUID(as_uuid=True), nullable=True, index=True)  # NULL for global scope
    
    # Actions this assignment applies to (supports wildcards)
    # e.g., 'order.*', 'order.create', '*'
    action_pattern = Column(String(100), nullable=False, default='*')
    
    # Override priority for this specific assignment
    priority_override = Column(Integer, nullable=True)
    
    # Status
    is_active = Column(Boolean, nullable=False, default=True)
    
    # Validity period (optional)
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_until = Column(DateTime(timezone=True), nullable=True)
    
    # Audit
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by = Column(SQLUUID(as_uuid=True), nullable=True)
    
    # Relationships
    policy = relationship("Policy", back_populates="assignments")
    
    __table_args__ = (
        Index('ix_assignment_scope', 'scope_type', 'scope_id', 'is_active'),
        Index('ix_assignment_action', 'action_pattern'),
    )


class PolicyDecisionLog(Base):
    """
    Immutable audit log of every policy evaluation.
    Used for compliance, debugging, and analytics.
    """
    __tablename__ = "policy_decisions"

    decision_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Context of the evaluation
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=False, index=True)
    action = Column(String(100), nullable=False, index=True)
    
    # What was evaluated (stored as JSON for flexibility)
    subject = Column(JSONB, nullable=False)  # Who performed the action
    resource = Column(JSONB, nullable=False)  # What they acted on
    context = Column(JSONB, nullable=True)    # Additional context
    
    # The decision
    decision = Column(String(20), nullable=False, index=True)  # 'allowed', 'denied', 'approval_required'
    
    # Which policies/rules contributed to the decision
    matched_policies = Column(JSONB, nullable=False)
    
    # Human-readable explanation
    reason = Column(Text, nullable=True)
    
    # If approval required, which chain
    approval_chain_id = Column(SQLUUID(as_uuid=True), nullable=True)
    
    # Performance metrics
    evaluation_duration_ms = Column(Integer, nullable=True)
    
    # Correlation for request tracing
    correlation_id = Column(String(100), nullable=True, index=True)
    request_id = Column(SQLUUID(as_uuid=True), nullable=True)
    
    # Timestamp
    evaluated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    
    # Retention management
    retention_until = Column(DateTime(timezone=True), nullable=True)
    
    __table_args__ = (
        Index('ix_decision_tenant_action', 'tenant_id', 'action', 'evaluated_at'),
        Index('ix_decision_date', 'evaluated_at'),
    )


class PolicyActionType(Base):
    """
    Catalog of known action types for documentation and validation.
    """
    __tablename__ = "policy_action_types"

    action_type_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    code = Column(String(100), nullable=False, unique=True, index=True)  # e.g., 'order.create'
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Expected context schema (for documentation)
    subject_schema = Column(JSONB, nullable=True)
    resource_schema = Column(JSONB, nullable=True)
    context_schema = Column(JSONB, nullable=True)
    
    # Categorization
    category = Column(String(50), nullable=True)  # orders, budget, catalog, etc.
    
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
