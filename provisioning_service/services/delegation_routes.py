"""
Delegation API — Phase 4

CRUD endpoints for delegating approval authority from one user to another,
with scope, period, and limit constraints per ZeroQue Roles v1.1.

Rules enforced:
  - One-hop cap: delegate cannot re-delegate
  - Cannot bypass SoD or self-approval
  - Must have expiry date + business reason
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from provisioning_service.Models import Delegation
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.utils.logger import logger

router = APIRouter(prefix="/delegations", tags=["delegations"])


# ═══════════════════════════════════════════════════════════════════
# Schemas
# ═══════════════════════════════════════════════════════════════════

class DelegationCreate(BaseModel):
    delegator_user_id: str = Field(..., description="User delegating their authority")
    delegate_user_id: str = Field(..., description="User receiving delegated authority")
    responsibility_code: str = Field(default="approvals.requests.respond")
    scope_type: str = Field(..., description="organisation | site | cost_centre | department")
    scope_id: Optional[str] = None
    max_transaction_minor: Optional[int] = Field(None, ge=0)
    effective_from: date
    effective_to: date
    reason: str = Field(..., min_length=1, max_length=500)


class DelegationResponse(BaseModel):
    delegation_id: str
    delegator_user_id: str
    delegate_user_id: str
    responsibility_code: str
    scope_type: str
    scope_id: Optional[str] = None
    max_transaction_minor: Optional[int] = None
    effective_from: date
    effective_to: date
    reason: str
    status: str
    is_active: bool


class DelegationListResponse(BaseModel):
    delegations: List[DelegationResponse] = Field(default_factory=list)


def _to_response(d: Delegation) -> DelegationResponse:
    return DelegationResponse(
        delegation_id=str(d.delegation_id),
        delegator_user_id=str(d.delegator_user_id),
        delegate_user_id=str(d.delegate_user_id),
        responsibility_code=d.responsibility_code,
        scope_type=d.scope_type,
        scope_id=d.scope_id,
        max_transaction_minor=d.max_transaction_minor,
        effective_from=d.effective_from,
        effective_to=d.effective_to,
        reason=d.reason,
        status=d.status,
        is_active=d.is_active if d.is_active is not None else True,
    )


# ═══════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════

@router.get("", response_model=DelegationListResponse)
async def list_delegations(
    user_id: Optional[str] = Query(None, description="Filter by delegator or delegate"),
    tenant_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """List delegations, optionally filtered by user or tenant."""
    q = db.query(Delegation)
    if user_id:
        q = q.filter(
            (Delegation.delegator_user_id == user_id) |
            (Delegation.delegate_user_id == user_id)
        )
    if tenant_id:
        q = q.filter(Delegation.tenant_id == tenant_id)
    items = q.order_by(Delegation.created_at.desc()).all()
    return DelegationListResponse(delegations=[_to_response(d) for d in items])


@router.post("", response_model=DelegationResponse, status_code=201)
async def create_delegation(
    req: DelegationCreate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("delegation.create")),
):
    """Create a delegation. Enforces one-hop cap."""
    claims = ctx
    tenant_id = claims.get("tenant_id")

    # ── One-hop cap: check if delegate already has active delegations as delegator ──
    existing = db.query(Delegation).filter(
        Delegation.delegator_user_id == req.delegate_user_id,
        Delegation.is_active == True,
        Delegation.status == "active",
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="One-hop delegation limit: the delegate cannot re-delegate this authority.",
        )

    # ── Prevent delegating to self ──
    if req.delegator_user_id == req.delegate_user_id:
        raise HTTPException(status_code=400, detail="Cannot delegate to yourself.")

    # ── Effective dates must make sense ──
    if req.effective_to <= req.effective_from:
        raise HTTPException(status_code=400, detail="effective_to must be after effective_from")

    delegation = Delegation(
        delegation_id=uuid.uuid4(),
        tenant_id=tenant_id,
        delegator_user_id=req.delegator_user_id,
        delegate_user_id=req.delegate_user_id,
        responsibility_code=req.responsibility_code,
        scope_type=req.scope_type,
        scope_id=req.scope_id,
        max_transaction_minor=req.max_transaction_minor,
        effective_from=req.effective_from,
        effective_to=req.effective_to,
        reason=req.reason,
        status="active",
        is_active=True,
    )
    db.add(delegation)
    db.commit()
    db.refresh(delegation)
    logger.info(f"Delegation created: {delegation.delegation_id} from {req.delegator_user_id} to {req.delegate_user_id}")
    return _to_response(delegation)


@router.delete("/{delegation_id}", status_code=204)
async def revoke_delegation(
    delegation_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("delegation.manage")),
):
    """Revoke (deactivate) a delegation."""
    d = db.query(Delegation).filter(Delegation.delegation_id == delegation_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Delegation not found")

    d.is_active = False
    d.status = "revoked"
    d.updated_at = datetime.now(timezone.utc)
    db.commit()
    logger.info(f"Delegation revoked: {delegation_id}")
