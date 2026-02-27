"""
Policy Engine — Pydantic Schemas
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Policy Rule schemas
# ---------------------------------------------------------------------------
class PolicyRuleCreate(BaseModel):
    rule_order: int = Field(default=0, description="Evaluation order within version")
    name: str = Field(..., max_length=255, description="Human-readable rule name")
    condition_expression: str = Field(..., description="Safe expression, e.g. 'subject.budget_remaining < resource.order_total'")
    effect: str = Field(default="deny", description="allow / deny / require_approval")
    denial_reason: Optional[str] = Field(None, description="Reason shown when rule denies")
    approval_chain_id: Optional[UUID] = Field(None, description="Approval chain to trigger on require_approval")
    actions: Optional[Dict[str, Any]] = Field(None, description="Optional structured actions")
    is_active: bool = Field(default=True)


class PolicyRuleUpdate(BaseModel):
    rule_order: Optional[int] = None
    name: Optional[str] = None
    condition_expression: Optional[str] = None
    effect: Optional[str] = None
    denial_reason: Optional[str] = None
    approval_chain_id: Optional[UUID] = None
    actions: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class PolicyRuleResponse(BaseModel):
    rule_id: UUID
    version_id: UUID
    rule_order: int
    name: str
    condition_expression: str
    effect: str
    denial_reason: Optional[str] = None
    approval_chain_id: Optional[UUID] = None
    actions: Optional[Dict[str, Any]] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Policy Version schemas
# ---------------------------------------------------------------------------
class PolicyVersionResponse(BaseModel):
    version_id: UUID
    policy_id: UUID
    version_number: int
    effective_from: datetime
    effective_until: Optional[datetime] = None
    change_reason: Optional[str] = None
    rules: List[PolicyRuleResponse] = []
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Policy schemas
# ---------------------------------------------------------------------------
class PolicyCreate(BaseModel):
    tenant_id: Optional[UUID] = Field(None, description="NULL = global policy")
    code: str = Field(..., max_length=150, description="Unique policy code (per tenant)")
    name: str = Field(..., max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    policy_type: str = Field(..., description="entitlement / budget / approval / product / access / vendor")
    priority: int = Field(default=100, description="Lower = evaluated first")
    is_active: bool = Field(default=True)
    status: str = Field(default="active", description="draft / active / archived")
    created_by: Optional[UUID] = None
    rules: List[PolicyRuleCreate] = Field(default_factory=list, description="Initial rules for version 1")
    change_reason: Optional[str] = Field(None, description="Reason for initial version")


class PolicyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    policy_type: Optional[str] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None
    status: Optional[str] = None
    rules: Optional[List[PolicyRuleCreate]] = Field(None, description="If provided, creates a new version with these rules")
    change_reason: Optional[str] = None


class PolicyResponse(BaseModel):
    policy_id: UUID
    tenant_id: Optional[UUID] = None
    code: str
    name: str
    description: Optional[str] = None
    policy_type: str
    priority: int
    is_active: bool
    status: str
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    current_version: Optional[PolicyVersionResponse] = None

    class Config:
        from_attributes = True


class PolicyListResponse(BaseModel):
    policies: List[PolicyResponse]
    total: int
    skip: int
    limit: int


# ---------------------------------------------------------------------------
# Policy Assignment schemas
# ---------------------------------------------------------------------------
class PolicyAssignmentCreate(BaseModel):
    scope_type: str = Field(default="global", description="global / tenant / site / store / org_unit / user")
    scope_id: Optional[UUID] = Field(None, description="NULL for global")
    action_pattern: str = Field(..., description="e.g. 'order.create', 'order.*', '*'")
    priority_override: Optional[int] = None
    is_active: bool = Field(default=True)
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None


class PolicyAssignmentResponse(BaseModel):
    assignment_id: UUID
    policy_id: UUID
    scope_type: str
    scope_id: Optional[UUID] = None
    action_pattern: str
    priority_override: Optional[int] = None
    is_active: bool
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Evaluate schemas
# ---------------------------------------------------------------------------
class EvaluateRequest(BaseModel):
    action: str = Field(..., description="Action code, e.g. 'order.create'")
    subject: Dict[str, Any] = Field(..., description="Subject context (user_id, tenant_id, etc.)")
    resource: Dict[str, Any] = Field(default_factory=dict, description="Resource context (order_total, product_id, etc.)")
    tenant_id: UUID = Field(..., description="Tenant scope for policy lookup")
    correlation_id: Optional[str] = Field(None, description="Optional correlation ID for tracing")


class EvaluateResponse(BaseModel):
    decision: str = Field(..., description="allow / deny / require_approval")
    allowed: bool
    reason: Optional[str] = None
    matched_policies: List[Dict[str, Any]] = Field(default_factory=list)
    evaluation_ms: int = 0
    correlation_id: Optional[str] = None
    dry_run: bool = False


# ---------------------------------------------------------------------------
# Decision Log (read-only)
# ---------------------------------------------------------------------------
class PolicyDecisionLogResponse(BaseModel):
    decision_id: UUID
    tenant_id: UUID
    user_id: Optional[UUID] = None
    action: str
    subject: Dict[str, Any]
    resource: Dict[str, Any]
    decision: str
    matched_policies: Optional[List[Dict[str, Any]]] = None
    reason: Optional[str] = None
    evaluation_ms: Optional[int] = None
    correlation_id: Optional[str] = None
    evaluated_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------
class SeedResponse(BaseModel):
    seeded: int
    skipped: int
    details: List[str] = []

