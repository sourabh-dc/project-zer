from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime

class UserContext(BaseModel):
    """User context for RLS and authorization"""
    user_id: str
    tenant_id: str
    roles: List[str] = []
    permissions: List[str] = []
    site_id: Optional[str] = None
    store_id: Optional[str] = None

class SecurityValidation(BaseModel):
    """Security validation result"""
    is_valid: bool
    user_context: Optional[UserContext] = None
    error_message: Optional[str] = None

# Pydantic Models
class CreateApprovalChainRequest(BaseModel):
    """Request model for creating approval chains"""
    name: str = Field(..., description="Chain name", min_length=1)
    description: Optional[str] = Field(None, description="Chain description")
    chain_type: str = Field(..., description="Chain type")
    is_active: bool = Field(True, description="Whether chain is active")

class CreateApprovalChainStepRequest(BaseModel):
    """Request model for creating approval chain steps"""
    approval_chain_id: str = Field(..., description="Chain ID")
    step_number: int = Field(..., description="Step number", gt=0)
    approver_role: str = Field(..., description="Approver role")
    approver_scope: str = Field(..., description="Approver scope")
    escalation_after_hours: Optional[int] = Field(None, description="Escalation timeout in hours", gt=0)
    is_required: bool = Field(True, description="Whether this step is required")

class CreateApprovalRequestRequest(BaseModel):
    """Request model for creating approval requests"""
    request_type: str = Field(..., description="Request type")
    requested_by: str = Field(..., description="Requester user ID")
    chain_id: str = Field(..., description="Chain ID")
    tenant_id: str = Field(..., description="Tenant ID for multi-tenancy")
    request_data: Dict[str, Any] = Field(..., description="Request data")
    total_amount_minor: Optional[int] = Field(None, description="Amount in minor units")
    currency: str = Field("GBP", description="Currency code")
    due_date: Optional[datetime] = Field(None, description="Due date")

class ApproveRequest(BaseModel):
    """Request model for responding to approval requests"""
    approver_user_id: str = Field(..., description="Approver user ID")
    approved: bool = Field(..., description="Whether to approve or deny")
    notes: Optional[str] = Field(None, description="Approval notes", max_length=500)

class RespondToRequestRequest(BaseModel):
    """Request model for responding to approval requests (new workflow logic)"""
    approver_user_id: str = Field(..., description="Approver user ID")
    approved: bool = Field(..., description="Whether to approve or deny")
    notes: Optional[str] = Field(None, description="Approver notes", max_length=500)
    step_number: int = Field(..., description="Step number being responded to")

class ApprovalRequestApproverResponse(BaseModel):
    """Response model for approval request approvers"""
    id: str
    request_id: str
    approver_user_id: str
    approver_role: str
    step_number: int
    status: str
    notes: Optional[str]
    responded_at: Optional[datetime]
    escalation_sent: bool
    created_at: datetime
    updated_at: Optional[datetime]