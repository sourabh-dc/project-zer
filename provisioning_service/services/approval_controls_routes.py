"""
User Approval Controls API — Phase 3

CRUD endpoints for per-user approval authority:
  - Scope (organisation / site / cost centre / department)
  - Transaction limits, period limits, effective dates
  - Escalation routing

The frontend "Controls" step (Step 5 of the setup journey) uses these
endpoints to define what a user can approve and under what conditions.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from provisioning_service.Models import UserApprovalControl
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import (
    check_user_authorization, decode_jwt_with_settings,
)
from provisioning_service.utils.logger import logger

router = APIRouter(prefix="/approval-controls", tags=["approval-controls"])

# ═══════════════════════════════════════════════════════════════════
# Schemas
# ═══════════════════════════════════════════════════════════════════


class ApprovalControlCreate(BaseModel):
    user_id: str = Field(..., description="User ID")
    scope_type: str = Field(..., description="organisation | site | cost_centre | department")
    scope_id: Optional[str] = Field(None, description="Site / cost centre / org unit ID")
    max_transaction_minor: Optional[int] = Field(None, ge=0, description="Max per-transaction value in minor units (pence)")
    max_period_minor: Optional[int] = Field(None, ge=0, description="Max cumulative per-period value in minor units")
    period_type: Optional[str] = Field("monthly", description="weekly | monthly | quarterly | annual | custom")
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    currency: Optional[str] = Field("GBP", max_length=3)
    escalation_user_id: Optional[str] = Field(None, description="User ID to escalate to when limits exceeded")
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None


class ApprovalControlUpdate(BaseModel):
    """All fields optional for PATCH-style updates."""
    scope_type: Optional[str] = None
    scope_id: Optional[str] = None
    max_transaction_minor: Optional[int] = Field(None, ge=0)
    max_period_minor: Optional[int] = Field(None, ge=0)
    period_type: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    currency: Optional[str] = Field(None, max_length=3)
    escalation_user_id: Optional[str] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    is_active: Optional[bool] = None


class ApprovalControlResponse(BaseModel):
    control_id: str
    user_id: str
    scope_type: str
    scope_id: Optional[str] = None
    max_transaction_minor: Optional[int] = None
    max_period_minor: Optional[int] = None
    period_type: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    currency: Optional[str] = None
    escalation_user_id: Optional[str] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    is_active: bool = True


class ApprovalControlListResponse(BaseModel):
    controls: List[ApprovalControlResponse] = Field(default_factory=list)


def _to_response(ctrl: UserApprovalControl) -> ApprovalControlResponse:
    return ApprovalControlResponse(
        control_id=str(ctrl.control_id),
        user_id=str(ctrl.user_id),
        scope_type=ctrl.scope_type,
        scope_id=ctrl.scope_id,
        max_transaction_minor=ctrl.max_transaction_minor,
        max_period_minor=ctrl.max_period_minor,
        period_type=ctrl.period_type,
        period_start=ctrl.period_start,
        period_end=ctrl.period_end,
        currency=ctrl.currency,
        escalation_user_id=str(ctrl.escalation_user_id) if ctrl.escalation_user_id else None,
        effective_from=ctrl.effective_from,
        effective_to=ctrl.effective_to,
        is_active=ctrl.is_active if ctrl.is_active is not None else True,
    )


# ═══════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════


@router.get("", response_model=ApprovalControlListResponse)
async def list_approval_controls(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    tenant_id: Optional[str] = Query(None, description="Filter by tenant ID"),
    db: Session = Depends(get_db),
):
    """List approval controls, optionally filtered by user or tenant."""
    q = db.query(UserApprovalControl)
    if user_id:
        q = q.filter(UserApprovalControl.user_id == user_id)
    if tenant_id:
        q = q.filter(UserApprovalControl.tenant_id == tenant_id)
    controls = q.order_by(UserApprovalControl.created_at.desc()).all()
    return ApprovalControlListResponse(controls=[_to_response(c) for c in controls])


@router.post("", response_model=ApprovalControlResponse, status_code=201)
async def create_approval_control(
    req: ApprovalControlCreate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("users.manage")),
):
    """Create an approval control for a user."""
    # Resolve tenant from the JWT context
    claims = ctx
    tenant_id = claims.get("tenant_id")

    control = UserApprovalControl(
        control_id=uuid.uuid4(),
        user_id=req.user_id,
        tenant_id=tenant_id,
        scope_type=req.scope_type,
        scope_id=req.scope_id,
        max_transaction_minor=req.max_transaction_minor,
        max_period_minor=req.max_period_minor,
        period_type=req.period_type,
        period_start=req.period_start,
        period_end=req.period_end,
        currency=req.currency,
        escalation_user_id=req.escalation_user_id,
        effective_from=req.effective_from,
        effective_to=req.effective_to,
        is_active=True,
    )
    db.add(control)
    db.commit()
    db.refresh(control)
    logger.info(f"Approval control created: {control.control_id} for user {req.user_id}")
    return _to_response(control)


@router.put("/{control_id}", response_model=ApprovalControlResponse)
async def update_approval_control(
    control_id: str,
    req: ApprovalControlUpdate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("users.manage")),
):
    """Update an existing approval control. Only non-None fields are updated."""
    control = db.query(UserApprovalControl).filter(
        UserApprovalControl.control_id == control_id
    ).first()
    if not control:
        raise HTTPException(status_code=404, detail="Approval control not found")

    update_data = req.model_dump(exclude_unset=True, exclude_none=True)
    for key, value in update_data.items():
        setattr(control, key, value)
    control.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(control)
    return _to_response(control)


@router.delete("/{control_id}", status_code=204)
async def delete_approval_control(
    control_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("users.manage")),
):
    """Soft-delete (deactivate) an approval control."""
    control = db.query(UserApprovalControl).filter(
        UserApprovalControl.control_id == control_id
    ).first()
    if not control:
        raise HTTPException(status_code=404, detail="Approval control not found")

    control.is_active = False
    control.updated_at = datetime.now(timezone.utc)
    db.commit()
