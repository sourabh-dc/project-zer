"""
Policy Engine Pydantic Schemas
Request/Response models for the Policy Engine API
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from uuid import UUID


# =============================================================================
# Base Schemas
# =============================================================================

class BaseSchema(BaseModel):
    """Base schema with common config"""
    class Config:
        from_attributes = True
        populate_by_name = True


# =============================================================================
# Policy Rule Schemas
# =============================================================================

class PolicyRuleCreate(BaseModel):
    """Schema for creating a policy rule"""
    name: Optional[str] = None
    description: Optional[str] = None
    rule_order: int = Field(default=0, description="Order of evaluation (lower = first)")
    condition_expression: str = Field(..., description="Expression to evaluate, e.g., 'subject.budget_remaining < resource.order_total'")
    effect: str = Field(..., description="Effect when condition matches: 'allow', 'deny', 'require_approval'")
    denial_reason: Optional[str] = Field(None, description="Reason template with {variable} placeholders")
    approval_chain_id: Optional[UUID] = None
    actions: Optional[List[Dict[str, Any]]] = None
    is_active: bool = True


class PolicyRuleResponse(BaseSchema):
    """Schema for policy rule response"""
    rule_id: UUID
    version_id: UUID
    rule_order: int
    name: Optional[str]
    description: Optional[str]
    condition_expression: str
    effect: str
    denial_reason: Optional[str]
    approval_chain_id: Optional[UUID]
    actions: Optional[List[Dict[str, Any]]]
    is_active: bool
    created_at: datetime


# =============================================================================
# Policy Version Schemas
# =============================================================================

class PolicyVersionCreate(BaseModel):
    """Schema for creating a new policy version"""
    rules: List[PolicyRuleCreate] = Field(..., min_length=1, description="List of rules for this version")
    change_reason: Optional[str] = Field(None, description="Reason for creating this version")


class PolicyVersionResponse(BaseSchema):
    """Schema for policy version response"""
    version_id: UUID
    policy_id: UUID
    version_number: int
    rules_json: List[Dict[str, Any]]
    effective_from: datetime
    effective_until: Optional[datetime]
    created_at: datetime
    created_by: Optional[UUID]
    change_reason: Optional[str]


class PolicyVersionDetailResponse(PolicyVersionResponse):
    """Detailed policy version with rules"""
    rules: List[PolicyRuleResponse] = []


# =============================================================================
# Policy Schemas
# =============================================================================

class PolicyCreate(BaseModel):
    """Schema for creating a policy"""
    tenant_id: Optional[UUID] = Field(None, description="Tenant ID, or null for global policy")
    code: str = Field(..., min_length=1, max_length=100, description="Unique policy code")
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    policy_type: str = Field(..., description="Type: budget, access, entitlement, approval, product")
    priority: int = Field(default=100, ge=0, le=1000, description="Evaluation priority (lower = first)")
    is_active: bool = True
    rules: Optional[List[PolicyRuleCreate]] = Field(None, description="Initial rules (creates first version)")


class PolicyUpdate(BaseModel):
    """Schema for updating a policy"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    priority: Optional[int] = Field(None, ge=0, le=1000)
    is_active: Optional[bool] = None


class PolicyResponse(BaseSchema):
    """Schema for policy response"""
    policy_id: UUID
    tenant_id: Optional[UUID]
    code: str
    name: str
    description: Optional[str]
    policy_type: str
    priority: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    created_by: Optional[UUID]


class PolicyDetailResponse(PolicyResponse):
    """Detailed policy with current version and rules"""
    current_version: Optional[PolicyVersionDetailResponse] = None
    version_count: int = 0


class PolicyListResponse(BaseModel):
    """Paginated list of policies"""
    policies: List[PolicyResponse]
    total: int
    limit: int
    offset: int


# =============================================================================
# Policy Assignment Schemas
# =============================================================================

class PolicyAssignmentCreate(BaseModel):
    """Schema for creating a policy assignment"""
    policy_id: UUID
    scope_type: str = Field(..., description="Scope: global, tenant, site, store, org_unit, user")
    scope_id: Optional[UUID] = Field(None, description="ID of the scope entity (null for global)")
    action_pattern: str = Field(default="*", description="Action pattern, e.g., 'order.*' or 'order.create'")
    priority_override: Optional[int] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    is_active: bool = True


class PolicyAssignmentResponse(BaseSchema):
    """Schema for policy assignment response"""
    assignment_id: UUID
    policy_id: UUID
    scope_type: str
    scope_id: Optional[UUID]
    action_pattern: str
    priority_override: Optional[int]
    valid_from: Optional[datetime]
    valid_until: Optional[datetime]
    is_active: bool
    created_at: datetime


# =============================================================================
# Policy Evaluation Schemas
# =============================================================================

class EvaluationRequest(BaseModel):
    """Request to evaluate an action against policies"""
    action: str = Field(..., description="Action to evaluate, e.g., 'order.create'")
    subject: Dict[str, Any] = Field(..., description="Who is performing the action")
    resource: Dict[str, Any] = Field(..., description="What they are acting on")
    context: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional context")
    
    # Optional: skip logging for testing
    dry_run: bool = Field(default=False, description="If true, don't log the decision")
    
    # Optional: correlation for tracing
    correlation_id: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "action": "order.create",
                "subject": {
                    "user_id": "550e8400-e29b-41d4-a716-446655440000",
                    "tenant_id": "550e8400-e29b-41d4-a716-446655440001",
                    "roles": ["employee"]
                },
                "resource": {
                    "order_total": 15000,
                    "products": [{"id": "prod-1", "restricted": False}]
                },
                "context": {
                    "channel": "web",
                    "store_id": "550e8400-e29b-41d4-a716-446655440002"
                }
            }
        }


class MatchedRule(BaseModel):
    """Information about a rule that matched during evaluation"""
    policy_id: str
    policy_code: str
    rule_id: str
    rule_name: Optional[str]
    effect: str


class EvaluationResponse(BaseModel):
    """Response from policy evaluation"""
    allowed: bool = Field(..., description="Whether the action is allowed")
    decision: str = Field(..., description="Decision: 'allowed', 'denied', 'approval_required'")
    reason: Optional[str] = Field(None, description="Human-readable explanation")
    matched_rules: List[MatchedRule] = Field(default_factory=list, description="Rules that matched")
    approval_chain_id: Optional[str] = Field(None, description="If approval required, which chain")
    actions: List[Dict[str, Any]] = Field(default_factory=list, description="Additional actions to trigger")
    decision_id: Optional[str] = Field(None, description="ID of the logged decision (if not dry_run)")
    evaluation_duration_ms: int = Field(default=0, description="Time taken to evaluate")
    
    class Config:
        json_schema_extra = {
            "example": {
                "allowed": False,
                "decision": "denied",
                "reason": "Insufficient budget. Available: 5000, Required: 15000",
                "matched_rules": [
                    {
                        "policy_id": "550e8400-e29b-41d4-a716-446655440000",
                        "policy_code": "budget.user.check",
                        "rule_id": "550e8400-e29b-41d4-a716-446655440001",
                        "rule_name": "Insufficient User Budget",
                        "effect": "deny"
                    }
                ],
                "decision_id": "550e8400-e29b-41d4-a716-446655440002",
                "evaluation_duration_ms": 15
            }
        }


# =============================================================================
# Policy Decision Log Schemas
# =============================================================================

class DecisionLogResponse(BaseSchema):
    """Schema for decision log entry"""
    decision_id: UUID
    tenant_id: UUID
    action: str
    subject: Dict[str, Any]
    resource: Dict[str, Any]
    context: Optional[Dict[str, Any]]
    decision: str
    matched_policies: List[Dict[str, Any]]
    reason: Optional[str]
    approval_chain_id: Optional[UUID]
    evaluation_duration_ms: Optional[int]
    correlation_id: Optional[str]
    evaluated_at: datetime


class DecisionLogListResponse(BaseModel):
    """Paginated list of decision logs"""
    decisions: List[DecisionLogResponse]
    total: int
    limit: int
    offset: int


class DecisionLogQuery(BaseModel):
    """Query parameters for searching decision logs"""
    tenant_id: Optional[UUID] = None
    action: Optional[str] = None
    decision: Optional[str] = None
    user_id: Optional[UUID] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None
    correlation_id: Optional[str] = None


# =============================================================================
# Action Type Schemas
# =============================================================================

class ActionTypeCreate(BaseModel):
    """Schema for creating an action type"""
    code: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    category: Optional[str] = None
    subject_schema: Optional[Dict[str, Any]] = None
    resource_schema: Optional[Dict[str, Any]] = None
    context_schema: Optional[Dict[str, Any]] = None


class ActionTypeResponse(BaseSchema):
    """Schema for action type response"""
    action_type_id: UUID
    code: str
    name: str
    description: Optional[str]
    category: Optional[str]
    subject_schema: Optional[Dict[str, Any]]
    resource_schema: Optional[Dict[str, Any]]
    context_schema: Optional[Dict[str, Any]]
    is_active: bool
    created_at: datetime


# =============================================================================
# Utility Schemas
# =============================================================================

class UserContext(BaseModel):
    """User context from JWT/authentication"""
    user_id: str
    tenant_id: str
    roles: List[str] = []
    permissions: List[str] = []
    
    class Config:
        extra = "allow"  # Allow additional fields


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    service: str
    version: str
    timestamp: datetime


class ErrorResponse(BaseModel):
    """Standard error response"""
    detail: str
    error_code: Optional[str] = None
    field_errors: Optional[Dict[str, str]] = None
